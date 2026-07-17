"""LoopGuard 资源限制测试。"""

import unittest

from harness_agent.agent.loop_guard import (
    GuardStopReason,
    LoopGuard,
    LoopGuardConfig,
)
from harness_agent.agent.state import TurnState


class LoopGuardTests(unittest.TestCase):
    def test_iteration_limit(self) -> None:
        guard = LoopGuard(LoopGuardConfig(max_iterations=2))
        state = TurnState(iterations=2)

        decision = guard.before_iteration(state)

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, GuardStopReason.MAX_ITERATIONS)

    def test_tool_call_below_limit(self) -> None:
        guard = LoopGuard(LoopGuardConfig(max_tool_calls=2))
        state = TurnState(tool_calls=1)

        self.assertTrue(guard.before_tool_call(state).allowed)

    def test_third_identical_action_is_rejected(self) -> None:
        guard = LoopGuard(LoopGuardConfig(repeated_action_limit=3))
        state = TurnState(recent_action_digests=("same", "same"))

        decision = guard.check_repeated_action(state, "same")

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, GuardStopReason.REPEATED_ACTION)

    def test_non_consecutive_digest_is_allowed(self) -> None:
        guard = LoopGuard(LoopGuardConfig(repeated_action_limit=3))
        state = TurnState(recent_action_digests=("same", "different"))

        self.assertTrue(guard.check_repeated_action(state, "same").allowed)


if __name__ == "__main__":
    unittest.main()

