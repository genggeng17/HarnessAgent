# HarnessAgent

## 项目简介

HarnessAgent 是一个使用 Python 实现的本地 Coding Agent 运行内核。它把大语言模型每轮给出的单个结构化 Action，接入工作区工具、权限治理、客观验证、会话持久化与恢复机制，使模型能够在明确边界内读取代码、修改文件、运行测试并根据失败证据继续修正。

本项目不使用 LangChain、AutoGen、CrewAI 等现成 Agent 编排框架。以下核心机制均由仓库代码实现，并可在移除真实 LLM 后通过 Mock LLM 离线验证：

- Agent 主循环与严格 Action Schema；
- 工具注册、参数校验、治理与统一分发；
- 工作区边界、文件读取、搜索和多种精确修改；
- `ALLOW / ASK / DENY` 策略、一次性审批和业务澄清；
- 绑定工作区 revision 的测试反馈与成功门禁；
- Session、Turn、Trace、长期记忆和中断恢复；
- DeepSeek-V4-Pro Provider 与顺序 Mock Provider。

当前版本为 `0.1.0`，要求 Python 3.12 或更高版本。项目发布纯 Python `py3-none-any` wheel，可运行于 Windows、macOS 和 Linux；主要开发与真实验证环境为 Windows PowerShell。

## 安装

### 普通用户：两步启动

版本发布后，可直接从 GitHub Release 安装 wheel 并运行：

```powershell
python -m pip install https://github.com/genggeng17/HarnessAgent/releases/download/v0.1.0/harness_agent-0.1.0-py3-none-any.whl
harness-agent --project C:\path\to\target-project
```

首次运行会以隐藏输入录入 API Key 并保存到系统钥匙串，无需预先执行凭据命令。正式 Release 创建前，可从 GitHub Actions 的 `package-build` Artifact 下载 wheel 后使用本地路径安装。

### 开发者：从源码安装

```powershell
git clone https://github.com/genggeng17/HarnessAgent.git
Set-Location HarnessAgent
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

macOS 或 Linux 激活虚拟环境时使用：

```bash
source .venv/bin/activate
```

开发安装使用额外的测试和构建依赖；普通用户不需要执行这些命令。`harness-agent` 与 `python -m harness_agent` 是等价入口。

## 运行

### 安全配置 API Key

真实 Provider 的 API Key 只从操作系统钥匙串读取：Windows Credential Manager、macOS Keychain，或 Linux 已配置的 Secret Service 后端。Key 不从命令行、环境变量、`.env` 或项目配置文件读取。

首次真实运行时，如果终端可交互且尚未配置 Key，CLI 会以隐藏输入引导保存。凭据管理统一使用以下命令形式：

```powershell
harness-agent --project C:\path\to\target-project credentials set
```

将 `set` 替换为 `status`、`update` 或 `clear` 可执行对应操作；`status` 不回显明文。默认钥匙串服务名为 `HarnessAgent`，凭据名为 `deepseek-v4-pro`；不同项目可在 `.agent/config.json` 中使用不同的 `deepseek.credential_name`。

### 真实模型模式

操作当前目录：

```powershell
harness-agent --project .
```

操作其他项目：

```powershell
harness-agent --project C:\path\to\target-project
```

默认连接 `https://njusehub.info/v1/chat/completions`，模型为 `deepseek-v4-pro`。交互命令如下：

| 输入 | 行为 |
|---|---|
| 普通文字 | 在当前 Session 创建一个 Turn |
| `/resume` | 恢复唯一等待任务，或列出多个候选任务 |
| `/resume <session-id> <turn-id>` | 恢复指定 Turn |
| `yes` / `no` | 一次性批准或拒绝待审批动作 |
| `abort` | 中止等待中的 Turn |
| `exit` / `quit` | 退出 CLI |

### 离线 Mock 模式

创建 `responses.json`；数组中的每一项都是一次模型调用返回的 JSON 字符串：

