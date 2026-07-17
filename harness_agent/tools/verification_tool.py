"""已注册验证器工具；命令执行复用统一 ShellExecutor。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from harness_agent.runtime.workspace import LocalWorkspace
from harness_agent.tools.models import ExecutionContext, SideEffect, ToolKind, ToolResult
from harness_agent.tools.shell import ShellExecutor


class ValidatorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
    argv: tuple[str, ...] = Field(min_length=1, max_length=256)
    cwd: str = "."
    timeout_seconds: float = Field(default=60, gt=0, le=3600)
    required: bool = True


class RunVerificationArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    validator_id: str


class RunVerificationTool:
    name = "run_verification"
    description = "运行配置中预先注册的可信验证器"
    kind = ToolKind.VERIFICATION
    side_effect = SideEffect.PROCESS
    idempotent = True
    arguments_model = RunVerificationArguments

    def __init__(
        self,
        executor: ShellExecutor,
        validators: tuple[ValidatorConfig, ...] | list[ValidatorConfig],
    ) -> None:
        self.executor = executor
        self.validators = {validator.id: validator for validator in validators}
        if len(self.validators) != len(validators):
            raise ValueError("validator id 不得重复")

    async def execute(
        self,
        arguments: BaseModel,
        workspace: LocalWorkspace,
        execution_context: ExecutionContext,
        *,
        tool_call_id: str,
    ) -> ToolResult:
        args = RunVerificationArguments.model_validate(arguments)
        validator = self.validators.get(args.validator_id)
        if validator is None:
            raise ValueError(f"验证器未注册：{args.validator_id}")
        cwd = workspace.resolve_path(validator.cwd)
        if not cwd.is_dir():
            raise ValueError(f"验证器 cwd 不是目录：{validator.cwd}")
        return await self.executor.execute(
            argv=validator.argv,
            cwd=cwd,
            timeout_seconds=validator.timeout_seconds,
            tool_name=self.name,
            tool_call_id=tool_call_id,
            execution_context=execution_context,
            data={
                "validator_id": validator.id,
                "required": validator.required,
            },
        )

    @property
    def required_validator_ids(self) -> frozenset[str]:
        return frozenset(
            validator.id for validator in self.validators.values() if validator.required
        )
