"""M2/M3 最小 AgentLoop：模型、治理、工具和验证的确定性协调者。"""

from __future__ import annotations

import json
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from harness_agent.agent.action_parser import ActionParseError, ActionParser
from harness_agent.agent.actions import (
    FinalAction,
    ReflectAction,
    ToolCallAction,
)
from harness_agent.agent.loop_guard import LoopGuard
from harness_agent.agent.state import TERMINAL_PHASES, TurnState
from harness_agent.agent.state_machine import StateMachine, StateTransitionError
from harness_agent.agent.verification import VerificationResult, VerificationService
from harness_agent.governance.policy import PolicyEngine, PolicyOutcome
from harness_agent.llm.base import ChatMessage, LLMClient, MessageRole
from harness_agent.runtime.workspace import LocalWorkspace
from harness_agent.tools.dispatcher import ToolDispatcher
from harness_agent.tools.models import ExecutionContext, SideEffect, ToolKind, ToolResultStatus
from harness_agent.tools.verification_tool import RunVerificationTool


class AgentLoopResult(BaseModel):
    """M2/M3 可测试的 Turn 结果。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: TurnState
    messages: tuple[ChatMessage, ...]
    tool_results: tuple[dict[str, object], ...] = ()
    verification_results: tuple[VerificationResult, ...] = ()


class AgentLoop:
    """不直接执行工具，也不解释工具失败。"""

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

    async def run(
        self,
        user_task: str,
        *,
        initial_state: TurnState | None = None,
        prior_messages: Sequence[ChatMessage] = (),
    ) -> AgentLoopResult:
        """运行到终态或等待态；M4 前不处理审批恢复。"""

        state = initial_state or self.state_machine.start(TurnState())
        messages = [*prior_messages, ChatMessage(role=MessageRole.USER, content=user_task)]
        tool_results: list[dict[str, object]] = []
        verification_results: list[VerificationResult] = []
        passed_revisions: dict[str, int] = {}

        while state.phase not in TERMINAL_PHASES:
            guard = self.loop_guard.before_iteration(state)
            if not guard.allowed:
                state = self.state_machine.fail(state, guard.message or "迭代资源耗尽")
                break
            state = self.state_machine.record_iteration(state)
            response = await self.llm.complete(messages, self.dispatcher.registry.specs())
            messages.append(ChatMessage(role=MessageRole.ASSISTANT, content=response.content))
            try:
                parsed = self.parser.parse(response.content)
            except ActionParseError as exc:
                messages.append(self._observation("action_parse_error", exc.message))
                continue

            repeated = self.loop_guard.check_repeated_action(state, parsed.digest)
            if not repeated.allowed:
                state = self.state_machine.fail(state, repeated.message or "Action 重复")
                break
            action = parsed.action

            if isinstance(action, ReflectAction):
                reflection_guard = self.loop_guard.before_reflection(state)
                if not reflection_guard.allowed:
                    state = self.state_machine.fail(
                        state, reflection_guard.message or "反思资源耗尽"
                    )
                    break

            if isinstance(action, ToolCallAction):
                tool = self.dispatcher.registry.get(action.tool)
                if tool is None:
                    try:
                        state = self.state_machine.apply_action(state, parsed)
                    except StateTransitionError as exc:
                        messages.append(self._observation(exc.code.value, exc.message))
                        continue
                    messages.append(self._observation("tool_not_found", f"工具未注册：{action.tool}"))
                    continue
                needs_plan = self.state_machine.requires_plan_for_tool(
                    state, has_side_effect=tool.side_effect != SideEffect.NONE
                )
                if needs_plan:
                    state = self.state_machine.mark_plan_required(state)
                    messages.append(self._observation("plan_required", "该工具调用前必须先建立计划"))
                    continue
                tool_guard = self.loop_guard.before_tool_call(state)
                if not tool_guard.allowed:
                    state = self.state_machine.fail(
                        state, tool_guard.message or "工具调用资源耗尽"
                    )
                    break
                try:
                    next_state = self.state_machine.apply_action(state, parsed)
                except StateTransitionError as exc:
                    messages.append(self._observation(exc.code.value, exc.message))
                    continue
                decision = self.policy.evaluate(tool, action.arguments, self.workspace)
                if decision.outcome != PolicyOutcome.ALLOW:
                    messages.append(
                        self._observation(
                            f"policy_{decision.outcome.value.lower()}", decision.reason
                        )
                    )
                    continue
                state = self.state_machine.record_tool_call(next_state)
                if tool.kind == ToolKind.VERIFICATION:
                    state = self.state_machine.record_verification_started(state)
                result = await self.dispatcher.dispatch(
                    action.tool,
                    action.arguments,
                    self.workspace,
                    self.execution_context,
                )
                dumped = result.model_dump(mode="json")
                tool_results.append(dumped)
                if (
                    tool.kind == ToolKind.WRITE
                    and result.status == ToolResultStatus.SUCCEEDED
                    and result.modified_paths
                ):
                    state = self.state_machine.record_write_succeeded(state)
                    passed_revisions.clear()

                if tool.kind == ToolKind.VERIFICATION:
                    validator_id = str(result.data.get("validator_id", action.arguments.get("validator_id", "")))
                    verification = self.verification_service.evaluate(
                        result,
                        validator_id=validator_id,
                        workspace_revision=state.workspace_revision,
                    )
                    verification_results.append(verification)
                    if verification.passed:
                        passed_revisions[validator_id] = state.workspace_revision
                    else:
                        passed_revisions.pop(validator_id, None)
                    required = (
                        tool.required_validator_ids
                        if isinstance(tool, RunVerificationTool)
                        else frozenset({validator_id})
                    )
                    all_passed = all(
                        passed_revisions.get(item) == state.workspace_revision
                        for item in required
                    )
                    state = self.state_machine.record_verification_finished(
                        state, all_required_passed=all_passed
                    )
                    messages.append(
                        self._observation(
                            "verification_result",
                            json.dumps(verification.model_dump(mode="json"), ensure_ascii=False),
                        )
                    )
                else:
                    messages.append(
                        self._observation(
                            "tool_result", json.dumps(dumped, ensure_ascii=False)
                        )
                    )
                continue

            try:
                state = self.state_machine.apply_action(state, parsed)
            except StateTransitionError as exc:
                messages.append(self._observation(exc.code.value, exc.message))
                continue
            if isinstance(action, FinalAction):
                break

        return AgentLoopResult(
            state=state,
            messages=tuple(messages),
            tool_results=tuple(tool_results),
            verification_results=tuple(verification_results),
        )

    @staticmethod
    def _observation(code: str, message: str) -> ChatMessage:
        body = json.dumps({"code": code, "message": message}, ensure_ascii=False)
        return ChatMessage(role=MessageRole.TOOL, content=body)
