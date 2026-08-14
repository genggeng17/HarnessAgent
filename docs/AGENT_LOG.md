# HarnessAgent Agent 协作日志

## 2026-07-07

### INIT：初始化仓库

- 阶段：项目初始化
- 关键上下文：建立 HarnessAgent 仓库和 README 占位。
- 产出：commit `46caf96`。
- 人工责任：选择 Coding Agent Harness 作为项目方向。

## 2026-07-17

### SPEC-01：简化验证架构

- 阶段：brainstorming 设计讨论
- 关键问题：是否需要独立 Feedback、失败分类和修复指令体系。
- Agent 建议：删除独立 Feedback 层，保留 ToolResult 和薄 VerificationResult。
- 人工决定：采纳；Harness 只判断客观通过，具体修复交给模型。
- 产出：精简规格、验证门禁、组件边界和纵向测试场景。
- 教训：第一阶段应优先保证客观信号和执行约束，不提前构建根因规则库。

### SPEC-02：长任务一致性和恢复设计

- 阶段：brainstorming 等价设计讨论
- Agent 建议：分层上下文、固定验收卡、相关文件工作集、旧记录摘要、自动重读和有限重试。
- 人工决定：采纳任务卡、上下文裁剪、文件版本、批量读写、有限恢复、Shell 写源码拒绝和中途验证；排除失败任务交接单。
- 产出：`agent/context.py` 和 Loop/Tool/Policy 增强。
- 验证：68 项离线测试通过，1 项跳过。

### SPEC-03：冻结实施契约

- 阶段：brainstorming / writing-plans 阶段
- 关键上下文：复核 spec v0.4 可实现性。
- Agent 输出：指出 Action Schema、状态转换、Policy、工具协议、验证和恢复语义仍不完整。
- 人工决定：先完成 M0，再进入实现；规格升级为 v0.5。
- 产出：M0–M6 纵向计划和公共契约。
- 教训：架构图不足以冷启动实现，关键语义必须落实到 Schema、状态和矩阵。

### M1：核心模型与 Mock

- 阶段：TDD 实现阶段
- 关键上下文：Python 3.12、Pydantic v2、异步 LLM 接口。
- 产出：ActionParser、TurnState、StateMachine、LoopGuard、MockLLMClient 和 22 项离线测试。
- 验证：Mock 输出可驱动无工具 Turn 到 Final。
- 人工检查：确认 `.venv` 使用 Python 3.12.13 和 Pydantic 2.13.4。

### M2-M3：只读、修改与验证闭环

- 阶段：TDD / executing-plans 阶段
- 产出：Workspace、Registry、Dispatcher、只读工具、Patch、Shell、验证器、revision 门禁和最小 AgentLoop。
- 验证：只读分析、一次验证通过、首次失败后修复、持续失败资源耗尽。
- Commit：`81efe83`，同时包含 M0–M3 规格、实现和测试。
- 人工反思：提交粒度过大，后续应拆分任务和证据。

## 2026-08-06

### REVIEW-01：M0-M3 状态审查

- 阶段：requesting-code-review 审查
- Agent 输出：确认 M0–M3 已接通，M4–M6 尚未实现。
- 验证：35 项通过；Windows 无符号链接权限导致 1 项准备失败。
- 人工决定：下一步先实现审批恢复，再做 CLI/持久化，最后接真实 Provider。

## 2026-08-09

### M4-M5：审批、恢复、Session 与 CLI

- 阶段：TDD / executing-plans 阶段
- 产出：PendingInteraction、ApprovalGrant、业务澄清、DISPATCHING、EXECUTION_UNKNOWN、本地 Store、Trace、命令日志和 `/resume`。
- 验证：Mock 集成测试覆盖允许、拒绝、中止、澄清、未知执行和持久化。
- 人工决定：批准只绑定原动作和参数一次，恢复不静默重放未知副作用。

### M6：治理、记忆、配置与 Provider

- 阶段：TDD / executing-plans 阶段
- 产出：三种权限模式、命令规则、严格配置、Project/Decision Memory、DeepSeek-V4-Pro Provider。
- Agent 建议：Provider 从最初候选调整为 DeepSeek-V4-Pro。
- 人工决定：真实密钥只从环境变量或被忽略的 `.env` 读取，不写入版本化配置。
- Commit：`1f28306`。

### REVIEW-02：M1-M6 完整性复核

