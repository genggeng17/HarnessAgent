"""记账业务服务。"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from expense_tracker.models import Expense
from expense_tracker.storage import JsonExpenseRepository


class ExpenseService:
    """组合支出校验、查询和汇总。"""

    def __init__(self, repository: JsonExpenseRepository) -> None:
        self.repository = repository

    def add_expense(
        self,
        *,
        spent_on: str,
        category: str,
        amount: str,
        note: str = "",
    ) -> Expense:
        try:
            parsed_amount = Decimal(amount)
        except InvalidOperation as exc:
            raise ValueError("支出金额格式无效") from exc
        expense = Expense(
            expense_id=str(uuid4()),
            spent_on=date.fromisoformat(spent_on),
            category=category,
            amount=parsed_amount,
            note=note,
        )
        expenses = (*self.repository.load(), expense)
        self.repository.save(expenses)
        return expense

    def list_expenses(self, *, month: str | None = None) -> tuple[Expense, ...]:
        expenses = self.repository.load()
        if month is None:
            return tuple(sorted(expenses, key=lambda item: (item.spent_on, item.expense_id)))
        self._validate_month(month)
        return tuple(
            expense
            for expense in sorted(expenses, key=lambda item: (item.spent_on, item.expense_id))
            if expense.spent_on.strftime("%Y-%m") == month
        )

    def category_totals(self, *, month: str) -> dict[str, Decimal]:
        totals: dict[str, Decimal] = {}
        for expense in self.list_expenses(month=month):
            totals[expense.category] = totals.get(expense.category, Decimal("0")) + expense.amount
        return dict(sorted(totals.items()))

    def monthly_report(self, *, month: str) -> str:
        """生成指定月份的 Markdown 月报。

        包含支出明细表、分类汇总表及当月合计。
        """
        self._validate_month(month)
        expenses = self.list_expenses(month=month)
        if not expenses:
            return f"# {month} 月度支出报告\n\n本月暂无支出。\n"

        lines: list[str] = []
        lines.append(f"# {month} 月度支出报告")
        lines.append("")

        # 支出明细表
        lines.append("## 支出明细")
        lines.append("")
        lines.append("| 日期 | 分类 | 金额 | 备注 |")
        lines.append("|------|------|------|------|")
        for expense in expenses:
            note = expense.note if expense.note else ""
            lines.append(
                f"| {expense.spent_on} | {expense.category} | {expense.amount} | {note} |"
            )
        lines.append("")

        # 分类汇总表
        totals = self.category_totals(month=month)
        lines.append("## 分类汇总")
        lines.append("")
        lines.append("| 分类 | 金额 |")
        lines.append("|------|------|")
        for category, amount in totals.items():
            lines.append(f"| {category} | {amount} |")
        lines.append("")

        total = sum(totals.values(), Decimal("0"))
        lines.append(f"总计：{total}")
        lines.append("")

        # 确保以换行结尾
        lines.append("")
        return "\n".join(lines)

    def budget_check(self, *, month: str, limit: str) -> dict[str, object]:
        """检查指定月份的预算执行情况。"""
        self._validate_month(month)
        try:
            budget_limit = Decimal(limit)
        except InvalidOperation as exc:
            raise ValueError("预算金额格式无效") from exc
        if budget_limit <= 0:
            raise ValueError("预算金额必须大于零")

        spent = sum(
            (expense.amount for expense in self.list_expenses(month=month)),
            Decimal("0"),
        )
        remaining = budget_limit - spent
        over_budget = remaining < 0
        over_amount = -remaining if over_budget else Decimal("0")
        return {
            "month": month,
            "limit": budget_limit,
            "spent": spent,
            "remaining": remaining,
            "over_budget": over_budget,
            "over_amount": over_amount,
        }

    @staticmethod
    def _validate_month(month: str) -> None:
        try:
            parsed = datetime.strptime(month, "%Y-%m")
        except ValueError as exc:
            raise ValueError("月份必须使用 YYYY-MM 格式") from exc
        if parsed.strftime("%Y-%m") != month:
            raise ValueError("月份必须使用 YYYY-MM 格式")

