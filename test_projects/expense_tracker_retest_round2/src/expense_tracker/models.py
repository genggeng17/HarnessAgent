"""记账领域模型。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True, slots=True)
class Expense:
    """一笔不可变的支出记录。"""

    expense_id: str
    spent_on: date
    category: str
    amount: Decimal
    note: str = ""

    def __post_init__(self) -> None:
        category = self.category.strip()
        if not category:
            raise ValueError("支出分类不能为空")
        if self.amount <= 0:
            raise ValueError("支出金额必须大于零")
        object.__setattr__(self, "category", category)
        object.__setattr__(self, "note", self.note.strip())

    def to_dict(self) -> dict[str, str]:
        """转换为适合 JSON 保存的字典。"""

        return {
            "expense_id": self.expense_id,
            "spent_on": self.spent_on.isoformat(),
            "category": self.category,
            "amount": str(self.amount),
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, str]) -> "Expense":
        """从 JSON 字典恢复支出，并拒绝无效金额。"""

        try:
            amount = Decimal(payload["amount"])
        except (InvalidOperation, KeyError) as exc:
            raise ValueError("支出金额格式无效") from exc
        return cls(
            expense_id=payload["expense_id"],
            spent_on=date.fromisoformat(payload["spent_on"]),
            category=payload["category"],
            amount=amount,
            note=payload.get("note", ""),
        )

