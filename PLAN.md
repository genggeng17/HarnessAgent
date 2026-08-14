# HarnessAgent 实现计划

计划原则：每个任务包含目标、文件、实现要点、验证步骤、依赖和证据；后续继续按此格式维护。

## 1. 状态标记

- `完成`：实现和验证证据已存在；
- `完成，待提交`：当前工作区已经实现和验证，但尚未形成独立 commit；
- `计划中`：规格已明确，尚未进入本轮实现。

提交基线：

| Commit | 内容 |
|---|---|
| `46caf96` | 初始化仓库 |
| `81efe83` | M0–M3：规格、核心循环、工具和验证闭环 |
| `1f28306` | M4–M6：审批恢复、CLI、持久化、记忆和真实 Provider |

## 2. 依赖关系

```text
T01 → T02 → T03
             ├─→ T04 → T05
             ├─→ T06 → T07
             └─→ T08
T05 + T07 + T08 → T09 → T10 → T11
T11 → T12 → T13
T11 → T14 → T15 → T16
T13 + T16 → T17 → T18
T13 + T14 + T18 → T19
```

T04/T06/T08、T12/T14 在接口冻结后可分别在独立 worktree 中并行；涉及 `AgentLoop` 的汇总任务保持串行，避免同时修改核心循环。

## 3. 任务清单

### T01：冻结问题、范围与公共术语

- 状态：完成（`81efe83`）
- 目标：定义 Project、Workspace、Session、Turn、Action、ToolResult 和 VerificationResult。
- 文件：`SPEC.md`，原始规格可从 commit `81efe83` 追溯。
- 实现要点：区分模型决策与 Harness 的确定性执行责任；明确第一阶段不实现并行编排。
- 验证：从规格出发能够解释一次普通 Turn、修改验证和审批恢复流程。
- 依赖：无。

### T02：定义 Action Schema 与状态转换

- 状态：完成（`81efe83`）
- 目标：让模型只能输出一个严格 JSON Action。
- 文件：`harness_agent/agent/actions.py`、`action_parser.py`、`state.py`、`state_machine.py`。
- 实现要点：先写非法 type、额外字段、非法计划状态的失败测试，再实现严格解析和转换。
- 验证：
  - `python -m pytest tests/unit/test_action_parser.py`
  - `python -m pytest tests/unit/test_state_machine.py`
- 依赖：T01。

### T03：建立可注入 LLM 与循环资源限制

- 状态：完成（`81efe83`）
- 目标：在没有真实模型时驱动 AgentLoop，并防止无限循环。
- 文件：`harness_agent/llm/base.py`、`mock.py`、`agent/loop_guard.py`、`agent/loop.py`。
- 实现要点：先测试 Mock 顺序消费、cursor 快照、迭代/工具/反思预算和重复 Action，再接入主循环。
- 验证：
  - `python -m pytest tests/unit/test_mock_llm.py tests/unit/test_loop_guard.py`
  - `python -m pytest tests/integration/test_m1_mock_turn.py`
- 依赖：T02。

### T04：实现本地工作区边界

- 状态：完成（`81efe83`）
- 目标：阻止绝对路径、`..` 和符号链接逃逸。
- 文件：`harness_agent/runtime/workspace.py`、`tests/unit/test_workspace_tools.py`。
- TDD：先构造越界和符号链接失败用例，再实现真实路径检查。
- 验证：`python -m pytest tests/unit/test_workspace_tools.py`。
- 依赖：T03。

### T05：实现只读工具、Registry 与 Dispatcher

- 状态：完成；多文件读取增强为“完成，待提交”。
- 目标：所有工具共享注册、Schema 生成、参数校验和分发路径。
- 文件：`harness_agent/tools/registry.py`、`dispatcher.py`、`readonly.py`。
- TDD：先测试未知工具、非法参数、目录、读取和搜索，再实现工具；为 `read_files` 增加多文件与截断测试。
- 验证：`python -m pytest tests/unit/test_workspace_tools.py`。
- 依赖：T04。

### T06：实现 Policy 治理

