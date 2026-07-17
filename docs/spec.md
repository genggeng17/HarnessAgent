# 本地交互式 Coding Agent Harness 规格说明

版本：0.5  
状态：第一阶段实施契约  
主要语言：Python  
产品形态：本地交互式 CLI

## 1. 项目目标

本项目实现一个小而完整、可测试、可恢复的本地 Coding Agent Harness。

用户可以在同一 Session 中连续提出代码分析、修改和验证任务。Harness 负责构造上下文、调用 LLM、解析结构化 Action、执行安全检查、调用工具、验证修改、维护状态并记录过程。

第一阶段重点证明以下机制由程序实现，而不是只依赖提示词：

1. 结构化 Action 和确定性的执行循环；
2. 所有工具调用统一经过治理和分发；
3. 文件修改后必须通过客观验证才能报告成功；
4. 审批可以暂停、持久化并恢复原动作；
5. 核心流程可以完全使用 Mock LLM 离线测试。

第一阶段不尝试用规则理解具体错误原因，也不由 Harness 决定具体修复方案。验证失败的原始证据交给 LLM，由 LLM 分析并产生下一步 Action；Harness 只负责客观判断、流程约束和资源上限。

## 2. 第一阶段范围

### 2.1 必须实现

- 本地交互式 CLI；
- 可创建和恢复的 Session；
- 一个 Session 中的多个 Turn；
- 一个 Turn 内的多次 LLM 和工具调用；
- 可注入的 `LLMClient` 和序列化 `MockLLMClient`；
- 结构化 Action 协议和严格解析；
- 线性 Plan；
- 文件读取、目录浏览、搜索、Patch、Shell 和验证工具；
- 显式传递的 `LocalWorkspace`；
- `ALLOW / ASK / DENY` 治理；
- 路径越界、符号链接逃逸和危险命令拦截；
- 审批与业务澄清的暂停和恢复；
- 修改后的验证门禁；
- Turn 状态机和循环资源限制；
- Event、Trace、命令日志和最终结果持久化；
- Project Memory 和 Decision Memory 的最低实现；
- 无网络、无真实 LLM 的单元测试和场景测试。

### 2.2 不实现

- Subagent、DelegateAction 和 Orchestrator；
- 并行 Agent 和 DAG 调度；
- Git Worktree 的创建、分配、合并与清理；
- 云端执行、IDE 插件和完整容器沙箱；
- 自动 Git commit、push 或发布；
- 多模型自动路由；
- 错误原因规则库、失败类别体系和确定性修复策略。

未来能力只保留演进原则，不提前创建空包、空类或没有调用者的接口。

## 3. 核心概念

### Project、Workspace、Session 和 Turn

- **Project**：当前代码仓库或目录，拥有配置、长期记忆、Session 和执行记录。
- **LocalWorkspace**：工具允许操作的本地文件范围，至少包含 `workspace_id`、`root_path`、`read_only` 和可选 `base_revision`。
- **Session**：可持久化和恢复的多轮对话，保存用户与 Agent 可见的消息。
- **Turn**：从一次用户输入开始，到返回最终结果、失败或中止为止的完整执行生命周期。
- **Iteration**：AgentLoop 的一次 LLM—Action—结果循环，只是 Turn 状态中的计数，不单独持久化为实体。

`ProjectRuntime` 是项目级资源的组合对象，持有配置、默认 Workspace、Store、EventBus 等共享资源。它不得成为全局单例，也不得保存某个 Turn 的可变执行状态。

Session 持久化所使用的 `workspace_id`。Turn 创建时获得 Workspace 引用，AgentLoop、PolicyEngine 和 ToolDispatcher 均通过参数接收 Workspace，不自行创建或缓存它。

### Action、ToolResult 和 VerificationResult

- **Action**：LLM 请求 Harness 执行的结构化意图。
- **ToolResult**：工具执行的原始事实，不包含 Harness 对错误原因的推测。
- **VerificationResult**：对验证类 ToolResult 的薄封装，只表达验证是否客观通过。
- **Event**：已经发生的系统事实，是 Trace 和终端过程展示的统一数据来源。

