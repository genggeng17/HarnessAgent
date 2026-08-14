# HarnessAgent Agent 协作日志

说明：本日志根据原始 `agentlog.md`、Git 历史和测试记录整理。早期记录没有保存精确时间、逐字 Prompt、subagent ID 或 Superpowers 技能调用，因此“阶段”表示工作性质映射，不冒充不存在的工具调用记录。

## 2026-07-07

### INIT：初始化仓库

- 阶段：项目初始化
- 关键上下文：建立 HarnessAgent 仓库和 README 占位。
- 产出：commit `46caf96`。
- 人工责任：选择 Coding Agent Harness 作为项目方向。

## 2026-07-17

### SPEC-01：简化验证架构

- 阶段：brainstorming 等价设计讨论
- 关键问题：是否需要独立 Feedback、失败分类和修复指令体系。
- Agent 建议：删除独立 Feedback 层，保留 ToolResult 和薄 VerificationResult。
- 人工决定：采纳；Harness 只判断客观通过，具体修复交给模型。
- 产出：精简规格、验证门禁、组件边界和纵向测试场景。
- 教训：第一阶段应优先保证客观信号和执行约束，不提前构建根因规则库。

### SPEC-02：冻结实施契约

- 阶段：brainstorming / writing-plans 等价阶段
- 关键上下文：复核 spec v0.4 可实现性。
- Agent 输出：指出 Action Schema、状态转换、Policy、工具协议、验证和恢复语义仍不完整。
- 人工决定：先完成 M0，再进入实现；规格升级为 v0.5。
- 产出：M0–M6 纵向计划和公共契约。
- 教训：架构图不足以冷启动实现，关键语义必须落实到 Schema、状态和矩阵。

### M1：核心模型与 Mock

- 阶段：TDD 等价实现阶段
- 关键上下文：Python 3.12、Pydantic v2、异步 LLM 接口。
- 产出：ActionParser、TurnState、StateMachine、LoopGuard、MockLLMClient 和 22 项离线测试。
- 验证：Mock 输出可驱动无工具 Turn 到 Final。
- 人工检查：确认 `.venv` 使用 Python 3.12.13 和 Pydantic 2.13.4。

### M2-M3：只读、修改与验证闭环

- 阶段：TDD / executing-plans 等价阶段
- 产出：Workspace、Registry、Dispatcher、只读工具、Patch、Shell、验证器、revision 门禁和最小 AgentLoop。
- 验证：只读分析、一次验证通过、首次失败后修复、持续失败资源耗尽。
- Commit：`81efe83`，同时包含 M0–M3 规格、实现和测试。
- 人工反思：提交粒度过大，后续应拆分任务和证据。

## 2026-08-06

### REVIEW-01：M0-M3 状态审查

- 阶段：requesting-code-review 等价审查
- Agent 输出：确认 M0–M3 已接通，M4–M6 尚未实现。
- 验证：35 项通过；Windows 无符号链接权限导致 1 项准备失败。
- 人工决定：下一步先实现审批恢复，再做 CLI/持久化，最后接真实 Provider。

## 2026-08-09

### M4-M5：审批、恢复、Session 与 CLI

- 阶段：TDD / executing-plans 等价阶段
- 产出：PendingInteraction、ApprovalGrant、业务澄清、DISPATCHING、EXECUTION_UNKNOWN、本地 Store、Trace、命令日志和 `/resume`。
- 验证：Mock 集成测试覆盖允许、拒绝、中止、澄清、未知执行和持久化。
- 人工决定：批准只绑定原动作和参数一次，恢复不静默重放未知副作用。

### M6：治理、记忆、配置与 Provider

- 阶段：TDD / executing-plans 等价阶段
- 产出：三种权限模式、命令规则、严格配置、Project/Decision Memory、DeepSeek-V4-Pro Provider。
- Agent 建议：Provider 从最初候选调整为 DeepSeek-V4-Pro。
- 人工决定：真实密钥只从环境变量或被忽略的 `.env` 读取，不写入版本化配置。
- Commit：`1f28306`。

### REVIEW-02：M1-M6 完整性复核

- 阶段：spec compliance / code quality 等价审查
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

- 阶段：finishing branch 等价发布
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

### DESIGN-01：长任务一致性和恢复设计

- 阶段：brainstorming 等价设计讨论
- Agent 建议：分层上下文、固定验收卡、相关文件工作集、旧记录摘要、自动重读和有限重试。
- 人工决定：采纳任务卡、上下文裁剪、文件版本、批量读写、有限恢复、Shell 写源码拒绝和中途验证；排除失败任务交接单。
- 产出：`agent/context.py` 和 Loop/Tool/Policy 增强。
- 验证：68 项离线测试通过，1 项跳过。

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
- 产出：将项目概览、使用、架构和状态从单一 README 拆分整理。
- 验证：文档内部链接通过；核心测试 68 项通过、1 项跳过。

### DOC-02：课程交付文档重构

