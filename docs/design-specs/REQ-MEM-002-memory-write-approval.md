# REQ-MEM-002 记忆写入审批详细设计

> 版本：v0.1-designed  
> 状态：详细设计已完成，待跨模块评审与冻结  
> 优先级：P1  
> 所属模块：记忆管理（MEM）  
> 设计日期：2026-10-04  
> 前置依赖：REQ-MEM-001 Memory Schema、REQ-SEC-003 Policy Gateway  
> 后续依赖：REQ-MEM-003 记忆检索与冲突、REQ-MEM-004 记忆生命周期

---

## 1. 需求基本信息

| 属性 | 内容 |
|---|---|
| 编号 | REQ-MEM-002 |
| 名称 | 记忆写入审批 |
| 优先级 | P1 |
| 所属模块 | 记忆管理（MEM） |
| 原始位置 | `docs/design-specs/PENDING-REQUIREMENTS.md`，第 150-151 行 |
| 原始描述 | 写入条件、审核、撤销和审计 |
| 原定目标 | 记忆写入审批：确定何时需要审批、审批流程、撤销机制、审计追踪 |
| 前置依赖 | REQ-MEM-001、REQ-SEC-003 |
| 设计状态 | v0.1-designed；不代表实现或验证完成 |

---

## 2. 目标、范围与边界

### 2.1 目标

建立统一、确定、可审计的记忆写入审批机制，确保：
1. 记忆写入经过适当授权，防止未经同意的持久化
2. 支持灵活的同意粒度（一次性/会话级/永久），满足不同自动化场景
3. 敏感信息在审批前扫描并隔离，保护用户隐私
4. 撤销操作可追溯，满足 GDPR 等合规要求

### 2.2 范围

**本需求包含**：
- 审批触发条件的四维评估算法（memory_type、source、confidence、sensitivity）
- 完整的审批流程：触发→扫描→路由→审批→生效→撤销
- 三级同意粒度：一次性（临时）、会话级、永久
- 敏感信息扫描、隔离、脱敏和选择性恢复机制
- 审批通知、提醒、升级和超时兜底策略
- 撤销机制：软删除、索引清理、审计保留、物理删除
- 与 Policy Gateway 的集成和决策优先级
- 审批状态序列化和会话恢复
- 审计事件和可观测性指标

**本需求不包含**：
- 具体的存储后端选型（PostgreSQL / MongoDB / Redis）
- 向量检索的具体算法（归属 REQ-MEM-003）
- 记忆衰减策略（归属 REQ-MEM-004）
- UI/通知渠道的具体实现（归属前端设计）
- 审批人组织结构管理（归属组织管理模块）

### 2.3 问题分析

原待办仅提出"写入条件、审核、撤销和审计"的高层描述，存在以下系统性缺口：

| 缺口类别 | 具体问题 | 影响 |
|----------|----------|------|
| 触发条件缺失 | 未定义何时需要审批 | 过度审批或审批不足 |
| 审批流程模糊 | 未定义审批层级、超时机制 | 审批无限悬挂或仓促决定 |
| 同意粒度缺失 | 未定义一次性/会话级/永久边界 | 用户无法灵活控制 |
| 敏感信息处理缺失 | 未定义扫描、隔离、恢复机制 | 可能泄露密码、密钥 |
| 撤销语义模糊 | 未定义撤销后状态和审计 | 不一致状态 |
| Policy Gateway 关系不清 | 职责边界模糊 | 职责重叠或安全漏洞 |

---

## 3. 行业标杆依据

研究访问日期：2026-10-04。以下为公开事实和设计推断。

### 3.1 OpenAI Agents SDK

**公开事实**：工具声明 `needs_approval` 触发 HITL 暂停；`RunState` 序列化支持跨会话恢复；支持 `always_approve/reject` 持久化规则。

**设计推断**：声明式审批与运行时暂停分离，支持一次性/会话级/永久三级同意。