普通读取、搜索、Patch 和一般 Shell 调用只产生 ToolResult。只有 Registry 中被可信元数据标记为验证类型的工具，其结果才会额外生成 VerificationResult。LLM 输出不能自行把任意工具调用标记为验证。

## 4. 组件职责和依赖方向

### 4.1 AgentLoop

AgentLoop 是一个 Turn 的流程协调者，负责：

- 构造 LLM 上下文；
- 调用 LLM 并解析 Action；
- 依次调用 StateMachine、PolicyEngine、ToolDispatcher 和 VerificationService；
- 把 ToolResult 或 VerificationResult 回灌给 LLM；
- 更新循环计数、发出 Event 并判断是否继续。

AgentLoop 不直接判断权限、不执行工具、不解释失败原因、不直接读写终端，也不绕过 StateMachine 修改 TurnPhase。

### 4.2 StateMachine

StateMachine 只负责：

- 判断当前 Phase 是否允许某种 Action；
- 根据明确的系统事件执行合法状态转换；
- 拒绝跳过审批或验证门禁的非法转换。

StateMachine 不调用 LLM、Policy、Tool、Storage 或 Renderer，也不决定怎样修复验证失败。

### 4.3 PolicyEngine

PolicyEngine 根据规范化 ToolCall、Workspace、权限模式、配置和一次性授权返回：

- `ALLOW`：可以执行；
- `ASK`：需要用户审批；
- `DENY`：确定性拒绝。

PolicyEngine 不执行工具、不改变 TurnState，也不负责终端交互或审批持久化。

### 4.4 ToolDispatcher

ToolDispatcher 负责根据 Registry 查找 Tool、校验参数并统一执行，返回 ToolResult。所有 ToolCall，包括验证调用，都必须经过同一条 PolicyEngine 和 ToolDispatcher 路径。

`verification_tool.py` 只声明验证工具的参数和可信类型元数据，实际命令执行复用统一 Shell 执行能力，不创建第二套 subprocess 执行器。

### 4.5 VerificationService

`agent/verification.py` 中的 VerificationService 只处理验证类 ToolResult：

- 根据退出码、超时、启动失败等客观字段判断是否通过；
- 生成简短输出摘要；
- 保留原始 ToolResult 的引用和完整命令日志引用；
- 返回 VerificationResult。

它不分类具体错误、不建议修复方案、不比较语义进展，也不直接改变 TurnState。

### 4.6 Runtime、Storage 和 Tracing

- Runtime 管理 Project、Session、Turn、交互等待和 Event 分发；
- Storage 实现 Session、Turn 和 Memory 的持久化接口；
- Tracing 作为 EventSink 保存 Event，并根据 Event 展示时间线；
- CLI 入口负责创建具体组件并完成依赖注入。

以下箭头表示代码依赖方向：

```text
CLI main（唯一组合根）
├──→ ProjectRuntime、Runtime Manager 和 AgentLoop
└──→ 本地工具、文件存储、TraceWriter、LLM 等具体适配器

Runtime Manager ──→ AgentLoop
Runtime Manager ──→ Store 抽象接口
AgentLoop ──→ StateMachine、PolicyEngine、VerificationService
AgentLoop ──→ LLM、Tool 和 EventPublisher 等抽象接口
具体适配器 ──→ 对应抽象接口和领域数据模型
```

ProjectRuntime 只接收组合根已经创建好的项目级资源，不负责导入或构造具体适配器。

领域组件不得导入具体本地存储或 TraceWriter；Storage 和 Tracing 不得反向调用 AgentLoop 或 Runtime Manager。EventBus 只依赖 EventSink 接口。

## 5. 执行流程

### 5.1 普通 Turn

```text
用户输入
→ 创建或恢复 Session
→ 创建 Turn
→ AgentLoop 构造上下文
→ LLM 返回结构化 Action
→ ActionParser 严格解析
→ StateMachine 检查 Action 合法性
→ PolicyEngine 判断 ToolCall
→ ToolDispatcher 执行
→ 回灌 ToolResult
→ 继续循环或结束 Turn
```

Action 解析失败时不得猜测执行。Harness 生成格式错误消息并允许 LLM 在资源限制内重新输出。

### 5.2 修改和验证

成功的写入类 ToolResult 会把 Turn 标记为 `workspace_dirty = true`。

