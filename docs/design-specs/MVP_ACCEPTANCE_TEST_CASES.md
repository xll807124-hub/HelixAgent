# MVP 验收用例设计 - Issue → PR 端到端场景

> **设计版本**: v0.1-draft  
> **目标**: 定义 AI Agent 平台 MVP 的关键验收场景  
> **范围**: 端到端工作流、权限拒绝、Kill Switch、Checkpoint 恢复等关键路径  
> **状态**: 用例文案清单，待 QA 团队补齐参数化测试  
> **依赖**: REQ-RT-001~008、REQ-SEC-002/003/004/009、REQ-REL-004/006、REQ-OBS-002

---

## 用例设计原则

1. **黑盒验证**：只关心用户可观察的行为，不关心内部实现细节
2. **原子性**：每个用例验证单一关键行为
3. **EARS 格式**：使用"当...时...必须..."的可验证陈述
4. **多维覆盖**：快乐路径 + 权限边界 + 故障恢复 + 安全拦截

---

## A. 快乐路径（Happy Path）

### UC-A1: 完整的 Bug 修复闭环

**背景**：用户创建一个 GitHub Issue，Agent 完成修复并生成 PR

**前置条件**：
- 用户已授权 Agent 访问仓库
- 仓库项目与权限已配置
- 代理模型 API 已就绪

**场景步骤**（GIVEN-WHEN-THEN）：

**GIVEN**：
- GitHub Issue：`#123: Fix typo in README.md`
- Issue 内容被正确索引到 Agent 上下文
- Repository 的代码符号已索引（symbol extraction 通过）

**WHEN**：
- 用户在 Agent 控制台点击"自动修复"按钮
- Agent 创建 Task（状态：CREATED）
- Task 过 Policy Gateway 授权（状态：AUTHORIZING）
- Agent 启动 Coder Worker（状态：RUNNING）
- Coder Worker 提议 3 个 Action：
  1. ReadFile 读取 `README.md`
  2. WriteFile 写回修复内容
  3. GitCommit 提交变更

**THEN**：
- 所有 Action 通过 Policy Gateway（AUTHORIZED）
- Action 按顺序执行，产生 Evidence（file_read / file_write / git_commit）
- Task 进入 CREATING_PR 状态
- 在 GitHub 上生成 PR（链接可见）
- Task 转入 WAITING_REVIEW 状态
- 返回状态：SUCCESS，用户可点击 PR 链接

**验收断言**：
```
✅ GitHub PR 已创建，且 Base Branch 正确
✅ PR 标题和描述由 Agent 生成（格式符合规范）
✅ 变更集（Diff）仅包含预期修改（无额外改动）
✅ 所有 Evidence 已记录（3 条操作）
✅ Task 事件链完整，可追踪（Event Store 可查）
✅ 执行耗时 < 5 分钟
✅ 成本计费正确（token 消耗 + API 调用）
```

**用时**: ~3-5 分钟

---

### UC-A2: 含工具链的多步骤修复

**背景**：修复需要编译、测试、代码分析多个环节

**场景步骤**：

**GIVEN**：
- Issue 描述的缺陷涉及：代码改动 + 测试失败

**WHEN**：
- Coder Worker 生成代码变更
- Tester Worker 自动运行测试套件
- 测试失败（某个 test case 不通过）
- Agent 调用故障归因（REL-008）判定根因
- Coder Worker 基于归因结果重新修改代码

**THEN**：
- Task 进入重试循环（EXECUTING cycle）
- 最多重试 3 次（max_iterations 约束）
- 最终所有测试通过
- PR 生成时包含完整的 Diff 和测试覆盖率报告
- 返回状态：SUCCESS

**验收断言**：
```
✅ Coder 和 Tester Worker 的交互日志完整
✅ 故障归因记录在 Evidence（failure_root_cause 字段）
✅ 重试次数不超过配置限制
✅ 最终 PR 中包含测试覆盖率 > 80%
✅ 所有中间 Checkpoint 已保存
```

---

## B. 权限与授权场景

### UC-B1: 权限不足导致拒绝

**背景**：User 对特定文件没有写权限，Agent 尝试修改时被拒绝

**场景步骤**：

**GIVEN**：
- User 是 Repository 的 Contributor（读权限）
- 文件 `config/secret-config.yaml` 为 Admin-only（写权限）
- Task 授权范围：当前用户的权限

**WHEN**：
- Coder Worker 提议 Action：`WriteFile config/secret-config.yaml`
- Policy Gateway 校验：`user_permissions ∩ org_policy ∩ code_platform_permissions ∩ task_scope`

**THEN**：
- Policy Gateway 返回 DENY（权限交集为空）
- Action 转入 FAILED 状态
- Task 失败，返回明确的错误消息："No write permission for config/secret-config.yaml (Admin-only)"
- 不产生任何实际修改（Sandbox 隔离保证）

