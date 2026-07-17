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
            new_state = self._apply_clarification(state)
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

    def resume_waiting(self, state: TurnState, *, abort: bool = False) -> TurnState:
        """恢复等待中的 Turn，或按用户选择中止。"""

        if state.phase != TurnPhase.WAITING_FOR_USER:
            raise StateTransitionError(
                TransitionErrorCode.NOT_WAITING,
                "只有 WAITING_FOR_USER 可以恢复",
            )
        if abort:
            return self._replace(
                state, phase=TurnPhase.ABORTED, suspended_phase=None
            )
        return self._replace(
            state, phase=state.suspended_phase, suspended_phase=None
        )

    def record_iteration(self, state: TurnState) -> TurnState:
        """记录一次 LLM 迭代。"""

        self._require_non_terminal(state)
        return self._replace(state, iterations=state.iterations + 1)

    def record_tool_call(self, state: TurnState) -> TurnState:
        """记录一次已接受的工具调用。"""

        self._require_non_terminal(state)
        return self._replace(state, tool_calls=state.tool_calls + 1)

    def record_write_succeeded(self, state: TurnState) -> TurnState:
        """成功写入后递增工作区 revision 并使验证失效。"""

        self._require_non_terminal(state)
        return self._replace(
            state,
            workspace_dirty=True,
            workspace_revision=state.workspace_revision + 1,
        )

    def record_verification_started(self, state: TurnState) -> TurnState:
        """已获准的验证调用开始派发。"""

        self._require_phase(state, {TurnPhase.EXECUTING})
        return self._replace(state, phase=TurnPhase.VERIFYING)

    def record_verification_finished(
        self, state: TurnState, *, all_required_passed: bool
    ) -> TurnState:
        """验证完成后回到 EXECUTING；全部必需验证通过才清除 dirty。"""

        self._require_phase(state, {TurnPhase.VERIFYING})
        return self._replace(
            state,
            phase=TurnPhase.EXECUTING,
            workspace_dirty=state.workspace_dirty and not all_required_passed,
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
            state, phase=TurnPhase.EXECUTING, plan=tuple(updated_plan)
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

    def _apply_clarification(self, state: TurnState) -> TurnState:
        self._require_phase(
            state,
            {TurnPhase.PREPARING, TurnPhase.PLANNING, TurnPhase.EXECUTING},
        )
        return self._replace(
            state,
            phase=TurnPhase.WAITING_FOR_USER,
            suspended_phase=state.phase,
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