```text
写入成功
→ workspace_dirty = true
→ LLM 请求验证工具
→ PolicyEngine
→ ToolDispatcher
→ VerificationService
→ VerificationResult
```

- 验证通过：清除 dirty 状态；
- 验证失败：把 VerificationResult、输出摘要和日志引用回灌给 LLM；
- LLM 决定修改、重新验证、请求用户信息或结束失败；
- 验证通过后如果再次修改文件，之前的通过立即失效；
- `workspace_dirty = true` 时，StateMachine 不允许成功的 FinalAction。

修复循环只受 `max_iterations`、`max_tool_calls`、重复 Action 和其他 LoopGuard 限制，不设置 FailureCategory、RepairDirective 或独立 RepairPolicy。

### 5.3 审批暂停和恢复

PolicyEngine 返回 ASK 时，Turn 进入 `WAITING_FOR_USER`，并原子保存：

- 暂停前 Phase；
- 等待类型和请求内容；
- 规范化的原 ToolCall；
- `action_id`、`interaction_id` 和参数摘要；
- 恢复所需上下文。

允许本次时，一次性授权必须绑定原 Action 和规范化参数，恢复流程重新检查当前状态与 Policy，然后最多执行一次原 ToolCall。拒绝本次时，拒绝结果回灌给 LLM；中止时 Turn 进入 ABORTED。

业务澄清使用不同的 Interaction 类型。恢复后把用户答案加入上下文，不重新执行 AskClarificationAction。

## 6. Action 和状态

第一阶段支持：

- `PlanAction`；
- `UpdatePlanAction`；
- `ToolCallAction`；
- `ReflectAction`；
- `AskClarificationAction`；
- `FinalAction`。

所有 Action 必须有明确的 `type` 和符合 Schema 的参数。ActionParser 校验成功后由 Harness 分配稳定的 `action_id`；审批不是由 LLM 产生的 Action。

主要 TurnPhase：

```text
CREATED → PREPARING → PLANNING → EXECUTING → VERIFYING → COMPLETED
                         ↘ WAITING_FOR_USER ↗
```

终止状态为 `COMPLETED`、`FAILED` 和 `ABORTED`。等待恢复到暂停前 Phase。验证失败返回 EXECUTING，由 LLM 根据证据产生下一个 Action；第一阶段不需要独立 `REPAIRING` Phase。

## 7. 数据模型最低要求

### ToolResult

至少包含：

- `tool_call_id`、工具名和执行状态；
- 退出码、是否超时、stdout/stderr 摘要；
- 完整命令日志引用；
- 开始与结束时间；
- 对写入工具记录实际修改的文件；
- 启动失败、参数错误等客观错误信息。

### VerificationResult

至少包含：

- `verification_id`；
- `tool_call_id`；
- `passed`；
- `exit_code`；
- `timed_out`；
- `output_summary`；
- `tool_result_ref`；
- `command_log_ref`。

VerificationResult 不包含 FailureCategory、根因、修复建议或下一状态。

### Event

Event 至少包含 `event_id`、`session_id`、`turn_id`、类型、时间、关联 Action/ToolCall ID 和结构化 payload。Event 是 Trace 的唯一事实模型，不替代当前 TurnState 快照。

## 8. 上下文、记忆和持久化

每次 LLM 调用按需包含：

- 当前用户任务、Plan 和 TurnState；
- 最近相关对话和 ToolResult；
- 最新 VerificationResult；
- 可用工具及其 Schema；
- Workspace、权限和资源限制；
- 相关 Project Fact 和 Design Decision；
- 按需读取的代码内容。

默认不注入完整历史 Session、Trace、commands.log、所有项目文件或全部长期记忆。

Project Memory 只保存可重新扫描验证的事实。Decision Memory 只保存用户明确确认、项目规范规定或人工接受的长期决策。

持久化目录：

```text
<project>/.agent/
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
        ├── changes.diff
        └── result.json
```

`state.json` 是恢复快照，`trace.jsonl` 是只追加时间线，`commands.log` 保存未截断命令输出。Session transcript 不复制完整命令日志和底层 Event。

## 9. 项目结构

