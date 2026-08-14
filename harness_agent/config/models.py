"""版本化项目配置；密钥不属于项目配置文件。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from harness_agent.agent.loop_guard import LoopGuardConfig
from harness_agent.governance.policy import PermissionMode
from harness_agent.storage.local import _write_json_atomically
from harness_agent.tools.verification_tool import ValidatorConfig


class DeepSeekConfig(BaseModel):
    """DeepSeek OpenAI 兼容接口的非敏感配置。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    base_url: str = "https://njusehub.info/v1"
    model: Literal["deepseek-v4-pro"] = "deepseek-v4-pro"
    credential_name: str = "deepseek-v4-pro"
    timeout_seconds: float = Field(default=60, gt=0, le=600)
    max_retries: int = Field(default=2, ge=0, le=5)


class ProjectConfig(BaseModel):
    """`.agent/config.json` 的完整 Schema。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    permission_mode: PermissionMode = PermissionMode.SAFE_EDIT
    validators: tuple[ValidatorConfig, ...] = ()
    read_only_command_allowlist: tuple[str, ...] = (
        "git status",
        "git diff",
        "git log",
        "git show",
    )
    allow_idempotent_unknown_execution_retry: bool = False
    enable_long_term_memory: bool = True
    loop_guard: LoopGuardConfig = Field(default_factory=LoopGuardConfig)
    deepseek: DeepSeekConfig = Field(default_factory=DeepSeekConfig)

def config_path(project_root: Path) -> Path:
    """返回项目配置的固定位置。"""

    return project_root / ".agent" / "config.json"


def load_project_config(project_root: Path) -> ProjectConfig:
    """读取非敏感项目配置；没有配置文件时使用安全默认值。"""

    path = config_path(project_root)
    if not path.exists():
        return ProjectConfig(validators=detect_validators(project_root))
    return ProjectConfig.model_validate_json(path.read_text(encoding="utf-8"))


def save_project_config(project_root: Path, config: ProjectConfig) -> None:
    """以原子替换保存已校验的配置。"""

    _write_json_atomically(config_path(project_root), config.model_dump(mode="json"))


def detect_validators(project_root: Path) -> tuple[ValidatorConfig, ...]:
    """根据明确项目标记登记常见测试命令；支持一个仓库中的多种项目。"""

    root = project_root.resolve(strict=True)
    validators: list[ValidatorConfig] = []
    python_markers = ("pyproject.toml", "pytest.ini", "setup.cfg", "tox.ini")
    if any((root / name).is_file() for name in python_markers) or _has_python_tests(root):
        validators.append(
            ValidatorConfig(id="python_tests", argv=(sys.executable, "-m", "pytest"))
        )

    package_json = root / "package.json"
    if package_json.is_file() and _has_node_test_script(package_json):
        validators.append(ValidatorConfig(id="node_tests", argv=("npm", "test")))
    if (root / "Cargo.toml").is_file():
        validators.append(ValidatorConfig(id="cargo_tests", argv=("cargo", "test")))
    if (root / "go.mod").is_file():
        validators.append(ValidatorConfig(id="go_tests", argv=("go", "test", "./...")))
    if (root / "pom.xml").is_file():
        validators.append(ValidatorConfig(id="maven_tests", argv=("mvn", "test")))
    if (root / "gradlew.bat").is_file():
        validators.append(
            ValidatorConfig(id="gradle_tests", argv=("gradlew.bat", "test"))
        )
    elif (root / "gradlew").is_file():
        validators.append(ValidatorConfig(id="gradle_tests", argv=("./gradlew", "test")))
    return tuple(validators)


def _has_python_tests(root: Path) -> bool:
    """只在常用测试目录内寻找 Python 测试，避免扫描整个工作区。"""

    for directory_name in ("tests", "test"):
        directory = root / directory_name
        if directory.is_dir() and (
            next(directory.rglob("test_*.py"), None) is not None
            or next(directory.rglob("*_test.py"), None) is not None
        ):
            return True
    return False


def _has_node_test_script(path: Path) -> bool:
    """确认 package.json 真的声明了测试脚本，并过滤 npm 初始化占位脚本。"""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    scripts = payload.get("scripts") if isinstance(payload, dict) else None
    command = scripts.get("test") if isinstance(scripts, dict) else None
    if not isinstance(command, str) or not command.strip():
        return False
    return "no test specified" not in command.lower()
