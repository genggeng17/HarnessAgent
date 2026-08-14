"""库存业务服务。"""

from __future__ import annotations

from inventory_app.models import Product
from inventory_app.storage import JsonInventoryRepository


class InventoryService:
    def __init__(self, repository: JsonInventoryRepository) -> None:
        self.repository = repository

    def list_products(self) -> tuple[Product, ...]:
        return self.repository.load()

    def add_product(self, *, sku: str, name: str, stock: int) -> Product:
        products = self.repository.load()
        if any(item.sku == sku.strip() for item in products):
            raise ValueError(f"SKU 已存在：{sku.strip()}")
        product = Product(sku=sku, name=name, stock=stock)
        self.repository.save((*products, product))
        return product

    def restock(self, *, sku: str, quantity: int) -> Product:
        if quantity <= 0:
            raise ValueError("入库数量必须大于零")
        products = self.repository.load()
        product = self._find(products, sku)
        updated = product.with_stock(product.stock + quantity)
        self.repository.save(self._replace(products, updated))
        return updated

    def reserve(self, *, sku: str, quantity: int) -> Product:
        if quantity <= 0:
            raise ValueError("预留数量必须大于零")
        products = self.repository.load()
        product = self._find(products, sku)
        if quantity > product.available:
            raise ValueError(f"可用库存不足：{sku} 仅剩 {product.available}")
        updated = product.with_reserved(product.reserved + quantity)
        self.repository.save(self._replace(products, updated))
        return updated

    def release(self, *, sku: str, quantity: int) -> Product:
        if quantity <= 0:
            raise ValueError("释放数量必须大于零")
        products = self.repository.load()
        product = self._find(products, sku)
        if quantity > product.reserved:
            raise ValueError(f"释放数量超过已预留数量：{sku}")
        updated = product.with_reserved(product.reserved - quantity)
        self.repository.save(self._replace(products, updated))
        return updated

    def batch_reserve(self, items: list[tuple[str, int]]) -> list[Product]:
        """批量预留，全部成功或完全不保存。"""
        if not items:
            raise ValueError("预留请求不能为空")
        for sku, quantity in items:
            if quantity <= 0:
                raise ValueError(f"预留数量必须大于零：{sku}")
        # 合并重复 SKU 的数量
        merged: dict[str, int] = {}
        for sku, quantity in items:
            norm = sku.strip()
            merged[norm] = merged.get(norm, 0) + quantity
        products = self.repository.load()
        for sku, total_quantity in merged.items():
            product = self._find(products, sku)
            if total_quantity > product.available:
                raise ValueError(f"可用库存不足：{sku} 仅剩 {product.available}")
        product_map = {p.sku: p for p in products}
        results: list[Product] = []
        for sku, total_quantity in merged.items():
            norm = sku.strip()
            p = product_map[norm]
            updated = p.with_reserved(p.reserved + total_quantity)
            product_map[norm] = updated
            results.append(updated)
        self.repository.save(tuple(product_map.values()))
        return results

    @staticmethod
    def _find(products: tuple[Product, ...], sku: str) -> Product:
        normalized = sku.strip()
        for product in products:
            if product.sku == normalized:
                return product
        raise ValueError(f"SKU 不存在：{normalized}")

    @staticmethod
    def _replace(products: tuple[Product, ...], updated: Product) -> tuple[Product, ...]:
        return tuple(updated if item.sku == updated.sku else item for item in products)

