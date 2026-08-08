"""长期记忆只保存事实与明确决定，不保存模型猜测。"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ProjectFact(BaseModel):
    """可由项目文件重新验证的一条事实。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fact_id: str = Field(default_factory=lambda: str(uuid4()))
    key: str = Field(min_length=1, max_length=200)
    value: str = Field(min_length=1, max_length=4000)
    source_path: str = Field(min_length=1)
    evidence_summary: str = Field(min_length=1, max_length=4000)
    updated_at: datetime = Field(default_factory=_now)
    valid: bool = True


class Decision(BaseModel):
    """用户明确确认或项目规范直接规定的长期决定。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision_id: str = Field(default_factory=lambda: str(uuid4()))
    content: str = Field(min_length=1, max_length=4000)
    source: str = Field(pattern=r"^(user_confirmed|project_spec)$")
    created_at: datetime = Field(default_factory=_now)
