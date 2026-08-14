"""TurnState 的唯一合法转换入口。"""

from __future__ import annotations

from enum import StrEnum

from harness_agent.agent.action_parser import ParsedAction
from harness_agent.agent.actions import (
    AskClarificationAction,
    FinalAction,
    FinalOutcome,
    PlanAction,
    PlanItemStatus,
    ReflectAction,
    ToolCallAction,
    UpdatePlanAction,
)
from harness_agent.agent.state import PlanItem, TERMINAL_PHASES, TurnPhase, TurnState
from harness_agent.agent.verification import VerificationResult
from harness_agent.agent.interactions import (
    ApprovalGrant,
    ApprovalGrantStatus,
    PendingInteraction,
    ToolExecution,
    ToolExecutionStatus,
)
from harness_agent.agent.context import EditRecovery, FileSnapshot, TaskContract


class TransitionErrorCode(StrEnum):
    """稳定的非法转换错误代码。"""

    TERMINAL_STATE = "terminal_state"
    ACTION_NOT_ALLOWED = "action_not_allowed"
    PLAN_REQUIRED = "plan_required"
    PLAN_MISSING = "plan_missing"
    PLAN_ITEM_NOT_FOUND = "plan_item_not_found"
    PLAN_STATE_INVALID = "plan_state_invalid"
    DIRTY_WORKSPACE = "dirty_workspace"
    NOT_WAITING = "not_waiting"