- 状态：完成；Shell 写源码旁路拒绝为“完成，待提交”。
- 目标：实现 ALLOW/ASK/DENY，并确保模型不能覆盖工具可信元数据。
- 文件：`harness_agent/governance/policy.py`、`tests/unit/test_policy.py`。
- TDD：先写只读、删除、普通 Shell、破坏性 Git 和脚本写源码的决策测试。
- 验证：`python -m pytest tests/unit/test_policy.py tests/unit/test_m6_config_memory_provider.py`。
- 依赖：T03。

### T07：实现修改工具

- 状态：Patch 完成（`81efe83`）；精确单/多文件修改为“完成，待提交”。
- 目标：支持 unified diff、唯一锚点、SHA-256 乐观并发和成组修改。
- 文件：`harness_agent/tools/patch.py`、`tests/unit/test_patch_and_verification.py`。
- TDD：先覆盖上下文不匹配、陈旧文件、锚点缺失/重复和成组预检查失败，再实现写入。
- 验证：`python -m pytest tests/unit/test_patch_and_verification.py`。
- 依赖：T04、T05、T06。

### T08：实现统一 Shell 与验证器

- 状态：完成（`81efe83`），多技术栈自动发现增强于 `1f28306`。
- 目标：一般命令和验证共用唯一 `shell=False` 子进程执行器。
- 文件：`harness_agent/tools/shell.py`、`verification_tool.py`、`agent/verification.py`、`config/models.py`。
- TDD：先覆盖成功、非零退出、超时、启动失败和验证器自动发现。
- 验证：`python -m pytest tests/unit/test_patch_and_verification.py tests/unit/test_m6_config_memory_provider.py`。
- 依赖：T03、T04、T05。

### T09：接通 revision 验证闭环

- 状态：完成（`81efe83`），基线和中途验证增强为“完成，待提交”。
- 目标：写入后旧验证失效，全部必需验证器通过前禁止成功。
- 文件：`harness_agent/agent/loop.py`、`state.py`、`state_machine.py`、`tests/integration/test_m3_edit_verify_loop.py`。
- TDD：先写“写入后直接 Final 应失败”“首次失败后再次修改并通过”“持续失败耗尽预算”。
- 验证：`python -m pytest tests/integration/test_m3_edit_verify_loop.py`。
- 依赖：T05、T07、T08。

### T10：实现审批与业务澄清

- 状态：完成（`1f28306`）。
- 目标：ASK 暂停并保存原 ToolCall；允许、拒绝、中止和业务回答具有不同语义。
- 文件：`harness_agent/agent/interactions.py`、`state_machine.py`、`loop.py`。
- TDD：先写暂停、精确一次执行、拒绝不派发和澄清等待测试。
- 验证：`python -m pytest tests/integration/test_m4_m5_runtime.py`。
- 依赖：T06、T09。

### T11：实现崩溃窗口与本地持久化

- 状态：完成（`1f28306`）。
- 目标：外部副作用前保存 DISPATCHING；未知结果不静默重放。
- 文件：`harness_agent/storage/local.py`、`runtime/manager.py`、`tracing/events.py`。
- TDD：先构造派发后结果前崩溃状态，再验证恢复为 EXECUTION_UNKNOWN。
- 验证：
  - `python -m pytest tests/integration/test_m4_m5_runtime.py`
  - 检查临时项目中的 state、trace、transcript 和 commands.log。
- 依赖：T10。

### T12：实现交互式 CLI

- 状态：完成（`1f28306`）。
- 目标：支持多 Turn Session、新任务、`/resume`、审批回答和中止。
- 文件：`harness_agent/cli/main.py`、`__main__.py`、`pyproject.toml`。
- 验证：
  - `python -m harness_agent --help`
  - 使用 Mock responses 启动一次无网络 Turn。
- 依赖：T11。

### T13：实现配置和长期记忆

- 状态：完成（`1f28306`）。
- 目标：严格加载版本化配置，只向记忆写入证据事实和明确决定。
- 文件：`harness_agent/config/models.py`、`memory/models.py`、`memory/manager.py`。
- TDD：先写未知配置字段、自动验证器、事实证据和未确认决定拒绝测试。
- 验证：`python -m pytest tests/unit/test_m6_config_memory_provider.py`。
- 依赖：T11。

