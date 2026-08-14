"""M2/M3 所需的确定性工具治理矩阵。"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from harness_agent.runtime.workspace import LocalWorkspace
from harness_agent.tools.models import SideEffect, Tool, ToolKind


class PermissionMode(StrEnum):
    READ_ONLY = "READ_ONLY"
    SAFE_EDIT = "SAFE_EDIT"
    FULL_AUTO = "FULL_AUTO"


class PolicyOutcome(StrEnum):
    ALLOW = "ALLOW"
    ASK = "ASK"
    DENY = "DENY"


class PolicyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: PolicyOutcome
    reason: str


class PolicyEngine:
    """只判断 Registry 元数据；不执行工具或修改 TurnState。"""

    _DANGEROUS_GIT = {
        ("git", "reset", "--hard"),
        ("git", "checkout", "--"),
        ("git", "restore"),
    }

    def __init__(
        self,
        mode: PermissionMode = PermissionMode.SAFE_EDIT,
        *,
        read_only_command_allowlist: tuple[str, ...] = (
            "git status",
            "git diff",
            "git log",
            "git show",
        ),
    ) -> None:
        self.mode = mode
        self.read_only_command_allowlist = frozenset(read_only_command_allowlist)

    def evaluate(
        self,
        tool: Tool,
        arguments: dict[str, object],
        workspace: LocalWorkspace,
    ) -> PolicyDecision:
        """返回当前里程碑可执行的 ALLOW/ASK/DENY。"""

        if tool.side_effect == SideEffect.NONE and tool.kind == ToolKind.READ:
            return PolicyDecision(outcome=PolicyOutcome.ALLOW, reason="工作区内只读工具")
        if tool.kind == ToolKind.VERIFICATION:
            if self.mode == PermissionMode.READ_ONLY:
                return PolicyDecision(outcome=PolicyOutcome.ASK, reason="只读模式运行验证需要审批")
            return PolicyDecision(outcome=PolicyOutcome.ALLOW, reason="已注册验证器")
        if tool.kind == ToolKind.SHELL:
            return self._evaluate_shell(arguments)
        if workspace.read_only or self.mode == PermissionMode.READ_ONLY:
            return PolicyDecision(outcome=PolicyOutcome.DENY, reason="只读模式禁止修改工作区")
        if tool.kind == ToolKind.WRITE and tool.name == "apply_patch":
            patch = str(arguments.get("patch", ""))
            if "+++ /dev/null" in patch:
                return PolicyDecision(outcome=PolicyOutcome.ASK, reason="删除文件需要审批")
        if tool.kind == ToolKind.WRITE:
            return PolicyDecision(outcome=PolicyOutcome.ALLOW, reason="允许受控工作区修改")
        return PolicyDecision(outcome=PolicyOutcome.DENY, reason="未知工具类别")

    def _evaluate_shell(self, arguments: dict[str, object]) -> PolicyDecision:
        argv = arguments.get("argv")
        if not isinstance(argv, (list, tuple)) or not all(isinstance(item, str) for item in argv):
            outcome = PolicyOutcome.DENY if self.mode == PermissionMode.READ_ONLY else PolicyOutcome.ASK
            return PolicyDecision(outcome=outcome, reason="Shell 参数将在执行前进行校验")
        values = tuple(argv)
        if self._is_dangerous_command(values):
            return PolicyDecision(outcome=PolicyOutcome.DENY, reason="命令会丢弃修改或破坏系统")
        if self._looks_like_file_edit_script(values):
            return PolicyDecision(
                outcome=PolicyOutcome.DENY,
                reason="禁止用 Shell、临时脚本或字符串替换命令修改源码；请使用受控文件修改工具",
            )
        if self._is_readonly_git(values):
            return PolicyDecision(outcome=PolicyOutcome.ALLOW, reason="已允许的只读 Git 命令")
        if self.mode == PermissionMode.READ_ONLY:
            return PolicyDecision(outcome=PolicyOutcome.DENY, reason="只读模式仅允许已登记的只读命令")
        return PolicyDecision(outcome=PolicyOutcome.ASK, reason="该 Shell 命令需要用户审批")

    def _is_readonly_git(self, argv: tuple[str, ...]) -> bool:
        if len(argv) < 2 or argv[0] != "git":
            return False
        command = " ".join(argv[:2])
        if command not in self.read_only_command_allowlist:
            return False
        unsafe_markers = {"-c", "--config-env", "--exec-path", "--no-pager", ">", "<", "|", "&&", ";"}
        return not any(item in unsafe_markers or item.startswith("-") and item != "--stat" for item in argv[2:])

    @classmethod
    def _is_dangerous_command(cls, argv: tuple[str, ...]) -> bool:
        if len(argv) >= 3 and argv[:3] in cls._DANGEROUS_GIT:
            return True
        if len(argv) >= 2 and argv[:2] == ("git", "restore"):
            return True
        if len(argv) >= 2 and argv[:2] == ("git", "clean") and any(
            "f" in item and "d" in item for item in argv[2:]
        ):
            return True
        joined = " ".join(argv).lower()
        markers = ("rm -rf /", "rm -rf .", "rmdir /s", "del /s", "format ", "shutdown ", "reboot", "fork bomb")
        return any(marker in joined for marker in markers)

    @staticmethod
    def _looks_like_file_edit_script(argv: tuple[str, ...]) -> bool:
        """识别常见的 Shell 写文件兜底，避免 Patch 失败后绕过受控工具。"""

        joined = " ".join(argv).lower()
        executable = argv[0].lower() if argv else ""
        script_markers = (
            "write_text(",
            "write_bytes(",
            "writefile(",
            "writefilesync(",
            "set-content",
            "add-content",
            "out-file",
            "writealltext",
            "writeallbytes",
        )
        if any(marker in joined for marker in script_markers):
            return True
        if executable in {"sed", "perl"} and any(
            item in {"-i", "-pi", "-p-i"} or item.startswith("-i")
            for item in argv[1:]
        ):
            return True
        if executable in {"cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh"}:
            return any(marker in joined for marker in (">", "copy ", "move "))
        return False
