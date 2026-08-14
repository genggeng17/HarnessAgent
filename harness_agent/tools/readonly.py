"""工作区内的目录、文件和文本搜索工具。"""

from __future__ import annotations

import fnmatch
import hashlib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from harness_agent.runtime.workspace import LocalWorkspace
from harness_agent.tools.models import (
    ExecutionContext,
    SideEffect,
    ToolKind,
    ToolResult,
    ToolResultStatus,
    utc_now,
)


class _Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… 已截断 {len(text) - limit} 个字符"


class ListDirectoryArguments(_Arguments):
    path: str = "."
    max_depth: int = Field(default=1, ge=0, le=20)
    max_entries: int = Field(default=200, ge=1, le=10_000)


class ListDirectoryTool:
    name = "list_directory"
    description = "列出工作区目录内容"
    kind = ToolKind.READ
    side_effect = SideEffect.NONE
    idempotent = True
    arguments_model = ListDirectoryArguments

    async def execute(
        self,
        arguments: BaseModel,
        workspace: LocalWorkspace,
        execution_context: ExecutionContext,
        *,
        tool_call_id: str,
    ) -> ToolResult:
        args = ListDirectoryArguments.model_validate(arguments)
        started = utc_now()
        root = workspace.resolve_path(args.path)
        if not root.is_dir():
            raise ValueError(f"不是目录：{args.path}")
        entries: list[str] = []

        def visit(directory: Path, depth: int) -> None:
            if len(entries) >= args.max_entries or depth > args.max_depth:
                return
            for child in sorted(directory.iterdir(), key=lambda item: item.name):
                if len(entries) >= args.max_entries:
                    return
                relative = child.relative_to(workspace.root_path).as_posix()
                suffix = "/" if child.is_dir() else ""
                entries.append(relative + suffix)
                if child.is_dir() and not child.is_symlink() and depth < args.max_depth:
                    visit(child, depth + 1)

        visit(root, 0)
        output = "\n".join(entries)
        return ToolResult(
            tool_call_id=tool_call_id,
            tool_name=self.name,
            status=ToolResultStatus.SUCCEEDED,
            stdout_summary=_truncate(output, execution_context.max_tool_output_chars),
            started_at=started,
            finished_at=utc_now(),
            data={"entry_count": len(entries), "truncated": len(entries) >= args.max_entries},
        )


