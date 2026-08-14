"""JSON 仓库测试。"""

from datetime import date
from decimal import Decimal
from pathlib import Path

from expense_tracker.models import Expense
from expense_tracker.storage import JsonExpenseRepository


def test_repository_returns_empty_then_round_trips(tmp_path: Path) -> None:
    repository = JsonExpenseRepository(tmp_path / "nested" / "expenses.json")
    assert repository.load() == ()
    expected = (Expense("id", date(2026, 8, 1), "学习", Decimal("88.00")),)

    repository.save(expected)

    assert repository.load() == expected

