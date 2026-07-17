"""可序列化、按顺序返回固定响应的 Mock LLM。"""

from __future__ import annotations

from typing import Sequence

from pydantic import BaseModel, ConfigDict, Field

from harness_agent.llm.base import ChatMessage, LLMClient, LLMResponse
from harness_agent.llm.errors import MockResponseExhaustedError


class MockLLMSnapshot(BaseModel):
    """Mock 调用进度的可持久化快照。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    responses: tuple[str, ...]
    cursor: int = Field(default=0, ge=0)
    model: str = "mock-llm"


class MockLLMClient(LLMClient):
    """每次调用消费一条预设 JSON 文本。"""

    def __init__(
        self,
        responses: Sequence[str],
        *,
        cursor: int = 0,
        model: str = "mock-llm",
    ) -> None:
        if cursor < 0 or cursor > len(responses):
            raise ValueError("cursor 必须位于响应序列范围内")
        self._responses = tuple(responses)
        self._cursor = cursor
        self._model = model

    @property
    def cursor(self) -> int:
        """下一条待消费响应的位置。"""

        return self._cursor

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        tool_specs: Sequence[dict[str, object]] = (),
    ) -> LLMResponse:
        """返回下一条固定响应；参数仅用于满足真实端口。"""

        del messages, tool_specs
        if self._cursor >= len(self._responses):
            raise MockResponseExhaustedError("Mock LLM 预设响应已耗尽")
        content = self._responses[self._cursor]
        request_id = f"mock-{self._cursor}"
        self._cursor += 1
        return LLMResponse(
            content=content,
            model=self._model,
            request_id=request_id,
        )

    def snapshot(self) -> MockLLMSnapshot:
        """保存剩余响应位置，用于 Session 恢复测试。"""

        return MockLLMSnapshot(
            responses=self._responses,
            cursor=self._cursor,
            model=self._model,
        )

    @classmethod
    def from_snapshot(cls, snapshot: MockLLMSnapshot) -> MockLLMClient:
        """从快照恢复 Mock。"""

        return cls(
            snapshot.responses,
            cursor=snapshot.cursor,
            model=snapshot.model,
        )

