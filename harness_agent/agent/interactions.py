"""审批、业务澄清与工具执行恢复所需的持久化模型。"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class InteractionKind(StrEnum):
    """等待用户处理的原因。"""

    APPROVAL = "approval"
    CLARIFICATION = "clarification"
    EXECUTION_UNKNOWN = "execution_unknown"


class ApprovalGrantStatus(StrEnum):
    """一次性审批的可用状态。"""

    AVAILABLE = "available"
    CONSUMED = "consumed"


class ToolExecutionStatus(StrEnum):
    """外部工具调用的可恢复状态。"""

    DISPATCHING = "dispatching"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    EXECUTION_UNKNOWN = "execution_unknown"


def canonical_digest(value: object) -> str:
    """生成稳定摘要，用于把审批精确绑定到原始工具调用。"""

    body = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


class ToolCallSnapshot(BaseModel):
    """等待审批时保存的规范化原始工具调用。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action_id: str
    action_digest: str
    tool_name: str
    arguments: dict[str, object]
    workspace_id: str

    @property
    def arguments_digest(self) -> str:
        """参数的稳定摘要。"""

        return canonical_digest({"tool": self.tool_name, "arguments": self.arguments})


class PendingInteraction(BaseModel):
    """可写入 state.json 的等待用户请求。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    interaction_id: str = Field(default_factory=lambda: str(uuid4()))
    kind: InteractionKind
    prompt: str
    tool_call: ToolCallSnapshot | None = None

    @classmethod
    def clarification(
        cls, *, prompt: str
    ) -> "PendingInteraction":
        """创建业务澄清请求。"""

        return cls(kind=InteractionKind.CLARIFICATION, prompt=prompt)

    @classmethod
    def approval(
        cls, *, prompt: str, tool_call: ToolCallSnapshot
    ) -> "PendingInteraction":
        """创建与单个工具调用绑定的审批请求。"""

        return cls(
            kind=InteractionKind.APPROVAL,
            prompt=prompt,
            tool_call=tool_call,
        )


class ApprovalGrant(BaseModel):
    """仅可消费一次、且精确绑定原调用的批准记录。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    grant_id: str = Field(default_factory=lambda: str(uuid4()))
    action_id: str
    action_digest: str
    workspace_id: str
    tool_name: str
    arguments_digest: str
    status: ApprovalGrantStatus = ApprovalGrantStatus.AVAILABLE

    @classmethod
    def from_tool_call(cls, tool_call: ToolCallSnapshot) -> "ApprovalGrant":
        """从等待审批的调用创建一次性批准。"""

        return cls(
            action_id=tool_call.action_id,
            action_digest=tool_call.action_digest,
            workspace_id=tool_call.workspace_id,
            tool_name=tool_call.tool_name,
            arguments_digest=tool_call.arguments_digest,
        )

    def matches(self, tool_call: ToolCallSnapshot) -> bool:
        """确认批准不会被挪用于另一条工具调用。"""

        return (
            self.status == ApprovalGrantStatus.AVAILABLE
            and self.action_id == tool_call.action_id
            and self.action_digest == tool_call.action_digest
            and self.workspace_id == tool_call.workspace_id
            and self.tool_name == tool_call.tool_name
            and self.arguments_digest == tool_call.arguments_digest
        )


class ToolExecution(BaseModel):
    """在外部副作用前写入状态的工具执行记录。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_call_id: str
    action_id: str
    action_digest: str
    tool_name: str
    arguments_digest: str
    idempotent: bool
    status: ToolExecutionStatus = ToolExecutionStatus.DISPATCHING
    error: str | None = None