class StateTransitionError(ValueError):
    """Action 或系统事件不满足当前状态约束。"""

    def __init__(self, code: TransitionErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class StateMachine:
    """以纯函数风格返回新的不可变 TurnState。"""

    _ACTION_DIGEST_HISTORY = 10

    def start(self, state: TurnState) -> TurnState:
        """启动新 Turn。"""

        self._require_phase(state, {TurnPhase.CREATED})
        return self._replace(state, phase=TurnPhase.PREPARING)

    def apply_action(
        self,
        state: TurnState,
        parsed: ParsedAction,
        *,
        plan_required: bool = False,
    ) -> TurnState:
        """检查并应用一个已解析 Action，不执行任何外部操作。"""

        if state.phase in TERMINAL_PHASES:
            raise StateTransitionError(
                TransitionErrorCode.TERMINAL_STATE,
                f"终态 {state.phase} 不接受新 Action",
            )

        action = parsed.action
        if plan_required and not state.has_plan and not isinstance(action, PlanAction):
            raise StateTransitionError(
                TransitionErrorCode.PLAN_REQUIRED,
                "该 Action 执行前必须先建立显式计划",
            )

        if isinstance(action, PlanAction):
            new_state = self._apply_plan(state, action)
        elif isinstance(action, UpdatePlanAction):
            new_state = self._apply_plan_update(state, action)
        elif isinstance(action, ToolCallAction):
            new_state = self._apply_tool_call(state)
        elif isinstance(action, ReflectAction):
            new_state = self._apply_reflect(state)
        elif isinstance(action, AskClarificationAction):
            new_state = self._apply_clarification(state, action)
        elif isinstance(action, FinalAction):
            new_state = self._apply_final(state, action)
        else:  # pragma: no cover - Action 联合类型未来扩展时的安全网
            raise StateTransitionError(
                TransitionErrorCode.ACTION_NOT_ALLOWED,
                f"未实现的 Action：{type(action).__name__}",
            )

        history = (*new_state.recent_action_digests, parsed.digest)[
            -self._ACTION_DIGEST_HISTORY :
        ]
        return self._replace(new_state, recent_action_digests=history)

    def mark_plan_required(self, state: TurnState) -> TurnState:
        """当渐进式计划规则触发时进入 PLANNING。"""

        self._require_phase(state, {TurnPhase.PREPARING, TurnPhase.EXECUTING})
        return self._replace(state, phase=TurnPhase.PLANNING)

    @staticmethod
    def requires_plan_for_tool(
        state: TurnState, *, has_side_effect: bool
    ) -> bool:
        """统一判断工具调用是否触发渐进式计划规则。"""

        if state.has_plan:
            return False
        return has_side_effect or state.tool_calls >= 2

    def wait_for_approval(
        self, state: TurnState, pending: PendingInteraction
    ) -> TurnState:
        """把已接受但尚未派发的工具调用暂停为审批请求。"""

        self._require_phase(state, {TurnPhase.PREPARING, TurnPhase.EXECUTING, TurnPhase.VERIFYING})
        if pending.tool_call is None:
            raise ValueError("审批请求必须绑定工具调用")
        return self._replace(
            state,
            phase=TurnPhase.WAITING_FOR_USER,
            suspended_phase=state.phase,
            pending_interaction=pending,
        )

    def resume_waiting(
        self,
        state: TurnState,
        *,
        abort: bool = False,
    ) -> TurnState:
        """恢复等待中的 Turn，或按用户选择中止。"""

        if state.phase != TurnPhase.WAITING_FOR_USER:
            raise StateTransitionError(
                TransitionErrorCode.NOT_WAITING,
                "只有 WAITING_FOR_USER 可以恢复",
            )
        if abort:
            return self._replace(
                state,
                phase=TurnPhase.ABORTED,
                suspended_phase=None,
                pending_interaction=None,
            )
        return self._replace(
            state,
            phase=state.suspended_phase,
            suspended_phase=None,
            pending_interaction=None,
        )

    def start_approved_dispatch(
        self,
        state: TurnState,
        *,
        grant: ApprovalGrant,
        execution: ToolExecution,
        verification: bool = False,
    ) -> TurnState:
        """原子消费批准，并在外部调用前记录 DISPATCHING。"""

        if state.phase != TurnPhase.WAITING_FOR_USER:
            raise StateTransitionError(TransitionErrorCode.NOT_WAITING, "当前没有等待审批")
        pending = state.pending_interaction
        if pending is None or pending.tool_call is None or not grant.matches(pending.tool_call):
            raise StateTransitionError(
                TransitionErrorCode.ACTION_NOT_ALLOWED,
                "批准与等待中的工具调用不匹配",
            )
        if execution.status != ToolExecutionStatus.DISPATCHING:
            raise ValueError("审批恢复只能从 DISPATCHING 开始")
        consumed = grant.model_copy(update={"status": ApprovalGrantStatus.CONSUMED})
        return self._replace(
            state,
            phase=TurnPhase.VERIFYING if verification else state.suspended_phase,
            suspended_phase=None,
            pending_interaction=None,
            approval_grant=consumed,
            tool_execution=execution,
            tool_calls=state.tool_calls + 1,
        )

    def mark_tool_dispatching(self, state: TurnState, execution: ToolExecution) -> TurnState:
        """在执行普通工具前记录 DISPATCHING，供崩溃恢复使用。"""

        self._require_non_terminal(state)
        if execution.status != ToolExecutionStatus.DISPATCHING:
            raise ValueError("工具开始时状态必须为 DISPATCHING")
        return self._replace(state, tool_execution=execution)

    def record_tool_finished(
        self,
        state: TurnState,
        *,
        succeeded: bool,
        error: str | None = None,
    ) -> TurnState:
        """记录工具已经返回，避免恢复时将其误认为未完成。"""

        if state.tool_execution is None:
            raise ValueError("没有正在执行的工具调用")
        execution = state.tool_execution.model_copy(
            update={
                "status": ToolExecutionStatus.SUCCEEDED if succeeded else ToolExecutionStatus.FAILED,
                "error": error,
            }
        )
        return self._replace(state, tool_execution=execution)

    def mark_execution_unknown(self, state: TurnState) -> TurnState:
        """恢复时发现 DISPATCHING；绝不自动重复派发。"""

        execution = state.tool_execution
        if execution is None or execution.status != ToolExecutionStatus.DISPATCHING:
            raise ValueError("只有 DISPATCHING 工具调用可标记为未知")
        unknown = execution.model_copy(update={"status": ToolExecutionStatus.EXECUTION_UNKNOWN})
        pending = PendingInteraction(
            kind="execution_unknown",
            prompt="上次工具调用可能已经开始执行，结果无法确认。请检查工作区后决定下一步。",
        )
        return self._replace(
            state,
            phase=TurnPhase.WAITING_FOR_USER,
            suspended_phase=state.phase,
            pending_interaction=pending,
            tool_execution=unknown,
        )

    def record_iteration(self, state: TurnState) -> TurnState:
        """记录一次 LLM 迭代。"""

        self._require_non_terminal(state)
        return self._replace(state, iterations=state.iterations + 1)

    def record_task_contract(
        self, state: TurnState, contract: TaskContract
    ) -> TurnState:
        """只允许在任务开始时写入一次原始任务卡。"""

        self._require_non_terminal(state)
        if state.task_contract is not None:
            if state.task_contract != contract:
                raise ValueError("当前 Turn 的原始任务卡不可改写")
            return state
        return self._replace(state, task_contract=contract)

    def record_file_read(self, state: TurnState, snapshot: FileSnapshot) -> TurnState:
        """保存模型看到的最新文件版本。"""

        self._require_non_terminal(state)
        snapshots = {item.path: item for item in state.file_snapshots}
        snapshots[snapshot.path] = snapshot
        recovery = state.edit_recovery
        if (
            recovery is not None
            and recovery.path == snapshot.path
            and snapshot.complete
        ):
            recovery = recovery.model_copy(update={"require_full_read": False})
        return self._replace(
            state,
            file_snapshots=tuple(snapshots[path] for path in sorted(snapshots)),
            edit_recovery=recovery,
        )

    def record_edit_failure(self, state: TurnState, recovery: EditRecovery) -> TurnState:
        """记录当前任务内的修改恢复范围。"""

        self._require_non_terminal(state)
        return self._replace(state, edit_recovery=recovery)

    def record_tool_call(self, state: TurnState) -> TurnState:
        """记录一次已接受的工具调用。"""

        self._require_non_terminal(state)
        return self._replace(state, tool_calls=state.tool_calls + 1)

    def record_write_succeeded(
        self, state: TurnState, *, modified_paths: tuple[str, ...] = ()
    ) -> TurnState:
        """成功写入后递增工作区 revision 并使验证失效。"""

        self._require_non_terminal(state)
        known_paths = dict.fromkeys((*state.modified_paths, *modified_paths))
        snapshots = tuple(
            item.model_copy(update={"stale": True})
            if item.path in modified_paths
            else item
            for item in state.file_snapshots
        )
        recovery = state.edit_recovery
        if recovery is not None and recovery.path in modified_paths:
            recovery = None
        return self._replace(
            state,
            workspace_dirty=True,
            workspace_revision=state.workspace_revision + 1,
            modified_paths=tuple(known_paths),
            file_snapshots=snapshots,
            edit_recovery=recovery,
        )

    def record_verification_started(self, state: TurnState) -> TurnState:
        """已获准的验证调用开始派发。"""

        self._require_phase(state, {TurnPhase.EXECUTING})
        return self._replace(state, phase=TurnPhase.VERIFYING)

    def record_verification_finished(
        self,
        state: TurnState,
        *,
        verification: VerificationResult,
        required_validator_ids: frozenset[str],
    ) -> TurnState:
        """持久化验证证据；非空必需集合在当前 revision 全通过才清除 dirty。"""

        self._require_phase(state, {TurnPhase.VERIFYING})
        if verification.workspace_revision != state.workspace_revision:
            raise ValueError("验证结果与当前工作区 revision 不一致")
        history = (*state.verification_history, verification)
        latest: dict[str, VerificationResult] = {}
        for result in history:
            if result.workspace_revision == state.workspace_revision:
                latest[result.validator_id] = result
        all_required_passed = bool(required_validator_ids) and all(
            latest.get(validator_id) is not None
            and latest[validator_id].passed
            for validator_id in required_validator_ids
        )
        return self._replace(
            state,
            phase=TurnPhase.EXECUTING,
            workspace_dirty=(state.workspace_dirty or state.workspace_revision > 0)
            and not all_required_passed,
            verification_history=history,
        )

    def fail(self, state: TurnState, message: str) -> TurnState:
        """因资源耗尽或不可恢复错误终止。"""

        self._require_non_terminal(state)
        return self._replace(
            state,
            phase=TurnPhase.FAILED,
            outcome=FinalOutcome.FAILED,
            final_message=message,
            suspended_phase=None,
        )

    def _apply_plan(self, state: TurnState, action: PlanAction) -> TurnState:
        self._require_phase(
            state,
            {TurnPhase.PREPARING, TurnPhase.PLANNING, TurnPhase.EXECUTING},
        )
        plan = tuple(
            PlanItem(id=item.id, description=item.description) for item in action.items
        )
        return self._replace(state, phase=TurnPhase.EXECUTING, plan=plan)

    def _apply_plan_update(
        self, state: TurnState, action: UpdatePlanAction
    ) -> TurnState:
        self._require_phase(state, {TurnPhase.PLANNING, TurnPhase.EXECUTING})
        if not state.plan:
            raise StateTransitionError(
                TransitionErrorCode.PLAN_MISSING,
                "没有可更新的计划",
            )

        updates = {update.item_id: update for update in action.updates}
        known_ids = {item.id for item in state.plan}
        unknown_ids = sorted(set(updates) - known_ids)
        if unknown_ids:
            raise StateTransitionError(
                TransitionErrorCode.PLAN_ITEM_NOT_FOUND,
                f"计划项不存在：{', '.join(unknown_ids)}",
            )

        append_ids = {item.id for item in action.append_items}
        duplicates = sorted(known_ids & append_ids)
        if duplicates:
            raise StateTransitionError(
                TransitionErrorCode.PLAN_STATE_INVALID,
                f"追加计划项 id 已存在：{', '.join(duplicates)}",
            )

        updated_plan: list[PlanItem] = []
        for item in state.plan:
            update = updates.get(item.id)
            if update is None:
                updated_plan.append(item)
            else:
                updated_plan.append(
                    item.model_copy(
                        update={"status": update.status, "note": update.note}
                    )
                )
        updated_plan.extend(
            PlanItem(id=item.id, description=item.description)
            for item in action.append_items
        )
        if sum(item.status == PlanItemStatus.IN_PROGRESS for item in updated_plan) > 1:
            raise StateTransitionError(
                TransitionErrorCode.PLAN_STATE_INVALID,
                "同一时刻最多一个计划项处于 in_progress",
            )
        return self._replace(
            state,
            phase=TurnPhase.EXECUTING,
            plan=tuple(updated_plan),
            plan_updates=state.plan_updates + 1,
        )

    def _apply_tool_call(self, state: TurnState) -> TurnState:
        self._require_phase(state, {TurnPhase.PREPARING, TurnPhase.EXECUTING})
        return self._replace(state, phase=TurnPhase.EXECUTING)

    def _apply_reflect(self, state: TurnState) -> TurnState:
        self._require_phase(state, {TurnPhase.PREPARING, TurnPhase.EXECUTING})
        return self._replace(
            state,
            phase=TurnPhase.EXECUTING,
            reflections=state.reflections + 1,
        )

    def _apply_clarification(
        self, state: TurnState, action: AskClarificationAction
    ) -> TurnState:
        self._require_phase(
            state,
            {TurnPhase.PREPARING, TurnPhase.PLANNING, TurnPhase.EXECUTING},
        )
        return self._replace(
            state,
            phase=TurnPhase.WAITING_FOR_USER,
            suspended_phase=state.phase,
            pending_interaction=PendingInteraction.clarification(prompt=action.question),
        )

    def _apply_final(self, state: TurnState, action: FinalAction) -> TurnState:
        if action.outcome == FinalOutcome.SUCCESS:
            self._require_phase(state, {TurnPhase.PREPARING, TurnPhase.EXECUTING})
            if state.workspace_dirty:
                raise StateTransitionError(
                    TransitionErrorCode.DIRTY_WORKSPACE,
                    "工作区修改尚未通过验证，不能成功结束",
                )
            phase = TurnPhase.COMPLETED
        else:
            self._require_phase(
                state,
                {TurnPhase.PREPARING, TurnPhase.PLANNING, TurnPhase.EXECUTING},
            )
            phase = TurnPhase.FAILED
        return self._replace(
            state,
            phase=phase,
            outcome=action.outcome,
            final_message=action.message,
        )

    @staticmethod
    def _replace(state: TurnState, **updates: object) -> TurnState:
        """更新状态并重新执行全部 Pydantic 不变量校验。"""

        payload = state.model_dump(mode="python")
        payload.update(updates)
        return TurnState.model_validate(payload)

    @staticmethod
    def _require_phase(state: TurnState, allowed: set[TurnPhase]) -> None:
        if state.phase not in allowed:
            allowed_names = ", ".join(sorted(phase.value for phase in allowed))
            raise StateTransitionError(
                TransitionErrorCode.ACTION_NOT_ALLOWED,
                f"状态 {state.phase.value} 不允许该操作；允许状态：{allowed_names}",
            )

    @staticmethod
    def _require_non_terminal(state: TurnState) -> None:
        if state.phase in TERMINAL_PHASES:
            raise StateTransitionError(
                TransitionErrorCode.TERMINAL_STATE,
                f"终态 {state.phase.value} 不允许继续转换",
            )
