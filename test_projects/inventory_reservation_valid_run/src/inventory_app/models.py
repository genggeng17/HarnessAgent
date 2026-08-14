"""库存领域对象。"""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class Product:
    """一个不可变的商品库存快照。"""

    sku: str
    name: str
    stock: int
    reserved: int = 0

    def __post_init__(self) -> None:
        sku = self.sku.strip()
        name = self.name.strip()
        if not sku:
            raise ValueError("SKU 不能为空")
        if not name:
            raise ValueError("商品名称不能为空")
        if self.stock < 0:
            raise ValueError("库存不能为负数")
        if self.reserved < 0:
            raise ValueError("预留数量不能为负数")
        if self.reserved > self.stock:
            raise ValueError("预留数量不能超过库存")
        object.__setattr__(self, "sku", sku)
        object.__setattr__(self, "name", name)

    @property
    def available(self) -> int:
        """当前仍可预留的数量。"""

        return self.stock - self.reserved

    def with_stock(self, stock: int) -> "Product":
        return replace(self, stock=stock)

    def with_reserved(self, reserved: int) -> "Product":
        return replace(self, reserved=reserved)

    def to_dict(self) -> dict[str, str | int]:
        return {
            "sku": self.sku,
            "name": self.name,
            "stock": self.stock,
            "reserved": self.reserved,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "Product":
        try:
            return cls(
                sku=str(payload["sku"]),
                name=str(payload["name"]),
                stock=int(payload["stock"]),
                reserved=int(payload.get("reserved", 0)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("库存数据格式无效") from exc

