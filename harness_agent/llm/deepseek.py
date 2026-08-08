"""DeepSeek-V4-Pro 的 OpenAI 兼容 HTTP 适配器。"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Sequence
from typing import Any

import httpx

from harness_agent.agent.protocol import action_protocol_prompt
from harness_agent.llm.base import ChatMessage, LLMClient, LLMResponse, MessageRole
from harness_agent.llm.errors import LLMError


class DeepSeekConfigurationError(LLMError):
    """缺少密钥或配置无效时抛出。"""


class DeepSeekResponseError(LLMError):
    """接口连续失败或返回不完整内容时抛出。"""


class DeepSeekClient(LLMClient):
    """不依赖厂商 SDK 的 DeepSeek-V4-Pro 异步客户端。"""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = "https://njusehub.info/v1",
        model: str = "deepseek-v4-pro",
        api_key_env: str = "NEW_API_KEY",
        timeout_seconds: float = 60,
        max_retries: int = 2,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get(api_key_env)
        if not self.api_key:
            raise DeepSeekConfigurationError(
                f"未设置 DeepSeek API Key，请设置环境变量 {api_key_env}"
            )
        if model != "deepseek-v4-pro":
            raise DeepSeekConfigurationError("第一阶段真实模型固定为 deepseek-v4-pro")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_retries = max_retries
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None

    async def aclose(self) -> None:
        """关闭本类创建的 HTTP 客户端。"""

        if self._owns_client:
            await self._client.aclose()

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        tool_specs: Sequence[dict[str, object]] = (),
    ) -> LLMResponse:
        """请求一次 JSON Action；只返回 assistant content。"""

        payload = {
            "model": self.model,
            "messages": self._messages(messages, tool_specs),
            "stream": False,
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        last_error: str | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = await self._client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )
            except httpx.TimeoutException as exc:
                last_error = f"网络超时：{exc}"
            except httpx.RequestError as exc:
                last_error = f"网络请求失败：{exc}"
            else:
                if response.status_code in {429, 500, 502, 503, 504}:
                    last_error = f"DeepSeek 暂时不可用：HTTP {response.status_code}"
                elif response.is_error:
                    raise DeepSeekResponseError(
                        f"DeepSeek 请求被拒绝：HTTP {response.status_code} {response.text[:500]}"
                    )
                else:
                    return self._parse_response(response.json())
            if attempt < self.max_retries:
                await asyncio.sleep(0.25 * (attempt + 1))
        raise DeepSeekResponseError(last_error or "DeepSeek 请求失败")

    @staticmethod
    def _messages(
        messages: Sequence[ChatMessage], tool_specs: Sequence[dict[str, object]]
    ) -> list[dict[str, str]]:
        system = action_protocol_prompt(tool_specs)
        converted: list[dict[str, str]] = [{"role": "system", "content": system}]
        for message in messages:
            if message.role == MessageRole.TOOL:
                converted.append(
                    {
                        "role": "user",
                        "content": "HARNESS_TOOL_OBSERVATION\n" + message.content,
                    }
                )
            else:
                converted.append({"role": message.role.value, "content": message.content})
        return converted

    def _parse_response(self, payload: dict[str, Any]) -> LLMResponse:
        try:
            choice = payload["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise DeepSeekResponseError("DeepSeek 响应缺少 assistant content") from exc
        if not isinstance(content, str) or not content.strip():
            raise DeepSeekResponseError("DeepSeek 返回了空的 assistant content")
        return LLMResponse(
            content=content,
            model=str(payload.get("model", self.model)),
            finish_reason=str(choice.get("finish_reason", "stop")),
            request_id=str(payload["id"]) if payload.get("id") is not None else None,
        )
