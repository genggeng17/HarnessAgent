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

    def __init__(self, mode: PermissionMode = PermissionMode.SAFE_EDIT) -> None:
        self.mode = mode

    def evaluate(
        self,
        tool: Tool,
        arguments: dict[str, object],
        workspace: LocalWorkspace,
    ) -> PolicyDecision:
        """返回当前里程碑可执行的 ALLOW/ASK/DENY。"""

        if tool.side_effect == SideEffect.NONE and tool.kind == ToolKind.READ:
            return PolicyDecision(outcome=PolicyOutcome.ALLOW, reason="工作区内只读工具")
        if workspace.read_only or self.mode == PermissionMode.READ_ONLY:
            return PolicyDecision(outcome=PolicyOutcome.DENY, reason="只读模式禁止副作用")
        if tool.kind == ToolKind.WRITE and tool.name == "apply_patch":
            patch = str(arguments.get("patch", ""))
            if "+++ /dev/null" in patch:
                return PolicyDecision(outcome=PolicyOutcome.ASK, reason="删除文件需要审批")
        if tool.kind in {ToolKind.WRITE, ToolKind.VERIFICATION}:
            return PolicyDecision(outcome=PolicyOutcome.ALLOW, reason="安全编辑模式允许受控写入和已注册验证")
        if tool.kind == ToolKind.SHELL:
            return PolicyDecision(outcome=PolicyOutcome.ASK, reason="一般 Shell 需要审批；审批恢复属于 M4")
        return PolicyDecision(outcome=PolicyOutcome.DENY, reason="未知工具类别")
