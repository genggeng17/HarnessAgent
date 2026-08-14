"""使用操作系统钥匙串保存真实 Provider 凭据。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


SERVICE_NAME = "HarnessAgent"


class CredentialError(RuntimeError):
    """操作系统钥匙串不可用或凭据操作失败。"""


class CredentialSource(StrEnum):
    """运行时实际使用的凭据来源。"""

    SYSTEM_KEYRING = "system_keyring"


@dataclass(frozen=True)
class ResolvedCredential:
    """只在进程内短暂存在的凭据及来源。"""

    value: str
    source: CredentialSource


class CredentialBackend(Protocol):
    """最小钥匙串端口，便于使用内存替身离线测试。"""

    def get_password(self, service: str, username: str) -> str | None: ...

    def set_password(self, service: str, username: str, password: str) -> None: ...

    def delete_password(self, service: str, username: str) -> None: ...


class SystemKeyringBackend:
    """对 Python keyring 的薄封装。"""

    def __init__(self) -> None:
        try:
            import keyring
        except ImportError as exc:  # pragma: no cover - 安装包会声明该依赖
            raise CredentialError("缺少 keyring 依赖，无法访问系统钥匙串") from exc
        self._keyring = keyring

    def get_password(self, service: str, username: str) -> str | None:
        return self._keyring.get_password(service, username)

    def set_password(self, service: str, username: str, password: str) -> None:
        self._keyring.set_password(service, username, password)

    def delete_password(self, service: str, username: str) -> None:
        self._keyring.delete_password(service, username)


class CredentialManager:
    """提供不回显明文的 Provider Key 生命周期。"""

    def __init__(self, backend: CredentialBackend | None = None) -> None:
        self._backend = backend or SystemKeyringBackend()

    @staticmethod
    def _account(credential_name: str) -> str:
        return credential_name

    def get(self, credential_name: str) -> str | None:
        """读取 Key；底层异常被转换为不含敏感值的稳定错误。"""

        try:
            return self._backend.get_password(
                SERVICE_NAME, self._account(credential_name)
            )
        except Exception as exc:
            raise CredentialError("无法读取系统钥匙串，请检查系统凭据后端") from exc

    def set(self, credential_name: str, value: str) -> None:
        """新增或覆盖 Key，禁止保存空白值。"""

        secret = value.strip()
        if not secret:
            raise CredentialError("API Key 不能为空")
        try:
            self._backend.set_password(
                SERVICE_NAME, self._account(credential_name), secret
            )
        except Exception as exc:
            raise CredentialError("无法写入系统钥匙串，请检查系统凭据后端") from exc

    def is_configured(self, credential_name: str) -> bool:
        """只返回是否存在，不返回或打印明文。"""

        return self.get(credential_name) is not None

    def clear(self, credential_name: str) -> bool:
        """删除系统钥匙串中的 Key；不存在时保持幂等。"""

        if self.get(credential_name) is None:
            return False
        try:
            self._backend.delete_password(
                SERVICE_NAME, self._account(credential_name)
            )
        except Exception as exc:
            raise CredentialError("无法清除系统钥匙串，请检查系统凭据后端") from exc
        return True


def resolve_api_key(
    credential_name: str, manager: CredentialManager
) -> ResolvedCredential | None:
    """只从系统钥匙串解析 Key。"""

    keyring_value = manager.get(credential_name)
    if keyring_value:
        return ResolvedCredential(keyring_value, CredentialSource.SYSTEM_KEYRING)
    return None
