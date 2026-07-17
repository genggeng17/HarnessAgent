"""显式传递的本地工作区及路径边界检查。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath


class WorkspacePathError(ValueError):
    """路径不满足工作区边界约束。"""


@dataclass(frozen=True, slots=True)
class LocalWorkspace:
    """工具唯一允许访问的本地目录。"""

    workspace_id: str
    root_path: Path
    read_only: bool = False
    base_revision: str | None = None

    def __post_init__(self) -> None:
        root = self.root_path.expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ValueError("工作区根路径必须是目录")
        object.__setattr__(self, "root_path", root)

    def resolve_path(self, relative_path: str, *, must_exist: bool = True) -> Path:
        """解析相对 POSIX 路径，并阻止越界与符号链接逃逸。"""

        if not relative_path:
            raise WorkspacePathError("路径不能为空；根目录请使用 .")
        pure = PurePosixPath(relative_path)
        if pure.is_absolute() or ".." in pure.parts:
            raise WorkspacePathError("路径必须是工作区内的相对 POSIX 路径")

        candidate = self.root_path.joinpath(*pure.parts)
        if must_exist:
            try:
                resolved = candidate.resolve(strict=True)
            except FileNotFoundError as exc:
                raise WorkspacePathError(f"路径不存在：{relative_path}") from exc
        else:
            existing = candidate
            missing_parts: list[str] = []
            while not existing.exists() and existing != self.root_path:
                missing_parts.append(existing.name)
                existing = existing.parent
            resolved = existing.resolve(strict=True).joinpath(*reversed(missing_parts))

        if not resolved.is_relative_to(self.root_path):
            raise WorkspacePathError(f"路径逃逸工作区：{relative_path}")
        return resolved

    def relative_path(self, path: Path) -> str:
        """把已验证的真实路径转换为 POSIX 工作区相对路径。"""

        resolved = path.resolve(strict=False)
        if not resolved.is_relative_to(self.root_path):
            raise WorkspacePathError("路径不属于当前工作区")
        relative = resolved.relative_to(self.root_path).as_posix()
        return relative or "."
