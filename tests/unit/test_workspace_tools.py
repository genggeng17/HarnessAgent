"""Workspace 边界、只读工具、Registry 和 Dispatcher 测试。"""

import tempfile
import unittest
from pathlib import Path

from harness_agent.runtime.workspace import LocalWorkspace, WorkspacePathError
from harness_agent.tools.dispatcher import ToolDispatcher
from harness_agent.tools.models import ExecutionContext, ToolResultStatus
from harness_agent.tools.readonly import readonly_tools
from harness_agent.tools.registry import ToolRegistry


class WorkspaceToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "main.py").write_text(
            "第一行\nneedle = 1\n", encoding="utf-8"
        )
        self.workspace = LocalWorkspace("test", self.root)
        self.registry = ToolRegistry(list(readonly_tools()))
        self.dispatcher = ToolDispatcher(self.registry)
        self.context = ExecutionContext(turn_id="turn")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_rejects_absolute_parent_and_symlink_escape(self) -> None:
        outside = self.root.parent / f"{self.root.name}-outside.txt"
        outside.write_text("secret", encoding="utf-8")
        self.addCleanup(outside.unlink)
        try:
            (self.root / "escape").symlink_to(outside)
        except OSError as exc:
            self.skipTest(f"当前 Windows 账户无法创建符号链接：{exc.winerror}")

        with self.assertRaises(WorkspacePathError):
            self.workspace.resolve_path("../outside")
        with self.assertRaises(WorkspacePathError):
            self.workspace.resolve_path(str(outside))
        with self.assertRaises(WorkspacePathError):
            self.workspace.resolve_path("escape")

    async def test_dispatches_directory_read_and_search(self) -> None:
        listing = await self.dispatcher.dispatch(
            "list_directory", {"path": "."}, self.workspace, self.context
        )
        reading = await self.dispatcher.dispatch(
            "read_file", {"path": "src/main.py", "start_line": 2}, self.workspace, self.context
        )
        search = await self.dispatcher.dispatch(
            "search_text", {"query": "needle", "glob": "*.py"}, self.workspace, self.context
        )

        self.assertEqual(listing.status, ToolResultStatus.SUCCEEDED)
        self.assertIn("src/main.py", listing.stdout_summary)
        self.assertIn("2: needle = 1", reading.stdout_summary)
        self.assertIn("src/main.py:2:needle = 1", search.stdout_summary)

    async def test_invalid_arguments_and_unknown_tool_are_results(self) -> None:
        invalid = await self.dispatcher.dispatch(
            "read_file", {"path": "src/main.py", "extra": True}, self.workspace, self.context
        )
        missing = await self.dispatcher.dispatch(
            "missing", {}, self.workspace, self.context
        )

        self.assertEqual(invalid.status, ToolResultStatus.INVALID_ARGUMENTS)
        self.assertEqual(missing.status, ToolResultStatus.NOT_FOUND)

    def test_registry_rejects_duplicate_names(self) -> None:
        tool = readonly_tools()[0]
        with self.assertRaises(ValueError):
            ToolRegistry([tool, tool])


if __name__ == "__main__":
    unittest.main()
