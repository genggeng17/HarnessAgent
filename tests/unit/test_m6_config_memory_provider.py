"""M6：配置、治理、长期记忆和 DeepSeek Provider 的离线测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from harness_agent.config.models import ProjectConfig, load_project_config
from harness_agent.governance.policy import PermissionMode, PolicyEngine, PolicyOutcome
from harness_agent.llm.base import ChatMessage, MessageRole
from harness_agent.llm.deepseek import DeepSeekClient, DeepSeekConfigurationError
from harness_agent.memory.manager import MemoryManager
from harness_agent.memory.models import Decision, ProjectFact
from harness_agent.runtime.workspace import LocalWorkspace
from harness_agent.tools.shell import RunShellTool, ShellExecutor


class M6ConfigMemoryProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_deepseek_v4_pro_uses_configured_compatible_request(self) -> None:
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                json={
                    "id": "request-1",
                    "model": "deepseek-v4-pro",
                    "choices": [
                        {
                            "message": {"content": '{"schema_version":1,"type":"final","outcome":"success","message":"完成"}'},
                            "finish_reason": "stop",
                        }
                    ],
                },
            )

        client = DeepSeekClient(
            api_key="test-key",
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        try:
            response = await client.complete(
                [
                    ChatMessage(role=MessageRole.USER, content="完成任务"),
                    ChatMessage(role=MessageRole.TOOL, content="工具结果"),
                ],
                [{"name": "read_file", "parameters": {}}],
            )
        finally:
            await client._client.aclose()

        body = json.loads(requests[0].content)
        self.assertEqual(str(requests[0].url), "https://njusehub.info/v1/chat/completions")
        self.assertEqual(requests[0].headers["authorization"], "Bearer test-key")
        self.assertEqual(body["model"], "deepseek-v4-pro")
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertEqual(body["messages"][-1]["role"], "user")
        self.assertTrue(
            body["messages"][-1]["content"].startswith("HARNESS_TOOL_OBSERVATION")
        )
        system_prompt = body["messages"][0]["content"]
        self.assertIn("完整 Action JSON Schema", system_prompt)
        self.assertIn('"schema_version":{"const":1', system_prompt)
        self.assertIn("禁止 Markdown", system_prompt)
        self.assertIn('"type":"tool_call"', system_prompt)
        self.assertIn("单次或两次只读操作不要建立计划", system_prompt)
        self.assertIn("已有专用文件工具时不得改用 Shell", system_prompt)
        self.assertEqual(response.model, "deepseek-v4-pro")

    async def test_deepseek_requires_key(self) -> None:
        with self.assertRaises(DeepSeekConfigurationError):
            DeepSeekClient(api_key="")

    async def test_deepseek_retries_rate_limit_then_returns_response(self) -> None:
        attempts = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return httpx.Response(429, json={"error": {"message": "busy"}})
            return httpx.Response(
                200,
                json={
                    "id": "request-2",
                    "choices": [{"message": {"content": "{}"}}],
                },
            )

        transport = httpx.MockTransport(handler)
        client = DeepSeekClient(
            api_key="test-key",
            client=httpx.AsyncClient(transport=transport),
        )
        try:
            response = await client.complete([])
        finally:
            await client._client.aclose()

        self.assertEqual(attempts, 2)
        self.assertEqual(response.content, "{}")

    async def test_policy_distinguishes_read_only_and_dangerous_shell(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = LocalWorkspace("test", Path(directory))
            shell = RunShellTool(ShellExecutor())
            readonly = PolicyEngine(PermissionMode.READ_ONLY)
            safe = PolicyEngine(PermissionMode.SAFE_EDIT)

            self.assertEqual(
                readonly.evaluate(shell, {"argv": ["git", "status"]}, workspace).outcome,
                PolicyOutcome.ALLOW,
            )
            self.assertEqual(
                readonly.evaluate(shell, {"argv": ["pip", "install", "x"]}, workspace).outcome,
                PolicyOutcome.DENY,
            )
            self.assertEqual(
                safe.evaluate(shell, {"argv": ["pip", "install", "x"]}, workspace).outcome,
                PolicyOutcome.ASK,
            )
            self.assertEqual(
                safe.evaluate(shell, {"argv": ["git", "reset", "--hard"]}, workspace).outcome,
                PolicyOutcome.DENY,
            )

    async def test_memory_keeps_evidence_and_rejects_unconfirmed_decision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = MemoryManager(Path(directory))
            fact = manager.upsert_fact(
                ProjectFact(
                    key="test_command",
                    value="python -m pytest",
                    source_path="pyproject.toml",
                    evidence_summary="pytest 配置指向 tests",
                )
            )
            self.assertEqual(manager.select_facts("test")[0].fact_id, fact.fact_id)
            invalid = manager.invalidate_fact(fact.fact_id)
            self.assertFalse(invalid.valid)
            self.assertEqual(manager.select_facts("test"), ())

            decision = Decision(content="保持 UTF-8 编码", source="user_confirmed")
            with self.assertRaises(ValueError):
                manager.append_decision(decision, explicitly_confirmed=False)
            manager.append_decision(decision, explicitly_confirmed=True)
            self.assertEqual(manager.list_decisions()[0].content, "保持 UTF-8 编码")

    async def test_config_is_strict_and_detects_python_validator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
            config = load_project_config(root)
            self.assertEqual(config.validators[0].id, "python_tests")
            config_path = root / ".agent" / "config.json"
            config_path.parent.mkdir()
            config_path.write_text('{"schema_version":1,"unknown":true}', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_project_config(root)
            self.assertEqual(ProjectConfig().deepseek.model, "deepseek-v4-pro")

    async def test_project_env_is_not_loaded_as_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text(
                "# 本地密钥\nNEW_API_KEY='from-env-file'\n",
                encoding="utf-8",
            )
            config = load_project_config(root)

            self.assertEqual(config.deepseek.credential_name, "deepseek-v4-pro")
            self.assertFalse(hasattr(config.deepseek, "api_key_env"))

    async def test_config_detects_multiple_real_test_systems(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pyproject.toml").write_text(
                "[project]\nname='mixed'\n", encoding="utf-8"
            )
            (root / "package.json").write_text(
                json.dumps({"scripts": {"test": "vitest run"}}), encoding="utf-8"
            )

            config = load_project_config(root)

            self.assertEqual(
                [validator.id for validator in config.validators],
                ["python_tests", "node_tests"],
            )

    async def test_config_ignores_npm_placeholder_test(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text(
                json.dumps(
                    {
                        "scripts": {
                            "test": 'echo "Error: no test specified" && exit 1'
                        }
                    }
                ),
                encoding="utf-8",
            )

            config = load_project_config(root)

            self.assertEqual(config.validators, ())


if __name__ == "__main__":
    unittest.main()
