"""所有工具调用的统一参数校验和分发路径。"""

from __future__ import annotations

from pydantic import ValidationError

from harness_agent.runtime.workspace import LocalWorkspace, WorkspacePathError
from harness_agent.tools.models import (
    ExecutionContext,
    ToolResult,
    ToolResultStatus,
    new_tool_call_id,
    utc_now,
)
from harness_agent.tools.registry import ToolRegistry


class ToolDispatcher:
    """Registry 之外不存在旁路工具执行。"""

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def dispatch(
        self,
        tool_name: str,
        raw_arguments: dict[str, object],
        workspace: LocalWorkspace,
        execution_context: ExecutionContext,
        *,
        tool_call_id: str | None = None,
    ) -> ToolResult:
        """校验参数并调用工具；协议错误也统一转成 ToolResult。"""

        call_id = tool_call_id or new_tool_call_id()
        tool = self.registry.get(tool_name)
        if tool is None:
            now = utc_now()
            return ToolResult(
                tool_call_id=call_id,
                tool_name=tool_name,
                status=ToolResultStatus.NOT_FOUND,
                error=f"工具未注册：{tool_name}",
                started_at=now,
                finished_at=now,
            )
        try:
            arguments = tool.arguments_model.model_validate(raw_arguments)
        except ValidationError as exc:
            now = utc_now()
            return ToolResult(
                tool_call_id=call_id,
                tool_name=tool_name,
                status=ToolResultStatus.INVALID_ARGUMENTS,
                error=str(exc),
                started_at=now,
                finished_at=now,
            )
        try:
            return await tool.execute(
                arguments,
                workspace,
                execution_context,
                tool_call_id=call_id,
            )
        except (WorkspacePathError, ValueError) as exc:
            now = utc_now()
            return ToolResult(
                tool_call_id=call_id,
                tool_name=tool_name,
                status=ToolResultStatus.INVALID_ARGUMENTS,
                error=str(exc),
                started_at=now,
                finished_at=now,
            )
        except OSError as exc:
            now = utc_now()
            return ToolResult(
                tool_call_id=call_id,
                tool_name=tool_name,
                status=ToolResultStatus.FAILED,
                error=f"工具启动失败：{exc}",
                started_at=now,
                finished_at=now,
            )
