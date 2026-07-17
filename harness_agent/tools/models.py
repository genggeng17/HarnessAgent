"""统一工具协议和执行结果。"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from harness_agent.runtime.workspace import LocalWorkspace


def utc_now() -> datetime:
    """返回带时区的 UTC 时间。"""

    return datetime.now(timezone.utc)


class ToolKind(StrEnum):
    """由 Registry 信任的工具类别。"""

    READ = "read"
    WRITE = "write"
    SHELL = "shell"
    VERIFICATION = "verification"


class SideEffect(StrEnum):
    """工具的可观察副作用级别。"""

    NONE = "none"
    WORKSPACE = "workspace"
    PROCESS = "process"


class ToolResultStatus(StrEnum):
    """工具执行的客观状态。"""

    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    INVALID_ARGUMENTS = "INVALID_ARGUMENTS"
    NOT_FOUND = "NOT_FOUND"


class ExecutionContext(BaseModel):
    """组合根传给工具的执行期信息。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    turn_id: str
    command_log_dir: Path | None = None
    max_tool_output_chars: int = Field(default=12_000, ge=100)


class ToolResult(BaseModel):
    """工具返回的原始事实，不解释失败原因。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_call_id: str
    tool_name: str
    status: ToolResultStatus
    exit_code: int | None = None
    timed_out: bool = False
    stdout_summary: str = ""
    stderr_summary: str = ""
    command_log_ref: str | None = None
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime = Field(default_factory=utc_now)
    modified_paths: tuple[str, ...] = ()
    error: str | None = None
    data: dict[str, object] = Field(default_factory=dict)


class Tool(Protocol):
    """所有具体工具必须实现的异步端口。"""

    name: str
    description: str
    kind: ToolKind
    side_effect: SideEffect
    idempotent: bool
    arguments_model: type[BaseModel]

    async def execute(
        self,
        arguments: BaseModel,
        workspace: LocalWorkspace,
        execution_context: ExecutionContext,
        *,
        tool_call_id: str,
    ) -> ToolResult:
        """执行已经过 Schema 校验的参数。"""

        ...


def new_tool_call_id() -> str:
    """生成稳定的工具调用 ID。"""

    return str(uuid4())
