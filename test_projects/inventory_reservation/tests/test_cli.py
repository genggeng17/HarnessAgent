"""库存命令行测试。"""

from pathlib import Path

from inventory_app.cli import main


def test_cli_add_reserve_and_list(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    data = tmp_path / "inventory.json"
    assert main(["--data", str(data), "add", "--sku", "A-1", "--name", "键盘", "--stock", "8"]) == 0
    assert main(["--data", str(data), "reserve", "--sku", "A-1", "--quantity", "3"]) == 0
    reserve_output = capsys.readouterr().out
    assert "reserved=3" in reserve_output
    assert "available=5" in reserve_output

    assert main(["--data", str(data), "list"]) == 0
    assert "A-1 | 键盘 | stock=8 | reserved=3 | available=5" in capsys.readouterr().out


def test_cli_business_error_returns_two(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    data = tmp_path / "inventory.json"

    assert main(["--data", str(data), "reserve", "--sku", "missing", "--quantity", "1"]) == 2
    assert "错误：SKU 不存在" in capsys.readouterr().out

