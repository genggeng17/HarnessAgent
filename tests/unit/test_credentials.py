"""系统钥匙串凭据生命周期与 CLI 的离线测试。"""

from __future__ import annotations

import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harness_agent.cli.main import main
from harness_agent.credentials import (
    CredentialManager,
    CredentialSource,
    resolve_api_key,
)


class FakeKeyring:
    """不访问操作系统的内存钥匙串。"""

    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.values.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.values[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.values.pop((service, username), None)


class CredentialTests(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = FakeKeyring()
        self.manager = CredentialManager(self.backend)

    def test_keyring_lifecycle_never_requires_plaintext_status(self) -> None:
        self.assertFalse(self.manager.is_configured("deepseek-v4-pro"))

        self.manager.set("deepseek-v4-pro", "secret-value")
        self.assertTrue(self.manager.is_configured("deepseek-v4-pro"))
        self.assertEqual(self.manager.get("deepseek-v4-pro"), "secret-value")

        self.assertTrue(self.manager.clear("deepseek-v4-pro"))
        self.assertFalse(self.manager.clear("deepseek-v4-pro"))
        self.assertIsNone(self.manager.get("deepseek-v4-pro"))

    def test_resolve_uses_only_system_keyring(self) -> None:
        self.manager.set("deepseek-v4-pro", "from-keyring")
        with patch.dict(os.environ, {"NEW_API_KEY": "must-be-ignored"}):
            resolved = resolve_api_key("deepseek-v4-pro", self.manager)
        self.assertEqual(resolved.value, "from-keyring")
        self.assertEqual(resolved.source, CredentialSource.SYSTEM_KEYRING)

    def test_cli_set_status_update_and_clear_without_echoing_secret(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = io.StringIO()
            manager_factory = lambda: self.manager
            with (
                patch("harness_agent.cli.main.CredentialManager", manager_factory),
                patch("harness_agent.cli.main.getpass.getpass", return_value="first-secret"),
                patch("sys.stdout", output),
            ):
                self.assertEqual(
                    main(["--project", str(root), "credentials", "set"]), 0
                )
                self.assertEqual(
                    main(["--project", str(root), "credentials", "status"]), 0
                )

            text = output.getvalue()
            self.assertIn("系统钥匙串", text)
            self.assertNotIn("first-secret", text)

            with (
                patch("harness_agent.cli.main.CredentialManager", manager_factory),
                patch("harness_agent.cli.main.getpass.getpass", return_value="updated-secret"),
            ):
                self.assertEqual(
                    main(["--project", str(root), "credentials", "update"]), 0
                )
                self.assertEqual(self.manager.get("deepseek-v4-pro"), "updated-secret")
                self.assertEqual(
                    main(["--project", str(root), "credentials", "clear"]), 0
                )
                self.assertFalse(self.manager.is_configured("deepseek-v4-pro"))


if __name__ == "__main__":
    unittest.main()