```json
[
  "{\"schema_version\":1,\"type\":\"final\",\"outcome\":\"success\",\"message\":\"离线回答完成\"}"
]
```

然后运行：

```powershell
harness-agent --project . --mock-responses .\responses.json
```

Mock 响应按顺序消费，耗尽时明确失败；该模式不访问网络，也不需要 API Key。

### 项目配置与运行记录

`.agent/config.json` 是可选的非敏感配置，可声明权限模式、验证器、循环预算和 Provider 参数。文件不存在时使用安全默认值，并自动发现 Python、Node.js、Rust、Go、Maven 和 Gradle 的常见测试入口。

最小配置示例：

```json
{
  "schema_version": 1,
  "permission_mode": "SAFE_EDIT",
  "validators": [
    {"id": "tests", "argv": ["python", "-m", "pytest"], "cwd": ".", "required": true}
  ]
}
```

运行证据写入目标项目的 `.agent/`：

```text
.agent/
├── config.json
├── memory/
└── sessions/<session-id>/
    ├── transcript.jsonl
    └── turns/<turn-id>/
        ├── state.json
        ├── trace.jsonl
        ├── commands.log
        └── result.json
```

## 测试

安装开发依赖后，一条命令运行全部离线单元测试和集成测试：

```powershell
python -m pytest
```

2026-08-14 的本地验证结果为 `71 passed, 1 skipped`。跳过项是 Windows 账户缺少创建符号链接权限时无法执行的符号链接逃逸测试。测试不访问真实 LLM、网络或系统钥匙串中的真实凭据。

CI 配置位于 `.github/workflows/ci.yml`，其中 `unit-test` job 会在 Python 3.12 环境执行同一条测试命令。

## 机制演示

机制演示使用 Mock LLM 或直接构造领域对象，确定性覆盖三类专项要求：

1. Policy 拦截危险命令和 Shell 修改源码旁路；
2. 注入验证失败后，失败证据回灌并驱动下一步动作改变；
3. 一次性审批、崩溃窗口不重放副作用和修改失败有限恢复。

一键运行六项机制演示：

```powershell
python -m pytest -m mechanism_demo
```

六个精确演示用例、预期状态转换和单独运行命令见 [MECHANISM_DEMO.md](docs/MECHANISM_DEMO.md)。真实模型端到端实验保存在 `test_projects/`，不属于离线回归的必要条件。

## 分发命令

以下命令面向维护者，不是普通用户的启动步骤。项目使用 `setuptools` 构建 wheel 与源码包：

```powershell
python -m pip install -e ".[dev]"
python -m build
python -m twine check dist/*
```

生成：

```text
dist/
├── harness_agent-0.1.0-py3-none-any.whl
└── harness_agent-0.1.0.tar.gz
```

本地安装构建产物并冒烟检查：

```powershell
python -m pip install .\dist\harness_agent-0.1.0-py3-none-any.whl
harness-agent --help
```

GitHub Actions 的分发流程为：

- `unit-test`：运行完整离线测试；
- `package-build`：构建并校验 wheel/sdist，在隔离虚拟环境安装 wheel 并检查 CLI；
- `release`：仅在 `v<主版本>.<次版本>.<修订号>` tag 上使用 GitHub 自动提供的短期令牌创建 Release，并上传 wheel/sdist。

CI 不需要或保存真实 API Key。未创建发布 tag 时，可从 `package-build` Artifact 获取安装包；创建 tag 后，可从仓库的 Releases 页面长期下载。

当前实现满足“标准 Python 包可由 `pip` 安装”的技术要求。最终交付前仍需推送语义版本 tag，并确认 GitHub Actions 成功创建 Release；本项目通过 Release URL 安装，不声称已发布到公共 Python 包索引。

## 目录结构

