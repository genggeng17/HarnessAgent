# HarnessAgent 设计规约

版本：1.0

状态：M0–M6 核心纵向切片已实现

主要语言：Python 3.12+

产品形态：本地交互式 Coding Agent CLI

## 1. 问题陈述

大语言模型可以提出代码修改方案，但一次模型调用本身不能保证动作格式、安全边界、测试真实性、暂停恢复和执行证据。HarnessAgent 面向希望研究或构建可靠本地 Coding Agent 的开发者，将这些能力实现为可离线测试的运行内核。

目标用户包括：

- 希望理解 AgentLoop、工具治理和验证闭环的开发者；
- 需要在本地项目中试验结构化 Coding Agent 的研究者；
- 希望用 Mock LLM 确定性测试 Agent 行为的工程团队。

项目的价值不在于包装一次模型请求，而在于用代码回答：模型可以做什么、何时需要人工介入、怎样证明修改经过验证、进程中断后如何安全恢复。

## 2. 目标与范围

### 2.1 项目目标

1. 实现不依赖现成 Agent 框架的异步 Agent 主循环；
2. 使用严格 JSON Action 协议约束模型输出；
3. 让所有工具调用统一经过 Registry、Policy 和 Dispatcher；
4. 将验证结果绑定工作区 revision，阻止未验证修改报告成功；
5. 支持审批、业务澄清、崩溃窗口和会话恢复；
6. 保存状态、Trace、命令日志和受证据约束的长期记忆；
7. 使用 Mock LLM 完全离线验证核心机制；
8. 接入一个真实 Provider，完成真实项目代码增改实验。

### 2.2 当前范围之外

- 并行 Agent、DAG 和 Subagent 编排；
- Git Worktree 自动创建、合并和清理；
- 自动 commit、push 和发布；
- 云端执行和完整容器沙箱；
- 多模型自动路由；
- IDE 插件和图形界面。

这些能力不得通过绕过现有治理和验证链路的方式加入。

## 3. 用户故事

### US-1：受控分析项目

作为开发者，我希望 Agent 只能读取目标工作区内的文件，以便在不泄露工作区外数据的情况下完成代码分析。

验收标准：绝对路径、`..` 越界和符号链接逃逸被确定性拒绝；合法读取可通过 Registry 和 Dispatcher 完成。

### US-2：修改后强制验证

作为项目维护者，我希望 Agent 修改文件后必须运行可信测试，以免模型仅凭自述宣布完成。

验收标准：写入增加 workspace revision；旧验证失效；当前 revision 的全部必需验证器通过前，success Final 被拒绝。

### US-3：根据失败反馈自我修正

作为用户，我希望测试失败的客观输出能返回给 Agent，使它可以修改并再次验证。

验收标准：验证失败产生 VerificationResult；结果回灌模型；Mock LLM 可以确定性驱动“失败—修改—通过”流程。

### US-4：危险动作需要治理

作为用户，我希望危险或不确定的命令在执行前被拒绝或暂停，以便保留对外部副作用的控制权。

验收标准：Policy 返回 ALLOW、ASK 或 DENY；一次性授权与原 Action 和参数绑定；DENY 不能被审批覆盖。

### US-5：中断后安全恢复

作为用户，我希望程序退出后恢复等待中的任务，同时避免重复执行结果未知的副作用。

验收标准：状态在派发前落盘；恢复发现 DISPATCHING 时转为 EXECUTION_UNKNOWN；非幂等动作不会静默重放。

### US-6：离线测试 Harness

作为 Harness 开发者，我希望移除真实 LLM 后仍能测试主循环、工具、治理、反馈、记忆和停机机制。

验收标准：Mock LLM 按序消费响应；核心测试不访问网络；同一输入产生确定性状态结果。

### US-7：跨会话保留证据

作为长期使用者，我希望 Session、Turn、命令和决定保存在项目目录，以便恢复和审查。

验收标准：`.agent/sessions/` 保存状态、Transcript、Trace、命令日志和结果；项目事实必须带来源和证据。

### US-8：适配不同项目测试系统

作为多语言项目维护者，我希望 Harness 能发现常见测试命令，也允许显式配置验证器。

验收标准：支持 Python、Node.js、Rust、Go、Maven 和 Gradle 标记；多个必需验证器可分次完成。

## 4. 功能规约

### 4.1 结构化 Action

输入：LLM 返回的单个 JSON 对象。

行为：ActionParser 按 Pydantic Schema 严格校验类型、字段和额外字段。

输出：合法 Action 或精确格式错误 Observation。

边界：不接受 Markdown 包裹、未知 type、缺失字段和额外字段。

错误处理：格式错误不执行任何副作用，并在资源预算内允许模型修正。

支持的 Action：

