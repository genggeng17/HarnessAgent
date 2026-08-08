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
    description = "运行配置或项目结构中发现的可信验证器"
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
        visible = "、".join(self.validators) or "暂无固定项"
        self.description = (
            f"运行可信项目测试。当前验证器：{visible}。"
            "传 auto 可在只有一个候选时自动选择，并能发现本次任务中新建的测试配置。"
        )

    async def execute(
        self,
        arguments: BaseModel,
        workspace: LocalWorkspace,
        execution_context: ExecutionContext,
        *,
        tool_call_id: str,
    ) -> ToolResult:
        args = RunVerificationArguments.model_validate(arguments)
        validator = self._resolve_validator(args.validator_id, workspace)
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

    @property
    def validator_configs(self) -> tuple[ValidatorConfig, ...]:
        """返回模型上下文可展示的只读验证器配置。"""

        return tuple(self.validators.values())

    def _resolve_validator(
        self, validator_id: str, workspace: LocalWorkspace
    ) -> ValidatorConfig:
        """先用启动时配置；必要时重新检查本次任务新建的项目测试标记。"""

        if validator_id != "auto" and validator_id in self.validators:
            return self.validators[validator_id]
        candidates = self.validators
        if not candidates:
            from harness_agent.config.models import detect_validators

            detected = detect_validators(workspace.root_path)
            candidates = {validator.id: validator for validator in detected}
        if validator_id != "auto":
            validator = candidates.get(validator_id)
            if validator is None:
                available = "、".join(candidates) or "无"
                raise ValueError(
                    f"验证器未注册：{validator_id}；当前可用验证器：{available}"
                )
            return validator
        if len(candidates) == 1:
            return next(iter(candidates.values()))
        if not candidates:
            raise ValueError("没有发现可用测试命令，请先检查或创建项目测试配置")
        raise ValueError(f"发现多个验证器，请明确选择：{'、'.join(candidates)}")
