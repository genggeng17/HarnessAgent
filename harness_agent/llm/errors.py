"""LLM 端口的稳定错误类型。"""


class LLMError(RuntimeError):
    """所有 LLM 调用错误的基类。"""


class MockResponseExhaustedError(LLMError):
    """MockLLMClient 没有剩余预设响应。"""
