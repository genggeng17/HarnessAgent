"""模型、治理、工具、审批和验证的确定性协调者。"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Sequence

from pydantic import BaseModel, ConfigDict

from harness_agent.agent.action_parser import ActionParseError, ActionParser, ParsedAction
from harness_agent.agent.actions import FinalAction, ReflectAction, ToolCallAction
from harness_agent.agent.interactions import (
    ApprovalGrant,
    InteractionKind,
    PendingInteraction,
    ToolCallSnapshot,
    ToolExecution,
)
from harness_agent.agent.loop_guard import LoopGuard
from harness_agent.agent.protocol import action_correction_message
from harness_agent.agent.state import TERMINAL_PHASES, TurnPhase, TurnState
from harness_agent.agent.state_machine import StateMachine, StateTransitionError
from harness_agent.agent.verification import VerificationResult, VerificationService
from harness_agent.governance.policy import PolicyEngine, PolicyOutcome
from harness_agent.llm.base import ChatMessage, LLMClient, MessageRole
from harness_agent.runtime.workspace import LocalWorkspace
from harness_agent.tools.dispatcher import ToolDispatcher
from harness_agent.tools.models import (
    ExecutionContext,
    SideEffect,
    Tool,
    ToolKind,
    ToolResult,
    ToolResultStatus,
    new_tool_call_id,
)
from harness_agent.tools.verification_tool import RunVerificationTool


StateObserver = Callable[[TurnState], Awaitable[None]]
MemoryContextProvider = Callable[[str], str]


class AgentLoopResult(BaseModel):
    """单次运行到结束或等待用户时的结果。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: TurnState
    messages: tuple[ChatMessage, ...]
    tool_results: tuple[dict[str, object], ...] = ()
    verification_results: tuple[VerificationResult, ...] = ()


