# 独立验收测试

这里的测试不会被项目默认的 `python -m pytest` 自动执行，用于在 Agent 完成“批量预留”任务后进行外部复查。

运行方法：

```powershell
python -m pytest acceptance_tests -q
```

