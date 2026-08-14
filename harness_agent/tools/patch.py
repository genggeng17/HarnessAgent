"""受工作区边界约束的 unified diff Patch 工具。"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

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


class ApplyPatchArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    patch: str = Field(min_length=1, max_length=5_000_000)


class ExactEditArguments(BaseModel):
    """以唯一原文为锚点进行稳定的局部修改。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    mode: Literal["replace", "insert_before", "insert_after"] = "replace"
    target: str = Field(min_length=1, max_length=1_000_000)
    content: str = Field(max_length=1_000_000)
    expected_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class BatchExactEditArguments(BaseModel):
    """一次提交一组相互关联的精确修改。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    edits: tuple[ExactEditArguments, ...] = Field(min_length=1, max_length=20)


@dataclass(frozen=True, slots=True)
class _FilePatch:
    old_path: str | None
    new_path: str | None
    hunks: tuple[tuple[int, tuple[str, ...]], ...]


class PatchContextError(ValueError):
    """Patch 与当前文件内容不一致，并携带可恢复位置。"""

    def __init__(self, kind: str, path: str, line: int, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.path = path
        self.line = line


class ApplyPatchTool:
    name = "apply_patch"
    description = "应用 unified diff，可创建、修改或删除工作区文件"
    kind = ToolKind.WRITE
    side_effect = SideEffect.WORKSPACE
    idempotent = False
    arguments_model = ApplyPatchArguments

    _HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")

    async def execute(
        self,
        arguments: BaseModel,
        workspace: LocalWorkspace,
        execution_context: ExecutionContext,
        *,
        tool_call_id: str,
    ) -> ToolResult:
        del execution_context
        args = ApplyPatchArguments.model_validate(arguments)
        if workspace.read_only:
            raise ValueError("只读工作区禁止 Patch")
        started = utc_now()
        patches = self._parse(args.patch)
        prepared: list[tuple[Path, str | None, str]] = []
        modified_paths: list[str] = []
        for file_patch in patches:
            relative = file_patch.new_path or file_patch.old_path
            if relative is None:
                raise ValueError("Patch 缺少目标路径")
            path = workspace.resolve_path(
                relative,
                must_exist=file_patch.old_path is not None,
            )
            old_text = ""
            if file_patch.old_path is not None:
                if not path.is_file():
                    raise ValueError(f"Patch 目标不是文件：{relative}")
                old_text = path.read_text(encoding="utf-8")
            try:
                new_text = self._apply_hunks(old_text, file_patch.hunks, relative)
            except PatchContextError as exc:
                return _edit_failure_result(
                    tool_call_id=tool_call_id,
                    tool_name=self.name,
                    started=started,
                    path=path,
                    relative=relative,
                    kind=exc.kind,
                    line=exc.line,
                    message=str(exc),
                )
            prepared.append((path, None if file_patch.new_path is None else new_text, relative))

        for path, new_text, relative in prepared:
            if new_text is None:
                path.unlink()
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(new_text, encoding="utf-8")
            modified_paths.append(relative)
        return ToolResult(
            tool_call_id=tool_call_id,
            tool_name=self.name,
            status=ToolResultStatus.SUCCEEDED,
            stdout_summary=f"已修改 {len(modified_paths)} 个文件",
            started_at=started,
            finished_at=utc_now(),
            modified_paths=tuple(modified_paths),
            data={
                "file_sha256": {
                    relative: _sha256_path(path)
                    for path, new_text, relative in prepared
                    if new_text is not None
                }
            },
        )

    def _parse(self, patch: str) -> tuple[_FilePatch, ...]:
        lines = patch.splitlines()
        result: list[_FilePatch] = []
        index = 0
        while index < len(lines):
            if lines[index].startswith("diff --git "):
                index += 1
                continue
            if not lines[index].startswith("--- "):
                raise ValueError(f"Patch 第 {index + 1} 行应为 --- 文件头")
            old_path = self._header_path(lines[index][4:])
            index += 1
            if index >= len(lines) or not lines[index].startswith("+++ "):
                raise ValueError("Patch 缺少 +++ 文件头")
            new_path = self._header_path(lines[index][4:])
            index += 1
            hunks: list[tuple[int, tuple[str, ...]]] = []
            while index < len(lines) and not lines[index].startswith(("--- ", "diff --git ")):
                match = self._HUNK.match(lines[index])
                if match is None:
                    raise ValueError(f"Patch 第 {index + 1} 行缺少合法 hunk 头")
                old_start = int(match.group(1))
                index += 1
                body: list[str] = []
                while index < len(lines) and not lines[index].startswith(("@@ ", "--- ", "diff --git ")):
                    line = lines[index]
                    if line == "\\ No newline at end of file":
                        index += 1
                        continue
                    if not line or line[0] not in " +-":
                        raise ValueError(f"Patch 第 {index + 1} 行前缀非法")
                    body.append(line)
                    index += 1
                hunks.append((old_start, tuple(body)))
            if not hunks:
                raise ValueError("每个文件 Patch 至少需要一个 hunk")
            result.append(_FilePatch(old_path, new_path, tuple(hunks)))
        if not result:
            raise ValueError("Patch 中没有文件变更")
        return tuple(result)

    @staticmethod
    def _header_path(raw: str) -> str | None:
        value = raw.split("\t", 1)[0].strip()
        if value == "/dev/null":
            return None
        if value.startswith(("a/", "b/")):
            value = value[2:]
        if not value:
            raise ValueError("Patch 文件路径为空")
        return value

    @staticmethod
    def _apply_hunks(
        old_text: str,
        hunks: tuple[tuple[int, tuple[str, ...]], ...],
        relative: str,
    ) -> str:
        old_lines = old_text.splitlines()
        output: list[str] = []
        cursor = 0
        for old_start, body in hunks:
            target = max(old_start - 1, 0)
            if target < cursor or target > len(old_lines):
                raise PatchContextError(
                    "hunk_out_of_range",
                    relative,
                    old_start,
                    f"Patch hunk 行号越界：{relative}:{old_start}",
                )
            output.extend(old_lines[cursor:target])
            cursor = target
            for line in body:
                marker, content = line[0], line[1:]
                if marker == "+":
                    output.append(content)
                    continue
                if cursor >= len(old_lines) or old_lines[cursor] != content:
                    actual = old_lines[cursor] if cursor < len(old_lines) else "<EOF>"
                    raise PatchContextError(
                        "context_mismatch",
                        relative,
                        cursor + 1,
                        f"Patch 上下文不匹配：{relative}:{cursor + 1}，实际为 {actual!r}",
                    )
                if marker == " ":
                    output.append(content)
                cursor += 1
        output.extend(old_lines[cursor:])
        new_text = "\n".join(output)
        if output:
            new_text += "\n"
        return new_text


class ExactEditTool:
    """使用唯一原文锚点修改文件，不依赖易漂移的行号。"""

    name = "edit_file"
    description = (
        "按唯一原文稳定修改一个 UTF-8 文件；支持替换、在原文前插入、在原文后插入。"
        "读取文件后优先携带 expected_sha256，文件变化时会安全拒绝并返回最新摘要"
    )
    kind = ToolKind.WRITE
    side_effect = SideEffect.WORKSPACE
    idempotent = False
    arguments_model = ExactEditArguments

    async def execute(
        self,
        arguments: BaseModel,
        workspace: LocalWorkspace,
        execution_context: ExecutionContext,
        *,
        tool_call_id: str,
    ) -> ToolResult:
        del execution_context
        args = ExactEditArguments.model_validate(arguments)
        if workspace.read_only:
            raise ValueError("只读工作区禁止修改文件")
        started = utc_now()
        path = workspace.resolve_path(args.path)
        if not path.is_file():
            raise ValueError(f"修改目标不是文件：{args.path}")
        text = path.read_text(encoding="utf-8")
        digest = _sha256_path(path)
        if args.expected_sha256 is not None and args.expected_sha256 != digest:
            return _edit_failure_result(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                started=started,
                path=path,
                relative=args.path,
                kind="stale_file",
                line=1,
                message="文件在读取后已经变化，请使用返回的最新版本重新修改",
            )
        count = text.count(args.target)
        if count != 1:
            return _edit_failure_result(
                tool_call_id=tool_call_id,
                tool_name=self.name,
                started=started,
                path=path,
                relative=args.path,
                kind="target_not_unique" if count > 1 else "target_not_found",
                line=1,
                message=f"目标原文应唯一出现一次，实际出现 {count} 次",
            )
        replacement = args.content
        if args.mode == "insert_before":
            replacement = args.content + args.target
        elif args.mode == "insert_after":
            replacement = args.target + args.content
        updated = text.replace(args.target, replacement, 1)
        path.write_text(updated, encoding="utf-8")
        return ToolResult(
            tool_call_id=tool_call_id,
            tool_name=self.name,
            status=ToolResultStatus.SUCCEEDED,
            stdout_summary=f"已稳定修改文件：{args.path}",
            started_at=started,
            finished_at=utc_now(),
            modified_paths=(args.path,),
            data={"file_sha256": {args.path: _sha256_path(path)}},
        )


class BatchExactEditTool:
    """先在内存中检查全部修改，全部可行时再一次写入。"""

    name = "edit_files"
    description = (
        "一次原子修改多个相关文件；每项规则与 edit_file 相同。"
        "已读取多个相关文件并准备成组实现代码、测试和文档时优先使用"
    )
    kind = ToolKind.WRITE
    side_effect = SideEffect.WORKSPACE
    idempotent = False
    arguments_model = BatchExactEditArguments

    async def execute(
        self,
        arguments: BaseModel,
        workspace: LocalWorkspace,
        execution_context: ExecutionContext,
        *,
        tool_call_id: str,
    ) -> ToolResult:
        del execution_context
        args = BatchExactEditArguments.model_validate(arguments)
        if workspace.read_only:
            raise ValueError("只读工作区禁止修改文件")
        started = utc_now()
        prepared: dict[Path, str] = {}
        originals: dict[Path, str] = {}
        relative_paths: dict[Path, str] = {}
        for edit in args.edits:
            path = workspace.resolve_path(edit.path)
            if not path.is_file():
                raise ValueError(f"修改目标不是文件：{edit.path}")
            if path not in prepared:
                prepared[path] = path.read_text(encoding="utf-8")
                originals[path] = _sha256_path(path)
                relative_paths[path] = edit.path
            if edit.expected_sha256 is not None and edit.expected_sha256 != originals[path]:
                return _edit_failure_result(
                    tool_call_id=tool_call_id,
                    tool_name=self.name,
                    started=started,
                    path=path,
                    relative=edit.path,
                    kind="stale_file",
                    line=1,
                    message="文件在读取后已经变化，请使用返回的最新版本重新修改",
                )
            current = prepared[path]
            count = current.count(edit.target)
            if count != 1:
                return _edit_failure_result(
                    tool_call_id=tool_call_id,
                    tool_name=self.name,
                    started=started,
                    path=path,
                    relative=edit.path,
                    kind="target_not_unique" if count > 1 else "target_not_found",
                    line=1,
                    message=f"目标原文应唯一出现一次，实际出现 {count} 次",
                )
            replacement = edit.content
            if edit.mode == "insert_before":
                replacement = edit.content + edit.target
            elif edit.mode == "insert_after":
                replacement = edit.target + edit.content
            prepared[path] = current.replace(edit.target, replacement, 1)

        for path, updated in prepared.items():
            path.write_text(updated, encoding="utf-8")
        modified_paths = tuple(relative_paths[path] for path in prepared)
        return ToolResult(
            tool_call_id=tool_call_id,
            tool_name=self.name,
            status=ToolResultStatus.SUCCEEDED,
            stdout_summary=f"已原子修改 {len(modified_paths)} 个文件",
            started_at=started,
            finished_at=utc_now(),
            modified_paths=modified_paths,
            data={
                "file_sha256": {
                    relative_paths[path]: _sha256_path(path) for path in prepared
                }
            },
        )


def _sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _edit_failure_result(
    *,
    tool_call_id: str,
    tool_name: str,
    started,  # type: ignore[no-untyped-def]
    path: Path,
    relative: str,
    kind: str,
    line: int,
    message: str,
) -> ToolResult:
    """返回当前文件版本和局部内容，供下一轮直接精准恢复。"""

    lines = path.read_text(encoding="utf-8").splitlines()
    start = max(line - 4, 1)
    end = min(line + 4, len(lines))
    excerpt = "\n".join(
        f"{number}: {lines[number - 1]}" for number in range(start, end + 1)
    )
    return ToolResult(
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        status=ToolResultStatus.INVALID_ARGUMENTS,
        error=message,
        started_at=started,
        finished_at=utc_now(),
        data={
            "edit_failure": {
                "path": relative,
                "kind": kind,
                "line": line,
                "latest_sha256": _sha256_path(path),
                "latest_excerpt": excerpt,
            }
        },
    )