class AgentLoop:
    """协调组件；状态保存由调用方提供的 observer 完成。"""

    def __init__(
        self,
        *,
        llm: LLMClient,
        parser: ActionParser,
        state_machine: StateMachine,
        loop_guard: LoopGuard,
        policy: PolicyEngine,
        dispatcher: ToolDispatcher,
        verification_service: VerificationService,
        workspace: LocalWorkspace,
        execution_context: ExecutionContext,
        memory_context_provider: MemoryContextProvider | None = None,
        project_instructions: str = "",
    ) -> None:
        self.llm = llm
        self.parser = parser
        self.state_machine = state_machine
        self.loop_guard = loop_guard
        self.policy = policy
        self.dispatcher = dispatcher
        self.verification_service = verification_service
        self.workspace = workspace
        self.execution_context = execution_context
        self.memory_context_provider = memory_context_provider
        self.project_instructions = project_instructions

    async def run(
        self,
        user_task: str,
        *,
        initial_state: TurnState | None = None,
        prior_messages: Sequence[ChatMessage] = (),
        state_observer: StateObserver | None = None,
    ) -> AgentLoopResult:
        """运行新任务，直到终态或需要用户处理的等待态。"""

        state = initial_state or TurnState()
        if state.phase == TurnPhase.CREATED:
            state = self.state_machine.start(state)
            await self._checkpoint(state_observer, state)
        messages = [*prior_messages]
        testing_contract = self._testing_contract()
        if testing_contract:
            messages.append(ChatMessage(role=MessageRole.SYSTEM, content=testing_contract))
        if self.memory_context_provider is not None:
            memory_context = self.memory_context_provider(user_task)
            if memory_context:
                messages.append(
                    ChatMessage(role=MessageRole.SYSTEM, content=f"与当前任务相关的长期记忆：\n{memory_context}")
                )
        if self.project_instructions:
            messages.append(
                ChatMessage(
                    role=MessageRole.SYSTEM,
                    content="项目工作规则（来自项目根目录 AGENTS.md）：\n"
                    + self.project_instructions,
                )
            )
        messages.append(ChatMessage(role=MessageRole.USER, content=user_task))
        return await self._continue(state, messages, state_observer)

    async def resume(
        self,
        *,
        state: TurnState,
        prior_messages: Sequence[ChatMessage],
        user_response: str,
        approved: bool | None = None,
        abort: bool = False,
        state_observer: StateObserver | None = None,
    ) -> AgentLoopResult:
        """恢复等待中的审批、业务澄清或未知执行请求。"""

        if state.phase != TurnPhase.WAITING_FOR_USER or state.pending_interaction is None:
            raise ValueError("当前 Turn 没有等待用户处理的请求")
        messages = [*prior_messages, ChatMessage(role=MessageRole.USER, content=user_response)]
        pending = state.pending_interaction
        if abort:
            state = self.state_machine.resume_waiting(state, abort=True)
            await self._checkpoint(state_observer, state)
            return self._result(state, messages, (), ())

        if pending.kind != InteractionKind.APPROVAL:
            state = self.state_machine.resume_waiting(state)
            await self._checkpoint(state_observer, state)
            messages.append(self._observation("user_response", user_response))
            return await self._continue(state, messages, state_observer)

        if approved is not True:
            state = self.state_machine.resume_waiting(state)
            await self._checkpoint(state_observer, state)
            messages.append(self._observation("approval_denied", "用户拒绝执行该工具调用"))
            return await self._continue(state, messages, state_observer)

        snapshot = pending.tool_call
        if snapshot is None:  # pragma: no cover - TurnState 与模型已保证
            raise ValueError("审批请求缺少原始工具调用")
        tool = self.dispatcher.registry.get(snapshot.tool_name)
        if tool is None:
            state = self.state_machine.resume_waiting(state)
            await self._checkpoint(state_observer, state)
            messages.append(self._observation("tool_not_found", f"工具未注册：{snapshot.tool_name}"))
            return await self._continue(state, messages, state_observer)

        decision = self.policy.evaluate(tool, snapshot.arguments, self.workspace)
        if decision.outcome == PolicyOutcome.DENY:
            state = self.state_machine.resume_waiting(state)
            await self._checkpoint(state_observer, state)
            messages.append(self._observation("policy_deny", decision.reason))
            return await self._continue(state, messages, state_observer)
        guard = self.loop_guard.before_tool_call(state)
        if not guard.allowed:
            state = self.state_machine.fail(state, guard.message or "工具调用资源耗尽")
            await self._checkpoint(state_observer, state)
            return self._result(state, messages, (), ())

        grant = ApprovalGrant.from_tool_call(snapshot)
        execution = self._execution(snapshot, tool)
        state = self.state_machine.start_approved_dispatch(
            state,
            grant=grant,
            execution=execution,
            verification=tool.kind == ToolKind.VERIFICATION,
        )
        await self._checkpoint(state_observer, state)
        state, results, verifications = await self._finish_dispatch(
            state=state,
            tool=tool,
            snapshot=snapshot,
            messages=messages,
            state_observer=state_observer,
        )
        continued = await self._continue(state, messages, state_observer)
        return AgentLoopResult(
            state=continued.state,
            messages=continued.messages,
            tool_results=tuple([*results, *continued.tool_results]),
            verification_results=tuple([*verifications, *continued.verification_results]),
        )

    async def _continue(
        self,
        state: TurnState,
        messages: list[ChatMessage],
        state_observer: StateObserver | None,
    ) -> AgentLoopResult:
        tool_results: list[dict[str, object]] = []
        verification_results: list[VerificationResult] = []
        while state.phase not in TERMINAL_PHASES and state.phase != TurnPhase.WAITING_FOR_USER:
            guard = self.loop_guard.before_iteration(state)
            if not guard.allowed:
                state = self.state_machine.fail(state, guard.message or "迭代资源耗尽")
                await self._checkpoint(state_observer, state)
                break
            state = self.state_machine.record_iteration(state)
            await self._checkpoint(state_observer, state)
            tool_specs = self.dispatcher.registry.specs()
            request_messages = [
                *messages,
                ChatMessage(
                    role=MessageRole.SYSTEM,
                    content=self._iteration_context(state),
                ),
            ]
            response = await self.llm.complete(request_messages, tool_specs)
            messages.append(ChatMessage(role=MessageRole.ASSISTANT, content=response.content))
            try:
                parsed = self.parser.parse(response.content)
            except ActionParseError as exc:
                messages.append(
                    ChatMessage(
                        role=MessageRole.TOOL,
                        content=action_correction_message(exc.message, tool_specs),
                    )
                )
                continue

            repeated = self.loop_guard.check_repeated_action(state, parsed.digest)
            if not repeated.allowed:
                state = self.state_machine.fail(state, repeated.message or "Action 重复")
                await self._checkpoint(state_observer, state)
                break
            action = parsed.action
            if isinstance(action, ReflectAction):
                reflection_guard = self.loop_guard.before_reflection(state)
                if not reflection_guard.allowed:
                    state = self.state_machine.fail(state, reflection_guard.message or "反思资源耗尽")
                    await self._checkpoint(state_observer, state)
                    break

            if not isinstance(action, ToolCallAction):
                try:
                    state = self.state_machine.apply_action(state, parsed)
                except StateTransitionError as exc:
                    messages.append(self._observation(exc.code.value, exc.message))
                    continue
                await self._checkpoint(state_observer, state)
                if isinstance(action, FinalAction) or state.phase == TurnPhase.WAITING_FOR_USER:
                    break
                continue

            tool = self.dispatcher.registry.get(action.tool)
            if tool is None:
                try:
                    state = self.state_machine.apply_action(state, parsed)
                except StateTransitionError as exc:
                    messages.append(self._observation(exc.code.value, exc.message))
                    continue
                await self._checkpoint(state_observer, state)
                messages.append(self._observation("tool_not_found", f"工具未注册：{action.tool}"))
                continue
            needs_plan = self.state_machine.requires_plan_for_tool(
                state, has_side_effect=tool.side_effect != SideEffect.NONE
            )
            if needs_plan:
                state = self.state_machine.mark_plan_required(state)
                await self._checkpoint(state_observer, state)
                messages.append(self._observation("plan_required", "该工具调用前必须先建立计划"))
                continue
            tool_guard = self.loop_guard.before_tool_call(state)
            if not tool_guard.allowed:
                state = self.state_machine.fail(state, tool_guard.message or "工具调用资源耗尽")
                await self._checkpoint(state_observer, state)
                break
            try:
                next_state = self.state_machine.apply_action(state, parsed)
            except StateTransitionError as exc:
                messages.append(self._observation(exc.code.value, exc.message))
                continue

            decision = self.policy.evaluate(tool, action.arguments, self.workspace)
            if decision.outcome == PolicyOutcome.DENY:
                messages.append(self._observation("policy_deny", decision.reason))
                continue
            snapshot = ToolCallSnapshot(
                action_id=parsed.action_id,
                action_digest=parsed.digest,
                tool_name=action.tool,
                arguments=action.arguments,
                workspace_id=self.workspace.workspace_id,
            )
            if decision.outcome == PolicyOutcome.ASK:
                pending = PendingInteraction.approval(prompt=decision.reason, tool_call=snapshot)
                state = self.state_machine.wait_for_approval(next_state, pending)
                await self._checkpoint(state_observer, state)
                messages.append(self._observation("approval_required", decision.reason))
                break

            state = self.state_machine.record_tool_call(next_state)
            if tool.kind == ToolKind.VERIFICATION:
                state = self.state_machine.record_verification_started(state)
            state = self.state_machine.mark_tool_dispatching(state, self._execution(snapshot, tool))
            await self._checkpoint(state_observer, state)
            state, results, verifications = await self._finish_dispatch(
                state=state,
                tool=tool,
                snapshot=snapshot,
                messages=messages,
                state_observer=state_observer,
            )
            tool_results.extend(results)
            verification_results.extend(verifications)

        return self._result(state, messages, tool_results, verification_results)

    async def _finish_dispatch(
        self,
        *,
        state: TurnState,
        tool: Tool,
        snapshot: ToolCallSnapshot,
        messages: list[ChatMessage],
        state_observer: StateObserver | None,
    ) -> tuple[TurnState, list[dict[str, object]], list[VerificationResult]]:
        """执行已持久化为 DISPATCHING 的工具调用并回灌事实。"""

        execution = state.tool_execution
        if execution is None:  # pragma: no cover - 调用点已经建立执行记录
            raise ValueError("派发前缺少工具执行记录")
        result = await self.dispatcher.dispatch(
            snapshot.tool_name,
            snapshot.arguments,
            self.workspace,
            self.execution_context,
            tool_call_id=execution.tool_call_id,
        )
        succeeded = result.status == ToolResultStatus.SUCCEEDED
        state = self.state_machine.record_tool_finished(
            state, succeeded=succeeded, error=result.error
        )
        await self._checkpoint(state_observer, state)
        dumped = result.model_dump(mode="json")
        results = [dumped]
        verifications: list[VerificationResult] = []

        if tool.kind == ToolKind.WRITE and succeeded and result.modified_paths:
            state = self.state_machine.record_write_succeeded(
                state, modified_paths=result.modified_paths
            )
            await self._checkpoint(state_observer, state)

        if tool.kind != ToolKind.VERIFICATION:
            messages.append(self._observation("tool_result", json.dumps(dumped, ensure_ascii=False)))
            return state, results, verifications

        validator_id = str(result.data.get("validator_id", snapshot.arguments.get("validator_id", "")))
        verification = self.verification_service.evaluate(
            result,
            validator_id=validator_id,
            workspace_revision=state.workspace_revision,
        )
        verifications.append(verification)
        required = (
            tool.required_validator_ids
            if isinstance(tool, RunVerificationTool)
            else frozenset({validator_id})
        )
        if not required and result.data.get("required") is True and validator_id:
            required = frozenset({validator_id})
        state = self.state_machine.record_verification_finished(
            state,
            verification=verification,
            required_validator_ids=required,
        )
        await self._checkpoint(state_observer, state)
        messages.append(
            self._observation(
                "verification_result",
                json.dumps(verification.model_dump(mode="json"), ensure_ascii=False),
            )
        )
        return state, results, verifications

    @staticmethod
    def _execution(snapshot: ToolCallSnapshot, tool: Tool) -> ToolExecution:
        """为单次执行分配稳定工具调用 ID。"""

        return ToolExecution(
            tool_call_id=new_tool_call_id(),
            action_id=snapshot.action_id,
            action_digest=snapshot.action_digest,
            tool_name=snapshot.tool_name,
            arguments_digest=snapshot.arguments_digest,
            idempotent=tool.idempotent,
        )

    @staticmethod
    async def _checkpoint(observer: StateObserver | None, state: TurnState) -> None:
        """把状态提交职责交给运行时，而不依赖具体存储。"""

        if observer is not None:
            await observer(state)

    @staticmethod
    def _observation(code: str, message: str) -> ChatMessage:
        body = json.dumps({"code": code, "message": message}, ensure_ascii=False)
        return ChatMessage(role=MessageRole.TOOL, content=body)

    def _testing_contract(self) -> str:
        """把测试工作方式和真实可用验证器明确交给模型。"""

        tool = self.dispatcher.registry.get("run_verification")
        if not isinstance(tool, RunVerificationTool):
            return ""
        if tool.validator_configs:
            lines = [
                f"- {item.id}: {' '.join(item.argv)}"
                f"（{'必须通过' if item.required else '可选'}，目录 {item.cwd}）"
                for item in tool.validator_configs
            ]
        else:
            lines = ["- 当前没有固定验证器；创建测试配置后可调用 validator_id=auto 重新发现。"]
        available = "\n".join(lines)
        return (
            "测试与验收规则（仅在任务会修改文件时适用）：\n"
            "1. 修改前先查看并尽量运行相关的已有测试，记录项目原本是否失败。\n"
            "2. 优先复用已有测试；需求缺少覆盖时补写测试。修复缺陷或新增行为时，"
            "尽量先确认新增测试在修复前会因正确原因失败。\n"
            "3. 不得为了通过而删除、跳过或弱化已有测试。\n"
            "4. 修改后先运行相关测试，再运行下面所有必须验证器；普通 run_shell 结果"
            "不能代替最终 run_verification。\n"
            "5. 文档等不适合单元测试的修改不要强写无意义测试，但仍应运行适合的检查。\n"
            f"当前验证器：\n{available}"
        )

    def _iteration_context(self, state: TurnState) -> str:
        """生成仅用于本次模型调用的当前状态快照，不写入对话历史。"""

        verification_tool = self.dispatcher.registry.get("run_verification")
        required: frozenset[str] = frozenset()
        if isinstance(verification_tool, RunVerificationTool):
            required = verification_tool.required_validator_ids
        latest_verifications: dict[str, dict[str, object]] = {}
        for result in state.verification_history:
            if result.workspace_revision == state.workspace_revision:
                latest_verifications[result.validator_id] = {
                    "passed": result.passed,
                    "exit_code": result.exit_code,
                    "timed_out": result.timed_out,
                }
        for validator_id in required:
            latest_verifications.setdefault(
                validator_id,
                {"passed": False, "status": "not_run_for_current_revision"},
            )

        allowed_actions = self._allowed_action_types(state)
        final_outcomes = ["partial", "failed"]
        if state.phase in {TurnPhase.PREPARING, TurnPhase.EXECUTING} and not state.workspace_dirty:
            final_outcomes.insert(0, "success")
        config = self.loop_guard.config
        payload = {
            "turn_state": {
                "phase": state.phase.value,
                "workspace_dirty": state.workspace_dirty,
                "workspace_revision": state.workspace_revision,
                "modified_paths": list(state.modified_paths),
                "plan": [item.model_dump(mode="json") for item in state.plan],
                "verification_for_current_revision": latest_verifications,
                "required_validator_ids": sorted(required),
                "last_tool_execution": state.tool_execution.model_dump(mode="json")
                if state.tool_execution
                else None,
            },
            "budget": {
                "iteration": state.iterations,
                "max_iterations": config.max_iterations,
                "iterations_remaining_after_this_response": max(
                    config.max_iterations - state.iterations, 0
                ),
                "tool_calls_used": state.tool_calls,
                "tool_calls_remaining": max(
                    config.max_tool_calls - state.tool_calls, 0
                ),
                "reflections_used": state.reflections,
                "reflections_remaining": max(
                    config.max_reflections - state.reflections, 0
                ),
                "repeated_action_limit": config.repeated_action_limit,
            },
            "governance": {
                "permission_mode": self.policy.mode.value,
                "workspace_paths_must_be_relative_posix": True,
                "plan_requirement": {
                    "side_effect_tool_requires_plan": not state.has_plan,
                    "next_read_only_tool_requires_plan": not state.has_plan
                    and state.tool_calls >= 2,
                    "simple_read_only_task_should_skip_plan": not state.has_plan
                    and state.tool_calls < 2,
                },
                "prefer_dedicated_read_tools_over_shell": True,
                "must_obey_user_forbidden_operations": True,
            },
            "allowed_next_action_types": allowed_actions,
            "allowed_final_outcomes": final_outcomes,
        }
        return (
            "HARNESS_CURRENT_STATE（系统生成的本轮事实）：\n"
            + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            + "\n只返回一个符合完整 Action Schema 的 JSON 对象。"
            "如果需要工具结果，本轮只请求工具，不要同时编造最终答案。"
        )

    @staticmethod
    def _allowed_action_types(state: TurnState) -> list[str]:
        """按状态机规则给模型列出当前真正可接受的 Action 类型。"""

        if state.phase == TurnPhase.PLANNING:
            allowed = ["plan", "ask_clarification", "final"]
            if state.plan:
                allowed.insert(1, "update_plan")
            return allowed
        if state.phase == TurnPhase.PREPARING:
            return ["tool_call", "final", "plan", "ask_clarification", "reflect"]
        if state.phase == TurnPhase.EXECUTING:
            allowed = ["tool_call", "final", "plan", "ask_clarification", "reflect"]
            if state.plan:
                allowed.insert(2, "update_plan")
            return allowed
        return []

    @staticmethod
    def _result(
        state: TurnState,
        messages: Sequence[ChatMessage],
        tool_results: Sequence[dict[str, object]],
        verification_results: Sequence[VerificationResult],
    ) -> AgentLoopResult:
        return AgentLoopResult(
            state=state,
            messages=tuple(messages),
            tool_results=tuple(tool_results),
            verification_results=tuple(verification_results),
        )
