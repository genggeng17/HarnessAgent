"""库存持久化测试。"""

import json
from pathlib import Path

import pytest

from inventory_app.models import Product
from inventory_app.storage import JsonInventoryRepository


def test_repository_round_trip_is_sorted(tmp_path: Path) -> None:
    repository = JsonInventoryRepository(tmp_path / "inventory.json")
    repository.save(
        (
            Product(sku="B-2", name="鼠标", stock=4),
            Product(sku="A-1", name="键盘", stock=8, reserved=1),
        )
    )

    assert [item.sku for item in repository.load()] == ["A-1", "B-2"]
    payload = json.loads((tmp_path / "inventory.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1


def test_repository_rejects_duplicate_sku(tmp_path: Path) -> None:
    path = tmp_path / "inventory.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "products": [
                    {"sku": "A-1", "name": "键盘", "stock": 2},
                    {"sku": "A-1", "name": "重复", "stock": 3},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="重复 SKU"):
        JsonInventoryRepository(path).load()

