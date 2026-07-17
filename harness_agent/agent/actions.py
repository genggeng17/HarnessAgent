"""LLM 可输出的第一阶段 Action 数据模型。"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    """公共协议模型：禁止额外字段，避免悄悄接受协议漂移。"""

    model_config = ConfigDict(extra="forbid", frozen=True)


class PlanItemStatus(StrEnum):
    """线性计划项允许的状态。"""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class FinalOutcome(StrEnum):
    """FinalAction 对外表达的结果。"""

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class PlanItemInput(StrictModel):
    """由模型声明的新计划项。"""

    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
    description: str = Field(min_length=1, max_length=500)


class PlanItemUpdate(StrictModel):
    """对已有计划项的状态更新。"""

    item_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
    status: PlanItemStatus
    note: str | None = Field(default=None, max_length=500)


class ActionBase(StrictModel):
    """所有 LLM Action 的公共字段。"""

    schema_version: Literal[1]


class PlanAction(ActionBase):
    """建立或替换当前 Turn 的线性计划。"""

    type: Literal["plan"]
    items: tuple[PlanItemInput, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_unique_item_ids(self) -> PlanAction:
        ids = [item.id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("计划项 id 不得重复")
        return self


class UpdatePlanAction(ActionBase):
    """更新计划项状态，并可在尾部追加新计划项。"""

    type: Literal["update_plan"]
    updates: tuple[PlanItemUpdate, ...] = Field(min_length=1, max_length=100)
    append_items: tuple[PlanItemInput, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def validate_unique_references(self) -> UpdatePlanAction:
        update_ids = [item.item_id for item in self.updates]
        append_ids = [item.id for item in self.append_items]
        if len(update_ids) != len(set(update_ids)):
            raise ValueError("同一计划项不能在一次 Action 中重复更新")
        if len(append_ids) != len(set(append_ids)):
            raise ValueError("追加的计划项 id 不得重复")
        return self


class ToolCallAction(ActionBase):
    """请求调用一个 Registry 中的工具。"""

    type: Literal["tool_call"]
    tool: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    arguments: dict[str, object]


class ReflectAction(ActionBase):
    """基于已有证据修正当前推理方向。"""

    type: Literal["reflect"]
    summary: str = Field(min_length=1, max_length=2000)
    next_step: str = Field(min_length=1, max_length=1000)


class AskClarificationAction(ActionBase):
    """请求用户补充业务信息，不表示治理审批。"""

    type: Literal["ask_clarification"]
    question: str = Field(min_length=1, max_length=1000)
    options: tuple[str, ...] | None = Field(default=None, min_length=2, max_length=10)


class FinalAction(ActionBase):
    """结束当前 Turn。"""

    type: Literal["final"]
    outcome: FinalOutcome
    message: str = Field(min_length=1, max_length=20_000)


Action = Annotated[
    PlanAction
    | UpdatePlanAction
    | ToolCallAction
    | ReflectAction
    | AskClarificationAction
    | FinalAction,
    Field(discriminator="type"),
]