```text
HarnessAgent/
├── harness_agent/
│   ├── agent/          # Action、主循环、状态机、上下文与验证门禁
│   ├── cli/            # CLI 组合入口
│   ├── config/         # 版本化非敏感项目配置
│   ├── governance/     # Policy 与权限模式
│   ├── llm/            # LLM 抽象、Mock 与 DeepSeek Provider
│   ├── memory/         # 项目事实与人工决定记忆
│   ├── runtime/        # Workspace、Session 与 Turn 协调
│   ├── storage/        # 原子状态和 JSONL 存储
│   ├── tools/          # Registry、Dispatcher 与工具实现
│   ├── tracing/        # 结构化 Trace 事件
│   └── credentials.py  # 系统钥匙串凭据生命周期
├── tests/
│   ├── unit/           # 确定性机制单元测试
│   └── integration/    # Mock LLM 纵向循环测试
├── test_projects/      # 真实模型端到端实验项目
├── docs/
│   ├── AGENT_LOG.md        # AI 协作过程记录
│   ├── MECHANISM_DEMO.md   # 可重复运行的机制演示
│   ├── PLAN.md             # 里程碑、TDD 步骤与实现证据
│   ├── REFLECTION.md       # 项目反思报告
│   ├── SPEC.md             # 设计与验收契约
│   └── SPEC_PROCESS.md     # 规约形成与关键取舍
├── .github/workflows/  # GitHub Actions 测试、构建和 Release 流水线
├── AGENTS.md           # Codex 项目约束
├── README.md           # 项目入口文档
└── pyproject.toml      # 包元数据、依赖与 CLI 入口
```

## 安全边界说明

HarnessAgent 在应用层实施以下确定性边界：

- **工作区围栏**：文件工具拒绝绝对路径、`..` 和符号链接逃逸，只允许访问目标项目；
- **命令执行**：Shell 使用参数数组和 `shell=False`，拒绝已知破坏性命令、丢弃 Git 修改以及常见 Shell 写源码方式；
- **最小授权**：只读工具可直接运行，普通 Shell 在 `SAFE_EDIT` / `FULL_AUTO` 下仍需人工审批；批准只绑定原 Action 与参数一次；
- **验证门禁**：发生修改后，只有当前 workspace revision 的全部必需验证器通过，Agent 才能报告成功；
- **安全恢复**：工具派发后、结果落盘前若发生崩溃，状态转为 `EXECUTION_UNKNOWN`，未知副作用不会自动重放；
- **凭据隔离**：真实 API Key 仅保存在系统钥匙串中，隐藏录入，状态、异常、Trace 与配置均不回显明文。

这些规则是应用层治理，不是操作系统沙箱。经用户批准的程序仍可能主动访问工作区外文件、网络或外部服务；请只在可信环境和可恢复的项目副本中运行。

## 已知限制

- 测试通过只能证明已声明验证器成功，不能证明 AI 新增测试完整覆盖用户意图；
- 验证器自动发现以项目根目录和常见项目标记为主，复杂 monorepo 应显式配置；
- 上下文裁剪基于字符预算和近期消息，不是语义检索；
- Linux 真实模式依赖可用的 Secret Service/keyring 后端；无后端的服务器仍可运行 Mock 模式；
- wheel 与 CPU 架构无关，但目标机必须预装 Python 3.12+；
- 当前主要交互形态为本地 CLI，仓库未提供 WebUI；
- GitHub Release 仅在语义版本 tag 的发布流水线成功后出现对应版本。

## 相关文档

- [SPEC.md](docs/SPEC.md)：问题、范围、架构、机制设计与验收标准；
- [PLAN.md](docs/PLAN.md)：实现任务、依赖、TDD 步骤和当前证据；
- [SPEC_PROCESS.md](docs/SPEC_PROCESS.md)：规约形成、冷启动检查与人工取舍；
- [MECHANISM_DEMO.md](docs/MECHANISM_DEMO.md)：六项确定性机制演示；
- [REFLECTION.md](docs/REFLECTION.md)：项目过程、工程取舍与方法论反思；
- [AGENT_LOG.md](docs/AGENT_LOG.md)：按时间整理的 AI 协作记录。
