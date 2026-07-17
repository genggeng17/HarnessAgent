"""受工作区边界约束的 unified diff Patch 工具。"""

from __future__ import annotations

import re
from dataclasses import dataclass
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


class ApplyPatchArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    patch: str = Field(min_length=1, max_length=5_000_000)


@dataclass(frozen=True, slots=True)
class _FilePatch:
    old_path: str | None
    new_path: str | None
    hunks: tuple[tuple[int, tuple[str, ...]], ...]


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
            new_text = self._apply_hunks(old_text, file_patch.hunks, relative)
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
                raise ValueError(f"Patch hunk 行号越界：{relative}:{old_start}")
            output.extend(old_lines[cursor:target])
            cursor = target
            for line in body:
                marker, content = line[0], line[1:]
                if marker == "+":
                    output.append(content)
                    continue
                if cursor >= len(old_lines) or old_lines[cursor] != content:
                    actual = old_lines[cursor] if cursor < len(old_lines) else "<EOF>"
                    raise ValueError(
                        f"Patch 上下文不匹配：{relative}:{cursor + 1}，实际为 {actual!r}"
                    )
                if marker == " ":
                    output.append(content)
                cursor += 1
        output.extend(old_lines[cursor:])
        new_text = "\n".join(output)
        if output:
            new_text += "\n"
        return new_text
