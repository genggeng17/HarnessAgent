"""使用原子 JSON 快照和追加 JSONL 的本地存储实现。"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from harness_agent.agent.state import TERMINAL_PHASES, TurnState
from harness_agent.llm.base import ChatMessage


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _write_json_atomically(path: Path, payload: object) -> None:
    """先写临时文件并 fsync，再替换快照文件。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    body = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _append_jsonl(path: Path, payload: object) -> None:
    """追加一条时间线或对话记录，并尽量落盘。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


class SessionMetadata(BaseModel):
    """一个项目会话的轻量元数据。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str
    workspace_id: str
    root_path: str
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


class TurnMetadata(BaseModel):
    """Turn 所属关系和创建时间。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str
    turn_id: str
    created_at: datetime = Field(default_factory=_utc_now)


class LocalSessionStore:
    """管理 `.agent/sessions/<session-id>` 下的会话文件。"""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve(strict=True)
        self.sessions_root = self.project_root / ".agent" / "sessions"

    def create(self, *, workspace_id: str, root_path: Path) -> SessionMetadata:
        metadata = SessionMetadata(
            session_id=str(uuid4()), workspace_id=workspace_id, root_path=str(root_path)
        )
        _write_json_atomically(
            self.session_dir(metadata.session_id) / "metadata.json",
            metadata.model_dump(mode="json"),
        )
        return metadata

    def load(self, session_id: str) -> SessionMetadata:
        path = self.session_dir(session_id) / "metadata.json"
        return SessionMetadata.model_validate_json(path.read_text(encoding="utf-8"))

    def append_message(self, session_id: str, message: ChatMessage) -> None:
        """保存 Agent 可见的对话消息。"""

        _append_jsonl(
            self.session_dir(session_id) / "transcript.jsonl",
            message.model_dump(mode="json"),
        )

    def load_messages(self, session_id: str) -> tuple[ChatMessage, ...]:
        path = self.session_dir(session_id) / "transcript.jsonl"
        if not path.exists():
            return ()
        return tuple(
            ChatMessage.model_validate(json.loads(line))
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )

    def session_dir(self, session_id: str) -> Path:
        return self.sessions_root / session_id


class LocalTurnStore:
    """Turn 状态、结果、命令日志和恢复列表的唯一文件入口。"""

    def __init__(self, session_store: LocalSessionStore) -> None:
        self.session_store = session_store

    def create(self, session_id: str, state: TurnState) -> TurnMetadata:
        self.session_store.load(session_id)
        metadata = TurnMetadata(session_id=session_id, turn_id=state.turn_id)
        directory = self.turn_dir(session_id, state.turn_id)
        _write_json_atomically(directory / "metadata.json", metadata.model_dump(mode="json"))
        self.save_state(session_id, state)
        (directory / "commands.log").touch(exist_ok=True)
        return metadata

    def load_state(self, session_id: str, turn_id: str) -> TurnState:
        path = self.turn_dir(session_id, turn_id) / "state.json"
        return TurnState.model_validate_json(path.read_text(encoding="utf-8"))

    def save_state(self, session_id: str, state: TurnState) -> None:
        _write_json_atomically(
            self.turn_dir(session_id, state.turn_id) / "state.json",
            state.model_dump(mode="json"),
        )

    def save_result(self, session_id: str, turn_id: str, result: dict[str, object]) -> None:
        _write_json_atomically(self.turn_dir(session_id, turn_id) / "result.json", result)

    def load_metadata(self, session_id: str, turn_id: str) -> TurnMetadata:
        path = self.turn_dir(session_id, turn_id) / "metadata.json"
        return TurnMetadata.model_validate_json(path.read_text(encoding="utf-8"))

    def list_resumable(self) -> tuple[TurnMetadata, ...]:
        if not self.session_store.sessions_root.exists():
            return ()
        resumable: list[TurnMetadata] = []
        for metadata_path in self.session_store.sessions_root.glob("*/turns/*/metadata.json"):
            metadata = TurnMetadata.model_validate_json(metadata_path.read_text(encoding="utf-8"))
            state = self.load_state(metadata.session_id, metadata.turn_id)
            if state.phase not in TERMINAL_PHASES:
                resumable.append(metadata)
        return tuple(resumable)

    def turn_dir(self, session_id: str, turn_id: str) -> Path:
        return self.session_store.session_dir(session_id) / "turns" / turn_id

    def command_log_path(self, session_id: str, turn_id: str) -> Path:
        return self.turn_dir(session_id, turn_id) / "commands.log"

    def trace_path(self, session_id: str, turn_id: str) -> Path:
        return self.turn_dir(session_id, turn_id) / "trace.jsonl"
