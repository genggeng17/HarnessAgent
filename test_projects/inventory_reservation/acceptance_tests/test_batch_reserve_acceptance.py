"""Agent 事先不可见的批量预留验收测试。"""

from pathlib import Path

import pytest

from inventory_app.cli import main
from inventory_app.models import Product
from inventory_app.service import InventoryService
from inventory_app.storage import JsonInventoryRepository


class CountingRepository:
    """记录保存次数，验证批量成功时只落盘一次。"""

    def __init__(self, products: tuple[Product, ...]) -> None:
        self.products = products
        self.save_calls = 0

    def load(self) -> tuple[Product, ...]:
        return self.products

    def save(self, products: tuple[Product, ...]) -> None:
        self.save_calls += 1
        self.products = products


def test_duplicate_items_are_merged_sorted_and_saved_once() -> None:
    repository = CountingRepository(
        (
            Product(sku="B-2", name="鼠标", stock=8),
            Product(sku="A-1", name="键盘", stock=10, reserved=1),
        )
    )
    service = InventoryService(repository)  # type: ignore[arg-type]

    updated = service.batch_reserve(
        [("B-2", 2), ("A-1", 2), ("A-1", 3)]
    )

    assert [item.sku for item in updated] == ["A-1", "B-2"]
    assert [item.reserved for item in updated] == [6, 2]
    assert repository.save_calls == 1


@pytest.mark.parametrize(
    "items",
    [
        [("A-1", 2), ("missing", 1)],
        [("A-1", 2), ("B-2", 4)],
        [("A-1", 0)],
    ],
)
def test_any_invalid_item_leaves_json_byte_for_byte_unchanged(
    tmp_path: Path, items: list[tuple[str, int]]
) -> None:
    repository = JsonInventoryRepository(tmp_path / "inventory.json")
    repository.save(
        (
            Product(sku="A-1", name="键盘", stock=5),
            Product(sku="B-2", name="鼠标", stock=3),
        )
    )
    before = repository.path.read_bytes()

    with pytest.raises(ValueError):
        InventoryService(repository).batch_reserve(items)

    assert repository.path.read_bytes() == before


def test_empty_batch_is_rejected_without_creating_file(tmp_path: Path) -> None:
    path = tmp_path / "inventory.json"

    with pytest.raises(ValueError):
        InventoryService(JsonInventoryRepository(path)).batch_reserve([])

    assert not path.exists()


def test_cli_batch_success_and_malformed_item(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    data = tmp_path / "inventory.json"
    assert main(["--data", str(data), "add", "--sku", "A-1", "--name", "键盘", "--stock", "8"]) == 0
    capsys.readouterr()

    assert main(
        [
            "--data",
            str(data),
            "reserve-batch",
            "--item",
            "A-1=2",
            "--item",
            "A-1=3",
        ]
    ) == 0
    output = capsys.readouterr().out
    assert "A-1: reserved=5 available=3" in output

    assert main(
        ["--data", str(data), "reserve-batch", "--item", "bad-format"]
    ) == 2
    assert "错误" in capsys.readouterr().out

