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
from harness_agent.agent.verification import VerificationResult


def verification(
    validator_id: str, *, revision: int = 1, passed: bool = True
) -> VerificationResult:
    return VerificationResult(
        verification_id=f"verification-{validator_id}-{passed}",
        validator_id=validator_id,
        workspace_revision=revision,
        tool_call_id=f"call-{validator_id}",
        passed=passed,
        exit_code=0 if passed else 1,
        timed_out=False,
        output_summary="",
        tool_result_ref=f"tool_result:call-{validator_id}",
        command_log_ref=None,
    )


class StateMachineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = ActionParser()
        self.machine = StateMachine()
        self.state = self.machine.start(TurnState())

    def parse(self, body: str):  # type: ignore[no-untyped-def]
        return self.parser.parse(body)

    def dirty_executing_state(self) -> TurnState:
        state = self.machine.record_write_succeeded(self.state)
        return self.machine.apply_action(
            state,
            self.parse(
                '{"schema_version":1,"type":"plan","items":['
                '{"id":"verify","description":"运行验证"}]}'
            ),
        )

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
            state,
            verification=verification("tests"),
            required_validator_ids=frozenset({"tests"}),
        )

        self.assertFalse(state.workspace_dirty)
        self.assertEqual(state.workspace_revision, 1)
        self.assertEqual(state.phase, TurnPhase.EXECUTING)
        self.assertEqual(state.verification_history[0].validator_id, "tests")

    def test_empty_required_validators_never_clear_dirty_workspace(self) -> None:
        state = self.dirty_executing_state()
        state = self.machine.record_verification_started(state)

        state = self.machine.record_verification_finished(
            state,
            verification=verification("missing"),
            required_validator_ids=frozenset(),
        )

        self.assertTrue(state.workspace_dirty)

    def test_multiple_validator_progress_survives_state_reload(self) -> None:
        state = self.dirty_executing_state()
        state = self.machine.record_verification_started(state)
        state = self.machine.record_verification_finished(
            state,
            verification=verification("unit"),
            required_validator_ids=frozenset({"unit", "integration"}),
        )
        reloaded = TurnState.model_validate_json(state.model_dump_json())
        self.assertTrue(reloaded.workspace_dirty)

        reloaded = self.machine.record_verification_started(reloaded)
        reloaded = self.machine.record_verification_finished(
            reloaded,
            verification=verification("integration"),
            required_validator_ids=frozenset({"unit", "integration"}),
        )

        self.assertFalse(reloaded.workspace_dirty)

    def test_later_required_failure_invalidates_previous_pass(self) -> None:
        state = self.dirty_executing_state()
        state = self.machine.record_verification_started(state)
        state = self.machine.record_verification_finished(
            state,
            verification=verification("tests"),
            required_validator_ids=frozenset({"tests"}),
        )
        self.assertFalse(state.workspace_dirty)

        state = self.machine.record_verification_started(state)
        state = self.machine.record_verification_finished(
            state,
            verification=verification("tests", passed=False),
            required_validator_ids=frozenset({"tests"}),
        )

        self.assertTrue(state.workspace_dirty)

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
