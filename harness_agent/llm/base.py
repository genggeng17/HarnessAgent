"""LLMClient 的公共端口。"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol, Sequence

from pydantic import BaseModel, ConfigDict


class MessageRole(StrEnum):
    """第一阶段上下文消息角色。"""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ChatMessage(BaseModel):
    """供应商无关的对话消息。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: MessageRole
    content: str


class LLMResponse(BaseModel):
    """单次模型调用的最小返回值。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    content: str
    model: str
    finish_reason: str = "stop"
    request_id: str | None = None


class LLMClient(Protocol):
    """真实 Provider 与 Mock 必须实现的异步接口。"""

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        tool_specs: Sequence[dict[str, object]] = (),
    ) -> LLMResponse:
        """完成一次模型调用，不执行 Agent 循环。"""

        ...

