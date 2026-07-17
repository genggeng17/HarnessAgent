"""M3 纵向切片：修改、验证、修复与资源耗尽场景。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

from harness_agent.agent.action_parser import ActionParser
from harness_agent.agent.loop import AgentLoop
from harness_agent.agent.loop_guard import LoopGuard, LoopGuardConfig
from harness_agent.agent.state import TurnPhase
from harness_agent.agent.state_machine import StateMachine
from harness_agent.agent.verification import VerificationService
from harness_agent.governance.policy import PolicyEngine
from harness_agent.llm.mock import MockLLMClient
from harness_agent.runtime.workspace import LocalWorkspace
from harness_agent.tools.dispatcher import ToolDispatcher
from harness_agent.tools.models import ExecutionContext
from harness_agent.tools.patch import ApplyPatchTool
from harness_agent.tools.registry import ToolRegistry
from harness_agent.tools.shell import RunShellTool, ShellExecutor
from harness_agent.tools.verification_tool import RunVerificationTool, ValidatorConfig


def action(action_type: str, **payload: object) -> str:
    return json.dumps(
        {"schema_version": 1, "type": action_type, **payload}, ensure_ascii=False
    )


def replacement(old: str, new: str) -> str:
    return f"--- a/value.txt\n+++ b/value.txt\n@@ -1 +1 @@\n-{old}\n+{new}\n"


class M3EditVerifyLoopTests(unittest.IsolatedAsyncioTestCase):
    def make_loop(
        self,
        root: Path,
        responses: list[str],
        *,
        guard: LoopGuard | None = None,
    ) -> AgentLoop:
        executor = ShellExecutor()
        validator = ValidatorConfig(
            id="value",
            argv=(
                sys.executable,
                "-c",
                "from pathlib import Path; raise SystemExit(0 if Path('value.txt').read_text().strip() == 'good' else 1)",
            ),
        )
        registry = ToolRegistry(
            [
                ApplyPatchTool(),
                RunShellTool(executor),
                RunVerificationTool(executor, [validator]),
            ]
        )
        return AgentLoop(
            llm=MockLLMClient(responses),
            parser=ActionParser(),
            state_machine=StateMachine(),
            loop_guard=guard or LoopGuard(),
            policy=PolicyEngine(),
            dispatcher=ToolDispatcher(registry),
            verification_service=VerificationService(),
            workspace=LocalWorkspace("project", root),
            execution_context=ExecutionContext(
                turn_id="m3", command_log_dir=root / ".logs"
            ),
        )

    @staticmethod
    def plan() -> str:
        return action(
            "plan",
            items=[
                {"id": "edit", "description": "修改文件"},
                {"id": "verify", "description": "运行验证"},
            ],
        )

    async def test_write_then_verification_passes_and_allows_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "value.txt").write_text("bad\n", encoding="utf-8")
            loop = self.make_loop(
                root,
                [
                    self.plan(),
                    action("tool_call", tool="apply_patch", arguments={"patch": replacement("bad", "good")}),
                    action("tool_call", tool="run_verification", arguments={"validator_id": "value"}),
                    action("final", outcome="success", message="修改和验证完成"),
                ],
            )

            result = await loop.run("把 value 改正确")

            self.assertEqual(result.state.phase, TurnPhase.COMPLETED)
            self.assertEqual(result.state.workspace_revision, 1)
            self.assertFalse(result.state.workspace_dirty)
            self.assertTrue(result.verification_results[0].passed)

    async def test_first_verification_fails_then_second_write_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "value.txt").write_text("bad\n", encoding="utf-8")
            loop = self.make_loop(
                root,
                [
                    self.plan(),
                    action("tool_call", tool="apply_patch", arguments={"patch": replacement("bad", "almost")}),
                    action("tool_call", tool="run_verification", arguments={"validator_id": "value"}),
                    action("tool_call", tool="apply_patch", arguments={"patch": replacement("almost", "good")}),
                    action("tool_call", tool="run_verification", arguments={"validator_id": "value"}),
                    action("final", outcome="success", message="修复后通过"),
                ],
            )

            result = await loop.run("修复 value")

            self.assertEqual(result.state.phase, TurnPhase.COMPLETED)
            self.assertEqual(result.state.workspace_revision, 2)
            self.assertEqual([item.passed for item in result.verification_results], [False, True])
            self.assertEqual((root / "value.txt").read_text(encoding="utf-8"), "good\n")

    async def test_persistent_failure_stops_at_tool_budget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "value.txt").write_text("bad\n", encoding="utf-8")
            verify = action("tool_call", tool="run_verification", arguments={"validator_id": "value"})
            loop = self.make_loop(
                root,
                [
                    self.plan(),
                    action("tool_call", tool="apply_patch", arguments={"patch": replacement("bad", "still_bad")}),
                    verify,
                    verify,
                    verify,
                ],
                guard=LoopGuard(
                    LoopGuardConfig(max_tool_calls=3, repeated_action_limit=10)
                ),
            )

            result = await loop.run("持续验证失败")

            self.assertEqual(result.state.phase, TurnPhase.FAILED)
            self.assertIn("最大工具调用次数", result.state.final_message or "")
            self.assertTrue(result.state.workspace_dirty)
            self.assertEqual(len(result.verification_results), 2)
            self.assertTrue(all(not item.passed for item in result.verification_results))


if __name__ == "__main__":
    unittest.main()