**验收断言**：
```
✅ Policy Gateway 拒绝决策被记录（audit log）
✅ Task 不进入 EXECUTING 状态
✅ 错误消息清晰指出权限缺陷（不泄露系统细节）
✅ 不产生 Evidence（无实际操作）
✅ 返回状态：FAILED with reason="PERMISSION_DENIED"
```

---

### UC-B2: 高风险操作触发审批等待

**背景**：Agent 尝试执行高风险操作（删除文件 / 修改 CI 配置），需要人工审批

**场景步骤**：

**GIVEN**：
- Policy 定义：`DELETE_FILE` 为高风险，需双人审批
- Organization 有两个可用审批者（Admin1, Admin2）

**WHEN**：
- Coder Worker 提议 Action：`DeleteFile deprecated-module.py`
- Policy Gateway 评估风险等级：HIGH
- 返回决策：REQUIRE_APPROVAL

**THEN**：
- Task 转入 WAITING_APPROVAL 状态
- 发送审批通知给 Admin1 和 Admin2
- 控制台显示"Awaiting approval from 2 reviewers"
- Admin1 打开审批面板，看到：
  - Action 参数的结构化展示（文件路径、删除原因等）
  - 预期影响范围（该文件的依赖关系）
  - 完整的 Audit Context（谁提议 / 何时 / 为什么）
- Admin1 批准，Admin2 也批准
- Task 继续执行，Action 转入 AUTHORIZED → EXECUTING

**验收断言**：
```
✅ 审批通知送达（邮件 / Slack / Dashboard）
✅ 审批界面显示结构化信息，不只有自然语言摘要
✅ 两次批准都被记录在 Audit Log
✅ Task 从 WAITING_APPROVAL 正确转入 EXECUTING
✅ 如果 1 小时内未获批，Task 自动超时失败
```

---

## C. 故障恢复场景

### UC-C1: Worker 崩溃后从 Checkpoint 恢复

**背景**：Coder Worker 在执行第 5 个 Action 时模拟崩溃，系统应恢复

**场景步骤**：

**GIVEN**：
- Task 有多个连续 Action 要执行（比如 10 个）
- 在第 5 个 Action 完成后创建 Checkpoint
- 第 6 个 Action 执行中，Worker 进程被杀死（模拟 Kill -9）

**WHEN**：
- Health Check 检测到 Worker 不响应（超过 30 秒）
- Harness（可靠性框架）启动恢复程序
- 查询最近的 Checkpoint
- 从 Checkpoint 恢复：
  - 恢复 Worker 状态
  - 恢复工作区（文件系统 / Git 分支）
  - 恢复凭据（从凭据代理重新签发）
- 重新启动 Worker，从第 7 个 Action 继续

**THEN**：
- Action 1-5 不重复执行（Evidence 保留）
- Action 6 的部分结果被废弃，不计入最终 PR
- Action 7-10 正常执行
- Task 最终完成
- 恢复过程的所有步骤被记录在 Trace + Audit Log

**验收断言**：
```
✅ 检测到 Worker 崩溃 < 10 秒
✅ Checkpoint 恢复成功（工作区一致性验证通过）
✅ 无重复执行（Action 1-5 的 Evidence 被跳过）
✅ 恢复后的 Task 状态转移正确（EXECUTING → EXECUTING）
✅ 最终 PR 中只包含 Action 7-10 的变更
✅ Trace 链接清晰（标记恢复点和跳过的 Action）
```

---

### UC-C2: 网络暂时故障导致重试

**背景**：ReadFile Action 因网络故障失败，系统应重试

**场景步骤**：

**GIVEN**：
- 读取远程仓库文件（通过 Git 协议）
- 网络连接超时（模拟）

**WHEN**：
- Action 因 TRANSIENT_CONNECTIVITY 失败
- Retry Engine（REL-002）判定：
  - 该操作是幂等的（读操作）
  - 网络瞬断（可重试）
  - Retry Budget 充足
- 应用指数退避重试（1s → 2s → 4s）
- 第 2 次重试成功

**THEN**：
- Action 转入 SUCCEEDED 状态
- Evidence 记录 2 次尝试和最终成功
- Task 继续
- 返回用户的消息："Retried once, succeeded"

**验收断言**：
```
✅ 重试 1 次后成功
✅ 退避时间符合指数策略
✅ 重试决策记录在 Audit Log
✅ 最终状态：SUCCEEDED（而非 FAILED）
✅ Retry Budget 消耗被正确计费
```

---

## D. 安全边界场景

### UC-D1: 沙箱隔离 - Shell 危险命令被拦截

**背景**：Coder Worker 尝试执行危险 Shell 命令，应被沙箱拒绝

**场景步骤**：