```text
plan              {schema_version, type, items}
update_plan       {schema_version, type, updates, append_items?}
tool_call         {schema_version, type, tool, arguments}
reflect           {schema_version, type, summary, next_step}
ask_clarification {schema_version, type, question, options?}
final             {schema_version, type, outcome, message}
```

### 4.2 Agent 主循环

输入：用户任务、历史消息、项目规则、记忆和可用工具。

行为：构造上下文、调用 LLM、解析 Action、检查状态、治理并执行工具、回灌结果。

输出：完成、失败、中止或等待用户的 Turn。

边界：默认最多 20 次迭代、40 次工具调用、3 次反思；连续重复 Action 达到阈值后停止。

错误处理：协议错误、资源耗尽和不可恢复状态进入明确失败，不无限循环。

### 4.3 工作区与工具

所有路径参数使用工作区相对 POSIX 路径。当前工具包括：

| 工具 | 输入 | 输出与边界 |
|---|---|---|
| `list_directory` | 路径、深度、条目上限 | 返回受限目录树，不越过工作区 |
| `read_file` | 路径、行范围、字符上限 | 返回 UTF-8 文本、SHA-256 和完整性信息 |
| `read_files` | 最多 20 个路径 | 批量返回相关文件和版本摘要 |
| `search_text` | 字面查询、目录、glob | 返回受数量限制的匹配 |
| `apply_patch` | unified diff | 创建、修改或删除文件 |
| `edit_file` | 唯一锚点、内容、可选 SHA-256 | 稳定局部修改，拒绝陈旧版本或非唯一锚点 |
| `edit_files` | 最多 20 项精确修改 | 统一预检查后成组写入相关文件 |
| `run_shell` | argv、cwd、超时 | 使用 `shell=False`，完整输出写命令日志 |
| `run_verification` | validator ID | 执行可信验证器并产生客观结果 |

### 4.4 治理与审批

PolicyEngine 根据工具可信元数据、参数、工作区和权限模式返回：

- `ALLOW`：允许派发；
- `ASK`：保存原 ToolCall，等待用户批准或拒绝；
- `DENY`：固定拒绝，Approval 不得覆盖。

权限模式：

| 操作 | READ_ONLY | SAFE_EDIT | FULL_AUTO |
|---|---|---|---|
| 工作区内读取 | ALLOW | ALLOW | ALLOW |
| 受控文件修改 | DENY | ALLOW | ALLOW |
| 已注册验证器 | ASK | ALLOW | ALLOW |
| 只读 Git allowlist | ALLOW | ALLOW | ALLOW |
| 普通 Shell | DENY | ASK | ASK |
| 已知破坏性命令与越界路径 | DENY | DENY | DENY |

固定拒绝覆盖常见系统破坏命令、丢弃 Git 修改的命令，以及使用 Shell、临时脚本或字符串替换写源码的常见兜底方式。

### 4.5 验证闭环

验证器结构为：

```json
{
  "id": "tests",
  "argv": ["python", "-m", "pytest"],
  "cwd": ".",
  "timeout_seconds": 60,
  "required": true
}
```

VerificationResult 只根据进程是否启动、是否超时和退出码是否为 0 判断通过，不推测根因。首次写入前运行已有必需验证器记录基线；写入后旧 revision 结果失效；任务过半仍未做修改后验证时，系统要求先测试再继续扩展修改。

### 4.6 修改失败恢复

精确修改可绑定读取时的 SHA-256。锚点不匹配时返回最新文件摘要和局部内容；一次失败后冻结恢复目标，第二次失败要求完整重读，连续三次失败终止任务，且不允许改用 Shell 写源码。

### 4.7 会话、持久化与恢复

```text
.agent/
├── config.json
├── memory/
│   ├── project.json
│   └── decisions.jsonl
└── sessions/<session-id>/
    ├── metadata.json
    ├── transcript.jsonl
    └── turns/<turn-id>/
        ├── metadata.json
        ├── state.json
        ├── trace.jsonl
        ├── commands.log
        └── result.json
```

JSON 快照使用临时文件、`fsync` 和原子替换；JSONL 只追加。`state.json` 是恢复真相源，Trace 不反推状态。

### 4.8 上下文与记忆

每轮上下文包括 Action/工具 Schema、任务卡、当前状态、计划、验证进度、文件版本、剩余预算、项目规则和相关记忆。根目录 `AGENTS.md` 最多读取 12,000 个字符；系统钥匙串凭据不进入模型上下文。

Project Memory 只保存带来源与证据摘要的事实；Decision Memory 只保存用户确认或项目规范规定的决定。旧消息按字符预算裁剪，保留固定规则、原始任务和近期证据。

### 4.9 CLI 与真实 Provider

