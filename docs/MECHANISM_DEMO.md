# HarnessAgent 机制演示

本演示使用 Mock LLM 或直接构造可信领域对象，确定性复现治理拦截、失败反馈闭环和重点治理机制。所有命令均不访问真实模型或网络。

## 1. 环境准备

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

## 2. 演示一：治理护栏拦截危险动作

运行：

```powershell
python -m pytest tests/unit/test_m6_config_memory_provider.py::M6ConfigMemoryProviderTests::test_policy_distinguishes_read_only_and_dangerous_shell -q
```

测试直接构造 PolicyEngine、工作区和 Shell Tool，不依赖 LLM。它验证：

- allowlist 中的只读 Git 命令被允许；
- `git reset --hard` 等丢弃修改的命令被固定拒绝；
- READ_ONLY 模式下普通 Shell 被拒绝。

补充演示 Shell 写源码旁路拒绝：

```powershell
python -m pytest tests/unit/test_policy.py::PolicyTests::test_shell_source_edit_fallback_is_denied -q
```

预期：测试通过，说明危险动作是否执行由确定性 Policy 代码决定，而不是依赖提示词。

## 3. 演示二：失败反馈驱动下一步动作改变

运行：

```powershell
python -m pytest tests/integration/test_m3_edit_verify_loop.py::M3EditVerifyLoopTests::test_first_verification_fails_then_second_write_passes -q
```

Mock 响应序列确定性执行：

```text
建立计划
→ 首次写入
→ 运行验证并失败
→ Harness 生成绑定 revision 的 VerificationResult
→ 失败输出回灌 Mock LLM
→ 第二次修改
→ 再次验证并通过
→ success Final
```

测试断言验证历史为失败、失败、通过三个客观结果，并确认最终 Turn 完成。该行为证明反馈闭环由真实工具结果、VerificationService、StateMachine 和 revision 门禁共同实现。

## 4. 演示三：重点治理机制——一次性审批与未知执行

本项目的重点维度是治理与可恢复执行。

### 4.1 一次性审批

```powershell
python -m pytest tests/integration/test_m4_m5_runtime.py::M4M5RuntimeTests::test_approval_pauses_then_runs_exact_original_tool_once -q
```

演示行为：

```text
Mock LLM 请求普通 Shell
→ Policy 返回 ASK
→ Turn 保存原 ToolCall 并暂停
→ 用户批准
→ 授权与原 Action 和参数精确绑定
→ 原工具最多派发一次
```

### 4.2 崩溃窗口不重放副作用

```powershell
python -m pytest tests/integration/test_m4_m5_runtime.py::M4M5RuntimeTests::test_crash_window_becomes_unknown_instead_of_replaying -q
```

演示行为：

```text
工具在执行前标记 DISPATCHING
→ 模拟进程在结果落盘前中断
→ 恢复读取 state.json
→ 状态转为 EXECUTION_UNKNOWN
→ 非幂等动作不自动重放
```

### 4.3 修改失败有限恢复

```powershell
python -m pytest tests/integration/test_m3_edit_verify_loop.py::M3EditVerifyLoopTests::test_third_patch_failure_stops_without_shell_fallback -q
```

演示行为：修改连续失败后，Harness 返回最新文件证据、要求重读并限制重试；第三次失败确定性终止，且不会改用 Shell 修改源码。

## 5. 一键运行全部机制演示

```powershell
python -m pytest -m mechanism_demo
```

预期结果：

```text
6 passed
```

## 6. 完整离线回归

```powershell
python -m pytest
```

最近一次结果：

```text
71 passed, 1 skipped
```

Windows 账户没有创建符号链接权限时，符号链接逃逸测试会跳过。完整回归不需要 API Key，不调用真实 LLM 或网络。