### T14：接入 DeepSeek-V4-Pro

- 状态：完成（`1f28306`）。
- 目标：通过 OpenAI 兼容接口请求严格 JSON Action。
- 文件：`harness_agent/llm/deepseek.py`、`config/models.py`。
- TDD：使用 `httpx.MockTransport` 先测试请求结构、缺少 Key、429 重试和错误响应。
- 验证：`python -m pytest tests/unit/test_m6_config_memory_provider.py`。
- 依赖：T03、T13。

### T15：补齐模型协议与动态上下文

- 状态：完成（`1f28306`）。
- 目标：每轮提供 Action Schema、工具 Schema、状态、预算和项目规则。
- 文件：`harness_agent/agent/protocol.py`、`loop.py`、`tests/unit/test_agent_context.py`。
- TDD：先断言系统上下文包含协议、最小示例、验证器和剩余资源。
- 验证：`python -m pytest tests/unit/test_agent_context.py`。
- 依赖：T12、T14。

### T16：加入任务卡、上下文裁剪和文件版本

- 状态：完成，待提交。
- 目标：减少真实多文件任务的需求漂移和无效调用。
- 文件：`harness_agent/agent/context.py`、`loop.py`、`state.py`、`state_machine.py`、`tools/readonly.py`。
- TDD：先测试原始要求固定、禁止项识别、近期消息裁剪、SHA-256 快照和计划更新限制。
- 验证：`python -m pytest tests/unit/test_agent_context.py tests/integration/test_m3_edit_verify_loop.py`。
- 依赖：T15。

### T17：加入修改失败有限恢复

- 状态：完成，待提交。
- 目标：Patch/锚点失败后提供最新证据，限制重试并禁止 Shell 兜底。
- 文件：`harness_agent/tools/patch.py`、`agent/loop.py`、`governance/policy.py`。
- TDD：先写第二次失败要求完整重读、第三次失败终止、Shell 写源码拒绝测试。
- 验证：
  - `python -m pytest tests/unit/test_patch_and_verification.py tests/unit/test_policy.py`
  - `python -m pytest tests/integration/test_m3_edit_verify_loop.py`
- 依赖：T07、T16。

### T18：真实项目独立验收与文档交付

- 状态：完成，待整理提交。
- 目标：用记账和库存项目验证跨文件实现、CLI、持久化和隐藏验收，并形成课程交付文档。
- 文件：`test_projects/`、`README.md`、`SPEC.md`、`PLAN.md`、`SPEC_PROCESS.md`、`AGENT_LOG.md`、`MECHANISM_DEMO.md`。
- 验证：
  - `python -m pytest`
  - `python -m pytest test_projects/inventory_reservation_valid_run/acceptance_tests -q`
  - 检查 Markdown 内部链接和 Git diff。
- 依赖：T13、T17。

### T19：系统钥匙串、包分发与 CI

- 状态：完成，待提交。
- 目标：让新机器可通过 wheel 安装 CLI，并只通过系统钥匙串安全录入、更新、查看和清除真实 Provider Key。
- 文件：`harness_agent/credentials.py`、`harness_agent/cli/main.py`、`pyproject.toml`、`.gitlab-ci.yml`、`tests/unit/test_credentials.py`、`README.md`。
- TDD：先使用内存钥匙串写凭据生命周期、环境变量不得覆盖钥匙串和 CLI 不回显明文的失败测试，再实现系统 keyring 适配与首次运行引导。
- 验证：
  - `python -m pytest tests/unit/test_credentials.py`
  - `python -m pytest`
  - `python -m build`
  - `python -m twine check dist/*`
  - 在隔离虚拟环境安装 wheel并运行 `harness-agent --help`。
- 依赖：T13、T14、T18。
- 补充证据：旧 `.env` 中唯一的 `NEW_API_KEY` 已无回显迁移到 Windows Credential Manager 并完成等值回读，随后删除 `.env` 与 `.env.example`；完整回归与更新后的 wheel 隔离安装均确认只使用系统钥匙串。

## 4. 当前验证结果

最近一次核心离线测试：

```text
71 passed, 1 skipped
```
