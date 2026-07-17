"""M2 纵向切片：Mock LLM 对真实工作区完成受控只读分析。"""

import tempfile
import unittest
from pathlib import Path

from harness_agent.agent.action_parser import ActionParser
from harness_agent.agent.loop import AgentLoop
from harness_agent.agent.loop_guard import LoopGuard
from harness_agent.agent.state import TurnPhase
from harness_agent.agent.state_machine import StateMachine
from harness_agent.agent.verification import VerificationService
from harness_agent.governance.policy import PermissionMode, PolicyEngine
from harness_agent.llm.mock import MockLLMClient
from harness_agent.runtime.workspace import LocalWorkspace
from harness_agent.tools.dispatcher import ToolDispatcher
from harness_agent.tools.models import ExecutionContext
from harness_agent.tools.readonly import readonly_tools
from harness_agent.tools.registry import ToolRegistry


class M2ReadonlyLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_mock_analyzes_real_local_project_through_policy_and_dispatcher(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("def answer():\n    return 42\n", encoding="utf-8")
            registry = ToolRegistry(list(readonly_tools()))
            loop = AgentLoop(
                llm=MockLLMClient(
                    [
                        '{"schema_version":1,"type":"tool_call","tool":"list_directory","arguments":{"path":"."}}',
                        '{"schema_version":1,"type":"tool_call","tool":"read_file","arguments":{"path":"app.py"}}',
                        '{"schema_version":1,"type":"final","outcome":"success","message":"answer 返回 42"}',
                    ]
                ),
                parser=ActionParser(),
                state_machine=StateMachine(),
                loop_guard=LoopGuard(),
                policy=PolicyEngine(PermissionMode.READ_ONLY),
                dispatcher=ToolDispatcher(registry),
                verification_service=VerificationService(),
                workspace=LocalWorkspace("project", root, read_only=True),
                execution_context=ExecutionContext(turn_id="m2"),
            )

            result = await loop.run("分析 answer 的返回值")

            self.assertEqual(result.state.phase, TurnPhase.COMPLETED)
            self.assertEqual(result.state.final_message, "answer 返回 42")
            self.assertEqual(result.state.tool_calls, 2)
            self.assertEqual(len(result.tool_results), 2)
            self.assertIn("return 42", result.messages[-2].content)


if __name__ == "__main__":
    unittest.main()
