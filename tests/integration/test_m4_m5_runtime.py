"""M4/M5：审批恢复、崩溃保护、会话与本地持久化场景。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from harness_agent.agent.action_parser import ActionParser
from harness_agent.agent.interactions import ToolCallSnapshot
from harness_agent.agent.loop import AgentLoop
from harness_agent.agent.loop_guard import LoopGuard
from harness_agent.agent.state import TurnPhase, TurnState
from harness_agent.agent.state_machine import StateMachine
from harness_agent.agent.verification import VerificationService
from harness_agent.governance.policy import PolicyEngine
from harness_agent.llm.mock import MockLLMClient
from harness_agent.runtime.manager import ProjectRuntime, SessionManager, TurnManager
from harness_agent.tools.dispatcher import ToolDispatcher
from harness_agent.tools.models import ExecutionContext
from harness_agent.tools.readonly import readonly_tools
from harness_agent.tools.registry import ToolRegistry
from harness_agent.tools.shell import RunShellTool, ShellExecutor


def action(action_type: str, **payload: object) -> str:
    return json.dumps({"schema_version": 1, "type": action_type, **payload})


class M4M5RuntimeTests(unittest.IsolatedAsyncioTestCase):
    def make_shell_loop(self, root: Path, responses: list[str]) -> AgentLoop:
        executor = ShellExecutor()
        return AgentLoop(
            llm=MockLLMClient(responses),
            parser=ActionParser(),
            state_machine=StateMachine(),
            loop_guard=LoopGuard(),
            policy=PolicyEngine(),
            dispatcher=ToolDispatcher(ToolRegistry([RunShellTool(executor)])),
            verification_service=VerificationService(),
            workspace=ProjectRuntime.open(root).workspace,
            execution_context=ExecutionContext(turn_id="test"),
        )

    @staticmethod
    def plan() -> str:
        return action("plan", items=[{"id": "command", "description": "运行命令"}])

    @staticmethod
    def shell() -> str:
        return action(
            "tool_call",
            tool="run_shell",
            arguments={"argv": [sys.executable, "-c", "print('ok')"]},
        )

    async def test_approval_pauses_then_runs_exact_original_tool_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            loop = self.make_shell_loop(
                Path(directory),
                [self.plan(), self.shell(), action("final", outcome="success", message="完成")],
            )

            waiting = await loop.run("运行命令")

            self.assertEqual(waiting.state.phase, TurnPhase.WAITING_FOR_USER)
            self.assertIsNotNone(waiting.state.pending_interaction)
            resumed = await loop.resume(
                state=waiting.state,
                prior_messages=waiting.messages,
                user_response="允许",
                approved=True,
            )

            self.assertEqual(resumed.state.phase, TurnPhase.COMPLETED)
            self.assertEqual(resumed.state.tool_calls, 1)
            self.assertEqual(len(resumed.tool_results), 1)
            self.assertEqual(resumed.state.approval_grant.status, "consumed")

    async def test_denied_approval_returns_evidence_to_model_without_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            loop = self.make_shell_loop(
                Path(directory),
                [self.plan(), self.shell(), action("final", outcome="partial", message="用户未允许")],
            )
            waiting = await loop.run("运行命令")

            result = await loop.resume(
                state=waiting.state,
                prior_messages=waiting.messages,
                user_response="拒绝",
                approved=False,
            )

            self.assertEqual(result.state.phase, TurnPhase.FAILED)
            self.assertEqual(result.state.tool_calls, 0)
            self.assertEqual(result.tool_results, ())
            self.assertIn("approval_denied", result.messages[-2].content)

    async def test_clarification_really_stops_until_user_reply(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            loop = self.make_shell_loop(
                Path(directory),
                [
                    action("ask_clarification", question="目标文件是什么？"),
                    action("final", outcome="success", message="已收到答案"),
                ],
            )
            waiting = await loop.run("需要信息")

            self.assertEqual(waiting.state.phase, TurnPhase.WAITING_FOR_USER)
            self.assertEqual(len(waiting.messages), 2)
            result = await loop.resume(
                state=waiting.state,
                prior_messages=waiting.messages,
                user_response="app.py",
            )

            self.assertEqual(result.state.phase, TurnPhase.COMPLETED)
            self.assertEqual(result.state.final_message, "已收到答案")

    async def test_crash_window_becomes_unknown_instead_of_replaying(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = ProjectRuntime.open(root)
            session = SessionManager(runtime).create()
            state = StateMachine().start(TurnState())
            snapshot = ToolCallSnapshot(
                action_id="action", action_digest="digest", tool_name="run_shell",
                arguments={"argv": ["fake"]}, workspace_id=runtime.workspace.workspace_id,
            )
            tool = RunShellTool(ShellExecutor())
            execution = AgentLoop._execution(snapshot, tool)
            state = StateMachine().mark_tool_dispatching(state, execution)
            runtime.turn_store.create(session.session_id, state)
            manager = TurnManager(runtime)
            loop = self.make_shell_loop(root, [])

            recovered = await manager.recover_interrupted(
                session_id=session.session_id, state=state, loop=loop
            )

            self.assertEqual(recovered.phase, TurnPhase.WAITING_FOR_USER)
            self.assertEqual(recovered.tool_execution.status, "execution_unknown")
            self.assertEqual(recovered.pending_interaction.kind, "execution_unknown")

    async def test_session_turn_state_transcript_and_trace_are_written(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "note.txt").write_text("hello\n", encoding="utf-8")
            runtime = ProjectRuntime.open(root)
            session = SessionManager(runtime).create()
            loop = AgentLoop(
                llm=MockLLMClient(
                    [
                        action("tool_call", tool="read_file", arguments={"path": "note.txt"}),
                        action("final", outcome="success", message="读完了"),
                    ]
                ),
                parser=ActionParser(),
                state_machine=StateMachine(),
                loop_guard=LoopGuard(),
                policy=PolicyEngine(),
                dispatcher=ToolDispatcher(ToolRegistry(list(readonly_tools()))),
                verification_service=VerificationService(),
                workspace=runtime.workspace,
                execution_context=ExecutionContext(turn_id="unused"),
            )

            result = await TurnManager(runtime).run_new(
                session_id=session.session_id, user_task="读取 note", loop=loop
            )
            turn_dir = runtime.turn_store.turn_dir(session.session_id, result.state.turn_id)

            self.assertEqual(result.state.phase, TurnPhase.COMPLETED)
            self.assertTrue((turn_dir / "state.json").exists())
            self.assertTrue((turn_dir / "result.json").exists())
            self.assertTrue((turn_dir / "commands.log").exists())
            self.assertTrue((turn_dir / "trace.jsonl").exists())
            self.assertGreaterEqual(len(runtime.session_store.load_messages(session.session_id)), 3)

    async def test_runtime_reads_root_agents_rules_but_not_env_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "AGENTS.md").write_text("只使用中文。\n", encoding="utf-8")
            (root / ".env").write_text("UNRELATED_SECRET=do-not-load-as-rule\n", encoding="utf-8")

            runtime = ProjectRuntime.open(root)

            self.assertEqual(runtime.project_instructions, "只使用中文。\n")
            self.assertNotIn("do-not-load-as-rule", runtime.project_instructions)


if __name__ == "__main__":
    unittest.main()
