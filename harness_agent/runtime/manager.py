"""项目、会话和 Turn 的组合与持久化协调。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from harness_agent.agent.interactions import ToolExecutionStatus
from harness_agent.agent.loop import AgentLoop, AgentLoopResult
from harness_agent.agent.state import TurnPhase, TurnState
from harness_agent.config.models import ProjectConfig, load_project_config
from harness_agent.memory.manager import MemoryManager
from harness_agent.runtime.workspace import LocalWorkspace
from harness_agent.storage.local import LocalSessionStore, LocalTurnStore, SessionMetadata, TurnMetadata
from harness_agent.tracing.events import Event, EventBus, EventType, TraceWriter


@dataclass(frozen=True, slots=True)
class ProjectRuntime:
    """组合项目级资源，不保存某个 Turn 的可变状态。"""

    project_root: Path
    workspace: LocalWorkspace
    session_store: LocalSessionStore
    turn_store: LocalTurnStore
    config: ProjectConfig
    memory: MemoryManager
    project_instructions: str = ""

    @classmethod
    def open(cls, project_root: Path, *, workspace_id: str = "default") -> "ProjectRuntime":
        """基于项目根目录创建本地运行时资源。"""

        root = project_root.resolve(strict=True)
        workspace = LocalWorkspace(workspace_id=workspace_id, root_path=root)
        sessions = LocalSessionStore(root)
        config = load_project_config(root)
        memory = MemoryManager(root, enabled=config.enable_long_term_memory)
        instructions = cls._load_project_instructions(root)
        return cls(
            root,
            workspace,
            sessions,
            LocalTurnStore(sessions),
            config,
            memory,
            instructions,
        )

    @staticmethod
    def _load_project_instructions(root: Path) -> str:
        """读取根目录项目规则；限制长度，且绝不读取 `.env` 等密钥文件。"""

        path = root / "AGENTS.md"
        if not path.is_file():
            return ""
        content = path.read_text(encoding="utf-8")
        limit = 12_000
        if len(content) <= limit:
            return content
        return content[:limit] + "\n[项目规则因长度限制已截断]"


class SessionManager:
    """创建和读取多轮会话。"""

    def __init__(self, runtime: ProjectRuntime) -> None:
        self.runtime = runtime

    def create(self) -> SessionMetadata:
        return self.runtime.session_store.create(
            workspace_id=self.runtime.workspace.workspace_id,
            root_path=self.runtime.workspace.root_path,
        )

    def messages(self, session_id: str):  # type: ignore[no-untyped-def]
        return self.runtime.session_store.load_messages(session_id)


class TurnManager:
    """唯一负责 Turn 状态、结果和 Trace 写入的运行时入口。"""

    def __init__(self, runtime: ProjectRuntime) -> None:
        self.runtime = runtime

    async def run_new(
        self, *, session_id: str, user_task: str, loop: AgentLoop
    ) -> AgentLoopResult:
        state = TurnState()
        self.runtime.turn_store.create(session_id, state)
        self._prepare_loop_context(session_id, state.turn_id, loop)
        bus = EventBus((TraceWriter(self.runtime.turn_store.trace_path(session_id, state.turn_id)),))
        self._emit(bus, session_id, state, EventType.TURN_STARTED)
        prior = self.runtime.session_store.load_messages(session_id)
        result = await loop.run(
            user_task,
            initial_state=state,
            prior_messages=prior,
            state_observer=self._observer(session_id, bus),
        )
        self._save_messages(session_id, prior, result)
        self._save_result(session_id, result)
        self._emit_terminal(bus, session_id, result.state)
        return result

    async def resume(
        self,
        *,
        session_id: str,
        turn_id: str,
        loop: AgentLoop,
        user_response: str,
        approved: bool | None = None,
        abort: bool = False,
    ) -> AgentLoopResult:
        state = self.runtime.turn_store.load_state(session_id, turn_id)
        self._prepare_loop_context(session_id, turn_id, loop)
        bus = EventBus((TraceWriter(self.runtime.turn_store.trace_path(session_id, turn_id)),))
        state = await self.recover_interrupted(
            session_id=session_id, state=state, loop=loop, event_bus=bus
        )
        prior = self.runtime.session_store.load_messages(session_id)
        self._emit(bus, session_id, state, EventType.APPROVAL_RESOLVED)
        result = await loop.resume(
            state=state,
            prior_messages=prior,
            user_response=user_response,
            approved=approved,
            abort=abort,
            state_observer=self._observer(session_id, bus),
        )
        self._save_messages(session_id, prior, result)
        self._save_result(session_id, result)
        self._emit_terminal(bus, session_id, result.state)
        return result

    async def recover_interrupted(
        self,
        *,
        session_id: str,
        state: TurnState,
        loop: AgentLoop,
        event_bus: EventBus | None = None,
    ) -> TurnState:
        """把崩溃窗口中的 DISPATCHING 转为未知，绝不静默重试。"""

        execution = state.tool_execution
        if execution is None or execution.status != ToolExecutionStatus.DISPATCHING:
            return state
        state = loop.state_machine.mark_execution_unknown(state)
        self.runtime.turn_store.save_state(session_id, state)
        if event_bus is not None:
            self._emit(event_bus, session_id, state, EventType.TOOL_EXECUTION_UNKNOWN)
        return state

    def list_resumable(self) -> tuple[TurnMetadata, ...]:
        return self.runtime.turn_store.list_resumable()

    def _prepare_loop_context(self, session_id: str, turn_id: str, loop: AgentLoop) -> None:
        """让统一 Shell 执行器把完整输出写到当前 Turn。"""

        loop.execution_context = loop.execution_context.model_copy(
            update={
                "turn_id": turn_id,
                "command_log_dir": self.runtime.turn_store.command_log_path(session_id, turn_id),
            }
        )

    def _observer(self, session_id: str, event_bus: EventBus):
        async def save(state: TurnState) -> None:
            self.runtime.turn_store.save_state(session_id, state)
            event_type = EventType.STATE_CHANGED
            if state.pending_interaction is not None:
                event_type = EventType.APPROVAL_REQUESTED
            elif state.tool_execution is not None:
                if state.tool_execution.status == ToolExecutionStatus.DISPATCHING:
                    event_type = EventType.TOOL_DISPATCHING
                elif state.tool_execution.status in {
                    ToolExecutionStatus.SUCCEEDED,
                    ToolExecutionStatus.FAILED,
                }:
                    event_type = EventType.TOOL_FINISHED
            self._emit(event_bus, session_id, state, event_type)

        return save

    def _save_messages(self, session_id: str, prior, result: AgentLoopResult) -> None:  # type: ignore[no-untyped-def]
        for message in result.messages[len(prior) :]:
            self.runtime.session_store.append_message(session_id, message)

    def _save_result(self, session_id: str, result: AgentLoopResult) -> None:
        self.runtime.turn_store.save_result(
            session_id,
            result.state.turn_id,
            result.model_dump(mode="json"),
        )

    @staticmethod
    def _emit(event_bus: EventBus, session_id: str, state: TurnState, event_type: EventType) -> None:
        execution = state.tool_execution
        event_bus.emit(
            Event(
                session_id=session_id,
                turn_id=state.turn_id,
                type=event_type,
                tool_call_id=execution.tool_call_id if execution else None,
                payload={"phase": state.phase.value},
            )
        )

    def _emit_terminal(self, event_bus: EventBus, session_id: str, state: TurnState) -> None:
        if state.phase in {TurnPhase.COMPLETED, TurnPhase.FAILED, TurnPhase.ABORTED}:
            self._emit(event_bus, session_id, state, EventType.TURN_FINISHED)
