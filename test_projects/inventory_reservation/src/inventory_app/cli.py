"""库存命令行入口。"""

from __future__ import annotations

import argparse
from pathlib import Path

from inventory_app.service import InventoryService
from inventory_app.storage import JsonInventoryRepository


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="本地库存预留工具")
    parser.add_argument("--data", type=Path, default=Path("inventory.json"))
    commands = parser.add_subparsers(dest="command", required=True)

    add = commands.add_parser("add", help="新建商品")
    add.add_argument("--sku", required=True)
    add.add_argument("--name", required=True)
    add.add_argument("--stock", required=True, type=int)

    for command, help_text in (
        ("restock", "增加库存"),
        ("reserve", "预留商品"),
        ("release", "释放预留"),
    ):
        child = commands.add_parser(command, help=help_text)
        child.add_argument("--sku", required=True)
        child.add_argument("--quantity", required=True, type=int)

    commands.add_parser("list", help="查看库存")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    service = InventoryService(JsonInventoryRepository(args.data))
    try:
        if args.command == "add":
            product = service.add_product(sku=args.sku, name=args.name, stock=args.stock)
            print(f"已新建：{product.sku} {product.name} stock={product.stock}")
        elif args.command == "restock":
            product = service.restock(sku=args.sku, quantity=args.quantity)
            print(f"{product.sku}: stock={product.stock} available={product.available}")
        elif args.command == "reserve":
            product = service.reserve(sku=args.sku, quantity=args.quantity)
            print(f"{product.sku}: reserved={product.reserved} available={product.available}")
        elif args.command == "release":
            product = service.release(sku=args.sku, quantity=args.quantity)
            print(f"{product.sku}: reserved={product.reserved} available={product.available}")
        elif args.command == "list":
            for product in service.list_products():
                print(
                    f"{product.sku} | {product.name} | stock={product.stock} | "
                    f"reserved={product.reserved} | available={product.available}"
                )
    except ValueError as exc:
        print(f"错误：{exc}")
        return 2
    return 0


def entrypoint() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()

