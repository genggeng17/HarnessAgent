"""M2/M3 治理矩阵测试。"""

import tempfile
import unittest
from pathlib import Path

from harness_agent.governance.policy import PermissionMode, PolicyEngine, PolicyOutcome
from harness_agent.runtime.workspace import LocalWorkspace
from harness_agent.tools.patch import ApplyPatchTool
from harness_agent.tools.readonly import ReadFileTool
from harness_agent.tools.shell import RunShellTool, ShellExecutor
from harness_agent.tools.verification_tool import RunVerificationTool, ValidatorConfig


class PolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = LocalWorkspace("test", Path(self.temporary.name))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_safe_edit_allows_read_write_and_registered_verification(self) -> None:
        policy = PolicyEngine(PermissionMode.SAFE_EDIT)
        executor = ShellExecutor()
        verification = RunVerificationTool(
            executor, [ValidatorConfig(id="tests", argv=("true",))]
        )

        self.assertEqual(policy.evaluate(ReadFileTool(), {}, self.workspace).outcome, PolicyOutcome.ALLOW)
        self.assertEqual(policy.evaluate(ApplyPatchTool(), {"patch": "change"}, self.workspace).outcome, PolicyOutcome.ALLOW)
        self.assertEqual(policy.evaluate(verification, {}, self.workspace).outcome, PolicyOutcome.ALLOW)
        self.assertEqual(policy.evaluate(RunShellTool(executor), {}, self.workspace).outcome, PolicyOutcome.ASK)

    def test_read_only_denies_writes_and_delete_patch_asks(self) -> None:
        patch = ApplyPatchTool()
        read_only = PolicyEngine(PermissionMode.READ_ONLY)
        safe = PolicyEngine(PermissionMode.SAFE_EDIT)

        self.assertEqual(read_only.evaluate(patch, {}, self.workspace).outcome, PolicyOutcome.DENY)
        self.assertEqual(
            safe.evaluate(patch, {"patch": "+++ /dev/null"}, self.workspace).outcome,
            PolicyOutcome.ASK,
        )


if __name__ == "__main__":
    unittest.main()
