# HarnessAgent

HarnessAgent 是一个 Python 实现的本地 Coding Agent 运行内核。它能够让模型以结构化动作读取项目、修改文件、执行受控命令、运行验证，并把会话、审批和执行过程保存到项目目录中。

项目不依赖现成 Agent 框架；主循环、工具分发、安全判断、验证门禁、记忆和恢复都由本项目实现，并支持使用 Mock LLM 完全离线测试。完整设计见 [docs/spec.md](docs/spec.md)。

## 当前完成度

M1–M6 都已经有可运行的纵向实现，但尚不能认为规格中的全部验收条件都已完整满足。

| 里程碑 | 当前状态 | 已实现内容 |
|---|---|---|
| M1 | 已达到核心目标 | 严格 Action 解析、计划、Turn 状态、状态转换、循环限制和可恢复 Mock LLM |
| M2 | 已达到核心目标 | 工作区边界、目录浏览、文件读取、文字搜索、工具注册与统一分发 |
| M3 | 核心流程可用，仍有门禁缺口 | Patch、统一命令执行、验证结果、修改 revision、验证失败后重试和成功结束门禁 |
| M4 | 核心流程可用，恢复策略仍可加强 | 审批暂停、拒绝与中止、一次性授权、业务澄清、执行前落盘和未知执行保护 |
| M5 | 最小 CLI 与持久化可用 | Session/Turn 保存、对话记录、状态快照、Trace、命令日志和 `/resume` |
| M6 | 基础能力已接入，产品化不足 | 三种权限模式、危险命令规则、项目/决定记忆、版本化配置和 DeepSeek-V4-Pro Provider |

## 已有功能

### 确定性的 Agent 循环

模型每次只能输出一个 JSON Action。系统会严格检查类型、字段和状态，不会从格式错误的文本中猜测并执行操作。

真实模型每次请求都会收到由代码生成的完整 Action JSON Schema、各 Action 最小示例和工具参数 Schema。每一轮还会临时加入当前阶段、计划、工作区 revision、验证进度、权限模式及剩余调用次数；这个动态快照不会重复写入持久对话。格式错误时，系统会返回缺失字段、禁止的外层包装和正确示例，帮助模型在下一轮精确修正。

目标项目根目录存在 `AGENTS.md` 时，启动后会自动读取最多 12,000 个字符作为项目规则；不会把 `.env` 内容放入模型上下文。对于简单只读任务，模型会被明确要求跳过计划、优先使用专用文件工具，并在取得足够证据后立即结束。

目前支持：

- 建立和更新线性计划；
- 调用一个受注册表管理的工具；
- 基于已有结果进行反思；
- 向用户询问业务信息；
- 以成功、部分完成或失败结束当前 Turn。

循环有最大迭代次数、最大工具调用次数、最大反思次数和重复动作限制，达到上限后会确定性停止。

### 工作区和工具

内置工具包括：

- `list_directory`：浏览工作区目录；
- `read_file`：按行读取 UTF-8 文件；
- `search_text`：在工作区中执行字面文字搜索；
- `apply_patch`：使用 unified diff 创建、修改或删除文件；
- `run_shell`：使用参数数组和 `shell=False` 执行命令；
- `run_verification`：运行配置中登记的验证器。

所有工具调用都经过参数校验、权限判断和统一分发。文件工具只接受工作区相对 POSIX 路径，并拦截绝对路径、`..` 越界和符号链接逃逸。

### 修改和验证

文件成功修改后，Turn 会进入“工作区尚未验证”的状态。验证工具根据进程是否成功启动、是否超时以及退出码是否为 0 判断通过与否。验证失败的原始输出会交回模型，由模型决定继续修改还是结束。

每个会修改文件的任务都会把以下测试约定交给模型：修改前先查看并尽量运行相关的已有测试；优先复用已有测试，缺少覆盖时再补写；修复问题或新增行为时尽量确认新测试在修复前会失败；修改后先运行相关测试，再运行全部必需验证器。不得通过删除、跳过或弱化原有测试来制造通过结果。

验证器会从 Python、Node.js、Rust、Go、Maven 和 Gradle 的明确项目标记中自动发现；同一仓库可以登记多个。任务开始后才创建测试配置时，可以使用 `auto` 重新发现。如果无法识别项目的真实测试方式，才需要在 `.agent/config.json` 中手动补充。

