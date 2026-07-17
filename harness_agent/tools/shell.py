"""一般 Shell 与验证工具共用的唯一子进程执行器。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from harness_agent.runtime.workspace import LocalWorkspace
from harness_agent.tools.models import (
    ExecutionContext,
    SideEffect,
    ToolKind,
    ToolResult,
    ToolResultStatus,
    utc_now,
)


class ShellExecutor:
    """使用 argv 和 shell=False 执行命令，并保留完整日志。"""

    async def execute(
        self,
        *,
        argv: tuple[str, ...],
        cwd: Path,
        timeout_seconds: float,
        tool_name: str,
        tool_call_id: str,
        execution_context: ExecutionContext,
        data: dict[str, object] | None = None,
    ) -> ToolResult:
        started = utc_now()
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            return ToolResult(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                status=ToolResultStatus.FAILED,
                error=f"命令启动失败：{exc}",
                started_at=started,
                finished_at=utc_now(),
                data=data or {},
            )

        timed_out = False
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(), timeout=timeout_seconds
            )
        except TimeoutError:
            timed_out = True
            process.kill()
            stdout_bytes, stderr_bytes = await process.communicate()

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        log_ref = self._write_log(
            execution_context,
            tool_call_id,
            argv,
            cwd,
            stdout,
            stderr,
        )
        limit = execution_context.max_tool_output_chars
        status = (
            ToolResultStatus.TIMED_OUT
            if timed_out
            else ToolResultStatus.SUCCEEDED
            if process.returncode == 0
            else ToolResultStatus.FAILED
        )
        return ToolResult(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            status=status,
            exit_code=process.returncode,
            timed_out=timed_out,
            stdout_summary=self._truncate(stdout, limit),
            stderr_summary=self._truncate(stderr, limit),
            command_log_ref=log_ref,
            started_at=started,
            finished_at=utc_now(),
            data=data or {},
        )

    @staticmethod
    def _truncate(value: str, limit: int) -> str:
        if len(value) <= limit:
            return value
        return value[:limit] + f"\n… 已截断 {len(value) - limit} 个字符"

    @staticmethod
    def _write_log(
        context: ExecutionContext,
        tool_call_id: str,
        argv: tuple[str, ...],
        cwd: Path,
        stdout: str,
        stderr: str,
    ) -> str | None:
        if context.command_log_dir is None:
            return None
        context.command_log_dir.mkdir(parents=True, exist_ok=True)
        path = context.command_log_dir / f"{tool_call_id}.log"
        body = (
            f"argv={list(argv)!r}\ncwd={cwd}\n\n"
            f"[stdout]\n{stdout}\n[stderr]\n{stderr}"
        )
        path.write_text(body, encoding="utf-8")
        return str(path)


class RunShellArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    argv: tuple[str, ...] = Field(min_length=1, max_length=256)
    cwd: str = "."
    timeout_seconds: float | None = Field(default=None, gt=0, le=3600)

    @field_validator("argv")
    @classmethod
    def reject_empty_arguments(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item or "\x00" in item for item in value):
            raise ValueError("argv 不得包含空参数或 NUL")
        return value


class RunShellTool:
    name = "run_shell"
    description = "以 argv、shell=False 在工作区运行命令"
    kind = ToolKind.SHELL
    side_effect = SideEffect.PROCESS
    idempotent = False
    arguments_model = RunShellArguments

    def __init__(
        self,
        executor: ShellExecutor,
        *,
        default_timeout_seconds: float = 60,
    ) -> None:
        self.executor = executor
        self.default_timeout_seconds = default_timeout_seconds

    async def execute(
        self,
        arguments: BaseModel,
        workspace: LocalWorkspace,
        execution_context: ExecutionContext,
        *,
        tool_call_id: str,
    ) -> ToolResult:
        args = RunShellArguments.model_validate(arguments)
        cwd = workspace.resolve_path(args.cwd)
        if not cwd.is_dir():
            raise ValueError(f"Shell cwd 不是目录：{args.cwd}")
        return await self.executor.execute(
            argv=args.argv,
            cwd=cwd,
            timeout_seconds=args.timeout_seconds or self.default_timeout_seconds,
            tool_name=self.name,
            tool_call_id=tool_call_id,
            execution_context=execution_context,
        )