CLI 支持在一个 Session 中连续创建 Turn，并通过 `/resume` 恢复等待任务。真实 Provider 使用 OpenAI 兼容的 DeepSeek-V4-Pro 接口，非流式、温度为 0、要求 JSON 输出，并对超时、429 和部分 5xx 进行有限重试。

### 4.10 凭据与分发设计

DeepSeek API Key 只存入操作系统钥匙串，服务名为 `HarnessAgent`，默认凭据名称为 `deepseek-v4-pro`，也可在非敏感项目配置中改用其他凭据名称。CLI 提供隐藏录入、更新、仅状态查看和清除命令；状态与错误信息不得包含 Key 明文。运行时不读取 `.env`、进程环境变量、命令行参数或项目配置中的明文 Key。

项目以 Python 3.12+ 的纯 Python wheel 和源码包分发。GitLab CI 的 `unit-test` job 运行离线测试，`package-build` 生成并校验 wheel/sdist、执行隔离安装冒烟测试，语义版本 tag 触发 `package-publish` 将产物发布到项目 PyPI Package Registry。构建、Mock 测试和发布过程不需要真实 LLM Key。

## 5. 非功能性需求

### 5.1 性能

- 文件和工具输出受字符与条目上限约束；
- 网络和子进程均设置超时；
- 多文件读取和成组修改减少模型往返；
- 简单只读任务应在取得足够证据后立即结束。

### 5.2 安全

- 工具只能在解析后的工作区真实路径内操作；
- Shell 使用 argv 和 `shell=False`；
- 已知破坏性命令固定拒绝；
- 普通 Shell 在可编辑模式下需要用户审批；
- API Key 只从系统钥匙串读取，不写入版本化配置、项目文件或进程环境；
- 系统钥匙串凭据不进入模型上下文、Trace、命令日志或状态输出；
- Approval 是应用层治理，不等同于操作系统沙箱。

主要威胁与当前对策：

| 威胁 | 对策 |
|---|---|
| 路径越界或符号链接逃逸 | 解析真实路径并检查工作区边界 |
| 模型伪造工具类别 | 工具 kind、side effect 和 idempotent 由 Registry 提供 |
| 未验证修改被宣布成功 | revision 验证门禁 |
| 审批被复用于其他动作 | 授权与原 Action、参数和工作区绑定一次 |
| 中断后重复副作用 | DISPATCHING 落盘与 EXECUTION_UNKNOWN |
| Key 进入 Git | 只存入系统钥匙串，配置只保存非敏感凭据名称 |
| Key 进入模型上下文 | 上下文构造器不读取系统钥匙串，Key 仅传给 Provider HTTP 适配器 |
| Key 被终端或状态命令回显 | `getpass` 隐藏录入，状态、更新和清除输出不包含明文 |

### 5.3 可用性

- 错误信息使用中文并给出可修正的字段或状态；
- CLI 展示修改文件和当前 revision 的验证摘要；
- 有唯一可恢复任务时 `/resume` 直接选择，多个任务时列出 ID。

### 5.4 可观测性

- 保存 Session transcript、Turn state、Trace、完整命令日志和最终结果；
- 验证结果记录 tool call、revision、退出码、超时和日志引用；
- 真实项目实验保存在 `test_projects/`，用于复查调度和需求保持。

## 6. 系统架构

```text
CLI（组合根）
├── ProjectRuntime / SessionManager / TurnManager
├── AgentLoop
│   ├── ActionParser
│   ├── StateMachine
│   ├── LoopGuard
│   ├── PolicyEngine
│   ├── ToolDispatcher → ToolRegistry → Tools
│   └── VerificationService
├── LLMClient
│   ├── MockLLMClient
│   └── DeepSeekClient
└── LocalWorkspace / LocalStore / TraceWriter / MemoryManager
```

主流程：

```text
用户任务
→ 固化任务卡与构造上下文
→ LLM 返回 JSON Action
→ 严格解析与状态检查
→ Policy 决策
→ 工具统一分发
→ ToolResult / VerificationResult 回灌
→ 状态与证据落盘
→ 下一轮、等待用户或结束
```

## 7. 数据模型

核心实体：

- Project：目标项目及其配置、记忆和 Session；
- Workspace：工具允许操作的本地根目录；
- Session：多轮对话容器；
- Turn：一次用户任务的完整生命周期；
- Action：模型提出的结构化下一步；
- ToolResult：工具执行的客观事实；
- VerificationResult：绑定 revision 的验证结果；
- PendingInteraction：审批或业务澄清；
- ApprovalGrant：绑定原动作的一次性授权；
- ProjectFact：带来源和证据的项目事实；
- Decision：用户确认或规范规定的长期决定。

公共 Pydantic 模型默认禁止额外字段，并在持久化时使用版本化 Schema。

