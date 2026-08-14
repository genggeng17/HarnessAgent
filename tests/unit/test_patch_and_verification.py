"""Patch、统一 Shell 与 VerificationService 测试。"""

import sys
import tempfile
import unittest
from pathlib import Path

from harness_agent.agent.verification import VerificationService
from harness_agent.runtime.workspace import LocalWorkspace
from harness_agent.tools.dispatcher import ToolDispatcher
from harness_agent.tools.models import ExecutionContext, ToolResult, ToolResultStatus
from harness_agent.tools.patch import ApplyPatchTool, BatchExactEditTool, ExactEditTool
from harness_agent.tools.readonly import ReadFilesTool
from harness_agent.tools.registry import ToolRegistry
from harness_agent.tools.shell import ShellExecutor
from harness_agent.tools.verification_tool import RunVerificationTool, ValidatorConfig


class PatchAndVerificationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "value.txt").write_text("bad\n", encoding="utf-8")
        self.workspace = LocalWorkspace("test", self.root)
        self.context = ExecutionContext(
            turn_id="turn", command_log_dir=self.root / ".logs", max_tool_output_chars=100
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    async def test_patch_modifies_and_creates_files(self) -> None:
        dispatcher = ToolDispatcher(ToolRegistry([ApplyPatchTool()]))
        patch = (
            "--- a/value.txt\n+++ b/value.txt\n@@ -1 +1 @@\n-bad\n+good\n"
            "--- /dev/null\n+++ b/new.txt\n@@ -0,0 +1 @@\n+new\n"
        )

        result = await dispatcher.dispatch(
            "apply_patch", {"patch": patch}, self.workspace, self.context
        )

        self.assertEqual(result.status, ToolResultStatus.SUCCEEDED)
        self.assertEqual((self.root / "value.txt").read_text(encoding="utf-8"), "good\n")
        self.assertEqual((self.root / "new.txt").read_text(encoding="utf-8"), "new\n")
        self.assertEqual(result.modified_paths, ("value.txt", "new.txt"))

    async def test_patch_context_mismatch_does_not_partially_write(self) -> None:
        dispatcher = ToolDispatcher(ToolRegistry([ApplyPatchTool()]))
        patch = "--- a/value.txt\n+++ b/value.txt\n@@ -1 +1 @@\n-other\n+good\n"

        result = await dispatcher.dispatch(
            "apply_patch", {"patch": patch}, self.workspace, self.context
        )

        self.assertEqual(result.status, ToolResultStatus.INVALID_ARGUMENTS)
        self.assertEqual((self.root / "value.txt").read_text(encoding="utf-8"), "bad\n")
        failure = result.data["edit_failure"]
        self.assertEqual(failure["path"], "value.txt")
        self.assertEqual(failure["kind"], "context_mismatch")
        self.assertIn("1: bad", failure["latest_excerpt"])
        self.assertEqual(len(failure["latest_sha256"]), 64)

    async def test_exact_edit_uses_unique_anchor_and_file_digest(self) -> None:
        dispatcher = ToolDispatcher(ToolRegistry([ExactEditTool()]))

        result = await dispatcher.dispatch(
            "edit_file",
            {
                "path": "value.txt",
                "mode": "replace",
                "target": "bad",
                "content": "good",
            },
            self.workspace,
            self.context,
        )

        self.assertEqual(result.status, ToolResultStatus.SUCCEEDED)
        self.assertEqual((self.root / "value.txt").read_text(encoding="utf-8"), "good\n")
        self.assertEqual(len(result.data["file_sha256"]["value.txt"]), 64)

    async def test_exact_edit_rejects_stale_or_missing_anchor(self) -> None:
        dispatcher = ToolDispatcher(ToolRegistry([ExactEditTool()]))
        stale = await dispatcher.dispatch(
            "edit_file",
            {
                "path": "value.txt",
                "target": "bad",
                "content": "good",
                "expected_sha256": "0" * 64,
            },
            self.workspace,
            self.context,
        )
        missing = await dispatcher.dispatch(
            "edit_file",
            {"path": "value.txt", "target": "other", "content": "good"},
            self.workspace,
            self.context,
        )

        self.assertEqual(stale.data["edit_failure"]["kind"], "stale_file")
        self.assertEqual(missing.data["edit_failure"]["kind"], "target_not_found")
        self.assertEqual((self.root / "value.txt").read_text(encoding="utf-8"), "bad\n")

    async def test_read_files_returns_multiple_file_versions(self) -> None:
        (self.root / "other.txt").write_text("second\n", encoding="utf-8")
        dispatcher = ToolDispatcher(ToolRegistry([ReadFilesTool()]))

        result = await dispatcher.dispatch(
            "read_files",
            {"paths": ["value.txt", "other.txt"], "max_chars_per_file": 200},
            self.workspace,
            self.context,
        )

        self.assertEqual(result.status, ToolResultStatus.SUCCEEDED)
        self.assertEqual([item["path"] for item in result.data["files"]], ["value.txt", "other.txt"])
        self.assertTrue(all(len(item["sha256"]) == 64 for item in result.data["files"]))
        self.assertIn("value.txt", result.stdout_summary)
        self.assertIn("other.txt", result.stdout_summary)

    async def test_batch_edit_is_atomic_across_multiple_files(self) -> None:
        (self.root / "other.txt").write_text("second\n", encoding="utf-8")
        dispatcher = ToolDispatcher(ToolRegistry([BatchExactEditTool()]))

        failed = await dispatcher.dispatch(
            "edit_files",
            {
                "edits": [
                    {"path": "value.txt", "target": "bad", "content": "good"},
                    {"path": "other.txt", "target": "missing", "content": "done"},
                ]
            },
            self.workspace,
            self.context,
        )

        self.assertEqual(failed.status, ToolResultStatus.INVALID_ARGUMENTS)
        self.assertEqual((self.root / "value.txt").read_text(encoding="utf-8"), "bad\n")
        self.assertEqual((self.root / "other.txt").read_text(encoding="utf-8"), "second\n")

        succeeded = await dispatcher.dispatch(
            "edit_files",
            {
                "edits": [
                    {"path": "value.txt", "target": "bad", "content": "good"},
                    {"path": "other.txt", "target": "second", "content": "done"},
                ]
            },
            self.workspace,
            self.context,
        )

        self.assertEqual(succeeded.status, ToolResultStatus.SUCCEEDED)
        self.assertEqual(set(succeeded.modified_paths), {"value.txt", "other.txt"})
        self.assertEqual((self.root / "value.txt").read_text(encoding="utf-8"), "good\n")
        self.assertEqual((self.root / "other.txt").read_text(encoding="utf-8"), "done\n")

    async def test_registered_verification_uses_shell_and_writes_full_log(self) -> None:
        executor = ShellExecutor()
        tool = RunVerificationTool(
            executor,
            [
                ValidatorConfig(
                    id="check",
                    argv=(sys.executable, "-c", "print('ok')"),
                )
            ],
        )
        dispatcher = ToolDispatcher(ToolRegistry([tool]))

        raw = await dispatcher.dispatch(
            "run_verification", {"validator_id": "check"}, self.workspace, self.context
        )
        verification = VerificationService().evaluate(
            raw, validator_id="check", workspace_revision=3
        )

        self.assertTrue(verification.passed)
        self.assertEqual(verification.workspace_revision, 3)
        self.assertIsNotNone(raw.command_log_ref)
        self.assertIn("ok", Path(raw.command_log_ref or "").read_text(encoding="utf-8"))

    async def test_auto_verification_discovers_tests_created_during_turn(self) -> None:
        tests = self.root / "tests"
        tests.mkdir()
        (tests / "test_generated.py").write_text(
            "def test_generated():\n    assert True\n",
            encoding="utf-8",
        )
        tool = RunVerificationTool(ShellExecutor(), [])
        dispatcher = ToolDispatcher(ToolRegistry([tool]))

        raw = await dispatcher.dispatch(
            "run_verification", {"validator_id": "auto"}, self.workspace, self.context
        )

        self.assertEqual(raw.status, ToolResultStatus.SUCCEEDED)
        self.assertEqual(raw.data["validator_id"], "python_tests")
        self.assertTrue(raw.data["required"])

    async def test_auto_verification_fails_clearly_without_test_marker(self) -> None:
        tool = RunVerificationTool(ShellExecutor(), [])
        dispatcher = ToolDispatcher(ToolRegistry([tool]))

        raw = await dispatcher.dispatch(
            "run_verification", {"validator_id": "auto"}, self.workspace, self.context
        )

        self.assertEqual(raw.status, ToolResultStatus.INVALID_ARGUMENTS)
        self.assertIn("没有发现可用测试命令", raw.error or "")

    def test_verification_failure_timeout_and_start_failure_are_objective(self) -> None:
        service = VerificationService()
        cases = [
            ToolResult(tool_call_id="failed", tool_name="run_verification", status=ToolResultStatus.FAILED, exit_code=1),
            ToolResult(tool_call_id="timeout", tool_name="run_verification", status=ToolResultStatus.TIMED_OUT, timed_out=True),
            ToolResult(tool_call_id="start", tool_name="run_verification", status=ToolResultStatus.FAILED, error="命令启动失败"),
        ]

        for raw in cases:
            with self.subTest(raw.tool_call_id):
                self.assertFalse(service.evaluate(raw, validator_id="check", workspace_revision=1).passed)


if __name__ == "__main__":
    unittest.main()
