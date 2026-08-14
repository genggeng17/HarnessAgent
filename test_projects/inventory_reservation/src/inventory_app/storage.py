"""JSON 库存存储。"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from inventory_app.models import Product


class JsonInventoryRepository:
    """使用单个 JSON 文件保存全部商品。"""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> tuple[Product, ...]:
        if not self.path.exists():
            return ()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if payload.get("schema_version") != 1:
                raise ValueError("不支持的库存文件版本")
            products = tuple(Product.from_dict(item) for item in payload["products"])
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ValueError("库存文件格式无效") from exc
        if len({item.sku for item in products}) != len(products):
            raise ValueError("库存文件包含重复 SKU")
        return tuple(sorted(products, key=lambda item: item.sku))

    def save(self, products: tuple[Product, ...]) -> None:
        """先写临时文件，再替换正式文件，避免半份 JSON。"""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "products": [item.to_dict() for item in sorted(products, key=lambda item: item.sku)],
        }
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)

