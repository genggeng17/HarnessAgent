"""业务服务测试。"""

from decimal import Decimal
from pathlib import Path

import pytest

from expense_tracker.service import ExpenseService
from expense_tracker.storage import JsonExpenseRepository


def service_at(path: Path) -> ExpenseService:
    return ExpenseService(JsonExpenseRepository(path / "expenses.json"))


def test_add_list_and_filter_by_month(tmp_path: Path) -> None:
    service = service_at(tmp_path)
    service.add_expense(spent_on="2026-08-02", category="交通", amount="12.00")
    service.add_expense(spent_on="2026-07-31", category="餐饮", amount="20.00")

    august = service.list_expenses(month="2026-08")

    assert len(august) == 1
    assert august[0].category == "交通"


def test_category_totals_are_exact_and_sorted(tmp_path: Path) -> None:
    service = service_at(tmp_path)
    service.add_expense(spent_on="2026-08-01", category="餐饮", amount="10.10")
    service.add_expense(spent_on="2026-08-02", category="交通", amount="3.20")
    service.add_expense(spent_on="2026-08-03", category="餐饮", amount="5.05")

    totals = service.category_totals(month="2026-08")

    assert totals == {"交通": Decimal("3.20"), "餐饮": Decimal("15.15")}


def test_invalid_month_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="YYYY-MM"):
        service_at(tmp_path).list_expenses(month="2026-8")


def test_monthly_report_returns_markdown(tmp_path: Path) -> None:
    """验证 monthly_report 返回包含标题、明细表、汇总表及合计的 Markdown。"""
    service = service_at(tmp_path)
    service.add_expense(spent_on="2026-08-01", category="餐饮", amount="10.10")
    service.add_expense(spent_on="2026-08-02", category="交通", amount="3.20")
    service.add_expense(spent_on="2026-08-03", category="餐饮", amount="5.05", note="午餐")

    report = service.monthly_report(month="2026-08")

    assert "# 2026-08 月度支出报告" in report
    assert "## 支出明细" in report
    assert "## 分类汇总" in report
    assert "| 日期 | 分类 | 金额 | 备注 |" in report
    assert "| 2026-08-01 | 餐饮 | 10.10 |  |" in report
    assert "| 2026-08-02 | 交通 | 3.20 |  |" in report
    assert "| 2026-08-03 | 餐饮 | 5.05 | 午餐 |" in report
    assert "| 分类 | 金额 |" in report
    assert "| 交通 | 3.20 |" in report
    assert "| 餐饮 | 15.15 |" in report
    assert "总计：18.35" in report


def test_monthly_report_empty_month(tmp_path: Path) -> None:
    """无支出记录的月份返回提示信息。"""
    service = service_at(tmp_path)
    service.add_expense(spent_on="2026-07-01", category="餐饮", amount="10.00")

    report = service.monthly_report(month="2026-08")

    assert "# 2026-08 月度支出报告" in report
    assert "本月暂无支出。" in report


def test_monthly_report_invalid_month_rejected(tmp_path: Path) -> None:
    """monthly_report 对无效月份同样抛出 ValueError。"""
    with pytest.raises(ValueError, match="YYYY-MM"):
        service_at(tmp_path).monthly_report(month="2026-8")