- 阶段：writing-plans / documentation 等价阶段
- 关键上下文：读取通用要求与 Coding Agent Harness 专项要求，迁移现有可核验内容。
- 产出：`SPEC.md`、`PLAN.md`、`SPEC_PROCESS.md`、`AGENT_LOG.md`、`MECHANISM_DEMO.md` 和新版 README。
- 人工要求：不生成反思报告；brainstorming 根据现有记录追溯重构。
- 验证结果：内部链接有效；6 项机制演示全部通过；完整离线回归 68 项通过、1 项因 Windows 符号链接权限跳过；`git diff --check` 通过。

## 日志维护规则

后续每条新增记录应包含：

1. 日期、时间和 PLAN task ID；
2. 实际使用的技能或工具；
3. 关键 Prompt、上下文边界和用户验收标准；
4. subagent 或独立 Agent 的任务、结果与 ID（如有）；
5. 测试的红/绿证据；
6. commit 或 PR；
7. 人工修改、拒绝和理由；
8. 从失败中得到的教训。

## 2026-08-14

### PROCESS-01：Superpowers 使用缺失的补救评估

- 阶段：流程审查
- 发现：项目早期虽然存在多轮设计、计划、TDD 和评审性质的工作，但没有安装和实际调用 Superpowers，不能将其记为 Superpowers 技能证据。
- 官方核对：Codex App 可从插件市场安装 Superpowers；当前标准流程为 brainstorming、worktree、writing-plans、subagent-driven development、TDD、code review 和 finishing branch。
- 补救决定：不回填虚假的历史调用；选择一个尚未完成的真实功能，从新会话和新分支开始完整执行 Superpowers 流程，并保留技能产物、红绿测试、评审和 PR 证据。
- 教训：方法论合规需要工具调用与过程证据，不能仅凭结果相似反推曾遵循指定流程。

### PROCESS-02：评估使用 Superpowers 从头重建

- 阶段：流程与范围决策
- 结论：Superpowers 不是单个 skill，而是包含多个工作流 skill 的插件与方法论；单个环节分别由 brainstorming、writing-plans、TDD、code review 等 skill 驱动。
- 可行性：在独立分支或新仓库中，以现有项目只作为需求与验收参考，从空实现重新走完整工作流，技术上可以达到当前 M0–M6 完成度。
- 风险：完整重建成本显著高于补做一个真实纵向功能；如果复用现有实现细节过多，会削弱“从规格冷启动”的过程证据。
- 建议：若课程流程证据比时间成本更重要，采用独立 clean-room rebuild；否则完成一个机制密集的完整 Superpowers 纵向迭代。

## 2026-08-14：重写规约形成过程

用户认为原 `SPEC_PROCESS.md` 不能充分体现 brainstorming 与冷启动试运行。基于当前 `SPEC.md`、`PLAN.md`、代码、测试、Git 与真实样例项目证据，将过程文档重写为追溯性模拟：明确区分模拟对话、人工取舍、已有证据和模拟冷启动发现；补充四轮关键迭代，并模拟陌生 Agent 仅凭 SPEC/PLAN 推进 T02 与 T09 时的暂停问题、错误解读风险、产出差距和建议修订 diff。由于当前环境未安装 Superpowers 且历史上没有可核验的第二 Agent 原始会话，文档明确声明不把模拟伪装成真实技能调用或独立 Agent 证据。本次未修改项目代码、`SPEC.md` 或 `PLAN.md`。

## 2026-08-14：说明 SPEC 的用途

向用户解释 `SPEC.md` 是项目的设计与验收契约：定义问题、用户、范围、功能行为、边界条件、非功能要求、架构与验收标准，使陌生实现者无需依赖历史对话也能理解“要做成什么”。同时区分其与 README（面向使用者的入口）、PLAN（实现步骤）、测试（可执行证据）及 SPEC_PROCESS（设计过程记录）的职责。

## 2026-08-14：评估分发要求

只读检查两份 requirement、`README.md`、`pyproject.toml`、`.gitignore` 和仓库构建文件。项目已声明 setuptools 构建后端、Python 依赖和 `harness-agent` CLI 入口，但 README 当前只提供 `pip install -e .` 的源码开发安装，仓库没有 `.gitlab-ci.yml`、wheel/sdist 构建说明或已发布包获取方式，因此尚不能视为完成“包管理器分发”。建议选择 Python 包作为唯一主分发形态：产出并校验 wheel/sdist，发布到 PyPI 或课程认可的包仓库，用 GitLab CI 的 `unit-test` 与 `package-build` job 自动测试和构建，并在 README 单列获取、安装、运行、目标平台、依赖、凭据安全配置和限制。另指出 requirement 的凭据安全录入/更新/清除要求与分发验收绑定，当前仅使用明文 `.env` 仍不足。

## 2026-08-14：T19 系统钥匙串、包分发与 CI

