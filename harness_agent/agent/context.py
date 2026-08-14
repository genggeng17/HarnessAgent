"""当前 Turn 的固定任务卡、文件版本和上下文裁剪。"""

from __future__ import annotations

import re
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from harness_agent.llm.base import ChatMessage, MessageRole


class TaskRequirement(BaseModel):
    """从用户原文中保留的一条验收要求。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement_id: str
    text: str
    prohibition: bool = False


class TaskContract(BaseModel):
    """当前任务不可被计划或模型输出改写的原始任务卡。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    original_request: str
    requirements: tuple[TaskRequirement, ...]


class FileSnapshot(BaseModel):
    """模型最近一次读取文件时看到的版本。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    sha256: str
    total_lines: int = Field(ge=0)
    complete: bool
    stale: bool = False


class EditRecovery(BaseModel):
    """当前任务内一次文件修改失败后的有限恢复状态。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    failure_kind: str
    attempts: int = Field(default=1, ge=1, le=3)
    latest_sha256: str | None = None
    latest_excerpt: str = ""
    require_full_read: bool = False
    blocked: bool = False


_LIST_PREFIX = re.compile(r"^\s*(?:[-*•]|\d+[.、)]|[一二三四五六七八九十]+[、.])\s*")
_PROHIBITION_MARKERS = ("不要", "不得", "禁止", "不能", "不允许", "只允许")


def build_task_contract(user_task: str) -> TaskContract:
    """按用户原文行构建任务卡；不让模型自行改写要求。"""

    candidates: list[str] = []
    for raw_line in user_task.splitlines():
        line = _LIST_PREFIX.sub("", raw_line).strip()
        if line:
            candidates.append(line)
    if not candidates:
        candidates = [user_task.strip() or "完成用户任务"]
    requirements = tuple(
        TaskRequirement(
            requirement_id=f"requirement_{index}",
            text=text,
            prohibition=any(marker in text for marker in _PROHIBITION_MARKERS),
        )
        for index, text in enumerate(dict.fromkeys(candidates), start=1)
    )
    return TaskContract(original_request=user_task, requirements=requirements)


def curate_messages(
    messages: Sequence[ChatMessage],
    *,
    task_contract: TaskContract | None,
    max_chars: int = 42_000,
    recent_messages: int = 10,
    per_message_chars: int = 8_000,
) -> tuple[ChatMessage, ...]:
    """保留固定规则、原始任务和最近证据，旧过程不再整段回灌。"""

    fixed = [message for message in messages if message.role == MessageRole.SYSTEM]
    recent = [message for message in messages if message.role != MessageRole.SYSTEM][
        -recent_messages:
    ]
    selected: list[ChatMessage] = []
    used = 0

    if task_contract is not None and not any(
        message.role == MessageRole.USER
        and message.content == task_contract.original_request
        for message in recent
    ):
        recent.insert(
            0,
            ChatMessage(role=MessageRole.USER, content=task_contract.original_request),
        )

    for message in [*fixed[-4:], *recent]:
        content = message.content
        if len(content) > per_message_chars:
            content = content[:per_message_chars] + "\n[较长内容已截断，完整内容保存在本地记录中]"
        remaining = max_chars - used
        if remaining <= 0:
            break
        if len(content) > remaining:
            content = content[:remaining] + "\n[上下文容量已满]"
        selected.append(message.model_copy(update={"content": content}))
        used += len(content)
    return tuple(selected)
