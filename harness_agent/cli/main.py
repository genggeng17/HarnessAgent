"""M5 最小交互式 CLI；真实模型接入将在 M6 提供。"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import sys
from pathlib import Path

from harness_agent.agent.action_parser import ActionParser
from harness_agent.agent.loop import AgentLoop
from harness_agent.agent.loop_guard import LoopGuard
from harness_agent.agent.state_machine import StateMachine
from harness_agent.agent.verification import VerificationService
from harness_agent.config.models import ProjectConfig, load_project_config
from harness_agent.credentials import (
    CredentialManager,
    CredentialSource,
    resolve_api_key,
)
from harness_agent.governance.policy import PolicyEngine
from harness_agent.llm.base import LLMClient
from harness_agent.llm.deepseek import DeepSeekClient
from harness_agent.llm.mock import MockLLMClient
from harness_agent.runtime.manager import ProjectRuntime, SessionManager, TurnManager
from harness_agent.tools.dispatcher import ToolDispatcher
from harness_agent.tools.models import ExecutionContext
from harness_agent.tools.patch import ApplyPatchTool, BatchExactEditTool, ExactEditTool
from harness_agent.tools.readonly import readonly_tools
from harness_agent.tools.registry import ToolRegistry
from harness_agent.tools.shell import RunShellTool, ShellExecutor
from harness_agent.tools.verification_tool import RunVerificationTool


def build_parser() -> argparse.ArgumentParser:
    """创建命令行参数解析器。"""

    parser = argparse.ArgumentParser(description="本地 HarnessAgent（DeepSeek-V4-Pro）")
    parser.add_argument("--project", type=Path, default=Path.cwd(), help="目标项目目录")
    parser.add_argument(
        "--mock-responses",
        type=Path,
        help="可选的离线测试响应文件；省略时调用 DeepSeek-V4-Pro",
    )
    commands = parser.add_subparsers(dest="command")
    credentials = commands.add_parser(
        "credentials", help="在系统钥匙串中管理 DeepSeek API Key"
    )
    credential_actions = credentials.add_subparsers(
        dest="credential_action", required=True
    )
    credential_actions.add_parser("set", help="隐藏录入并保存 API Key")
    credential_actions.add_parser("update", help="隐藏录入并覆盖已有 API Key")
    credential_actions.add_parser("status", help="查看配置状态，不回显明文")
    credential_actions.add_parser("clear", help="清除系统钥匙串中的 API Key")
    return parser


def _credential_command(
    action: str,
    config: ProjectConfig,
    manager: CredentialManager,
) -> int:
    """执行凭据子命令，所有输出均不包含 Key 明文。"""

    credential_name = config.deepseek.credential_name
    if action in {"set", "update"}:
        verb = "更新" if action == "update" else "保存"
        value = getpass.getpass("DeepSeek API Key（输入隐藏）> ")
        manager.set(credential_name, value)
        print(f"已在系统钥匙串中{verb} DeepSeek API Key。")
        return 0
    if action == "status":
        resolved = resolve_api_key(credential_name, manager)
        if resolved is None:
            print("DeepSeek API Key：未配置。")
        else:
            print("DeepSeek API Key：已在系统钥匙串中配置。")
        return 0
    if action == "clear":
        removed = manager.clear(credential_name)
        if removed:
            print("已清除系统钥匙串中的 DeepSeek API Key。")
        else:
            print("系统钥匙串中没有 DeepSeek API Key，无需清除。")
        return 0
    raise ValueError(f"未知凭据操作：{action}")


def _resolve_or_prompt_api_key(
    config: ProjectConfig,
    manager: CredentialManager,
) -> str:
    """首次真实运行缺少 Key 时，以隐藏输入引导保存到系统钥匙串。"""

    credential_name = config.deepseek.credential_name
    resolved = resolve_api_key(credential_name, manager)
    if resolved is not None:
        return resolved.value
    if not sys.stdin.isatty():
        raise RuntimeError(
            "未配置 DeepSeek API Key；请先运行 "
            "`harness-agent credentials set` 安全录入系统钥匙串"
        )
    print("首次运行尚未配置 DeepSeek API Key，将安全保存到系统钥匙串。")
    value = getpass.getpass("DeepSeek API Key（输入隐藏，直接回车取消）> ")
    if not value.strip():
        raise RuntimeError("已取消 API Key 录入")
    manager.set(credential_name, value)
    print("API Key 已保存；状态查询不会回显明文。")
    return value.strip()


def _load_mock_responses(path: Path) -> list[str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise ValueError("--mock-responses 必须是 JSON 字符串数组")
    return raw


def _build_loop(runtime: ProjectRuntime, client: LLMClient) -> AgentLoop:
    executor = ShellExecutor()
    registry = ToolRegistry(
        [
            *readonly_tools(),
            ApplyPatchTool(),
            ExactEditTool(),
            BatchExactEditTool(),
            RunShellTool(executor),
            RunVerificationTool(executor, runtime.config.validators),
        ]
    )
    return AgentLoop(
        llm=client,
        parser=ActionParser(),
        state_machine=StateMachine(),
        loop_guard=LoopGuard(runtime.config.loop_guard),
        policy=PolicyEngine(
            runtime.config.permission_mode,
            read_only_command_allowlist=runtime.config.read_only_command_allowlist,
        ),
        dispatcher=ToolDispatcher(registry),
        verification_service=VerificationService(),
        workspace=runtime.workspace,
        execution_context=ExecutionContext(turn_id="cli"),
        memory_context_provider=runtime.memory.context,
        project_instructions=runtime.project_instructions,
    )


async def _interactive(runtime: ProjectRuntime, client: LLMClient) -> int:
    sessions = SessionManager(runtime)
    turns = TurnManager(runtime)
    session = sessions.create()
    active: tuple[str, str] | None = None
    print(f"会话已创建：{session.session_id}")
    print("输入任务开始；/resume 恢复等待任务；exit 退出。")

    while True:
        try:
            text = input("\n任务> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已退出。可使用 /resume 恢复等待中的任务。")
            return 0
        if text in {"exit", "quit"}:
            return 0
        if not text:
            continue
        if text == "/resume":
            choices = turns.list_resumable()
            if not choices:
                print("没有可恢复的任务。")
                continue
            if len(choices) > 1:
                print("可恢复任务：")
                for item in choices:
                    print(f"  {item.session_id} {item.turn_id}")
                print("请用 /resume <session_id> <turn_id> 指定一个任务。")
                continue
            active = (choices[0].session_id, choices[0].turn_id)
        elif text.startswith("/resume "):
            parts = text.split()
            if len(parts) != 3:
                print("格式：/resume <session_id> <turn_id>")
                continue
            active = (parts[1], parts[2])
        else:
            loop = _build_loop(runtime, client)
            result = await turns.run_new(session_id=session.session_id, user_task=text, loop=loop)
            active = (session.session_id, result.state.turn_id)
            _show_result(result)
            if result.state.pending_interaction is None:
                active = None
            continue

        if active is None:
            continue
        state = runtime.turn_store.load_state(*active)
        pending = state.pending_interaction
        if pending is None:
            print("该任务当前不需要用户处理。")
            active = None
            continue
        print(f"需要你的回应：{pending.prompt}")
        answer = input("回答（yes/no/abort 或文字）> ").strip()
        loop = _build_loop(runtime, client)
        approved = True if answer.lower() in {"yes", "y", "允许"} else False if answer.lower() in {"no", "n", "拒绝"} else None
        result = await turns.resume(
            session_id=active[0],
            turn_id=active[1],
            loop=loop,
            user_response=answer,
            approved=approved,
            abort=answer.lower() in {"abort", "停止"},
        )
        _show_result(result)
        if result.state.pending_interaction is None:
            active = None


async def _run_client(runtime: ProjectRuntime, client: LLMClient) -> int:
    """运行交互界面并在退出时关闭真实 HTTP 客户端。"""

    try:
        return await _interactive(runtime, client)
    finally:
        if isinstance(client, DeepSeekClient):
            await client.aclose()


def _show_result(result) -> None:  # type: ignore[no-untyped-def]
    print(f"状态：{result.state.phase.value}")
    if result.state.final_message:
        print(result.state.final_message)
    if result.state.modified_paths:
        print(f"修改文件：{len(result.state.modified_paths)} 个")
        for path in result.state.modified_paths:
            print(f"  {path}")
    current_results = {}
    for verification in result.state.verification_history:
        if verification.workspace_revision == result.state.workspace_revision:
            current_results[verification.validator_id] = verification
    if current_results:
        passed = sum(item.passed for item in current_results.values())
        print(
            f"当前版本验证：{passed}/{len(current_results)} 项通过"
            f"（revision {result.state.workspace_revision}）"
        )
        for validator_id, verification in sorted(current_results.items()):
            status = "通过" if verification.passed else "失败"
            print(f"  {validator_id}: {status}")
    if result.state.workspace_dirty:
        print("验证状态：修改尚未通过全部必需检查")
    if result.state.pending_interaction:
        print(f"等待：{result.state.pending_interaction.prompt}")


def main(argv: list[str] | None = None) -> int:
    """运行命令行程序。"""

    args = build_parser().parse_args(argv)
    try:
        if args.command == "credentials":
            project_root = args.project.resolve(strict=True)
            config = load_project_config(project_root)
            return _credential_command(
                args.credential_action, config, CredentialManager()
            )
        runtime = ProjectRuntime.open(args.project)
        if args.mock_responses:
            client: LLMClient = MockLLMClient(_load_mock_responses(args.mock_responses))
        else:
            api_key = _resolve_or_prompt_api_key(
                runtime.config, CredentialManager()
            )
            client = DeepSeekClient(
                api_key=api_key,
                base_url=runtime.config.deepseek.base_url,
                model=runtime.config.deepseek.model,
                timeout_seconds=runtime.config.deepseek.timeout_seconds,
                max_retries=runtime.config.deepseek.max_retries,
            )
        return asyncio.run(_run_client(runtime, client))
    except (OSError, ValueError, json.JSONDecodeError, RuntimeError) as exc:
        print(f"启动失败：{exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
