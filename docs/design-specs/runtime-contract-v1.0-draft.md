# Runtime Contract v1.0 - 统一设计基线汇总

> **文档版本**: v1.0-draft  
> **汇总日期**: 2026-10-11  
> **源文档**: REQ-RT-001 至 REQ-RT-008 的 8 个专项设计  
> **当前状态**: 待跨模块评审与冻结  
> **适用范围**: AI Agent 平台的核心运行时契约、事件事实源和状态投影基线

---

## 📋 目录

1. [总体概述](#总体概述)
2. [核心实体模型（REQ-RT-001）](#核心实体模型)
3. [状态机与迁移约束（REQ-RT-002）](#状态机与迁移约束)
4. [事件 Schema 与版本策略（REQ-RT-003）](#事件-schema-与版本策略)
5. [状态投影与一致性规则（REQ-RT-004）](#状态投影与一致性规则)
6. [Checkpoint Protocol（REQ-RT-005）](#checkpoint-protocol)
7. [Trace 传播与审计关联（REQ-RT-006）](#trace-传播与审计关联)
8. [Idempotency Key 与副作用边界（REQ-RT-007）](#idempotency-key-与副作用边界)
9. [事件查询、留存与权限（REQ-RT-008）](#事件查询留存与权限)
10. [统一验收标准](#统一验收标准)
11. [跨模块接口约束](#跨模块接口约束)
12. [冻结条件与后续步骤](#冻结条件与后续步骤)

---

## 总体概述

### 设计愿景

Runtime Contract v1.0 建立一套**统一的、不可变的、完全可追踪**的运行时数据契约，使一次 Agent 研发任务能够在以下层面保持一致性和可恢复性：

```
业务意图 (AgentTask)
  └─ 执行实例 (Workflow)
      └─ 职责节点 (Worker)
          └─ 单次动作 (Action)
              └─ 结构化产物 (Artifact)
              └─ 可验证证据 (Evidence)
                  └─ 跨系统观测关联 (TraceContext)
```

### 核心设计原则

| 原则 | 说明 |
|------|------|
| **事实优先** | 事件是不可变的事实来源；投影是查询视图；状态机消费事实输出控制决策 |
| **分层职责** | 每个实体有明确职责边界；Task ≠ Workflow ≠ Worker ≠ Action |
| **版本可追踪** | 代码版本（`source_revision`）、配置版本、Schema 版本都必须明确 |
| **不可复用 ID** | 每个执行实例有唯一、不可复用的标识；重试产生新 ID，不覆盖旧历史 |
| **权限不向下继承** | Worker 的能力声明 ≠ 最终授权；Action 不能通过能力扩大权限 |
| **可恢复一致边界** | 暂停/故障后恢复必须回到已验证一致的边界 |

---

## 核心实体模型

### REQ-RT-001 核心实体模型（设计版本：v0.2-frozen）

#### 实体职责梳理

| 实体 | 职责 | 生命周期 | 父级 |
|------|------|---------|------|
| **AgentTask** | 用户研发意图和完整交付边界 | 创建 → 执行 → 完成/失败 | 组织/项目/仓库 |
| **Workflow** | 一次 Task 的具体执行实例 | 创建 → 运行 → 完成/失败 | Task |
| **Worker** | Workflow 中一个职责节点的执行实例（可重试） | 创建 → 运行 → 完成/失败 | Workflow（按 step_id 和 attempt 区分） |
| **Action** | Worker 提议的一次结构化动作（读/写/执行） | 提议 → 授权 → 执行 → 成功/失败 | Worker |
| **Artifact** | 不可变的结构化产物（计划、代码、测试结果等） | 生产后不可修改 | Worker（生产者） |
| **Evidence** | 经过验证的质量证据（测试通过、审查批准等） | 不可变，可撤销或过期 | Worker 或 Action |

#### 共享坐标（必须统一）

```typescript
// 标识类型
- TaskId: UUIDv7
- WorkflowId: UUIDv7
- WorkerId: UUIDv7（per attempt）
- ActionId: UUIDv7
- ArtifactId: UUIDv7
- EvidenceId: UUIDv7
- TraceId: 32位十六进制（兼容 OpenTelemetry）
- SpanId: 16位十六进制

// 版本坐标
- schema_version: "runtime.task.v1"
- workflow_template_version: 具体版本（创建后不可变）
- agent_profile_version: 具体版本（创建后不可变）
- toolset_version: 具体版本（创建后不可变）
- source_revision: Git commit SHA（产物基于的代码版本，不可变）
- base_revision: Git commit SHA（Task 开始时的基线，不可变）
- working_revision: 当前工作版本（查询投影，可更新）

// 范围坐标
- organization_id: EntityId
- project_id: EntityId
- repository_id: EntityId
- creator_id: EntityId
```

#### 核心不变量

1. **不可变性**：Artifact 和 Evidence 创建后不可修改；内容变化→新 ID
2. **身份不复用**：每个 attempt 的 Worker 有新 `worker_id`；旧 Worker 历史不被覆盖
3. **版本锁定**：Workflow 的模板版本、Agent Profile 版本在运行期不改变
4. **权限边界**：Worker 的 `allowed_resources` 不能超出 Task/Workflow 范围
5. **来源验证**：Artifact/Evidence 必须绑定 `source_revision`
6. **引用完整**：跨实体引用必须能逆向校验归属关系

---

## 状态机与迁移约束

### REQ-RT-002 状态机与迁移约束（设计版本：v0.1-frozen）

#### Task 状态机

```
CREATED → AUTHORIZING → PLANNING → [WAITING_APPROVAL] → PREPARING_WORKSPACE 
  → EXECUTING → VALIDATING → [EXECUTING/VALIDATING cycle on fix] 
  → CREATING_PR → WAITING_REVIEW → COMPLETED

并行控制状态：
- PAUSED（可从任何可暂停状态进入）
- CANCELLED（可从任何非终态进入）
- FAILED（当前运行无法继续）
```

| 状态 | 是否允许提议新 Action | 含义 |
|------|:---:|------|
| CREATED | ❌ | Task 已创建，尚未授权 |
| AUTHORIZING | ❌ | 身份、项目、预算授权中 |
| PLANNING | ⚠️ | 计划生成中（只允许计划相关 Action） |
| WAITING_APPROVAL | ❌ | 计划或高风险动作等待审批 |
| PREPARING_WORKSPACE | ⚠️ | 准备工作区（只允许环境搭建 Action） |
| EXECUTING | ✅ | 按计划执行（受 Policy Gateway 约束） |
| VALIDATING | ⚠️ | 测试验证中（只允许验证 Action） |
| CREATING_PR | ⚠️ | PR 创建中（只允许交付 Action） |
| WAITING_REVIEW | ❌ | PR 已生成，等待人工评审 |
| COMPLETED | ❌ | 所有完成条件满足 |
| PAUSED | ❌ | 暂停状态，不产生新业务 Action |
| CANCELLED | ❌ | 取消状态，仅允许清理动作 |
| FAILED | ❌ | 失败状态，不继续业务执行 |

#### Workflow 状态机

```
CREATED → READY → RUNNING → [WAITING_APPROVAL] → [RUNNING] 
  → COMPLETED / FAILED / CANCELLED
```

| 状态 | 是否允许新 Worker 进入 RUNNING | 含义 |
|------|:---:|------|
| CREATED | ❌ | 资源未完成准备 |
| READY | ❌ | 已冻结，待调度 |
| RUNNING | ✅ | 至少一个 Worker 运行中 |
| WAITING_APPROVAL | ❌ | 等待审批 |
| COMPLETED | ❌ | 所有必需节点完成 |
| FAILED | ❌ | 无法继续 |
| CANCELLED | ❌ | 已取消 |

#### Worker 状态机

```
CREATED → READY → RUNNING → [WAITING_APPROVAL] → [RUNNING] 
  → COMPLETED / FAILED / CANCELLED
```

| 状态 | 是否允许新 Action | 含义 |
|------|:---:|------|
| CREATED | ❌ | 初始化中 |
| READY | ❌ | 已就绪，待启动 |
| RUNNING | ✅ | 执行中 |
| WAITING_APPROVAL | ❌ | 高风险 Action 等待审批 |
| COMPLETED | ❌ | 输出满足契约 |
| FAILED | ❌ | 无法恢复继续 |
| CANCELLED | ❌ | 已取消 |

#### Action 状态机

```
PROPOSED → AUTHORIZED → EXECUTING → SUCCEEDED / FAILED
         ↘ REJECTED
         ↘ WAITING_APPROVAL → AUTHORIZED
         ↘ CANCELLED
```

**关键约束**：

1. `Action=SUCCEEDED` ≠ `Worker=COMPLETED`
2. `Worker=COMPLETED` ≠ `Workflow=COMPLETED`
3. `Workflow=COMPLETED` ≠ `Task=COMPLETED`
4. Task 完成需满足：所有必需 Artifact/Evidence + 测试通过 + PR 可审查

#### Task 完成条件（最低条件）

1. 必需 Workflow 节点已完成
2. 代码变更对应 `source_revision` 可验证
3. 必需测试/质量检查已生成 Evidence
4. 所需审批已完成
5. Policy Gateway 无拒绝
6. PR 或最终交付 Artifact 已生成
7. 无未处理的阻塞性问题
8. 预算/时间/范围未越界
9. Evidence 未被撤销或过期

---

## 事件 Schema 与版本策略

### REQ-RT-003 事件 Schema（设计版本：v0.1-frozen）

#### Event Envelope（通用信封）

```typescript
EventEnvelope {
  schema_version: "runtime.event-envelope.v1"
  event_id: UUIDv7                    // 不可重复
  event_type: string                  // 如 "ActionProposed"
  event_type_version: string          // 当前事件载荷版本
  event_category: enum                // DOMAIN / LIFECYCLE / ACTION / CONTROL / OBSERVATION / AUDIT / SYSTEM
  
  // 业务标识
  task_id: TaskId (required)
  workflow_id: WorkflowId
  worker_id: WorkerId
  action_id: ActionId
  step_id: string
  attempt: integer >= 1
  
  // 追踪关联
  trace_id: TraceId (required)
  span_id: SpanId
  parent_span_id: SpanId
  causation: CausationRef
  correlation_id: string
  
  // 版本与来源
  source_revision: string
  base_revision: string
  working_revision: string
  policy_decision_id: EntityId
  idempotency_key: string
  
  // 元数据
  producer: ProducerRef               // USER / WORKER / TOOL / SYSTEM / EXTERNAL_PROVIDER
  actor: ActorRef
  occurred_at: Timestamp              // 事实发生时间
  recorded_at: Timestamp              // 事实写入时间
  sequence: integer (by partition)    // 单调递增，partition 内唯一
  
  // 安全与分类
  data_classification: DataSensitivity
  content_refs: ContentRef[]
  redaction: RedactionInfo
  payload_schema: string
  payload: JsonObject
  extensions: SafeMetadata
}
```

#### 事件分类

| 类别 | 用途 | 示例 |
|------|------|------|
| **DOMAIN** | 业务事实 | TaskCreated、ArtifactProduced、EvidenceProduced |
| **LIFECYCLE** | 生命周期 | WorkerStarted、WorkflowCompleted、ActionSucceeded |
| **ACTION** | 动作流程 | ActionProposed、ActionAuthorized、ToolStarted |
| **CONTROL** | 人工/系统控制 | WorkflowPaused、ApprovalRequested、KillSwitchActivated |
| **OBSERVATION** | 执行结果 | ToolObserved、TestFinished、ScanFinished |
| **AUDIT** | 安全审计 | PolicyEvaluated、CredentialIssued、AccessDenied |
| **SYSTEM** | 基础设施 | CheckpointCreated、EventMigrated、ProjectionRebuilt |

#### MVP 事件目录（核心事件）

**Task 和 Workflow**：
- `TaskCreated` - Task 创建
- `TaskAuthorized` - 授权通过
- `WorkflowStarted` - Workflow 启动
- `WorkflowPaused` - Workflow 暂停
- `WorkflowCompleted` - Workflow 完成
- `WorkflowFailed` - Workflow 失败

**Worker 和 Action**：
- `WorkerStarted` - Worker 启动
- `ActionProposed` - Action 提议
- `PolicyEvaluated` - 策略评估
- `ActionAuthorized` - Action 授权
- `ApprovalRequested` - 等待审批
- `ActionRejected` - Action 拒绝
- `ToolStarted` - 工具启动
- `ToolObserved` - 工具完成
- `ActionSucceeded` - Action 成功
- `ActionFailed` - Action 失败

**Artifact 和 Evidence**：
- `ArtifactProduced` - Artifact 生成
- `EvidenceProduced` - Evidence 生成
- `EvidenceRevoked` - Evidence 撤销

**系统事件**：
- `CheckpointCreated` - Checkpoint 保存
- `EventMigrated` - 事件版本迁移
- `KillSwitchActivated` - Kill Switch 触发

#### 版本兼容规则

| 变更类型 | 升级方案 |
|---------|---------|
| 新增可选字段 | 小版本升级 |
| 新增枚举值 | 需消费者兼容评审 |
| 修改字段含义/类型 | **主版本升级** |
| 删除字段 | 弃用期 + **主版本升级** |
| 修改 ID、序列或幂等语义 | **全链路评审** |

#### 顺序与一致性

- `sequence` 是同一 `partition_key` 内的权威序列，单调递增、唯一
- `occurred_at` 用于显示和跨系统近似排序，允许时钟偏差
- 不允许用消息到达顺序替代事实 `sequence`
- 事件乱序到达时，消费者缓冲或进入待处理状态，不能静默重排

---

## 状态投影与一致性规则

### REQ-RT-004 状态投影（设计版本：v0.1-frozen）

#### 投影职责边界

```
事实事件 (Event Store)
  ↓ (不可反向写入)
投影器 (Dispatcher → Handler → Transaction)
  ↓
查询投影 (Task/Workflow/Worker/Action Projection)
  ↓ (只读)
授权查询 API / UI / Audit
```

**禁止路径**：
- ❌ API 直接修改投影
- ❌ 投影写回事实事件
- ❌ 查询缓存作为业务事实

#### 投影分区与一致性

MVP 采用分区键：`organization_id / task_id / workflow_id`

- 同一 Workflow 的所有事件按 `sequence` 有序应用
- 并行 Worker 的局部事件通过 causation 和父级引用汇聚
- 投影不能由任意子投影直接扩大父级权限

#### 四类查询投影

| 投影 | 职责 | 关键字段 |
|------|------|----------|
| **TaskProjection** | Task 当前状态视图 | task_id, status, current_workflow_id, artifact_count, evidence_count, last_sequence |
| **WorkflowProjection** | Workflow 当前状态视图 | workflow_id, status, runnable_worker_count, running_worker_count, failed_worker_count, last_sequence |
| **WorkerProjection** | Worker 当前状态视图 | worker_id, attempt, status, active_action_count, output_artifact_ids, last_sequence |
| **ActionProjection** | Action 当前状态视图 | action_id, status, risk_level, policy_decision_id, approval_id, observation_artifact_id, last_sequence |

#### 投影健康状态

```typescript
ProjectionCheckpoint {
  last_applied_sequence: integer
  last_applied_event_id: EventId
  last_applied_event_hash: string
  pending_gap_from: integer?          // 缺口起点
  pending_gap_to: integer?            // 缺口终点
  status: HEALTHY | CATCHING_UP | BLOCKED | REBUILDING | FAILED
  updated_at: Timestamp
}
```

#### 事件应用规则

1. **重复事件**：相同 `event_id` + 哈希一致 → 返回 `DUPLICATE_IGNORED`
2. **下一序列**：`sequence = last_applied_sequence + 1` → 校验→应用→提交
3. **乱序/缺口**：记录缺口，重取补齐，不能静默重排
4. **未知版本**：未知主版本 → 停止分区、保留原事件、告警
5. **冲突**：相同序列、不同内容 → 进入 `BLOCKED` 并告警

#### 投影重建

- **从零重建**：固定事件范围、版本、迁移器，按序应用，保留重建日志
- **增量重建**：校验 Checkpoint 哈希，从下一序列继续
- **修复原则**：重建解决，不直接编辑生产投影

---

## Checkpoint Protocol

### REQ-RT-005 Checkpoint Protocol（设计版本：v0.1-frozen）

#### 设计基本原则

> **Checkpoint 是恢复优化快照，不是新的事实来源。**

- Checkpoint 必须绑定已确认事件序列和事件哈希
- Checkpoint 不能删除或覆盖原始事件
- 恢复时必须校验 Checkpoint 与事件的一致性
- 检查点损坏后应回退到更早边界或从零重建

#### 恢复场景

| 场景 | 处理方式 |
|------|----------|
| Worker 进程崩溃 | 从 Checkpoint 重建状态 + 重放增量事件 |
| 用户暂停后恢复 | 校验权限/版本/预算 → 重新启动 Worker |
| 高风险 Action 审批后执行 | 重新校验所有条件 → 继续或新 attempt |
| Kill Switch 或系统故障 | 保存当前 Checkpoint → 后续恢复同上 |
| 检查点损坏 | 进入 `BLOCKED` 状态 → 人工决策或回退 |
| 长事件历史 | 按需分段、新建 Continue-As-New Workflow 实例 |

#### Checkpoint 必填信息

```typescript
WorkflowCheckpoint {
  workflow_id: WorkflowId (required)
  worker_id: WorkerId?                // 某个特定 Worker 的检查点
  attempt: integer >= 1
  
  // 恢复坐标
  last_applied_event_sequence: integer
  last_applied_event_id: EventId
  last_applied_event_hash: string
  
  // 版本与资产
  workflow_template_version: string
  agent_profile_version: string
  toolset_version: string
  
  // 工作区与权限
  working_revision: string
  workspace_ref: string?              // 工作区路径或 ID
  
  // 业务状态快照
  artifact_refs: ArtifactId[]
  evidence_refs: EvidenceId[]
  pending_approval_ids: ActionId[]
  
  // 恢复边界说明
  recovery_reason: string
  created_at: Timestamp
  expires_at: Timestamp?              // 检查点有效期
  can_skip_to_checkpoint: boolean     // 是否允许直接跳到检查点（不重放增量）
}
```

#### 恢复决策规则

恢复前必须验证：

1. ✅ Checkpoint 序列与最后事件哈希匹配
2. ✅ Workflow 模板版本仍有效
3. ✅ Agent Profile 版本兼容
4. ✅ Toolset 版本支持
5. ✅ 工作区和 `working_revision` 可恢复
6. ✅ 当前 Policy Gateway 允许继续
7. ✅ 预算、时间、并发限制未耗尽
8. ✅ 所依赖 Artifact/Evidence 未撤销或过期

**任一条件不满足 → 进入恢复阻塞或人工处理流程**

---

## Trace 传播与审计关联

### REQ-RT-006 Trace 传播（设计版本：v0.1-frozen）

#### Trace 身份

- **TraceId**：32 位十六进制字符串，兼容 OpenTelemetry W3C Trace Context
- **SpanId**：16 位十六进制字符串，标识 Trace 内的一个操作单元
- 业务 ID（TaskId、WorkflowId 等）与 Trace ID 分离，不能互相替代

#### Span 层级

```
根 Span: Task 执行
  ├─ Span: Workflow 初始化
  │   ├─ Span: Worker 执行
  │   │   ├─ Span: Action 提议
  │   │   ├─ Span: Policy 评估
  │   │   ├─ Span: 工具执行
  │   │   └─ Span: Evidence 验证
  │   └─ Span: Workflow 聚合
  └─ Span: Task 交付
```

#### 跨服务传播

- 仅在经过登记和信任评估的内部服务边界传播 W3C Trace Context
- 模型、外部 API、GitHub 等第三方服务获得 `correlation_id` 但不获得完整 Span ID
- 传播不等于授权或身份认证

#### 审计关联

| 审计关键字 | 绑定关系 |
|-----------|---------|
| actor（谁） | ActorRef（用户 ID 或系统身份） |
| action（做什么） | ActionType（READ/WRITE/EXECUTE 等） |
| resource（在哪个资源） | ResourceRef（文件/分支/PR 等） |
| decision（得到什么结果） | PolicyDecisionId + 结果代码 |
| trace（在哪条链路） | TraceId + SpanId |
| evidence（何时确认） | EvidenceId 或 TimestampVerified |

#### 采样策略

- MVP 默认采样率：**15%**
- 高风险操作（高权限、生产环境）：**100% 采样**
- 审计日志：**永不采样**（100% 记录）
- 诊断 Trace：可调配采样率

#### 保留期

| 数据类型 | 热存储期 | 冷存储期 | 法定保留期 |
|---------|--------|--------|-----------|
| 完整 Trace | 7 天 | 90 天 | 按合规规定 |
| 审计日志 | 30 天 | 180 天 | **不允许删除** |
| 指标聚合 | 无期限 | 无期限 | 无期限 |

---

## Idempotency Key 与副作用边界

### REQ-RT-007 幂等性（设计版本：v0.1-frozen）

#### 逻辑操作身份

每个可能产生外部副作用的 Action 必须有稳定的幂等键：

```typescript
IdempotencyKey {
  format: "{task_id}#{workflow_id}#{worker_id}#{step_id}#{action_type}#{attempt}"
  
  // 示例：
  // "0198b2d2-xxx#0198b2d2-yyy#0198b2d2-zzz#explore-step#WRITE_FILE#1"
}
```

#### 关键规则

1. **去重窗口**：24 小时（可配置）
   - 同一幂等键在窗口内只允许一个有效执行
   - 重复请求返回原结果，不重复执行

2. **重复请求检查**：
   ```
   收到相同幂等键
    → 查询结果缓存
    → 已完成 → 返回原结果 + 400 Conflict（如参数变化）
    → 进行中 → 返回进度或等待
    → 未开始 → 拒绝重复，返回正在处理
   ```

3. **并发领取**：
   - 同一幂等键的多个请求中只有一个被接受
   - 使用分布式锁或数据库唯一约束保证
   - 失败请求进入重试或死信队列

4. **结果未知处理**：
   ```
   Action 开始执行但结果未知
    → 在幂等键过期前，禁止发起新的相同 Action
    → 新建 NEW_ATTEMPT，更新幂等键
    → 调查原 Action 并更新状态
    → 前置条件或后置条件检查（条件写入、结果核验）
   ```

#### 外部副作用保护

| 副作用类型 | 保护机制 |
|-----------|---------|
| **Git 提交** | 基于 commit SHA 查询去重 + 条件推送 |
| **PR 创建** | 基于分支和 diff 哈希查重 + queryBy 检测 |
| **文件写入** | 基于 revision + path 的原子更新 |
| **API 调用** | 使用下游 Idempotency-Key 头传递 |
| **数据库写** | 唯一约束或版本号乐观锁 |

#### 补偿与回滚

- 未完成副作用不能因 Checkpoint 而假装"已完成"
- 需要补偿的操作必须在"成功"之前显式声明补偿策略
- 补偿本身也要幂等且能应对正向操作从未发生的情况

---

## 事件查询、留存与权限

### REQ-RT-008 事件查询与权限（设计版本：v0.1-frozen）

#### 查询接口边界

```
GET /api/v1/events
  ?task_id={TaskId}
  &workflow_id={WorkflowId}
  &event_type={string}
  &occurred_after={timestamp}
  &occurred_before={timestamp}
  &page={int}
  &limit={int}
  &include_payload={boolean}    // 默认 false，脱敏敏感字段
  &access_level={BASIC|AUDIT|ADMIN}
```

#### 权限控制

所有查询必须强制校验：

1. **租户隔离**：`organization_id` 必须与用户组织一致
2. **资源访问**：Project/Repository/Task 级别的访问权限
3. **数据敏感级别**：按角色分级返回不同内容
4. **审计访问**：需要 Audit 角色查看敏感内容

#### 留存政策

| 事件类型 | 热存储（Query） | 冷存储（Archive） | 法定保留 |
|---------|:---:|:---:|:---:|
| 业务事件 | 30 天 | 180 天 | 按行业规定 |
| 审计事件 | 30 天 | 180 天 | **永久** |
| 诊断 Trace | 7 天 | 90 天 | 可删除 |
| Payload 大对象 | ContentRef | ContentRef | 按内容分类 |

#### 敏感字段脱敏

**必须脱敏的字段**：
- API Key、Token、Secret、Private Key
- 环境变量（完整值）
- 模型隐藏思维链
- 未经授权的完整代码片段

**允许保存的字段**：
- 内容哈希、大小、类型
- 脱敏摘要（前 50 字符 + hash）
- ContentRef 和对象存储引用
- 敏感级别标记

#### 合规删除流程

- 用户/组织要求删除→ 生成 GDPR/CCPAssist 删除请求
- 分级审批：基础用户（自助） vs 管理员（需复核）
- 不影响法定审计日志保留
- 删除操作本身进入审计记录

---

## 统一验收标准

### 跨模块契约测试

#### SchemaSchema 契约

- [x] 必填字段缺失时拒绝
- [x] 非法 ID、时间、枚举拒绝
- [x] 跨实体引用不一致时拒绝
- [x] Artifact 内容哈希不一致时拒绝
- [x] Evidence 缺少验证方式时拒绝
- [x] 敏感字段含密钥/Token 时脱敏或拒绝
- [x] 未知 Schema 版本不静默解析

#### 事件应用

- [x] 合法事件按序更新正确投影
- [x] 重复事件只产生一次投影效果
- [x] 序列缺口不推进投影
- [x] 乱序事件补齐后按序应用
- [x] 未知主版本进入隔离

#### 状态机

- [x] 所有合法迁移通过
- [x] 非法迁移被拒绝
- [x] 父子状态一致性约束得到验证
- [x] Action 成功不自动推导 Task 完成

#### 一致性与恢复

- [x] 投影与从零重建结果一致
- [x] Checkpoint 与事件哈希不一致时不直接恢复
- [x] 投影器崩溃后自动恢复
- [x] 权限不向下继承

---

## 跨模块接口约束

所有后续模块必须使用本 Runtime Contract 的以下共享坐标，不能自行创造替代 ID：

| 依赖需求 | 必须使用 | 不得重定义 |
|---------|---------|----------|
| **REQ-RT-002** (状态机) | 本 Schema 的 ID、版本、status_projection | Task/Workflow/Worker/Action 状态主体 |
| **REQ-RT-003** (事件) | 本 Schema 的所有坐标 | TaskId、WorkflowId、sequence 含义 |
| **REQ-RT-004** (投影) | 同上 | 投影分区、一致性语义 |
| **REQ-SEC-002/003** (权限) | organization_id、allowed_tools、target_resources、policy_decision_id | 核心权限坐标 |
| **REQ-REL-001/006** (重试) | action_id、worker_id、attempt、idempotency_key | 重试身份 |
| **REQ-CTX-001** (索引) | source_revision、repository_id | 代码版本追踪 |
| **REQ-OBS-001** (遥测) | trace_id、span_id、actor_ref、resource_ref | 观测关联 |

---

## 冻结条件与后续步骤

### 升级到 v1.0-frozen 的条件

**必须完成**：

1. ✅ REQ-RT-001 ~ REQ-RT-008 设计文档完成
2. ⏳ 与后续模块（SEC、REL、CTX、EVA、OBS）的交叉评审
3. ⏳ Schema 契约测试设计完成
4. ⏳ 关键路径场景（Bug 修复、简单功能）的端到端验证
5. ⏳ 所有核心不变量的故障注入测试
6. ⏳ 数据库、事件存储、投影器的 PoC 实现
7. ⏳ 解决所有跨模块冲突

### 后续阶段规划

| 阶段 | 关键工作 | 时间表 |
|------|---------|-------|
| **评审与冻结** | 跨模块评审投票 | 2026-10-12~13 |
| **实现设计** | 数据库 DDL、API 设计、部署实现 | 2026-10-14~18 |
| **阶段 1.1** | Walking Skeleton（事件存储 + 投影 + 简单 Action 闭环） | 2026-10-21~11-04 |
| **阶段 1.2~1.5** | 核心运行时、安全、工具、Worker 实现 | 2026-11-05~2026-12-30 |

---

## 文档变更记录

| 版本 | 日期 | 变更 |
|------|------|------|
| **v1.0-draft** | 2026-10-11 | 初次汇总：合并 REQ-RT-001~008，统一格式，补充跨模块约束与验收标准 |

---

**下一步行动**：

1. ⏳ 发送本文档给相关模块负责人进行交叉评审
2. ⏳ 收集评审反馈，标记冲突点和待决议事项
3. ⏳ 定时组织评审投票会议（推荐 2026-10-12）
4. ⏳ 投票通过后升级为 v1.0-frozen，进入实现设计阶段

---

**文档维护者**：架构团队  
**维护日期**：2026-10-11  
**下次评审**：2026-10-12 评审会
