"""命令行入口测试。"""

from pathlib import Path

from expense_tracker.cli import main


def test_cli_add_and_summary(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    data = tmp_path / "expenses.json"
    assert main(["--data", str(data), "add", "--date", "2026-08-01", "--category", "餐饮", "--amount", "9.90"]) == 0
    assert "已添加" in capsys.readouterr().out

    assert main(["--data", str(data), "summary", "--month", "2026-08"]) == 0
    assert "餐饮: 9.90" in capsys.readouterr().out


def test_cli_report(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """验证 report 命令输出标题、明细、分类汇总和精确总计。"""
    data = tmp_path / "expenses.json"
    main(["--data", str(data), "add", "--date", "2026-08-01", "--category", "餐饮", "--amount", "12.00"])
    main(["--data", str(data), "add", "--date", "2026-08-02", "--category", "交通", "--amount", "8.00"])
    main(["--data", str(data), "add", "--date", "2026-08-03", "--category", "餐饮", "--amount", "20.00"])
    capsys.readouterr()

    assert main(["--data", str(data), "report", "--month", "2026-08"]) == 0
    out = capsys.readouterr().out

    # 标题正确显示实际月份
    assert "# 2026-08 月度支出报告" in out

    # 支出明细表
    assert "## 支出明细" in out
    assert "餐饮" in out
    assert "交通" in out

    assert "总计：40.00" in out
    assert "## 分类排名" not in out


def test_cli_budget_within(tmp_path: Path, capsys) -> None:
    data = tmp_path / "expenses.json"
    main(["--data", str(data), "add", "--date", "2026-08-01", "--category", "餐饮", "--amount", "30.00"])
    capsys.readouterr()
    assert main(["--data", str(data), "budget", "--month", "2026-08", "--limit", "100.00"]) == 0
    out = capsys.readouterr().out
    assert "月份：2026-08" in out
    assert "预算：100.00" in out
    assert "支出：30.00" in out
    assert "剩余：70.00" in out


def test_cli_budget_over(tmp_path: Path, capsys) -> None:
    data = tmp_path / "expenses.json"
    main(["--data", str(data), "add", "--date", "2026-08-01", "--category", "餐饮", "--amount", "80.00"])
    main(["--data", str(data), "add", "--date", "2026-08-02", "--category", "交通", "--amount", "30.00"])
    capsys.readouterr()
    assert main(["--data", str(data), "budget", "--month", "2026-08", "--limit", "100.00"]) == 0
    out = capsys.readouterr().out
    assert "超支：10.00" in out


def test_cli_budget_no_expenses(tmp_path: Path, capsys) -> None:
    data = tmp_path / "expenses.json"
    assert main(["--data", str(data), "budget", "--month", "2026-08", "--limit", "100.00"]) == 0
    out = capsys.readouterr().out
    assert "支出：0" in out
    assert "剩余：100.00" in out


def test_cli_budget_invalid_error(tmp_path: Path, capsys) -> None:
    data = tmp_path / "expenses.json"
    assert main(["--data", str(data), "budget", "--month", "2026-8", "--limit", "100.00"]) == 2
    out = capsys.readouterr().out
    assert "YYYY-MM" in out
    capsys.readouterr()
    assert main(["--data", str(data), "budget", "--month", "2026-08", "--limit", "abc"]) == 2
    out = capsys.readouterr().out
    assert "预算金额格式无效" in out


