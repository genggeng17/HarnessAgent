"""M1 纵向切片：Mock 输出经 Parser 和 StateMachine 完成 Turn。"""

import unittest

from harness_agent.agent.action_parser import ActionParser
from harness_agent.agent.state import TurnPhase, TurnState
from harness_agent.agent.state_machine import StateMachine
from harness_agent.llm.base import ChatMessage, MessageRole
from harness_agent.llm.mock import MockLLMClient


class M1MockTurnTests(unittest.IsolatedAsyncioTestCase):
    async def test_mock_can_drive_no_tool_turn_to_final(self) -> None:
        client = MockLLMClient(
            [
                '{"schema_version":1,"type":"final",'
                '"outcome":"success","message":"这是一个直接回答"}'
            ]
        )
        parser = ActionParser()
        machine = StateMachine()
        state = machine.start(TurnState())
        state = machine.record_iteration(state)

        response = await client.complete(
            [ChatMessage(role=MessageRole.USER, content="直接回答这个简单问题")]
        )
        parsed = parser.parse(response.content)
        state = machine.apply_action(state, parsed)

        self.assertEqual(state.phase, TurnPhase.COMPLETED)
        self.assertEqual(state.iterations, 1)
        self.assertEqual(state.final_message, "这是一个直接回答")


if __name__ == "__main__":
    unittest.main()