```text
HarnessAgent/
├── AGENTS.md
├── pyproject.toml
├── README.md
├── docs/spec.md
├── harness_agent/
│   ├── cli/                 # 输入、命令和渲染
│   ├── agent/               # Loop、Action、状态机、验证和结果
│   ├── llm/                 # LLMClient、Mock 和供应商适配
│   ├── tools/               # Registry、Dispatcher 和受控工具
│   ├── governance/          # Policy、路径和命令安全规则
│   ├── runtime/             # ProjectRuntime、Session、Turn、交互和 Event
│   ├── memory/              # Project Memory 和 Decision Memory
│   ├── storage/             # Store 接口和本地文件实现
│   ├── tracing/             # EventSink、命令日志和时间线回放
│   ├── config/              # 配置、权限和资源限制
│   └── prompts/             # 模型可见提示
└── tests/
    ├── unit/
    ├── integration/
    ├── scenarios/
    └── fixtures/
```

第一阶段不创建独立 `feedback/`、`orchestration/`、`subagent/` 或顶层 `workspace/` 包。

## 10. 测试和完成标准

核心测试必须不依赖网络和真实 LLM。

单元测试至少覆盖：

- Action 解析成功与失败；
- 合法和非法状态转换；
- 工具注册、参数校验和统一分发；
- 路径越界、符号链接逃逸和命令风险判断；
- `ALLOW / ASK / DENY`；
- VerificationResult 的通过、失败、超时和启动失败；
- dirty 状态、验证失效和 Final 门禁；
- LoopGuard 资源上限和重复 Action；
- 原子状态存储。

集成和 Mock LLM 场景至少覆盖：

1. 只读分析并正常结束；
2. 修改后一次验证通过；
3. 首次验证失败，LLM 修改后再次验证通过；
4. 验证持续失败并因资源上限终止；
5. 危险操作被 DENY；
6. ASK 后允许并恢复同一 ToolCall；
7. ASK 后拒绝或中止；
8. 进程退出后恢复 Session 和等待中的 Turn。

第一阶段完成时必须满足：

- CLI 能完成连续多轮对话；
- Mock LLM 能完整驱动 AgentLoop；
- Agent 能读取、修改并验证示例项目；
- 所有 ToolCall 都经过 PolicyEngine；
- ASK 能暂停、持久化并幂等恢复；
- 修改后不能绕过验证直接报告成功；
- 验证失败证据能回灌给 LLM 并支持至少一次修复；
- 资源达到上限时能确定性终止；
- Trace 能展示主要执行时间线。

## 11. 未来扩展原则

- Subagent 复用同一个 AgentLoop，不实现第二套循环；
- Orchestrator 未来负责任务分解、并发、上下文限制和结果汇总；
- DAG 属于 Orchestrator，不进入 AgentLoop 或线性 Plan 的第一阶段模型；
- 只读 Subagent 可以共享 Workspace，写入型 Subagent 必须使用独立 Worktree；
- Worktree 实现时再把 Workspace 演进为独立顶层包；
- Event、Action、ToolCall 和 Workspace 使用稳定 ID，为未来父子执行关联预留空间；
- 当前实现不得依赖全局单例、固定进程 cwd 或不可注入组件。

## 12. 实现里程碑

每个里程碑必须形成可运行或可测试的纵向切片；不得先批量创建没有真实调用者的空模块。

### M0：冻结实施契约

状态：已完成。

确定 Action JSON、状态转换、工具协议、Policy 矩阵、验证门禁、审批恢复、持久化责任、配置默认值和 Provider 接口。完成标准：后续实现不再需要临时决定公共协议或安全语义。

### M1：核心模型与 Mock 驱动

状态：已完成。

建立 Python 项目，实现 Action、TurnState、ActionParser、StateMachine、MockLLMClient 和 LoopGuard。完成标准：Mock 输出能够经过严格解析和状态转换，驱动一个无工具 Turn 到 Final；全部核心测试离线通过。

### M2：只读纵向切片

状态：已完成。

实现 LocalWorkspace、Tool Registry、Dispatcher、只读 Policy、目录/读取/搜索工具和最小 AgentLoop。完成标准：Mock LLM 能对真实本地项目完成一次受控只读分析。

### M3：修改与验证纵向切片

状态：已完成。

