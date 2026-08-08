"""只追加的 Turn 事件时间线。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class EventType(StrEnum):
    TURN_STARTED = "TURN_STARTED"
    STATE_CHANGED = "STATE_CHANGED"
    APPROVAL_REQUESTED = "APPROVAL_REQUESTED"
    APPROVAL_RESOLVED = "APPROVAL_RESOLVED"
    TOOL_DISPATCHING = "TOOL_DISPATCHING"
    TOOL_FINISHED = "TOOL_FINISHED"
    TOOL_EXECUTION_UNKNOWN = "TOOL_EXECUTION_UNKNOWN"
    TURN_FINISHED = "TURN_FINISHED"


class Event(BaseModel):
    """已经发生的事实；不作为状态恢复来源。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    turn_id: str
    type: EventType
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    action_id: str | None = None
    tool_call_id: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)


class EventSink(Protocol):
    """事件落地或展示的最小接口。"""

    def emit(self, event: Event) -> None:
        """接收已经发生的事件。"""


class TraceWriter:
    """将事件追加到单个 Turn 的 trace.jsonl。"""

    def __init__(self, path: Path) -> None:
        self.path = path

    def emit(self, event: Event) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(event.model_dump(mode="json"), ensure_ascii=False))
            handle.write("\n")
            handle.flush()


class EventBus:
    """向多个记录器或界面转发同一条事件。"""

    def __init__(self, sinks: tuple[EventSink, ...] = ()) -> None:
        self.sinks = list(sinks)

    def add_sink(self, sink: EventSink) -> None:
        self.sinks.append(sink)

    def emit(self, event: Event) -> None:
        for sink in self.sinks:
            sink.emit(event)
