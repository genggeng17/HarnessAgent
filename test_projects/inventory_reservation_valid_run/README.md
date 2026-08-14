# Inventory Reservation

一个只依赖 Python 标准库的小型库存预留程序，用于测试跨文件阅读、业务规则修改、JSON 持久化、命令行和自动测试。

## 当前功能

- 新建商品并设置初始库存；
- 增加库存；
- 预留或释放单个商品；
- 批量预留多个商品；
- 查看库存、已预留数量和可用数量；
- 使用 JSON 文件保存数据。

## 使用方法

```powershell
python -m pip install -e .
stock-room --data inventory.json add --sku A-100 --name 键盘 --stock 20
stock-room --data inventory.json reserve --sku A-100 --quantity 3
stock-room --data inventory.json release --sku A-100 --quantity 1
stock-room --data inventory.json liststock-room --data inventory.json reserve-batch --item A-100=2 --item B-200=1
stock-room --data inventory.json list
```

## 测试

```powershell
python -m pytest
```

