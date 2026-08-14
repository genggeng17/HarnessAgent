"""M3 纵向切片：修改、验证、修复与资源耗尽场景。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

import pytest

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
from harness_agent.tools.readonly import readonly_tools
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
        validators: list[ValidatorConfig] | None = None,
    ) -> AgentLoop:
        executor = ShellExecutor()
        if validators is None:
            validators = [
                ValidatorConfig(
                    id="value",
                    argv=(
                        sys.executable,
                        "-c",
                        "from pathlib import Path; raise SystemExit(0 if Path('value.txt').read_text().strip() == 'good' else 1)",
                    ),
                )
            ]
        registry = ToolRegistry(
            [
                ApplyPatchTool(),
                RunShellTool(executor),
                RunVerificationTool(executor, validators),
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
                    action("tool_call", tool="run_verification", arguments={"validator_id": "value"}),
                    action("tool_call", tool="apply_patch", arguments={"patch": replacement("bad", "good")}),
                    action("tool_call", tool="run_verification", arguments={"validator_id": "value"}),
                    action("final", outcome="success", message="修改和验证完成"),
                ],
            )

            result = await loop.run("把 value 改正确")

            self.assertEqual(result.state.phase, TurnPhase.COMPLETED)
            self.assertEqual(result.state.workspace_revision, 1)
            self.assertFalse(result.state.workspace_dirty)
            self.assertEqual(
                [item.passed for item in result.verification_results], [False, True]
            )
            self.assertEqual(result.state.modified_paths, ("value.txt",))
            self.assertEqual(len(result.state.verification_history), 2)

    async def test_testing_contract_exposes_validator_and_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            loop = self.make_loop(root, [])

            contract = loop._testing_contract()

            self.assertIn("修改前先查看", contract)
            self.assertIn("优先复用已有测试", contract)
            self.assertIn("value", contract)

    async def test_auto_discovered_generated_test_can_complete_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "value.txt").write_text("bad\n", encoding="utf-8")
            patch = replacement("bad", "good") + (
                "--- /dev/null\n"
                "+++ b/tests/test_value.py\n"
                "@@ -0,0 +1,4 @@\n"
                "+from pathlib import Path\n"
                "+\n"
                "+def test_value():\n"
                "+    assert Path('value.txt').read_text().strip() == 'good'\n"
            )
            loop = self.make_loop(
                root,
                [
                    self.plan(),
                    action("tool_call", tool="apply_patch", arguments={"patch": patch}),
                    action(
                        "tool_call",
                        tool="run_verification",
                        arguments={"validator_id": "auto"},
                    ),
                    action("final", outcome="success", message="新增测试并验证完成"),
                ],
                validators=[],
            )

            result = await loop.run("修改 value 并补充测试")

            self.assertEqual(result.state.phase, TurnPhase.COMPLETED)
            self.assertFalse(result.state.workspace_dirty)
            self.assertEqual(
                result.state.verification_history[-1].validator_id, "python_tests"
            )

    async def test_failed_auto_discovery_cannot_bypass_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "value.txt").write_text("bad\n", encoding="utf-8")
            loop = self.make_loop(
                root,
                [
                    self.plan(),
                    action(
                        "tool_call",
                        tool="apply_patch",
                        arguments={"patch": replacement("bad", "good")},
                    ),
                    action(
                        "tool_call",
                        tool="run_verification",
                        arguments={"validator_id": "auto"},
                    ),
                    action("final", outcome="success", message="错误放行"),
                    action("final", outcome="partial", message="缺少可用测试"),
                ],
                validators=[],
            )

            result = await loop.run("修改但没有测试配置")

            self.assertEqual(result.state.phase, TurnPhase.FAILED)
            self.assertTrue(result.state.workspace_dirty)
            self.assertFalse(result.state.verification_history[-1].passed)

    @pytest.mark.mechanism_demo
    async def test_first_verification_fails_then_second_write_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "value.txt").write_text("bad\n", encoding="utf-8")
            loop = self.make_loop(
                root,
                [
                    self.plan(),
                    action("tool_call", tool="run_verification", arguments={"validator_id": "value"}),
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
            self.assertEqual(
                [item.passed for item in result.verification_results],
                [False, False, True],
            )
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
                    verify,
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

    async def test_second_patch_failure_requires_full_read_before_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "value.txt").write_text("bad\n", encoding="utf-8")
            loop = self.make_loop(
                root,
                [
                    self.plan(),
                    action(
                        "tool_call",
                        tool="apply_patch",
                        arguments={"patch": replacement("missing-1", "good")},
                    ),
                    action(
                        "tool_call",
                        tool="apply_patch",
                        arguments={"patch": replacement("missing-2", "good")},
                    ),
                    action(
                        "tool_call",
                        tool="apply_patch",
                        arguments={"patch": replacement("bad", "good")},
                    ),
                    action(
                        "tool_call",
                        tool="read_file",
                        arguments={"path": "value.txt"},
                    ),
                    action(
                        "tool_call",
                        tool="apply_patch",
                        arguments={"patch": replacement("bad", "good")},
                    ),
                    action("final", outcome="partial", message="恢复修改完成但无验证器"),
                ],
                validators=[],
            )
            loop.dispatcher.registry.register(readonly_tools()[1])

            result = await loop.run("恢复 Patch 失败")

            self.assertEqual((root / "value.txt").read_text(encoding="utf-8"), "good\n")
            self.assertIsNone(result.state.edit_recovery)
            self.assertEqual(result.state.workspace_revision, 1)
            self.assertTrue(
                any("必须完整读取" in message.content for message in result.messages)
            )

    @pytest.mark.mechanism_demo
    async def test_third_patch_failure_stops_without_shell_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "value.txt").write_text("bad\n", encoding="utf-8")
            loop = self.make_loop(
                root,
                [
                    self.plan(),
                    action(
                        "tool_call",
                        tool="apply_patch",
                        arguments={"patch": replacement("missing-1", "good")},
                    ),
                    action(
                        "tool_call",
                        tool="apply_patch",
                        arguments={"patch": replacement("missing-2", "good")},
                    ),
                    action("tool_call", tool="read_file", arguments={"path": "value.txt"}),
                    action(
                        "tool_call",
                        tool="apply_patch",
                        arguments={"patch": replacement("missing-3", "good")},
                    ),
                ],
                validators=[],
                guard=LoopGuard(LoopGuardConfig(repeated_action_limit=10)),
            )
            loop.dispatcher.registry.register(readonly_tools()[1])

            result = await loop.run("连续修改失败")

            self.assertEqual(result.state.phase, TurnPhase.FAILED)
            self.assertIn("连续修改失败 3 次", result.state.final_message or "")
            self.assertEqual((root / "value.txt").read_text(encoding="utf-8"), "bad\n")


if __name__ == "__main__":
    unittest.main()
