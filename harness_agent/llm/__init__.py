"""可注入的单次 LLM 调用抽象。"""

from harness_agent.llm.base import ChatMessage, LLMClient, LLMResponse
from harness_agent.llm.mock import MockLLMClient

__all__ = ["ChatMessage", "LLMClient", "LLMResponse", "MockLLMClient"]

