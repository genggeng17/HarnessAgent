"""库存预留测试项目。"""

from inventory_app.models import Product
from inventory_app.service import InventoryService
from inventory_app.storage import JsonInventoryRepository

__all__ = ["InventoryService", "JsonInventoryRepository", "Product"]