- 阶段：TDD、分发与 CI。
- 过程：先新增 `tests/unit/test_credentials.py`，首次运行因 `harness_agent.credentials` 不存在而在收集阶段失败；随后实现可注入的钥匙串端口、`keyring` 系统适配、环境/`.env` 优先与钥匙串回退、隐藏录入，以及 `credentials set/update/status/clear` CLI。
- 安全决定：状态和异常不回显 Key；CI、Mock 测试和包构建不使用真实凭据；`.env` 仅保留为明文兼容来源。没有在自动测试中写入本机真实钥匙串，使用内存后端确定性验证完整生命周期。
- 分发：`pyproject.toml` 增加 `keyring`、构建元数据和 build/twine 开发依赖；`.gitlab-ci.yml` 增加必需的 `unit-test`、`package-build` 及语义版本 tag 才触发的 `package-publish`。
- 验证：凭据定向测试 3 项由红转绿；完整离线测试 71 passed、1 skipped；`python -m build` 生成 `harness_agent-0.1.0-py3-none-any.whl` 与 `.tar.gz`，两者通过 `twine check`；在独立临时虚拟环境只安装 wheel 后，主 CLI、凭据帮助和版本导入均成功。
- 尚需外部验证：只有将代码推送到 GitLab 后才能取得真实 CI pass 记录；只有创建 `v0.1.0` 等 tag 后才能验证 Package Registry 发布。本轮没有推送或创建 tag。

## 2026-08-14：凭据来源收敛为系统钥匙串

- 目标：删除当前 `.env`，不再允许真实 Provider 从项目文件或进程环境获得 Key。
- TDD：先把凭据测试改为“即使存在 `NEW_API_KEY` 环境变量也必须使用钥匙串”，并要求配置只暴露非敏感 `credential_name`；旧实现因缺少该字段而出现预期红灯，修改后 12 项凭据与 Provider 定向测试通过。
- 迁移：只检查 `.env` 的变量名，确认仅有 `NEW_API_KEY`；迁移程序在内存中读取值，写入 Windows Credential Manager 的 `HarnessAgent/deepseek-v4-pro` 项并使用常量时间比较完成等值回读，全程未输出明文。
- 删除：回读成功后精确删除 `C:\Users\20803\Desktop\HarnessAgent\.env`，并删除已过时的 `.env.example`。原 `.env` 文件本身不可恢复，但凭据已存在系统钥匙串，可用 `credentials status/update/clear` 管理。
- 实现：移除 `load_project_env`、`api_key_env`、环境变量回退与 DeepSeekClient 自行读取环境的路径；首次运行、普通运行和凭据子命令均只访问系统 keyring。`.gitignore` 继续忽略 `.env`，仅作为防止未来误建明文文件被提交的纵深防护。
- 验证：完整离线测试 `71 passed, 1 skipped`；真实 CLI 仅凭钥匙串初始化后正常退出；wheel/sdist 重新构建并通过 `twine check`；隔离安装的新 wheel 显示钥匙串已配置且断言不存在 `api_key_env`。
- 清理：真实 CLI 启动验收生成了一个仅含 metadata 的临时 Session，检查内容后逐项删除，未触碰用户会话数据。

## 2026-08-14：README 按交付要求重写

- 任务：阅读项目、`SPEC.md`、`PLAN.md` 与两份 requirement，重写面向使用者的 README。
- 工具：PowerShell（读取中文时显式使用 UTF-8）、`rg`、`pytest`、`build`、`twine` 和 `apply_patch`；未调用 subagent 或外部网络。
- 人工决定：按用户要求保留并精确命名“项目简介、安装、运行、分发命令、目录结构、安全边界说明”六个必选章节，另拆分“测试”和“机制演示”；测试命令保持单行、可复制，不在 README 堆叠测试实现代码。
- 文档调整：删除原 README 的重复能力说明，补齐 wheel 获取与构建、系统钥匙串录入流程、Mock 运行、运行证据、CI 分发路径、平台前提和应用层治理边界；同步将 `MECHANISM_DEMO.md` 的过期回归数字更新为当前结果。
- 验证：完整离线回归 `71 passed, 1 skipped`；六项机制演示全部通过；主 CLI 与凭据 CLI 帮助可用；wheel/sdist 构建成功且 `twine check` 全部通过。
- 经验：交付 README 的章节名应直接对应验收清单；机制演示与完整回归要分开说明，并明确 Mock 测试不需要网络或真实凭据。

## 2026-08-14：发布可恢复执行与安全分发功能

- 任务：将当前纵向功能切片提交并推送到远端，发布信息只描述实现能力。
- 工具：Git、GitHub CLI 与 GitHub 发布工作流；先核对分支、远端、完整变更和认证状态。
- 发布范围：长任务上下文与有限恢复、批量读写、治理策略增强、系统钥匙串凭据生命周期、多技术栈验证发现、包构建与 GitLab CI，以及相应的确定性测试和真实样例项目。
- 安全决定：不提交真实实验生成的 `.agent` 日志、输入、PID 或 Session 运行产物；仅保留非敏感 `.agent/config.json`。常见 GitHub/OpenAI/Bearer token 模式扫描未发现真实凭据。
- 验证：完整离线回归 `71 passed, 1 skipped`；六项机制演示和 README 精简演示测试集通过；wheel/sdist 构建及 `twine check` 通过。
