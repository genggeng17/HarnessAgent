"""JSON 文件持久化。"""

from __future__ import annotations

import json
from pathlib import Path

from expense_tracker.models import Expense


class JsonExpenseRepository:
    """以原子替换方式保存支出列表。"""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> tuple[Expense, ...]:
        if not self.path.exists():
            return ()
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("支出数据必须是 JSON 数组")
        return tuple(Expense.from_dict(item) for item in payload)

    def save(self, expenses: tuple[Expense, ...]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        body = [expense.to_dict() for expense in expenses]
        temporary.write_text(
            json.dumps(body, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)

