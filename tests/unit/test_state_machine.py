"""StateMachine 的合法转换与门禁测试。"""

import unittest

from harness_agent.agent.action_parser import ActionParser
from harness_agent.agent.actions import FinalOutcome, PlanItemStatus
from harness_agent.agent.state import TurnPhase, TurnState
from harness_agent.agent.state_machine import (
    StateMachine,
    StateTransitionError,
    TransitionErrorCode,
)


class StateMachineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = ActionParser()
        self.machine = StateMachine()
        self.state = self.machine.start(TurnState())

    def parse(self, body: str):  # type: ignore[no-untyped-def]
        return self.parser.parse(body)

    def test_simple_final_completes_without_plan(self) -> None:
        final = self.parse(
            '{"schema_version":1,"type":"final","outcome":"success",'
            '"message":"只读回答完成"}'
        )

        completed = self.machine.apply_action(self.state, final)

        self.assertEqual(completed.phase, TurnPhase.COMPLETED)
        self.assertEqual(completed.outcome, FinalOutcome.SUCCESS)

    def test_plan_then_update(self) -> None:
        plan = self.parse(
            '{"schema_version":1,"type":"plan","items":['
            '{"id":"inspect","description":"检查"},'
            '{"id":"report","description":"报告"}]}'
        )
        state = self.machine.apply_action(self.state, plan)
        update = self.parse(
            '{"schema_version":1,"type":"update_plan","updates":['
            '{"item_id":"inspect","status":"completed"},'
            '{"item_id":"report","status":"in_progress"}]}'
        )

        state = self.machine.apply_action(state, update)

        self.assertEqual(state.phase, TurnPhase.EXECUTING)
        self.assertEqual(state.plan[0].status, PlanItemStatus.COMPLETED)
        self.assertEqual(state.plan[1].status, PlanItemStatus.IN_PROGRESS)

    def test_plan_required_rejects_direct_tool_call(self) -> None:
        tool_call = self.parse(
            '{"schema_version":1,"type":"tool_call","tool":"apply_patch",'
            '"arguments":{"patch":"diff"}}'
        )

        with self.assertRaises(StateTransitionError) as raised:
            self.machine.apply_action(self.state, tool_call, plan_required=True)

        self.assertEqual(raised.exception.code, TransitionErrorCode.PLAN_REQUIRED)

    def test_third_read_only_tool_call_requires_plan(self) -> None:
        state = self.machine.record_tool_call(self.state)
        state = self.machine.record_tool_call(state)

        self.assertTrue(
            self.machine.requires_plan_for_tool(state, has_side_effect=False)
        )
        self.assertTrue(
            self.machine.requires_plan_for_tool(self.state, has_side_effect=True)
        )
        self.assertFalse(
            self.machine.requires_plan_for_tool(self.state, has_side_effect=False)
        )

    def test_dirty_workspace_blocks_success_final(self) -> None:
        dirty = self.machine.record_write_succeeded(self.state)
        final = self.parse(
            '{"schema_version":1,"type":"final","outcome":"success",'
            '"message":"完成"}'
        )

        with self.assertRaises(StateTransitionError) as raised:
            self.machine.apply_action(dirty, final)

        self.assertEqual(raised.exception.code, TransitionErrorCode.DIRTY_WORKSPACE)

    def test_verification_pass_clears_dirty(self) -> None:
        state = self.machine.record_write_succeeded(self.state)
        state = self.machine.apply_action(
            state,
            self.parse(
                '{"schema_version":1,"type":"plan","items":['
                '{"id":"verify","description":"验证"}]}'
            ),
        )
        state = self.machine.record_verification_started(state)
        state = self.machine.record_verification_finished(
            state, all_required_passed=True
        )

        self.assertFalse(state.workspace_dirty)
        self.assertEqual(state.workspace_revision, 1)
        self.assertEqual(state.phase, TurnPhase.EXECUTING)

    def test_clarification_suspends_and_resumes_previous_phase(self) -> None:
        clarification = self.parse(
            '{"schema_version":1,"type":"ask_clarification",'
            '"question":"选择目标？"}'
        )

        waiting = self.machine.apply_action(self.state, clarification)
        resumed = self.machine.resume_waiting(waiting)

        self.assertEqual(waiting.phase, TurnPhase.WAITING_FOR_USER)
        self.assertEqual(waiting.suspended_phase, TurnPhase.PREPARING)
        self.assertEqual(resumed.phase, TurnPhase.PREPARING)
        self.assertIsNone(resumed.suspended_phase)

    def test_terminal_state_rejects_new_action(self) -> None:
        final = self.parse(
            '{"schema_version":1,"type":"final","outcome":"success",'
            '"message":"完成"}'
        )
        completed = self.machine.apply_action(self.state, final)

        with self.assertRaises(StateTransitionError) as raised:
            self.machine.apply_action(completed, final)

        self.assertEqual(raised.exception.code, TransitionErrorCode.TERMINAL_STATE)


if __name__ == "__main__":
    unittest.main()