实现 Patch、统一 Shell 执行器、验证工具、VerificationService、workspace revision 和 Final 门禁。完成标准：覆盖一次验证通过、首次失败后再次修改并通过、持续失败后资源耗尽终止。

### M4：审批与崩溃恢复纵向切片

状态：待开始。

实现 ASK/DENY、PendingInteraction、ApprovalGrant、最小 TurnStore、DISPATCHING 和 EXECUTION_UNKNOWN。完成标准：允许、拒绝、中止、重复恢复以及崩溃窗口处理均可离线测试。

### M5：Session、CLI 与完整持久化

状态：待开始。

实现 ProjectRuntime、SessionManager、TurnManager、交互式 CLI、EventBus、TraceWriter、CommandLog 和恢复命令。完成标准：程序退出后可以恢复 Session 和等待中的 Turn，并展示主要执行时间线。

### M6：治理补全、长期记忆与真实 Provider

状态：待开始。

补全三种权限模式、命令规则、Project/Decision Memory 和 GLM 5.2 Provider，执行全部验收场景。完成标准：满足第 10 节所有第一阶段完成条件。

## 13. 第一阶段实施契约

本节冻结第一阶段的公共协议和默认行为。实现可以增加私有字段，但不得改变以下外部语义。

### 13.1 技术基线

- Python 3.12；
- Pydantic v2 定义 Action、配置和持久化 Schema，所有公共模型默认 `extra="forbid"`；
- pytest 负责测试，标准库 argparse 负责 CLI，httpx 负责 HTTP；
- 运行时核心不依赖 Agent 框架或厂商 SDK；
- 默认权限为 `SAFE_EDIT`；默认 `max_iterations=20`、`max_tool_calls=40`、`max_reflections=3`、`command_timeout_seconds=60`、`max_tool_output_chars=12000`。

AgentLoop、LLMClient 和 Tool 执行接口使用 `async def`，以便网络请求和子进程不阻塞交互层；纯 StateMachine、Policy 判断、Schema 校验和本地快照存储保持同步。核心端口为 `LLMClient.complete(messages, tool_specs) -> LLMResponse`、`Tool.execute(arguments, workspace, execution_context) -> ToolResult` 和 `EventSink.emit(event) -> None`。

### 13.2 Action JSON 协议

LLM 每次只返回一个 JSON 对象，不包含 Markdown 包裹。每个对象必须带 `schema_version: 1`；下表省略该公共字段：

```text
plan              {type, items:[{id, description}]}
update_plan       {type, updates:[{item_id, status, note?}], append_items?}
tool_call         {type, tool, arguments}
reflect           {type, summary, next_step}
ask_clarification {type, question, options?}
final             {type, outcome, message}
```

- `PlanItem.status` 只能为 `pending / in_progress / completed`，同一时刻最多一个 `in_progress`；
- `FinalAction.outcome` 只能为 `success / partial / failed`；
- Harness 在解析成功后生成 `action_id`，在接受 ToolCall 后生成 `tool_call_id`；
- Action Digest 是规范化 JSON（按 key 排序、UTF-8、无无意义空白）的 SHA-256，不包含 Harness 后加的 ID；
- 未知 type、缺失字段、额外字段、重复 PlanItem ID 或非法状态都作为解析错误回灌，不执行任何副作用。

计划采用渐进式强制规则：LLM 可以随时主动建立计划；任何写入、Shell、验证或其他非 `side_effect=none` 的 ToolCall 执行前必须已有计划；一个 Turn 请求第三次 ToolCall 前也必须已有计划。最多两次只读 ToolCall 的简单任务可以无计划执行，纯回答可以直接 Final。

### 13.3 状态转换

StateMachine 按下表处理主要事件：

