"""库存业务测试。"""

from pathlib import Path

import pytest

from inventory_app.service import InventoryService
from inventory_app.storage import JsonInventoryRepository


def service_at(tmp_path: Path) -> InventoryService:
    return InventoryService(JsonInventoryRepository(tmp_path / "inventory.json"))


def test_add_restock_reserve_and_release(tmp_path: Path) -> None:
    service = service_at(tmp_path)
    service.add_product(sku="A-1", name="键盘", stock=10)
    service.restock(sku="A-1", quantity=2)
    reserved = service.reserve(sku="A-1", quantity=5)
    released = service.release(sku="A-1", quantity=2)

    assert reserved.stock == 12
    assert reserved.reserved == 5
    assert released.reserved == 3
    assert released.available == 9


def test_failed_reserve_does_not_change_file(tmp_path: Path) -> None:
    service = service_at(tmp_path)
    service.add_product(sku="A-1", name="键盘", stock=3)
    path = tmp_path / "inventory.json"
    before = path.read_bytes()

    with pytest.raises(ValueError, match="库存不足"):
        service.reserve(sku="A-1", quantity=4)

    assert path.read_bytes() == before


def test_unknown_sku_and_invalid_quantity_are_rejected(tmp_path: Path) -> None:
    service = service_at(tmp_path)
    service.add_product(sku="A-1", name="键盘", stock=3)

    with pytest.raises(ValueError, match="SKU 不存在"):
        service.reserve(sku="missing", quantity=1)
    with pytest.raises(ValueError, match="大于零"):
        service.reserve(sku="A-1", quantity=0)

def test_batch_reserve_success(tmp_path: Path) -> None:
    service = service_at(tmp_path)
    service.add_product(sku="A-1", name="键盘", stock=10)
    service.add_product(sku="B-2", name="鼠标", stock=5)
    results = service.batch_reserve([("A-1", 3), ("B-2", 2)])
    assert len(results) == 2
    assert results[0].reserved == 3
    assert results[0].available == 7
    assert results[1].reserved == 2
    assert results[1].available == 3


def test_batch_reserve_empty_is_rejected(tmp_path: Path) -> None:
    service = service_at(tmp_path)
    with pytest.raises(ValueError, match="不能为空"):
        service.batch_reserve([])


def test_batch_reserve_atomic_rollback(tmp_path: Path) -> None:
    service = service_at(tmp_path)
    service.add_product(sku="A-1", name="键盘", stock=3)
    service.add_product(sku="B-2", name="鼠标", stock=5)
    path = tmp_path / "inventory.json"
    before = path.read_bytes()
    with pytest.raises(ValueError, match="库存不足"):
        service.batch_reserve([("A-1", 2), ("B-2", 10)])
    assert path.read_bytes() == before

def test_batch_reserve_duplicate_sku_merged(tmp_path: Path) -> None:
    service = service_at(tmp_path)
    service.add_product(sku="A-1", name="键盘", stock=10)
    results = service.batch_reserve([("A-1", 2), ("A-1", 3)])
    assert len(results) == 1
    assert results[0].reserved == 5
    assert results[0].available == 5


def test_batch_reserve_duplicate_sku_total_exceeds(tmp_path: Path) -> None:
    service = service_at(tmp_path)
    service.add_product(sku="A-1", name="键盘", stock=3)
    path = tmp_path / "inventory.json"
    before = path.read_bytes()
    with pytest.raises(ValueError, match="库存不足"):
        service.batch_reserve([("A-1", 2), ("A-1", 2)])
    assert path.read_bytes() == before


