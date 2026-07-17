"""验证类 ToolResult 的客观薄封装。"""

from __future__ import annotations

from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from harness_agent.tools.models import ToolResult, ToolResultStatus


class VerificationResult(BaseModel):
    """只表达命令是否客观通过，不推测错误原因。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    verification_id: str
    validator_id: str
    workspace_revision: int
    tool_call_id: str
    passed: bool
    exit_code: int | None
    timed_out: bool
    output_summary: str
    tool_result_ref: str
    command_log_ref: str | None


class VerificationService:
    """根据启动、超时与退出码生成确定性的 VerificationResult。"""

    def evaluate(
        self,
        result: ToolResult,
        *,
        validator_id: str,
        workspace_revision: int,
    ) -> VerificationResult:
        passed = (
            result.status == ToolResultStatus.SUCCEEDED
            and not result.timed_out
            and result.exit_code == 0
            and result.error is None
        )
        pieces = [part for part in (result.stdout_summary, result.stderr_summary) if part]
        if result.error:
            pieces.append(result.error)
        summary = "\n".join(pieces)
        return VerificationResult(
            verification_id=str(uuid4()),
            validator_id=validator_id,
            workspace_revision=workspace_revision,
            tool_call_id=result.tool_call_id,
            passed=passed,
            exit_code=result.exit_code,
            timed_out=result.timed_out,
            output_summary=summary,
            tool_result_ref=f"tool_result:{result.tool_call_id}",
            command_log_ref=result.command_log_ref,
        )
