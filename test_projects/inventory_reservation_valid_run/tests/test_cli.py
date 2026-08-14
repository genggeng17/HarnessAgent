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


def test_cli_reserve_batch_success(tmp_path: Path, capsys) -> None:
    data = tmp_path / "inventory.json"
    assert main(["--data", str(data), "add", "--sku", "B-2", "--name", "鼠标", "--stock", "5"]) == 0
    assert main(["--data", str(data), "add", "--sku", "A-1", "--name", "键盘", "--stock", "10"]) == 0
    capsys.readouterr()
    assert main(["--data", str(data), "reserve-batch", "--item", "A-1=3", "--item", "B-2=2"]) == 0
    out = capsys.readouterr().out
    assert "A-1: reserved=3 available=7" in out
    assert "B-2: reserved=2 available=3" in out


def test_cli_reserve_batch_duplicate_sku(tmp_path: Path, capsys) -> None:
    data = tmp_path / "inventory.json"
    assert main(["--data", str(data), "add", "--sku", "A-1", "--name", "键盘", "--stock", "10"]) == 0
    capsys.readouterr()
    assert main(["--data", str(data), "reserve-batch", "--item", "A-1=3", "--item", "A-1=2"]) == 0
    out = capsys.readouterr().out
    assert "A-1: reserved=5 available=5" in out


def test_cli_reserve_batch_failure_does_not_change(tmp_path: Path, capsys) -> None:
    data = tmp_path / "inventory.json"
    assert main(["--data", str(data), "add", "--sku", "A-1", "--name", "键盘", "--stock", "3"]) == 0
    assert main(["--data", str(data), "add", "--sku", "B-2", "--name", "鼠标", "--stock", "5"]) == 0
    capsys.readouterr()
    before = data.read_bytes()
    assert main(["--data", str(data), "reserve-batch", "--item", "A-1=2", "--item", "B-2=6"]) == 2
    assert "错误：可用库存不足" in capsys.readouterr().out
    assert data.read_bytes() == before


def test_cli_reserve_batch_empty(tmp_path: Path, capsys) -> None:
    data = tmp_path / "inventory.json"
    assert main(["--data", str(data), "reserve-batch"]) == 2
    assert "错误：批量预留请求不能为空" in capsys.readouterr().out


def test_cli_reserve_batch_invalid_format(tmp_path: Path, capsys) -> None:
    data = tmp_path / "inventory.json"
    assert main(["--data", str(data), "reserve-batch", "--item", "A-1"]) == 2
    assert "格式无效" in capsys.readouterr().out


