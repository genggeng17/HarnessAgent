"""MemoryManager 是长期记忆的唯一业务写入入口。"""

from __future__ import annotations

import json
from pathlib import Path

from harness_agent.memory.models import Decision, ProjectFact
from harness_agent.storage.local import _append_jsonl, _write_json_atomically


class MemoryManager:
    """保存可复查事实和明确决定，并提供按需上下文。"""

    def __init__(self, project_root: Path, *, enabled: bool = True) -> None:
        self.project_root = project_root.resolve(strict=True)
        self.enabled = enabled
        self.directory = self.project_root / ".agent" / "memory"
        self.project_path = self.directory / "project.json"
        self.decisions_path = self.directory / "decisions.jsonl"

    def list_facts(self, *, include_invalid: bool = False) -> tuple[ProjectFact, ...]:
        if not self.project_path.exists():
            return ()
        facts = tuple(
            ProjectFact.model_validate(item)
            for item in json.loads(self.project_path.read_text(encoding="utf-8"))
        )
        return facts if include_invalid else tuple(item for item in facts if item.valid)

    def select_facts(self, query: str, *, limit: int = 20) -> tuple[ProjectFact, ...]:
        """以简单文字匹配按需选取，而不是注入所有历史。"""

        needle = query.lower()
        matches = [
            item
            for item in self.list_facts()
            if needle in f"{item.key}\n{item.value}\n{item.evidence_summary}".lower()
        ]
        return tuple(matches[:limit])

    def upsert_fact(self, fact: ProjectFact) -> ProjectFact:
        """写入带来源证据的项目事实；相同 key 与来源会更新。"""

        if not self.enabled:
            return fact
        facts = list(self.list_facts(include_invalid=True))
        for index, current in enumerate(facts):
            if current.key == fact.key and current.source_path == fact.source_path:
                facts[index] = fact
                break
        else:
            facts.append(fact)
        _write_json_atomically(self.project_path, [item.model_dump(mode="json") for item in facts])
        return fact

    def invalidate_fact(self, fact_id: str) -> ProjectFact:
        """保留历史但不再把失效事实送入模型上下文。"""

        facts = list(self.list_facts(include_invalid=True))
        for index, fact in enumerate(facts):
            if fact.fact_id == fact_id:
                invalid = fact.model_copy(update={"valid": False})
                facts[index] = invalid
                _write_json_atomically(
                    self.project_path, [item.model_dump(mode="json") for item in facts]
                )
                return invalid
        raise KeyError(f"项目事实不存在：{fact_id}")

    def list_decisions(self) -> tuple[Decision, ...]:
        if not self.decisions_path.exists():
            return ()
        return tuple(
            Decision.model_validate(json.loads(line))
            for line in self.decisions_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )

    def select_decisions(self, query: str, *, limit: int = 20) -> tuple[Decision, ...]:
        needle = query.lower()
        return tuple(
            item for item in self.list_decisions() if needle in item.content.lower()
        )[:limit]

    def append_decision(self, decision: Decision, *, explicitly_confirmed: bool) -> Decision:
        """拒绝写入模型猜测，调用方必须明确声明来源已经确认。"""

        if decision.source == "user_confirmed" and not explicitly_confirmed:
            raise ValueError("用户未明确确认，不能保存为长期决定")
        if not self.enabled:
            return decision
        _append_jsonl(self.decisions_path, decision.model_dump(mode="json"))
        return decision

    def context(self, user_task: str) -> str:
        """为当前任务选择少量相关记忆。"""

        if not self.enabled:
            return ""
        facts = self.select_facts(user_task)
        decisions = self.select_decisions(user_task)
        parts = [
            f"项目事实：{item.key}={item.value}（来源 {item.source_path}；{item.evidence_summary}）"
            for item in facts
        ]
        parts.extend(f"已确认决定：{item.content}" for item in decisions)
        return "\n".join(parts)