## 8. 领域与机制设计

### 8.1 动作与工具

Coding 场景需要读取、搜索、精确修改、Patch、Shell 和验证。所有工具都通过同一 Registry 和 Dispatcher，模型不能声明可信治理属性。

### 8.2 客观反馈信号

主要反馈是可信验证器的真实退出码、超时和输出。Harness 不用提示词要求模型“自行确认”，而是由 VerificationService 和 StateMachine 强制门禁并把失败证据回灌。

### 8.3 危险动作

危险动作包括工作区越界、丢弃修改、系统破坏命令、普通 Shell、删除以及未知执行。Policy、Workspace、审批状态机和恢复机制共同形成代码级护栏。

### 8.4 记忆需求

跨会话只保留可验证项目事实和明确决定；临时推测、完整日志和无关历史不进入长期记忆。上下文按需选择，而不是全量载入。

### 8.5 主要贡献：治理与可恢复执行

本项目六个维度均有最低实现，重点维度是治理。主要贡献包括：

- 工作区真实路径边界；
- Registry 可信工具元数据；
- ALLOW/ASK/DENY Policy；
- 与原参数绑定的一次性授权；
- 外部副作用前 DISPATCHING 落盘；
- 中断后的 EXECUTION_UNKNOWN；
- 修改失败有限恢复与 Shell 写源码旁路拒绝；
- 当前 revision 的验证完成门禁。

这些机制移除真实 LLM 后仍可使用 Mock 或直接构造数据进行确定性测试。

## 9. 技术选型

| 技术 | 用途与理由 |
|---|---|
| Python 3.12+ | 跨平台、异步子进程和测试生态成熟 |
| Pydantic v2 | 严格 Action、配置和持久化 Schema |
| `asyncio` | 非阻塞模型请求与子进程执行 |
| `httpx` | 直接调用 OpenAI 兼容接口，不引入 Agent SDK |
| `keyring` | 统一接入 Windows Credential Manager、macOS Keychain 与 Linux Secret Service |
| pytest / unittest | 离线单元、集成与异步测试 |
| argparse | 保持 CLI 依赖小且易于分发 |
| JSON / JSONL | 可审查、可恢复的本地持久化格式 |

## 10. 获取、配置与运行

项目以 Python wheel 与源码包分发。用户可安装 GitLab CI Artifact 中的 wheel；开发者可通过 Git 获取后进行可编辑安装：

```powershell
git clone https://github.com/genggeng17/HarnessAgent.git
Set-Location HarnessAgent
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

目标机器使用 `harness-agent credentials set` 将 Key 隐藏录入系统钥匙串。非敏感行为配置保存在 `.agent/config.json`，其中只能保存凭据名称，不能保存 Key。构建、CI 与具体命令见 README。

## 11. 验收标准

1. `python -m pytest` 可以离线运行全部核心测试；
2. Mock LLM 能驱动无工具、只读、修改验证、失败修正和审批恢复场景；
3. 所有 ToolCall 都经过 Policy 和 Dispatcher；
4. 工作区路径逃逸和已知危险命令被拒绝；
5. ASK 可以暂停、落盘并最多执行一次原动作；
6. 修改后不能绕过当前 revision 验证直接成功；
7. 验证失败证据可以驱动下一次修改；
8. 资源耗尽时确定性停止；
9. 进程重启后可以恢复等待任务，未知副作用不自动重放；
10. Mock 模式不需要网络和 API Key；
11. 真实 Provider 可以完成受控只读和跨文件修改实验；
12. README、PLAN、SPEC_PROCESS、AGENT_LOG 和机制演示说明能够从仓库直接访问。
13. 凭据可以在系统钥匙串中新增、更新、查看状态和清除，所有状态输出不回显明文；
14. `python -m build` 生成通过 `twine check` 的 wheel/sdist，GitLab CI 包含 `unit-test` 与包构建任务。

## 12. 里程碑

| 里程碑 | 内容 | 状态 |
|---|---|---|
| M0 | 冻结 Action、状态、工具、Policy、验证和恢复契约 | 完成 |
| M1 | 核心模型、状态机、LoopGuard 与 Mock LLM | 完成 |
| M2 | 工作区、只读工具、Registry 与 Dispatcher | 完成 |
| M3 | 修改、Shell、验证、revision 和 Final 门禁 | 完成 |
| M4 | 审批、澄清、一次性授权与崩溃窗口 | 完成 |
| M5 | Session、CLI、持久化、Trace 与恢复 | 完成 |
| M6 | 配置、命令治理、长期记忆与真实 Provider | 完成核心切片 |
| R1 | 任务卡、上下文裁剪、文件版本和修改恢复 | 完成，待整理提交 |
| R2 | 真实记账与库存项目的独立验收 | 完成 |
