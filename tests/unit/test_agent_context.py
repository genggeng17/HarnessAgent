"""模型协议、动态状态和格式纠错上下文测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
from collections.abc import Sequence
from pathlib import Path

from harness_agent.agent.action_parser import ActionParser
from harness_agent.agent.loop import AgentLoop
from harness_agent.agent.loop_guard import LoopGuard
from harness_agent.agent.state_machine import StateMachine
from harness_agent.agent.verification import VerificationService
from harness_agent.governance.policy import PermissionMode, PolicyEngine
from harness_agent.llm.base import ChatMessage, LLMResponse, MessageRole
from harness_agent.runtime.workspace import LocalWorkspace
from harness_agent.tools.dispatcher import ToolDispatcher
from harness_agent.tools.models import ExecutionContext
from harness_agent.tools.readonly import readonly_tools
from harness_agent.tools.registry import ToolRegistry


class RecordingLLM:
    """保存每次收到的上下文，同时按顺序返回固定 Action。"""

    def __init__(self, responses: Sequence[str]) -> None:
        self.responses = tuple(responses)
        self.cursor = 0
        self.calls: list[tuple[ChatMessage, ...]] = []

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        tool_specs: Sequence[dict[str, object]] = (),
    ) -> LLMResponse:
        del tool_specs
        self.calls.append(tuple(messages))
        content = self.responses[self.cursor]
        self.cursor += 1
        return LLMResponse(content=content, model="recording")


class AgentContextTests(unittest.IsolatedAsyncioTestCase):
    def make_loop(self, root: Path, client: RecordingLLM) -> AgentLoop:
        return AgentLoop(
            llm=client,
            parser=ActionParser(),
            state_machine=StateMachine(),
            loop_guard=LoopGuard(),
            policy=PolicyEngine(PermissionMode.READ_ONLY),
            dispatcher=ToolDispatcher(ToolRegistry(list(readonly_tools()))),
            verification_service=VerificationService(),
            workspace=LocalWorkspace("context", root, read_only=True),
            execution_context=ExecutionContext(turn_id="context"),
            project_instructions="所有回答使用中文。",
        )

    async def test_each_call_receives_current_state_and_budget_ephemerally(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = RecordingLLM(
                [
                    '{"schema_version":1,"type":"final",'
                    '"outcome":"success","message":"完成"}'
                ]
            )
            loop = self.make_loop(Path(directory), client)

            result = await loop.run("直接回答")

            snapshot = client.calls[0][-1]
            self.assertEqual(snapshot.role, MessageRole.SYSTEM)
            self.assertIn("HARNESS_CURRENT_STATE", snapshot.content)
            self.assertIn('"phase":"preparing"', snapshot.content)
            self.assertIn('"iteration":1', snapshot.content)
            self.assertIn('"iterations_remaining_after_this_response":19', snapshot.content)
            self.assertIn('"permission_mode":"READ_ONLY"', snapshot.content)
            self.assertIn(
                '"simple_read_only_task_should_skip_plan":true', snapshot.content
            )
            self.assertIn(
                '"prefer_dedicated_read_tools_over_shell":true', snapshot.content
            )
            self.assertTrue(
                any("所有回答使用中文" in message.content for message in client.calls[0])
            )
            self.assertFalse(
                any("HARNESS_CURRENT_STATE" in message.content for message in result.messages)
            )

    async def test_parse_error_returns_exact_protocol_correction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = RecordingLLM(
                [
                    '{"tool":"read_file","arguments":{"path":"README.md"}}',
                    '{"schema_version":1,"type":"final",'
                    '"outcome":"success","message":"已修正"}',
                ]
            )
            loop = self.make_loop(Path(directory), client)

            await loop.run("测试纠错")

            correction = next(
                message
                for message in client.calls[1]
                if message.role == MessageRole.TOOL
                and "action_parse_error" in message.content
            )
            payload = json.loads(correction.content)
            self.assertEqual(payload["correction"]["schema_version"], 1)
            self.assertIn("tool_call", payload["correction"]["allowed_types"])
            self.assertIn("action", payload["correction"]["forbidden_wrappers"])


if __name__ == "__main__":
    unittest.main()
