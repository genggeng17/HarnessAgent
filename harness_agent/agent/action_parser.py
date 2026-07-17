"""严格解析 LLM 返回的单个 Action JSON。"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from harness_agent.agent.actions import Action


class ActionParseErrorCode(StrEnum):
    """可稳定回灌给 LLM 的解析错误代码。"""

    INVALID_JSON = "invalid_json"
    DUPLICATE_KEY = "duplicate_key"
    NOT_AN_OBJECT = "not_an_object"
    SCHEMA_ERROR = "schema_error"


class ActionParseError(ValueError):
    """Action 无法通过确定性解析。"""

    def __init__(self, code: ActionParseErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ParsedAction(BaseModel):
    """Harness 接受 Action 后附加的稳定运行期信息。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action_id: str
    digest: str
    action: Action


class _DuplicateKeyError(ValueError):
    """JSON 对象出现重复字段。"""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError(f"JSON 字段重复：{key}")
        result[key] = value
    return result


class ActionParser:
    """把模型文本转换为带 ID 和摘要的 Action。"""

    def __init__(self) -> None:
        self._adapter = TypeAdapter(Action)

    def parse(self, raw: str) -> ParsedAction:
        """解析一个完整 JSON 对象；任何歧义都显式失败。"""

        try:
            payload = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
        except _DuplicateKeyError as exc:
            raise ActionParseError(ActionParseErrorCode.DUPLICATE_KEY, str(exc)) from exc
        except json.JSONDecodeError as exc:
            raise ActionParseError(
                ActionParseErrorCode.INVALID_JSON,
                f"Action 必须是单个合法 JSON 对象：{exc.msg}",
            ) from exc

        if not isinstance(payload, dict):
            raise ActionParseError(
                ActionParseErrorCode.NOT_AN_OBJECT,
                "Action 顶层必须是 JSON 对象",
            )

        try:
            action = self._adapter.validate_python(payload)
        except ValidationError as exc:
            raise ActionParseError(
                ActionParseErrorCode.SCHEMA_ERROR,
                self._format_validation_error(exc),
            ) from exc

        canonical = json.dumps(
            action.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return ParsedAction(
            action_id=str(uuid4()),
            digest=hashlib.sha256(canonical).hexdigest(),
            action=action,
        )

    @staticmethod
    def _format_validation_error(exc: ValidationError) -> str:
        errors: list[str] = []
        for error in exc.errors(include_url=False):
            location = ".".join(str(part) for part in error["loc"])
            errors.append(f"{location or 'action'}: {error['msg']}")
        return "Action Schema 校验失败：" + "; ".join(errors)