来源：[OpenAI Agents SDK](https://openai.github.io/openai-agents-python/human_in_the_loop/)，访问日期：2026-10-04

### 3.2 DeepSeek Harness

**公开事实**：审批门控置于服务层不可绕过；`writePolicy: ask | auto | off` 模型不可见；拒绝的写入记录 `*-denied` 审计行。

**设计推断**：fail-closed + 全量审计，防止绕过。

来源：[DeepSeek Harness](https://deepseek-harness.github.io/deepseek-harness/en/reference/subsystems/approval)，访问日期：2026-10-04

### 3.3 Claude Code

**公开事实**：通过 `permissions.ask` 规则控制记忆写入；PreToolUse Hook 返回 `permissionDecision: "ask"/"deny"`。

**设计推断**：权限规则与 Hook 双保险，强制人工审批类别不可被自动覆盖。

来源：[Claude Code](https://code.claude.com/docs/en/permissions)，访问日期：2026-10-04

### 3.4 Qoder

**公开事实**：三级权限策略 `always_allow/always_ask/always_deny`；待审批项不自动超时。

**设计推断**：策略可配置 + 默认安全。

来源：[Qoder](https://docs.qoder.com/cloud-agents/permission-policies)，访问日期：2026-10-04

### 3.5 学术研究：SP-Mem

**公开事实**：脱敏存储 + 隐私映射 + 检索时同意；无同意时仅返回脱敏记忆。

**设计推断**：Privacy-by-design，敏感信息分区存储。

来源：[SP-Mem](https://arxiv.org/html/2608.16551v1)，访问日期：2026-10-04

### 3.6 学术研究：Consent Memory

**公开事实**：耐久性分级（临时/单次/范围限定/永久）；撤销必须配套删除能力。

**设计推断**：持续时间作为一等决策维度，同意生命周期管理。

来源：[Consent Memory](https://agentconsent.dev/patterns/consent-memory/)，访问日期：2026-10-04

---

## 4. 核心设计

### 4.1 功能目标与价值

**功能目标**：
1. 确保记忆写入经过适当授权
2. 支持灵活的同意粒度
3. 敏感信息扫描并隔离
4. 撤销操作可追溯

**用户价值**：
- 用户掌控记忆生命周期，建立信任
- 自动化场景可配置，减少打扰
- 敏感信息不泄露
- 操作可追溯，合规

### 4.2 目标用户与使用场景

| 目标用户 | 使用场景 |
|----------|----------|
| 终端用户 | 批准/拒绝记忆写入；设置默认同意策略；撤销已同意的记忆 |
| 组织管理员 | 配置组织级审批策略；管理敏感信息规则；审计成员操作 |
| Agent 开发者 | 触发审批；接收审批结果；处理异常 |
| 安全/合规团队 | 审计记忆操作；配置 DLP 规则；处理删除请求 |

### 4.3 用户故事

**用户故事 1**：手动审批记忆
```
作为终端用户，我希望在 Agent 尝试写入记忆时收到审批通知，
以便我可以审查内容并决定是否允许持久化。
```

**用户故事 2**：配置自动化审批策略
```
作为组织管理员，我希望配置"低置信度推断需要审批，
高置信度用户输入自动写入"，以便平衡自动化和用户体验。
```

**用户故事 3**：撤销已同意的记忆
```
作为终端用户，我希望能够撤销之前同意的记忆，
并且系统自动清理相关索引，以便完全控制我的数据。
```

### 4.4 输入与输出定义

**输入**：

| 输入类型 | 描述 | 来源 |
|----------|------|------|
| Memory 对象 | 待写入的记忆内容 | Agent/User |
| 记忆元数据 | memory_type、source、confidence | REQ-MEM-001 |
| 调用者上下文 | user_id、task_id、worker_id | Runtime |
| 审批策略 | 组织/用户默认策略 | 配置系统 |

**输出**：

| 输出类型 | 描述 | 消费者 |
|----------|------|--------|
| ApprovalResult | 审批决策 | Agent、审计 |
| Memory 对象 | 审批通过后持久化的记忆 | 存储 |
| AuditEvent | 审批操作审计记录 | 审计系统 |

---

## 5. 处理流程

### 5.1 记忆写入审批主流程

```
步骤 1：触发评估
  输入：Memory 对象、调用者上下文、审批策略
  处理：根据 memory_type、source、confidence、sensitivity 确定审批必要性
  输出：ApprovalRequirement（是否需要、审批级别、理由）

步骤 2：敏感信息扫描
  输入：Memory.content.content_text
  处理：扫描敏感信息（密码、密钥、PII），标记敏感类型和位置
  输出：SensitiveScanResult（是否敏感、类型、隔离内容）

步骤 3：审批决策路由
  输入：ApprovalRequirement、SensitiveScanResult、策略
  处理：根据策略路由到自动审批/人工审批/拒绝
  输出：DecisionRoute（AUTO_APPROVED/PENDING_APPROVAL/REJECTED）

步骤 4：自动审批（AUTO_APPROVED）
  处理：记录自动审批原因、写入记忆、生成审计事件
  输出：ApprovalResult.approved、Memory、AuditEvent

步骤 5：人工审批（PENDING_APPROVAL）
  处理：创建审批请求、分配审批人、发送通知、记录 PENDING 事件
  输出：ApprovalRequest、Notification

步骤 6：审批决策
  处理：验证审批人权限、记录决策、写入/拒绝记忆、生成审计
  输出：ApprovalResult、Memory（可选）、AuditEvent

步骤 7：撤销处理
  处理：验证权限、软删除、清除索引、记录撤销事件
  输出：RevocationResult、AuditEvent
```

### 5.2 审批通知与升级流程

```
步骤 1：发送初始通知
  - 根据用户偏好选择通知渠道
  - 通知包含：记忆摘要、审批理由、链接、过期时间

步骤 2：提醒机制
  - 如果审批人未在提醒周期内响应，发送提醒
  - 提醒次数和频率可配置

步骤 3：升级机制
  - 如果超过升级阈值，通知上级审批人或备份审批人
  - 升级记录包含原始请求和升级原因

步骤 4：超时处理
  - 如果超过最终超时阈值，执行组织配置的兜底策略
  - 兜底策略：默认拒绝 / 默认批准（需明确配置）/ 延长等待
  - 超时处理必须审计记录
```

### 5.3 Policy Gateway 集成审批

```
说明：记忆写入审批复用 REQ-SEC-003 Policy Gateway 的决策框架，
但审批决策由 MEM 模块的 ApprovalService 专门处理。

步骤 1：PEP 拦截写入请求
  - Tool Adapter 在记忆写入时拦截
  - 构造 ApprovalRequest

步骤 2：Policy Gateway 评估
  - 评估操作风险
  - 如果高风险，返回 REQUIRE_APPROVAL
  - 如果拒绝，返回 DENY

步骤 3：MEM ApprovalService 决策
  - 根据记忆元数据确定审批级别
  - 根据组织策略决定是否需要人工审批

步骤 4：决策合并
  - Policy Gateway 的 DENY > MEM 的 APPROVED
  - Policy Gateway 的 REQUIRE_APPROVAL + MEM 的 APPROVED = 需要人工审批
  - 两者都 APPROVED = 可自动写入
```

---

## 6. 算法设计

### 6.1 审批必要性评估算法

```text
输入：Memory.memory_type, source, confidence, sensitivity, OrganizationPolicy
输出：ApprovalRequirement

算法：

1. 计算基础评分：
   base_score = 
     (memory_type == WORKING ? 0 : 10) +
     (source == USER_EXPLICIT ? 0 :
       source == USER_IMPLICIT ? 5 :
       source == AGENT_EXTRACTED ? 15 :
       source == AGENT_INFERRED ? 25 :
       source == SYSTEM_GENERATED ? 20 : 0) +
     ((1 - confidence.value) * 30) +
     (sensitivity == HIGH ? 20 :
       sensitivity == MEDIUM ? 10 : 0)

2. 应用组织策略调整：
   adjusted_score = base_score * org_policy.approval_multiplier
   
   如果 org_policy.always_ask_for_types 包含 memory_type：
     adjusted_score = max(adjusted_score, 50)

3. 确定审批级别：
   如果 adjusted_score >= org_policy.approval_threshold.human：
     level = HUMAN_REQUIRED
   否则如果 adjusted_score >= org_policy.approval_threshold.auto：
     level = AUTO_WITH_NOTIFICATION
   否则：
     level = AUTO_APPROVED

4. 返回 ApprovalRequirement
```

### 6.2 敏感信息扫描算法

```text
输入：MemoryContent.content_text
输出：SensitiveScanResult

算法：

1. 正则匹配检测：
   - API 密钥/Token：sk-*, Bearer *, github_token_*
   - 密码/凭据：password=, secret=, api_key=
   - SSH 密钥：BEGIN RSA/DSA/EC/OPENSSH PRIVATE KEY

2. NER 实体识别：
   - 邮箱地址、电话号码、身份证号、信用卡号

3. 自定义规则检测：
   - 配置文件中的 sensitive_fields 列表
   - 环境变量模式

4. 分类输出
```

---

## 7. 核心实体 Schema

### 7.1 ApprovalRequest（审批请求）

```text
ApprovalRequest
- approval_request_id: UUIDv7
- memory_id: MemoryId
- memory_type: MemoryType
- memory_source: MemorySource
- confidence_value: float
- content_summary: string (1..500)
- sensitive_scan_result: SensitiveScanResult
- approval_requirement: ApprovalRequirement
- requester_id: EntityId
- approver_id: EntityId?
- approval_level: "HUMAN_REQUIRED" | "AUTO_WITH_NOTIFICATION" | "AUTO_APPROVED"
- state: ApprovalState
- decision_result: "APPROVED" | "REJECTED" | "CANCELLED"?
- decision_reason: string?
- decided_at: Timestamp?
- decided_by: EntityId?
- expires_at: Timestamp
- created_at: Timestamp
- notified_at: Timestamp?
- reminded_at: Timestamp[]?
- escalated_at: Timestamp?
- trace_id: TraceId
```

### 7.2 ApprovalState（审批状态）

```text
ApprovalState = PENDING | APPROVED | REJECTED | EXPIRED | CANCELLED
```

状态机：
```
PENDING
  ├──> [审批通过] ──> APPROVED
  ├──> [审批拒绝] ──> REJECTED
  ├──> [超时] ──> EXPIRED
  └──> [取消] ──> CANCELLED

APPROVED ──> [记忆被撤销] ──> [历史状态保留]
REJECTED ──> [无后续状态]
EXPIRED ──> [无后续状态]
CANCELLED ──> [无后续状态]
```

### 7.3 ConsentRecord（同意记录）

```text
ConsentRecord
- consent_id: UUIDv7
- memory_id: MemoryId
- user_id: EntityId
- consent_type: ConsentType
- consent_scope: ConsentScope
- granted_at: Timestamp
- expires_at: Timestamp?
- revoked_at: Timestamp?
- revoked_by: EntityId?
- revocation_reason: string?
```

```text
ConsentType = ONE_TIME | SESSION | PERMANENT

ConsentScope = SINGLE_MEMORY | MEMORY_TYPE | SOURCE_TYPE | ALL
```

---

## 8. 不变量与约束

### 8.1 审批不变量

1. 所有记忆写入必须经过审批必要性评估，不得绕过
2. WORKING 记忆类型可豁免审批，其他类型必须评估
3. USER_EXPLICIT 来源且 confidence >= 0.9 可自动审批
4. AGENT_INFERRED 来源且 confidence < 0.6 必须人工审批
5. 敏感信息扫描发现密码/密钥时必须进入待审批状态

### 8.2 决策优先级不变量

1. Policy Gateway 的 DENY 决策优先于 MEM 的 APPROVED
2. 审批人只能审批自己有权限范围内的记忆
3. 拒绝的记忆不写入存储，但审计记录保留
4. 审批超时必须执行组织配置的兜底策略，不得静默放行

### 8.3 撤销不变量

1. 撤销操作立即生效，记忆从新检索中排除
2. 软删除后 30 天物理删除，可配置
3. 撤销事件必须审计记录，包含撤销原因
4. 敏感信息映射必须在撤销时清除

---

## 9. 异常处理

| 异常场景 | 处理策略 |
|----------|----------|
| 审批服务不可用 | fail-closed：拒绝写入，记录错误 |
| 审批人不可达 | 触发升级通知，执行超时兜底策略 |
| 敏感信息扫描超时 | 保守处理：标记为敏感，进入待审批 |
| 审批决策冲突 | 以首次决策为准，后续忽略 |
| 撤销时记忆已被使用 | 软删除优先，立即从新检索排除 |
| 并发写入同一记忆 | 冲突检测，拒绝后者 |

---

## 10. 安全与合规

### 10.1 权限模型

| 权限 | 主体 | 描述 |
|------|------|------|
| memory:write | Owner、Agent | 申请写入记忆 |
| memory:approve | Owner、Admin、Delegated | 审批记忆写入 |
| memory:delete | Owner、Admin | 撤销/删除记忆 |

### 10.2 合规要求

| 要求 | 实现方式 |
|------|----------|
| GDPR 同意可撤回 | 撤销机制立即生效，30 天物理删除 |
| 审计保留 | 不可变审计日志，保留 180 天 |
| 数据最小化 | 仅存储审批必需的元数据 |
| 同意记录 | 记录同意类型、有效期、撤回时间 |

---

## 11. 验收标准

| 编号 | 验收标准 | 验证方法 |
|------|----------|----------|
| AC01 | 记忆写入前必须经过审批评估，不能绕过 | 绕过测试 |
| AC02 | USER_EXPLICIT 且 confidence >= 0.9 可自动审批 | 自动审批测试 |
| AC03 | AGENT_INFERRED 且 confidence < 0.6 必须人工审批 | 人工审批测试 |
| AC04 | 敏感信息扫描发现密码/密钥时进入待审批 | 敏感扫描测试 |
| AC05 | 审批人只能审批自己有权限的范围内记忆 | 权限隔离测试 |
| AC06 | 拒绝的记忆不写入存储，但审计记录保留 | 拒绝处理测试 |
| AC07 | 撤销操作立即生效，记忆从新检索中排除 | 撤销测试 |
| AC08 | 审批超时执行组织配置的兜底策略 | 超时测试 |
| AC09 | 所有审批操作生成不可变审计事件 | 审计完整性测试 |
| AC10 | Policy Gateway 的 DENY 优先于 MEM 的 APPROVED | 策略优先级测试 |
| AC11 | 敏感内容与脱敏内容分离存储 | 隐私隔离测试 |
| AC12 | 支持一次性、会话级、永久三种同意粒度 | 同意粒度测试 |
| AC13 | 审批状态可序列化，支持会话恢复 | 状态恢复测试 |

---

## 12. 依赖与接口

### 12.1 前置依赖

| 依赖 | 接口 | 使用方式 |
|------|------|----------|
| REQ-MEM-001 | Memory Schema | 复用 Memory、MemoryContent、ConfidenceScore |
| REQ-SEC-003 | Policy Gateway | 复用决策框架、风险评估 |
| REQ-SEC-002 | RBAC | 权限校验 |
| REQ-RT-001 | 核心实体 | 复用 EntityId、TaskId、TraceId |

### 12.2 下游接口

| 下游 | 接口 | 描述 |
|------|------|------|
| 记忆存储 | write(Memory) | 审批通过后写入 |
| 检索索引 | index(Memory) / remove(memory_id) | 索引/清除记忆 |
| 审计系统 | log(AuditEvent) | 写入审计事件 |
| 通知系统 | notify(Notification) | 发送审批通知 |

---

## 13. 性能、成本与可观测性

### 13.1 性能目标（推断，需基线测试）

| 操作 | 目标延迟 |
|------|----------|
| 敏感信息扫描 | p99 < 50ms |
| 审批必要性评估 | p99 < 20ms |
| 自动审批写入 | p99 < 100ms |
| 审批状态查询 | p99 < 30ms |
| 撤销处理 | p99 < 200ms |

### 13.2 关键指标

| 指标 | 定义 | 目标 | 告警阈值 |
|------|------|------|----------|
| memory_approval_pending_count | 待审批数量 | - | > 100 |
| memory_approval_latency_p95 | 审批完成时间 p95 | < 30 分钟 | > 1 小时 |
| memory_approval_auto_rate | 自动审批比例 | > 80% | < 60% |
| memory_approval_reject_rate | 审批拒绝比例 | < 10% | > 20% |
| memory_approval_timeout_rate | 审批超时比例 | < 5% | > 10% |

---

## 14. MVP 范围与后续扩展

### 14.1 MVP 包含

- 基础审批流程：触发→评估→审批→生效→审计
- 三级同意粒度：一次性/会话级/永久
- 敏感信息扫描：基础正则 + NER
- 撤销机制：软删除 + 索引清理

### 14.2 后续演进候选

| 演进方向 | 触发条件 | 优先级 |
|----------|----------|--------|
| 智能分类器审批 | 自动审批率低于目标 | P1 |
| 批量审批 | 待审批积压 > 阈值 | P2 |
| 审批委托规则 | 组织规模扩大 | P2 |

---

## 15. 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1-designed | 2026-10-04 | 基于 OpenAI、DeepSeek、Claude Code、Qoder、SP-Mem、Consent Memory 等行业标杆完成详细设计；定义审批触发条件、六步流程、三级同意粒度、敏感信息扫描、撤销机制、Policy Gateway 集成、异常处理、验收标准；待跨模块评审与冻结 |
