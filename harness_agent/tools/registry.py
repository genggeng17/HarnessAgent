"""工具注册表及可信元数据。"""

from __future__ import annotations

from pydantic import BaseModel

from harness_agent.tools.models import Tool


class ToolRegistry:
    """拒绝重名注册，并为 LLM 和治理提供同一份工具事实。"""

    def __init__(self, tools: tuple[Tool, ...] | list[Tool] = ()) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        """注册一个有真实执行者的工具。"""

        if tool.name in self._tools:
            raise ValueError(f"工具重复注册：{tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """按名称查找工具。"""

        return self._tools.get(name)

    def require(self, name: str) -> Tool:
        """查找工具，不存在时显式失败。"""

        tool = self.get(name)
        if tool is None:
            raise KeyError(f"工具未注册：{name}")
        return tool

    def specs(self) -> tuple[dict[str, object], ...]:
        """生成模型可见 Schema；可信治理字段不可由模型覆盖。"""

        specs: list[dict[str, object]] = []
        for tool in self._tools.values():
            model: type[BaseModel] = tool.arguments_model
            specs.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": model.model_json_schema(),
                }
            )
        return tuple(specs)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)
