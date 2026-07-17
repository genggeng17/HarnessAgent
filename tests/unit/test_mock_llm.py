"""MockLLMClient 的顺序消费与恢复测试。"""

import unittest

from harness_agent.llm.errors import MockResponseExhaustedError
from harness_agent.llm.mock import MockLLMClient


class MockLLMClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_responses_in_order(self) -> None:
        client = MockLLMClient(["first", "second"])

        first = await client.complete([])
        second = await client.complete([])

        self.assertEqual(first.content, "first")
        self.assertEqual(second.content, "second")
        self.assertEqual(client.cursor, 2)

    async def test_snapshot_restores_cursor(self) -> None:
        client = MockLLMClient(["first", "second"])
        await client.complete([])

        restored = MockLLMClient.from_snapshot(client.snapshot())
        response = await restored.complete([])

        self.assertEqual(response.content, "second")

    async def test_exhaustion_is_explicit(self) -> None:
        client = MockLLMClient([])

        with self.assertRaises(MockResponseExhaustedError):
            await client.complete([])


if __name__ == "__main__":
    unittest.main()

