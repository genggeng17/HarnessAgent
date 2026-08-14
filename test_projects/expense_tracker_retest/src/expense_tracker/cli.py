"""Expense Tracker 命令行入口。"""

from __future__ import annotations

import argparse
from pathlib import Path

from expense_tracker.service import ExpenseService
from expense_tracker.storage import JsonExpenseRepository


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="本地支出记录工具")
    parser.add_argument("--data", type=Path, default=Path("expenses.json"))
    commands = parser.add_subparsers(dest="command", required=True)

    add = commands.add_parser("add", help="添加支出")
    add.add_argument("--date", required=True)
    add.add_argument("--category", required=True)
    add.add_argument("--amount", required=True)
    add.add_argument("--note", default="")

    listing = commands.add_parser("list", help="列出支出")
    listing.add_argument("--month")

    report = commands.add_parser("report", help="生成月报")
    report.add_argument("--month", required=True)

    summary = commands.add_parser("summary", help="按分类汇总")
    summary.add_argument("--month", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    service = ExpenseService(JsonExpenseRepository(args.data))
    try:
        if args.command == "add":
            expense = service.add_expense(
                spent_on=args.date,
                category=args.category,
                amount=args.amount,
                note=args.note,
            )
            print(f"已添加：{expense.spent_on} {expense.category} {expense.amount}")
        elif args.command == "list":
            for expense in service.list_expenses(month=args.month):
                print(
                    f"{expense.spent_on} | {expense.category} | "
                    f"{expense.amount} | {expense.note}"
                )
        elif args.command == "summary":
            totals = service.category_totals(month=args.month)
            for category, amount in totals.items():
                print(f"{category}: {amount}")
        elif args.command == "report":
            report_text = service.monthly_report(month=args.month)
            print(report_text)
    except ValueError as exc:
        print(f"错误：{exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

