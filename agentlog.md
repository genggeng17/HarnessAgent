2026-07-17：评审并接受第一版验证架构的简化方向，删除独立 Feedback 体系，改为 ToolResult 加薄 VerificationResult。精简重写 docs/spec.md，并明确验证门禁、组件边界、依赖方向和纵向测试场景。
2026-07-17：复核 spec v0.4 的可实现性；确认架构足以启动，但完整实现前仍需补齐 Action Schema、状态转换表、Policy 矩阵、工具协议、验证规则和崩溃恢复语义，并给出建议的纵向实现顺序。
2026-07-17：完成 M0 实施契约，将 spec 升级到 v0.5；冻结 Action JSON、状态转换、工具与 Policy 协议、验证 revision 门禁、审批崩溃恢复、持久化责任、技术栈及 GLM 5.2 Provider 默认配置。
2026-07-17：将 M0-M6 纵向里程碑写入 spec，并完成 M1：建立 Python 3.12/Pydantic 项目、严格 ActionParser、不可变 TurnState/StateMachine、LoopGuard、可恢复 MockLLMClient 和 22 项离线测试。
2026-07-17：确认项目 `.venv` 已使用 Python 3.12.13 和 Pydantic 2.13.4，并说明通过现有 uv 完成用户级 Python 3.12 安装及项目虚拟环境依赖安装的命令。
2026-07-17：完成 M2/M3 纵向切片，接通 Workspace 边界、统一工具治理与分发、只读工具、Patch、Shell 验证、revision 门禁和最小 AgentLoop。新增只读分析、验证通过、失败后修复及资源耗尽场景测试，并更新里程碑状态。