| 当前状态 | 事件或 Action | 下一状态与条件 |
|---|---|---|
| CREATED | `TURN_STARTED` | PREPARING |
| PREPARING / EXECUTING | `PLAN_REQUIRED` 或 PlanAction | PLANNING；Plan 校验通过后进入 EXECUTING |
| PREPARING | 首个合法的 ToolCall 或 ReflectAction | EXECUTING |
| PREPARING / PLANNING / EXECUTING | AskClarificationAction | WAITING_FOR_USER，保存原状态 |
| EXECUTING | 验证 ToolCall 获准派发 | VERIFYING |
| VERIFYING | 验证完成、失败或超时 | EXECUTING，并回灌 VerificationResult |
| EXECUTING / VERIFYING | Policy ASK | WAITING_FOR_USER，保存原状态和 ToolCall |
| WAITING_FOR_USER | 用户响应 | 按交互类型恢复原状态、拒绝或 ABORTED |
| PREPARING / EXECUTING | FinalAction(success) | `workspace_dirty=false` 且无等待交互时进入 COMPLETED |
| PREPARING / PLANNING / EXECUTING | FinalAction(partial/failed) | FAILED，并在 TurnResult 保留 outcome |
| 任意非终态 | 用户中止 | ABORTED |
| 任意非终态 | 不可恢复内部错误或资源耗尽 | FAILED |

UpdatePlanAction 仅在已有 Plan 时允许；普通 ToolCall 仅在 PREPARING 或 EXECUTING 时允许；WAITING_FOR_USER 和终态不接受新的模型 Action。Policy DENY 不改变 Phase，只产生治理 Observation。所有计数、dirty 和 Plan 更新也必须通过 StateMachine 事件完成。

### 13.4 Tool 契约

所有路径参数使用 Workspace 相对 POSIX 路径；`.` 表示根目录，禁止绝对路径和 `..` 越界。工具最低集合：

```text
list_directory {path=".", max_depth=1, max_entries=200}
read_file      {path, start_line=1, end_line?, max_chars?}
search_text    {query, path=".", glob?, max_results=100}
apply_patch    {patch}                         # unified diff，可创建、修改或删除
run_shell      {argv:[...], cwd=".", timeout_seconds?}
run_verification {validator_id}
```

- `run_shell` 使用 `subprocess` 的 argv 和 `shell=False`；第一阶段不接受独立 env 覆盖；
- Tool 元数据至少包含 `kind`、`side_effect` 和 `idempotent`，这些值由 Registry 提供，LLM 不能覆盖；
- ToolResult.status 为 `SUCCEEDED / FAILED / TIMED_OUT / INVALID_ARGUMENTS / NOT_FOUND`；Policy 拒绝不是 ToolResult；
- ToolResult 同时记录摘要、日志引用、时间和 `modified_paths`；成功写入事件据此设置 dirty；
- 路径检查使用解析后的真实路径；目标不存在时检查最近存在的父目录，阻止符号链接逃逸。

### 13.5 Policy 矩阵

| 操作类别 | READ_ONLY | SAFE_EDIT | FULL_AUTO |
|---|---|---|---|
| 工作区内读取、目录和搜索 | ALLOW | ALLOW | ALLOW |
| 创建或修改工作区文件 | DENY | ALLOW | ALLOW |
| 删除文件、批量改写 | DENY | ASK | ASK |
| 已注册验证器 | ASK | ALLOW | ALLOW |
| 明确只读的 allowlist 命令 | ALLOW | ALLOW | ALLOW |
| 其他 Shell | DENY | ASK | ASK |
| 网络、安装依赖、Git 写操作 | DENY | ASK | ASK |
| 工作区外路径、符号链接逃逸、已知破坏性命令 | DENY | DENY | DENY |

复合 shell、`sh/bash/zsh -c`、解释器执行动态代码和无法可靠分类的命令不属于只读 allowlist。ApprovalGrant 只能把与其精确绑定的 ASK 转为 ALLOW，不能覆盖 DENY。

默认只读 Shell allowlist 仅包含 `git status`、`git diff`、`git log` 和 `git show`；参数中出现重定向、配置覆盖、外部执行或未知子命令时退出 allowlist。递归删除 Workspace 根、磁盘/系统控制、提权、fork bomb，以及 `git reset --hard`、`git clean -fd/-fdx`、`git checkout --`、`git restore` 等丢弃工作区修改的命令固定 DENY。

### 13.6 验证契约

配置中的 validator 结构为 `{id, argv, cwd=".", timeout_seconds=60, required=true}`，`run_verification` 只能引用已注册的 validator_id。若项目未配置 validator，按项目标记确定性注册：Python 测试配置、`package.json` test script、`Cargo.toml`、`go.mod` 分别映射到各自标准测试命令；无法识别时不猜测命令，写入后的成功 Final 保持被阻止并请求用户配置验证器。