验证进度和完整证据会写入 Turn 状态。多个必需验证器可以分次运行并在暂停、恢复或进程重启后继续；每次文件修改都会产生新 revision，让旧结果自动失效。没有可用验证器、测试失败或尚未运行全部必需检查时，系统都会阻止模型以成功结果结束 Turn。

### 权限和审批

支持三种权限模式：

- `READ_ONLY`：允许文件读取和少量只读 Git 命令，禁止文件修改和普通 Shell；
- `SAFE_EDIT`：允许受控文件修改和已注册验证器，普通 Shell、删除和安装依赖等操作需要审批；
- `FULL_AUTO`：当前与 `SAFE_EDIT` 的主要规则相同，仍不会绕过删除、Shell 和危险命令门禁。

`git reset --hard`、`git clean -fd`、`git restore` 等已知会丢弃修改的命令会被直接拒绝。需要审批的操作会暂停并保存原工具调用；批准只对该动作和原参数生效一次。

如果程序在工具已经标记为派发、但尚未记录结果时退出，恢复后会把该操作标记为“执行结果未知”，不会自动重复执行。

### 会话、恢复和记录

同一次 CLI 运行中可以在一个 Session 内连续提交多个任务。每个 Turn 都会保存状态快照、最终结果、事件时间线和完整命令输出。

数据默认保存在目标项目的 `.agent/` 中：