**GIVEN**：
- 沙箱策略：禁止 `rm -rf` / 访问 `/etc` / 网络调用等
- Worker 尝试执行危险 Action

**WHEN**：
- Coder Worker 提议 Action：`ExecuteShell rm -rf /workspace/build`
- Tool Harness 解析命令
- Policy Gateway 检查命令是否符合白名单

**THEN**：
- 命令被 DENIED（不允许递归删除）
- Action 转入 FAILED 状态
- 不产生实际 Shell 执行（Sandbox 隔离）
- 错误信息："Recursive delete operations not allowed"

**验收断言**：
```
✅ 危险命令被拦截（未执行）
✅ Action 失败，无副作用
✅ Audit Log 记录尝试（安全告警）
✅ 返回状态：FAILED with reason="SECURITY_POLICY_VIOLATION"
```

---

### UC-D2: Kill Switch 触发 - 任务立即停止

**背景**：安全告警触发 Kill Switch M2，所有新 Action 被拒绝

**场景步骤**：

**GIVEN**：
- Task 正在 EXECUTING 状态
- 有 10 个待执行 Action

**WHEN**：
- 安全系统检测到恶意行为（比如高频尝试权限提升）
- Kill Switch 触发 M2 模式（APPROVALS_REQUIRED）

**THEN**：
- Task 的所有后续 Action 需要双人审批
- 已经开始的 Action 允许完成
- 新 Action 提议时自动转入 WAITING_APPROVAL
- Task 不能自动进入 COMPLETED，必须经人工审查后才能完成

**验收断言**：
```
✅ M2 激活后新 Action 自动需双人审批
✅ 进行中的 Action 不被强制中断
✅ Kill Switch 决策被记录在 Audit Log
✅ Task 转入受限模式（显示在 UI 上）
✅ 若 Kill Switch 维持 15 分钟，状态自动降级回 M1 或恢复正常
```

---

## E. 多模块集成场景

### UC-E1: Trace + Audit 完整链路

**背景**：一个完整 Task 的执行过程，验证 Trace 和 Audit 的端到端记录

**场景步骤**：

**GIVEN**：
- UC-A1 的快乐路径 Task
- OBS 和 REL 模块已启用

**WHEN**：
- Task 执行全流程
- 每个关键转移点都产生 Event + Trace Span + Audit Log

**THEN**：
- Event Store 中：9 个事件（TaskCreated / AuthorizationStarted / ... / TaskCompleted）
- Trace：1 个根 Span（task.execute），包含 3 个子 Span（coder.plan / coder.execute / coder.deliver）
- Audit Log：6 条操作记录（TaskCreated / ActionAuthorized x3 / TaskCompleted）
- 关联验证：
  - 每个 Event 的 `trace_id` 和 `span_id` 匹配
  - 每个 Audit Log 的 `causation_chain` 指向相关 Event
  - Checkpoint 的 `last_event_id` 正确指向恢复点

**验收断言**：
```
✅ Event Chain 完整，无遗漏
✅ Trace Span 的父子关系正确
✅ Audit Log 的链（previous_hash）形成正确的 Merkle 链
✅ 三个系统的时间戳一致（差 < 1ms）
✅ Query API 可查询完整链路
```

---

### UC-E2: Idempotency - 重复请求去重

**背景**：同一个 Action 被意外提交两次，系统应只执行一次

**场景步骤**：

**GIVEN**：
- Action 提议时分配幂等键：`idempotency_key = sha256(action_type + params + worker_id)`
- 第一次提交成功

**WHEN**：
- 网络延迟导致客户端重试
- 完全相同的 Action 再次提交（相同幂等键和参数）

**THEN**：
- 系统查询 Idempotency 表，发现键已存在
- 返回之前的执行结果（缓存命中）
- 不重复执行 Action（文件未被写两次）
- 返回状态：SUCCEEDED（与第一次相同）

**验收断言**：
```
✅ 重复请求立即返回缓存结果（< 100ms）
✅ 无重复 Evidence 生成
✅ Action 状态和结果与第一次完全相同
✅ 如果参数不同，返回错误（不允许参数变化）
```

---

## F. 数据完整性与合规场景

### UC-F1: 审计日志不可篡改

**背景**：验证审计日志的 WORM 特性和 Merkle 链完整性

**场景步骤**：

**GIVEN**：
- Task 执行完毕，审计日志已密封（block_finalized = true）

**WHEN**：
- 尝试修改审计日志（模拟攻击）
- 计算 Merkle 链的哈希值验证

**THEN**：
- 审计日志不能被 UPDATE（RLS 策略拒绝）
- Merkle 链哈希验证失败
- 系统检测到篡改并告警

**验收断言**：
```
✅ UPDATE / DELETE 操作被数据库 RLS 拒绝
✅ 链哈希验证失败，篡改被检测
✅ 告警事件被记录到 Kill Switch 模块
```