VerificationResult 通过条件固定为：进程成功启动、未超时且退出码为 0。每次成功写入递增 `workspace_revision` 并设置 dirty；验证结果绑定该 revision。当前 revision 的全部 required validator 均通过后才能清除 dirty；再次写入会使旧结果失效。Harness 不解析错误根因，也不把任意 `echo/true` 命令当作验证。

### 13.7 审批和崩溃恢复

ApprovalGrant 与 `action_id + ToolCall 规范化内容 + workspace_id + Action Digest` 精确绑定，状态为 `AVAILABLE / CONSUMED`。批准只消费一次，不能用于修改后的参数或其他 Workspace。

任何消费 ApprovalGrant 的 ToolCall 在执行前，TurnManager 必须在一次原子 state 写入中消费 Grant，并把 ToolCall 记为 `DISPATCHING`；执行完成后再写为 `SUCCEEDED` 或 `FAILED`。恢复时发现 DISPATCHING，一律转为 `EXECUTION_UNKNOWN`：

- 纯读取或 Registry 明确标记为幂等的工具，可按配置或用户确认重试；
- Shell、网络、删除、Git 写入等非幂等操作不得自动重试，必须请求用户处理；
- 第一阶段只保证正常控制流和尚未开始执行的恢复路径不会重复派发，不承诺任意外部副作用的 exactly-once。

### 13.8 持久化责任

- AgentLoop 只产生 Action 处理结果、StateMachine 事件和 Event，不直接写 Store；
- TurnManager 是 state、pending interaction、approval、tool execution 和 result 的唯一写入者；
- SessionManager 写 metadata 和 transcript；MemoryManager 写 memory；
- EventBus 向 TraceWriter 和 Renderer 分发 Event；CommandLogSink 保存未截断输出；
- state.json 是恢复真相源。State 必须在外部副作用之前落盘；Trace 若因崩溃缺失，恢复后追加 recovery event，不以 Trace 反推当前状态；
- 所有 JSON 快照通过临时文件、fsync 和原子 replace 更新，JSONL 只追加。

Store 最低接口为：SessionStore 的 `create/load/list_resumable/append_message`，TurnStore 的 `create/load/save_state/save_result/list_resumable`，MemoryStore 的 `load/save`。首版 Event 类型固定为 `TURN_STARTED`、`ACTION_PARSED`、`ACTION_REJECTED`、`STATE_CHANGED`、`POLICY_DECIDED`、`APPROVAL_REQUESTED`、`APPROVAL_RESOLVED`、`TOOL_DISPATCHING`、`TOOL_FINISHED`、`TOOL_EXECUTION_UNKNOWN`、`VERIFICATION_FINISHED` 和 `TURN_FINISHED`。

### 13.9 配置、Provider 和最低 Memory

`.agent/config.json` 使用版本化 Pydantic Schema，未知字段报错。除 13.1 默认值外，至少支持 permission mode、validators、只读命令 allowlist、是否允许幂等未知执行自动重试和是否启用长期记忆。

真实 Provider 使用 GLM 5.2：默认 base URL 为 `https://open.bigmodel.cn/api/paas/v4`，模型名为 `glm-5.2`，调用 `/chat/completions`；base URL 可切换到 Coding Plan 端点。API Key 只从 `HARNESS_AGENT_GLM_API_KEY` 环境变量读取，不写入项目文件。第一阶段使用 `stream=false`、`do_sample=false` 和 JSON 结构化输出，只解析 assistant content，不把 reasoning content 注入下一轮上下文。网络超时、429 和 5xx 最多重试两次；格式错误交给 AgentLoop 的 Action 修正流程，不在 Provider 内猜测修复。

Project Memory 最低支持 `list/select/upsert/invalidate`，事实必须带来源路径、证据摘要和更新时间；Decision Memory 最低支持 `list/select/append`，只接受用户明确确认或项目规范中已有的决定。两类记忆都不自动保存模型推测。CLI `/resume` 在只有一个可恢复目标时直接选择；存在多个目标时必须展示列表让用户选择。
