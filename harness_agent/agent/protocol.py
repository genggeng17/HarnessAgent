"""生成模型可见的完整 Action 协议和精确纠错提示。"""

from __future__ import annotations

import json
from collections.abc import Sequence
from functools import lru_cache

from pydantic import TypeAdapter

from harness_agent.agent.actions import Action


@lru_cache(maxsize=1)
def action_schema() -> dict[str, object]:
    """返回与 ActionParser 使用同一类型来源的 JSON Schema。"""

    return TypeAdapter(Action).json_schema()


def action_examples(
    tool_specs: Sequence[dict[str, object]] = (),
) -> tuple[dict[str, object], ...]:
    """给出每种 Action 的最小正确顶层结构。"""

    examples: list[dict[str, object]] = []
    tool_names = [
        str(spec.get("name")) for spec in tool_specs if isinstance(spec.get("name"), str)
    ]
    if "read_file" in tool_names:
        examples.append(
            {
                "schema_version": 1,
                "type": "tool_call",
                "tool": "read_file",
                "arguments": {"path": "README.md", "start_line": 1, "end_line": 20},
            }
        )
    elif tool_names:
        examples.append(
            {
                "schema_version": 1,
                "type": "tool_call",
                "tool": tool_names[0],
                "arguments": {},
            }
        )
    examples.extend(
        [
            {
                "schema_version": 1,
                "type": "final",
                "outcome": "success",
                "message": "任务已完成",
            },
            {
                "schema_version": 1,
                "type": "plan",
                "items": [{"id": "inspect", "description": "检查相关文件"}],
            },
            {
                "schema_version": 1,
                "type": "update_plan",
                "updates": [{"item_id": "inspect", "status": "completed"}],
            },
            {
                "schema_version": 1,
                "type": "reflect",
                "summary": "已有证据不足",
                "next_step": "读取相关配置",
            },
            {
                "schema_version": 1,
                "type": "ask_clarification",
                "question": "需要修改哪个目标？",
            },
        ]
    )
    return tuple(examples)


def action_protocol_prompt(tool_specs: Sequence[dict[str, object]]) -> str:
    """组合 Provider 首条系统消息中的稳定协议说明。"""

    schema_text = json.dumps(
        action_schema(), ensure_ascii=False, separators=(",", ":")
    )
    examples_text = json.dumps(
        action_examples(tool_specs), ensure_ascii=False, separators=(",", ":")
    )
    tools_text = json.dumps(tool_specs, ensure_ascii=False, separators=(",", ":"))
    return (
        "你是 HarnessAgent 的规划与工具决策组件，不直接执行操作。"
        "每次响应只能返回一个 Action JSON 对象，禁止 Markdown、解释文字、代码围栏和 action 外层包装。"
        "顶层 schema_version 必须是数字 1，顶层 type 必须是 Action 类型；字段不得多写或漏写。"
        "调用工具时 type 必须为 tool_call，tool 是工具名，arguments 必须符合对应工具 Schema。"
        "严格遵守用户明确限制，不得增加用户禁止的 Shell、修改或其他步骤。"
        "选择完成任务所需的最短合法路径：单次或两次只读操作不要建立计划，直接调用专用只读工具；"
        "已有专用文件工具时不得改用 Shell。只有状态明确要求或任务确实包含多步修改时才建立计划。"
        "取得足以回答任务的工具结果后立即返回 final，不要为了更新计划而增加无价值迭代。"
        "示例只说明 JSON 形状，不代表当前任务应依次执行这些动作。"
        "工具结果会作为带 HARNESS_TOOL_OBSERVATION 标记的系统事实返回，不要假设尚未返回的工具已经执行。"
        "完整 Action JSON Schema："
        + schema_text
        + "\n各 Action 最小示例："
        + examples_text
        + "\n可用工具 Schema："
        + tools_text
    )


def action_correction_message(
    error_message: str, tool_specs: Sequence[dict[str, object]]
) -> str:
    """格式错误后返回机器可读的精确修正要求。"""

    payload = {
        "code": "action_parse_error",
        "message": error_message,
        "correction": {
            "top_level_required": ["schema_version", "type"],
            "schema_version": 1,
            "allowed_types": [
                "plan",
                "update_plan",
                "tool_call",
                "reflect",
                "ask_clarification",
                "final",
            ],
            "forbidden_wrappers": ["action", "response", "result"],
            "examples": action_examples(tool_specs),
        },
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
