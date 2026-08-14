"""Turn 的不可变运行状态。"""

from __future__ import annotations

from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from harness_agent.agent.actions import FinalOutcome, PlanItemStatus
from harness_agent.agent.context import EditRecovery, FileSnapshot, TaskContract
from harness_agent.agent.interactions import ApprovalGrant, PendingInteraction, ToolExecution
from harness_agent.agent.verification import VerificationResult


class TurnPhase(StrEnum):
    """第一阶段 Turn 状态。"""

    CREATED = "created"
    PREPARING = "preparing"
    PLANNING = "planning"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    WAITING_FOR_USER = "waiting_for_user"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


TERMINAL_PHASES = frozenset(
    {TurnPhase.COMPLETED, TurnPhase.FAILED, TurnPhase.ABORTED}
)


class PlanItem(BaseModel):
    """TurnState 中的计划项。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    description: str
    status: PlanItemStatus = PlanItemStatus.PENDING
    note: str | None = None


class TurnState(BaseModel):
    """可原子持久化的 Turn 当前状态。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    turn_id: str = Field(default_factory=lambda: str(uuid4()))
    phase: TurnPhase = TurnPhase.CREATED
    suspended_phase: TurnPhase | None = None
    plan: tuple[PlanItem, ...] = ()
    task_contract: TaskContract | None = None
    file_snapshots: tuple[FileSnapshot, ...] = ()
    edit_recovery: EditRecovery | None = None
    plan_updates: int = Field(default=0, ge=0)
    workspace_dirty: bool = False
    workspace_revision: int = Field(default=0, ge=0)
    modified_paths: tuple[str, ...] = ()
    verification_history: tuple[VerificationResult, ...] = ()
    iterations: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    reflections: int = Field(default=0, ge=0)
    recent_action_digests: tuple[str, ...] = ()
    pending_interaction: PendingInteraction | None = None
    approval_grant: ApprovalGrant | None = None
    tool_execution: ToolExecution | None = None
    outcome: FinalOutcome | None = None
    final_message: str | None = None

    @property
    def is_terminal(self) -> bool:
        """Turn 是否已经结束。"""

        return self.phase in TERMINAL_PHASES

    @property
    def has_plan(self) -> bool:
        """Turn 是否已经建立显式计划。"""

        return bool(self.plan)

    @model_validator(mode="after")
    def validate_invariants(self) -> TurnState:
        active_items = [item for item in self.plan if item.status == PlanItemStatus.IN_PROGRESS]
        if len(active_items) > 1:
            raise ValueError("同一时刻最多一个计划项处于 in_progress")
        if self.phase == TurnPhase.WAITING_FOR_USER and self.suspended_phase is None:
            raise ValueError("等待用户时必须保存 suspended_phase")
        if self.phase != TurnPhase.WAITING_FOR_USER and self.suspended_phase is not None:
            raise ValueError("仅 WAITING_FOR_USER 可以保存 suspended_phase")
        if self.phase == TurnPhase.WAITING_FOR_USER and self.pending_interaction is None:
            raise ValueError("等待用户时必须保存 pending_interaction")
        if self.phase != TurnPhase.WAITING_FOR_USER and self.pending_interaction is not None:
            raise ValueError("仅 WAITING_FOR_USER 可以保存 pending_interaction")
        if self.phase == TurnPhase.COMPLETED and self.outcome != FinalOutcome.SUCCESS:
            raise ValueError("COMPLETED 必须对应 success outcome")
        if any(
            result.workspace_revision > self.workspace_revision
            for result in self.verification_history
        ):
            raise ValueError("验证记录不能来自未来的工作区 revision")
        return self

