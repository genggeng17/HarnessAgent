# HarnessAgent

一个 Python-first、本地运行、可测试和可恢复的 Coding Agent Harness。

项目按照 [需求规格](docs/spec.md) 中的纵向里程碑开发。目前已完成：

- M0：冻结第一阶段实施契约；
- M1：Action/State 模型、严格 ActionParser、StateMachine、LoopGuard 和可恢复 MockLLMClient；
- M2：显式 LocalWorkspace、Registry/Dispatcher、只读治理及目录、读取、搜索工具；
- M3：unified diff Patch、统一 Shell/验证执行器、VerificationService、workspace revision 门禁和最小 AgentLoop。

## 当前验证方式

项目要求 Python 3.12 和 Pydantic v2。安装开发依赖后运行：

```bash
python -m pytest
```

如果当前环境只有 Pydantic 而没有 pytest，这批测试也兼容标准库 unittest：

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
```

当前最小 AgentLoop 已可由 Mock LLM 驱动真实工作区的只读分析、修改、验证和失败后重试。Session/CLI、审批恢复、完整持久化、长期记忆与真实 Provider 将在 M4-M6 按纵向切片加入。