- 阶段：spec compliance / code quality 审查
- 发现：验证持久化、Shell 边界、Trace、记忆入口和 Provider 仍有改进空间。
- 人工干预：重写 README，补充安装、配置、CLI、恢复、测试和限制说明。
- 教训：里程碑主链路完成不等于产品化细节全部完成。

### TEST-01：自主测试规则

- 阶段：brainstorming / TDD 规则设计
- 关键问题：怎样让 AI 复用已有测试并在缺失时补写测试，同时防止伪造通过。
- Agent 输出：Prompt 负责引导，代码负责测试发现、revision、证据和完成门禁。
- 人工决定：接受组合方案；禁止删除、跳过或弱化原测试制造通过。
- 产出：多技术栈发现、动态 `auto`、验证证据持久化和 CLI 摘要。
- 验证：58 项离线测试通过，1 项因 Windows 权限跳过。

### E2E-01：真实模型只读任务

- 阶段：真实 Provider 验证
- 初次结果：9 次迭代、约 107 秒才完成一次 README 读取。
- 根因：Action/工具 Schema、状态和纠错上下文不完整。
- 人工决定：补齐同源 Schema、最小示例、动态状态、预算、AGENTS.md 和精确纠错。
- 复测：2 次迭代、约 14.5 秒，无格式错误或多余 Shell。
- 教训：真实模型效率首先受协议完整性影响，而不是单纯受模型能力影响。

### RELEASE-01：整理并推送 M4-M6

- 阶段：finishing branch 发布
- 人工决定：按当时要求直接推送 main，不创建 PR。
- Commit：`1f28306`。
- 远端：GitHub `main`。

### E2E-02：记账项目三轮真实增改

- 阶段：独立样例项目验证
- 任务：新增月度 Markdown 报告、CLI 子命令、测试和 README。
- Agent 表现：暴露重复读取、计划更新、Patch 失败、需求漂移和收尾验证问题。
- 人工干预：拒绝 Shell 字符串替换；移除未要求的排名占比；手工修正文案与断言。
- 最终证据：12 项测试通过。
- 教训：安全门禁有效不代表任务可以在预算内独立完成。

## 2026-08-14

### E2E-03：记账项目改造后复测

- 阶段：真实模型回归验证
- 结果：16 轮完成 5 个文件修改，独立复查 22 项测试全部通过。
- 教训：固定任务卡、文件版本和有限恢复能明显改善跨文件任务完成率。

### E2E-04：库存批量预留

- 阶段：复杂独立样例验收
- 任务：跨文件业务、CLI、一次保存、失败不落盘和独立验收。
- 初次结果：60 秒模型请求上限下两次超时。
- 人工干预：将真实模型请求超时调整为 180 秒，保留循环与工具预算。
- 最终证据：15 轮、11 次工具调用；23 项项目测试和 6 项独立验收通过。
- 复查发现：README 示例存在一处命令粘连。
- 教训：测试通过仍需要人工检查用户文档和需求表达。

### DOC-01：README 与专题文档整理

- 阶段：文档重构
- 产出：将项目概览、使用、架构和状态从已有文档拆分整理。
- 验证：文档内部链接通过；核心测试 68 项通过、1 项跳过。

### DOC-02：文档目录归并

- 任务：除根目录 `README.md` 与 `AGENTS.md` 外，将项目文档统一归档到 `docs/`，并删除 `docs/requirement/` 下的要求副本。
- 工具：PowerShell UTF-8 路径核对、显式文件移动、`rg` 引用扫描与链接检查。
- 人工决定：保留根目录入口文档和项目约束；旧 `agentlog.md` 已处于删除状态，不恢复。
- 验证：更新根目录约束、README 链接、目录树和计划文件清单后，检查全部本地 Markdown 链接与旧路径残留。

### RELEASE-02：发布首个 GitHub Release

- 任务：将已确认版本直接推送到 `main`，并按项目版本 `0.1.0` 发布 GitHub Release。
- 工具：Git、GitHub CLI、Pytest、Build、Twine 与隔离虚拟环境。
- 人工决定：直接更新 `main`，不创建 Pull Request；测试运行生成的 `.agent` 输入与日志文件不纳入版本库。
- 验证：完整测试 71 项通过、1 项因平台条件跳过；wheel 与源码包检查通过；隔离安装 wheel 后 CLI 及凭据子命令帮助入口可用。