```text
.agent/
├── config.json                       # 可选项目配置
├── memory/
│   ├── project.json                  # 项目事实
│   └── decisions.jsonl               # 用户确认的长期决定
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

### 长期记忆

项目事实必须包含来源文件和证据摘要；用户决定必须来自用户明确确认或项目规范。模型的临时推测不会自动写入长期记忆。

当前记忆已经接入模型上下文选择，但写入事实和决定仍主要通过 Python API 完成，CLI 暂无专门的记忆管理命令。

### DeepSeek-V4-Pro

真实 Provider 默认使用以下配置：

```text
Base URL: https://njusehub.info/v1
Endpoint: /chat/completions
Model: deepseek-v4-pro
API Key 环境变量: NEW_API_KEY
```

请求采用 OpenAI 兼容的消息格式、非流式响应和 JSON 输出。网络超时、HTTP 429 和部分 5xx 错误最多重试两次。启动时会读取目标项目根目录的 `.env`，并从环境变量中取得 API Key；`.env` 已被 Git 忽略。

## 安装

项目要求 Python 3.12 或更高版本。

Windows PowerShell：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

只安装运行依赖：

```powershell
python -m pip install -e .
```

## 使用真实模型

首次使用时复制环境文件模板：

```powershell
Copy-Item .env.example .env
```

打开 `.env`，把占位内容替换为真实密钥：

```dotenv
NEW_API_KEY=你的_API_Key
```

以后启动时会自动读取，不需要在每个 PowerShell 窗口中重复输入。已经通过 `$env:NEW_API_KEY` 设置的当前进程变量优先于 `.env`，可用于临时覆盖。不要提交或分享 `.env`。

在当前项目中启动：

```powershell
python -m harness_agent --project .
```

安装项目后也可以使用脚本入口：

```powershell
harness-agent --project .
```

进入 CLI 后：

- 直接输入文字：创建一个新 Turn；
- `/resume`：恢复等待用户处理的 Turn；只有一个目标时直接选择，多个目标时列出 ID；
- `/resume <session-id> <turn-id>`：恢复指定 Turn；
- 审批回答 `yes`、`y` 或 `允许`：允许原操作；
- 审批回答 `no`、`n` 或 `拒绝`：拒绝原操作并让模型继续；
- 回答 `abort` 或 `停止`：中止 Turn；
- `exit` 或 `quit`：退出 CLI。

新任务如果停在审批或业务澄清状态，CLI 会显示等待原因。下一次输入 `/resume` 后，再输入审批选择或业务答案。

## 项目配置

`.agent/config.json` 是可选文件；不存在时使用安全默认值，并根据 Python 测试文件及 `pyproject.toml`、有效的 npm test 脚本、`Cargo.toml`、`go.mod`、`pom.xml` 或 Gradle Wrapper 尝试登记标准测试命令。配置字段严格校验，未知字段会导致启动失败。

完整示例：

```json
{
  "schema_version": 1,
  "permission_mode": "SAFE_EDIT",
  "validators": [
    {
      "id": "tests",
      "argv": ["python", "-m", "pytest"],
      "cwd": ".",
      "timeout_seconds": 60,
      "required": true
    }
  ],
  "read_only_command_allowlist": [
    "git status",
    "git diff",
    "git log",
    "git show"
  ],
  "allow_idempotent_unknown_execution_retry": false,
  "enable_long_term_memory": true,
  "loop_guard": {
    "max_iterations": 20,
    "max_tool_calls": 40,
    "max_reflections": 3,
    "repeated_action_limit": 3
  },
  "deepseek": {
    "base_url": "https://njusehub.info/v1",
    "model": "deepseek-v4-pro",
    "api_key_env": "NEW_API_KEY",
    "timeout_seconds": 60,
    "max_retries": 2
  }
}
```

建议在会修改文件的项目中显式配置至少一个可靠验证器。

## 离线 Mock 模式

Mock 模式不需要网络和 API Key。创建 `responses.json`：

```json
[
  "{\"schema_version\":1,\"type\":\"final\",\"outcome\":\"success\",\"message\":\"离线回答完成\"}"
]
```

启动：

```powershell
python -m harness_agent --project . --mock-responses responses.json
```

每次模型调用会按顺序消费数组中的一条字符串。响应耗尽时会明确报错。

## 测试

使用 pytest：

```powershell
python -m pytest
```

或使用标准库 unittest：

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

测试不调用真实模型和网络。当前 Windows 账户如果没有创建符号链接的权限，符号链接逃逸测试会跳过。

## 已知限制与审查结论

以下问题意味着 M1–M6 目前属于“核心实现完成”，还不是全部验收条件都已满足：

1. **AI 新写测试的质量仍需要判断。** 系统能证明测试实际运行、修改前后结果和当前 revision，但不能仅靠退出码证明测试内容真正理解了用户需求；现有测试和“先失败、后通过”只能降低这个风险。
2. **自动测试发现仍以项目根目录为主。** 复杂的多层 monorepo、需要数据库或外部服务的测试，仍建议显式配置验证器。
3. **Shell 不是沙箱。** `cwd` 被限制在工作区内，但用户批准后的命令参数仍可能主动访问工作区外路径；当前危险命令规则也不是完整的系统安全边界。
4. **Trace 事件不完整。** 当前主要保存状态变化和工具执行事件，尚缺少完整的 Action 解析、拒绝、权限决定和验证完成事件；CLI 也没有时间线回放界面。
5. **缺少 `changes.diff`。** 文件修改结果没有按规格汇总为每个 Turn 的变更补丁。
6. **Mock 的重启恢复不完整。** Mock LLM 自身支持 cursor 快照，但 Session/Turn 存储尚未保存并恢复该 cursor。
7. **长期记忆入口有限。** 已有存储和筛选能力，但没有 CLI 的查看、写入、确认和失效命令，也没有自动重新扫描事实。
8. **真实 Provider 的端到端覆盖仍有限。** 已使用真实密钥完成“读取文件后回答”的端到端测试，但真实修改、审批、失败修复和多验证器流程仍主要依靠离线测试。
9. **上下文会持续增长。** 当前 Session transcript 会整体回灌，尚未实现按相关性裁剪、摘要和 token 预算。
10. **测试场景仍不齐全。** 审批中止、重复恢复、危险命令集和真实 CLI 多轮重启恢复等场景还需要专门测试。

## 建议的后续优化顺序

优先级最高：

1. 加强 Shell 参数和工作区外路径判断，明确审批不是沙箱；
2. 补齐 AI 新增测试“修复前失败、修复后通过”的自动证据关联；
3. 补齐 M4–M6 验收测试，特别是中止、重复恢复和真实 CLI 进程重启。

随后可以完善：

- 由统一 Event 发布入口生成完整 Trace，并在 CLI 中提供 `/trace`；
- 生成 `changes.diff` 和面向用户的修改摘要；
- 提供 `/sessions`、`/memory`、`/config`、`/validators` 等管理命令；
- 持久化 Mock cursor，并改善 Session 选择和恢复体验；
- 为真实模型提供完整 Action 协议、状态和资源限制上下文；
- 增加上下文摘要、token 预算和相关消息选择；
- 增加 Provider 健康检查、连接测试和更清晰的错误提示。

更长期可考虑加入 Git Worktree 隔离、Subagent、并行任务和 DAG 调度，但这些属于第一阶段范围之外。
