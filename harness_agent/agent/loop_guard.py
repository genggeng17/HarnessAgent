"""AgentLoop 的确定性资源与重复动作限制。"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from harness_agent.agent.state import TurnState


class GuardStopReason(StrEnum):
    """循环停止原因。"""

    MAX_ITERATIONS = "max_iterations"
    MAX_TOOL_CALLS = "max_tool_calls"
    MAX_REFLECTIONS = "max_reflections"
    REPEATED_ACTION = "repeated_action"


class LoopGuardConfig(BaseModel):
    """第一阶段循环资源限制。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_iterations: int = Field(default=20, ge=1)
    max_tool_calls: int = Field(default=40, ge=1)
    max_reflections: int = Field(default=3, ge=0)
    repeated_action_limit: int = Field(default=3, ge=2)


class GuardDecision(BaseModel):
    """LoopGuard 的纯判断结果。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed: bool
    reason: GuardStopReason | None = None
    message: str | None = None


class LoopGuard:
    """只读取 TurnState，不自行修改计数或终止状态。"""

    def __init__(self, config: LoopGuardConfig | None = None) -> None:
        self.config = config or LoopGuardConfig()

    def before_iteration(self, state: TurnState) -> GuardDecision:
        """下一次 LLM 调用前检查迭代预算。"""

        if state.iterations >= self.config.max_iterations:
            return self._stop(
                GuardStopReason.MAX_ITERATIONS,
                f"达到最大迭代次数 {self.config.max_iterations}",
            )
        return GuardDecision(allowed=True)

    def before_tool_call(self, state: TurnState) -> GuardDecision:
        """下一次工具调用前检查工具预算。"""

        if state.tool_calls >= self.config.max_tool_calls:
            return self._stop(
                GuardStopReason.MAX_TOOL_CALLS,
                f"达到最大工具调用次数 {self.config.max_tool_calls}",
            )
        return GuardDecision(allowed=True)

    def before_reflection(self, state: TurnState) -> GuardDecision:
        """下一次 ReflectAction 前检查反思预算。"""

        if state.reflections >= self.config.max_reflections:
            return self._stop(
                GuardStopReason.MAX_REFLECTIONS,
                f"达到最大 ReflectAction 次数 {self.config.max_reflections}",
            )
        return GuardDecision(allowed=True)

    def check_repeated_action(
        self, state: TurnState, next_digest: str
    ) -> GuardDecision:
        """连续出现相同 Action Digest 时停止，避免无意义循环。"""

        needed_previous = self.config.repeated_action_limit - 1
        previous = state.recent_action_digests[-needed_previous:]
        if len(previous) == needed_previous and all(
            digest == next_digest for digest in previous
        ):
            return self._stop(
                GuardStopReason.REPEATED_ACTION,
                f"同一 Action 已连续出现 {self.config.repeated_action_limit} 次",
            )
        return GuardDecision(allowed=True)

    @staticmethod
    def _stop(reason: GuardStopReason, message: str) -> GuardDecision:
        return GuardDecision(allowed=False, reason=reason, message=message)

