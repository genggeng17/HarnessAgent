# Expense Tracker

一个只依赖 Python 标准库的小型本地记账程序，用来模拟真实项目中的代码阅读、跨文件修改、测试补充和回归验证。

## 当前功能

- 添加一笔支出；
- 按月份查看支出；
- 按分类汇总指定月份的金额；
- 使用 JSON 文件持久化；
- 通过命令行执行 `add`、`list`、`summary` 和 `report`。

## 安装和运行

```powershell
python -m pip install -e .
expense-tracker --data expenses.json add --date 2026-08-01 --category 餐饮 --amount 35.50
expense-tracker --data expenses.json list --month 2026-08
expense-tracker --data expenses.json summary --month 2026-08
expense-tracker --data expenses.json report --month 2026-08
```

## 测试

```powershell
python -m pytest
```

