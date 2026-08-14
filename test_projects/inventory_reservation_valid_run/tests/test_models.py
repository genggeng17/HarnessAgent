"""领域对象测试。"""

import pytest

from inventory_app.models import Product


def test_available_is_stock_minus_reserved() -> None:
    product = Product(sku=" A-1 ", name=" 键盘 ", stock=10, reserved=3)

    assert product.sku == "A-1"
    assert product.name == "键盘"
    assert product.available == 7


@pytest.mark.parametrize(
    ("stock", "reserved"),
    [(-1, 0), (2, -1), (2, 3)],
)
def test_invalid_stock_state_is_rejected(stock: int, reserved: int) -> None:
    with pytest.raises(ValueError):
        Product(sku="A-1", name="键盘", stock=stock, reserved=reserved)


def test_from_dict_keeps_integer_values() -> None:
    product = Product.from_dict({"sku": "A-1", "name": "键盘", "stock": 8, "reserved": 2})

    assert product.to_dict() == {"sku": "A-1", "name": "键盘", "stock": 8, "reserved": 2}