---

### UC-F2: 多租户数据隔离

**背景**：验证不同租户的数据严格隔离

**场景步骤**：

**GIVEN**：
- Organization A 创建 Task T1
- Organization B 创建 Task T2

**WHEN**：
- 以 Org A 的身份查询所有 Task

**THEN**：
- 结果只包含 T1，不包含 T2
- 尝试直接查询 Org B 的 Task（不加 organization_id 过滤）被 RLS 策略拒绝
- 跨租户 JOIN 返回空结果集（不报错，只是无行返回）

**验收断言**：
```
✅ 各租户只能看到自己的数据
✅ 跨租户查询被 RLS 拦截
✅ 无数据泄露路径
```

---

## G. 性能基线验收

### UC-G1: 事件写入吞吐与延迟

**背景**：验证 Event Store 性能基线

**场景步骤**：

**GIVEN**：
- 初始化：Event Store 中 0 条记录

**WHEN**：
- 1 个 Task 并行生成 100 个 Action
- 所有 Action 并发提交 Event

**THEN**：
- Event 写入吞吐 ≥ 5k events/sec
- P95 写入延迟 < 50ms
- 所有 100 个 Event 都被正确持久化和可查询

**验收断言**：
```
✅ 吞吐达到 ≥ 5k events/sec
✅ P95 < 50ms，P99 < 100ms
✅ 无丢失或重复
```

---

### UC-G2: 查询延迟 - Task 事件链

**背景**：检索一个 Task 的完整事件链的性能

**场景步骤**：

**GIVEN**：
- Event Store 中 100k 个 Task，每个 Task 平均 10 个 Event

**WHEN**：
- 查询特定 Task 的完整事件链（1000 个 Event）

**THEN**：
- 查询延迟 P95 < 200ms
- 结果被正确排序（按 occurred_at）
- 支持分页（limit 100，offset X）

**验收断言**：
```
✅ P95 查询延迟 < 200ms
✅ 分页正确
✅ 返回结果包括脱敏后的 payload
```

---

## H. 负面场景（边界条件）

### UC-H1: Task 预算耗尽

**背景**：Task 的 Token 预算已用完，新 Action 被拒绝

**场景步骤**：

**GIVEN**：
- Task 预算：1000 tokens
- 已消耗 950 tokens

**WHEN**：
- Coder Worker 提议新 Action，需要 100 tokens

**THEN**：
- Policy Gateway 检查预算
- 返回 DENY（预算不足）
- Action 被拒绝，Task 进入 FAILED 状态

**验收断言**：
```
✅ 预算检查工作（不允许超支）
✅ 错误消息："Budget exhausted: required 100, remaining 50"
```

---

### UC-H2: 超时导致自动失败

**背景**：Task 执行超过配置的最大时间

**场景步骤**：

**GIVEN**：
- Task 最大执行时间：10 分钟
- Task 已执行 9 分钟 50 秒

**WHEN**：
- 第 15 个 Action 被提议执行

**THEN**：
- 系统检查时间约束
- 拒绝新 Action（超时在即）
- Task 转入 FAILED 状态，原因："Execution timeout exceeded"

**验收断言**：
```
✅ 超时时间精确（差 < 1s）
✅ 最后一个 Action 不被执行
✅ 现有 Checkpoint 被保留用于事后分析
```

---

## 验收标准总结

| 类别 | 通过条件 | 数量 |
|------|---------|------|
| **快乐路径** | UC-A1 + UC-A2 完整执行 | 2 |
| **权限边界** | UC-B1 + UC-B2 拒绝正确 | 2 |
| **故障恢复** | UC-C1 + UC-C2 恢复成功 | 2 |
| **安全隔离** | UC-D1 + UC-D2 拦截成功 | 2 |
| **多模块集成** | UC-E1 + UC-E2 数据一致 | 2 |
| **合规审计** | UC-F1 + UC-F2 隔离成功 | 2 |
| **性能基线** | UC-G1 + UC-G2 达标 | 2 |
| **负面场景** | UC-H1 + UC-H2 拒绝正确 | 2 |

**MVP 验收总数**: 16 个关键用例（每个 ~ 5-15 分钟）

**预计总验证时间**: 2-4 小时（包括手动复验）

---

## 下一步

1. **参数化测试脚本**：QA 团队基于用例编写自动化测试
2. **测试数据准备**：GitHub Issue / PR 样本、用户权限配置
3. **环境搭建**：MVP 版本的 AI Agent 平台部署
4. **冒烟测试**：先执行快乐路径（UC-A1），验证基本流程畅通
5. **系统测试**：逐个验收其他用例

---

**设计者**: 架构组 + QA  
**最后更新**: 2026-10-12

