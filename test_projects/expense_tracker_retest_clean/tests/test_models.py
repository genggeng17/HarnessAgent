"""领域模型测试。"""

from datetime import date
from decimal import Decimal

import pytest

from expense_tracker.models import Expense


def test_expense_round_trip_keeps_decimal_and_chinese() -> None:
    expense = Expense("id-1", date(2026, 8, 1), " 餐饮 ", Decimal("35.50"), " 午餐 ")

    restored = Expense.from_dict(expense.to_dict())

    assert restored == Expense("id-1", date(2026, 8, 1), "餐饮", Decimal("35.50"), "午餐")


@pytest.mark.parametrize("amount", [Decimal("0"), Decimal("-1")])
def test_expense_rejects_non_positive_amount(amount: Decimal) -> None:
    with pytest.raises(ValueError, match="必须大于零"):
        Expense("id", date(2026, 8, 1), "餐饮", amount)