class ReadFileArguments(_Arguments):
    path: str
    start_line: int = Field(default=1, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    max_chars: int | None = Field(default=None, ge=1, le=1_000_000)


class ReadFileTool:
    name = "read_file"
    description = "按行读取 UTF-8 文本文件"
    kind = ToolKind.READ
    side_effect = SideEffect.NONE
    idempotent = True
    arguments_model = ReadFileArguments

    async def execute(
        self,
        arguments: BaseModel,
        workspace: LocalWorkspace,
        execution_context: ExecutionContext,
        *,
        tool_call_id: str,
    ) -> ToolResult:
        args = ReadFileArguments.model_validate(arguments)
        if args.end_line is not None and args.end_line < args.start_line:
            raise ValueError("end_line 不得小于 start_line")
        started = utc_now()
        path = workspace.resolve_path(args.path)
        if not path.is_file():
            raise ValueError(f"不是文件：{args.path}")
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError as exc:
            raise ValueError(f"文件不是 UTF-8 文本：{args.path}") from exc
        end = args.end_line or len(lines)
        selected = lines[args.start_line - 1 : end]
        output = "\n".join(
            f"{number}: {line}"
            for number, line in enumerate(selected, start=args.start_line)
        )
        limit = min(
            args.max_chars or execution_context.max_tool_output_chars,
            execution_context.max_tool_output_chars,
        )
        truncated = len(output) > limit
        return ToolResult(
            tool_call_id=tool_call_id,
            tool_name=self.name,
            status=ToolResultStatus.SUCCEEDED,
            stdout_summary=_truncate(output, limit),
            started_at=started,
            finished_at=utc_now(),
            data={
                "path": args.path,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "total_lines": len(lines),
                "returned_lines": len(selected),
                "start_line": args.start_line,
                "end_line": min(end, len(lines)),
                "complete": args.start_line == 1 and end >= len(lines) and not truncated,
            },
        )


class ReadFilesArguments(_Arguments):
    paths: tuple[str, ...] = Field(min_length=1, max_length=20)
    max_chars_per_file: int = Field(default=6_000, ge=200, le=100_000)


class ReadFilesTool:
    name = "read_files"
    description = "一次读取多个已知的 UTF-8 文本文件，适合查看相互关联的文件"
    kind = ToolKind.READ
    side_effect = SideEffect.NONE
    idempotent = True
    arguments_model = ReadFilesArguments

    async def execute(
        self,
        arguments: BaseModel,
        workspace: LocalWorkspace,
        execution_context: ExecutionContext,
        *,
        tool_call_id: str,
    ) -> ToolResult:
        args = ReadFilesArguments.model_validate(arguments)
        started = utc_now()
        sections: list[str] = []
        snapshots: list[dict[str, object]] = []
        remaining = execution_context.max_tool_output_chars
        seen: set[str] = set()
        for relative_path in args.paths:
            if relative_path in seen:
                continue
            seen.add(relative_path)
            path = workspace.resolve_path(relative_path)
            if not path.is_file():
                raise ValueError(f"不是文件：{relative_path}")
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError(f"文件不是 UTF-8 文本：{relative_path}") from exc
            numbered = "\n".join(
                f"{number}: {line}"
                for number, line in enumerate(text.splitlines(), start=1)
            )
            header = f"===== {relative_path} =====\n"
            if remaining <= len(header):
                break
            allowance = min(args.max_chars_per_file, remaining - len(header))
            marker = "\n… 文件内容已截断"
            visible_limit = allowance
            if len(numbered) > allowance:
                visible_limit = max(allowance - len(marker), 0)
            visible = numbered[:visible_limit]
            complete = len(visible) == len(numbered)
            section = header + visible + (marker if not complete else "")
            sections.append(section)
            snapshots.append(
                {
                    "path": relative_path,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "total_lines": len(text.splitlines()),
                    "complete": complete,
                }
            )
            remaining -= len(section)
        return ToolResult(
            tool_call_id=tool_call_id,
            tool_name=self.name,
            status=ToolResultStatus.SUCCEEDED,
            stdout_summary="\n\n".join(sections),
            started_at=started,
            finished_at=utc_now(),
            data={"files": snapshots},
        )


class SearchTextArguments(_Arguments):
    query: str = Field(min_length=1)
    path: str = "."
    glob: str | None = None
    max_results: int = Field(default=100, ge=1, le=10_000)


class SearchTextTool:
    name = "search_text"
    description = "在工作区 UTF-8 文件中执行字面文本搜索"
    kind = ToolKind.READ
    side_effect = SideEffect.NONE
    idempotent = True
    arguments_model = SearchTextArguments

    async def execute(
        self,
        arguments: BaseModel,
        workspace: LocalWorkspace,
        execution_context: ExecutionContext,
        *,
        tool_call_id: str,
    ) -> ToolResult:
        args = SearchTextArguments.model_validate(arguments)
        started = utc_now()
        target = workspace.resolve_path(args.path)
        candidates = [target] if target.is_file() else target.rglob("*")
        matches: list[str] = []
        for path in candidates:
            if len(matches) >= args.max_results:
                break
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(workspace.root_path).as_posix()
            if args.glob and not fnmatch.fnmatch(relative, args.glob):
                continue
            try:
                with path.open(encoding="utf-8") as handle:
                    for line_number, line in enumerate(handle, start=1):
                        if args.query in line:
                            matches.append(f"{relative}:{line_number}:{line.rstrip()}")
                            if len(matches) >= args.max_results:
                                break
            except (UnicodeDecodeError, OSError):
                continue
        output = "\n".join(matches)
        return ToolResult(
            tool_call_id=tool_call_id,
            tool_name=self.name,
            status=ToolResultStatus.SUCCEEDED,
            stdout_summary=_truncate(output, execution_context.max_tool_output_chars),
            started_at=started,
            finished_at=utc_now(),
            data={"match_count": len(matches), "truncated": len(matches) >= args.max_results},
        )


def readonly_tools() -> tuple[
    ListDirectoryTool, ReadFileTool, SearchTextTool, ReadFilesTool
]:
    """返回 M2 的完整只读工具切片。"""

    return ListDirectoryTool(), ReadFileTool(), SearchTextTool(), ReadFilesTool()
