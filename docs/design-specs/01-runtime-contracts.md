# 运行时基础契约设计规范

> 优先级：P0 - 阻塞全部实现与回放  
> 状态：部分完成（REQ-RT-001/002/003/004/005/006 已完成详细设计，整体待冻结）  
> 依赖：无  
> 阻塞：所有后续模块

## 一、设计目标

建立平台所有模块共享的运行时契约，确保状态、事件、权限、证据和版本使用统一坐标系。

### 核心问题

当前所有模块尚未对齐以下概念：

- 什么是一次 Action？
- 什么是一个 Worker？
- 什么是一个 Workflow？
- 任务状态如何表示和迁移？
- 如何关联用户、项目、仓库、模型、策略和成本？
- 如何保证事件不丢失、不重复、可回放？
- 如何在进程重启后恢复任务？

如果这些模型不统一，后续的 Worker、审计、恢复、评估和 UI 会各自形成不同的状态坐标系，导致：

- 无法追踪某次修改由谁、在什么任务中、经过什么授权产生
- 无法回放任务执行过程
- 无法从中断点恢复
- 无法统计成本和质量
- 无法评估模型、Prompt 或工具变化的影响

## 二、设计范围

### 必须定义的核心实体

#### 1. AgentTask

| 字段 | 类型 | 说明 |
|------|------|------|
| `task_id` | UUID | 任务唯一标识 |
| `organization_id` | UUID | 所属组织 |
| `project_id` | UUID | 所属项目 |
| `repository_id` | UUID | 目标仓库 |
| `creator_id` | UUID | 创建者 |
| `created_at` | Timestamp | 创建时间 |
| `status` | TaskStatus | 当前状态 |
| `risk_level` | RiskLevel | 风险等级 |
| `source_type` | SourceType | 来源类型（Issue、自然语言、PR 评审） |
| `source_reference` | String | 来源引用（Issue URL、PR 编号） |
| `workflow_id` | String | 使用的 Workflow 模板 |
| `budget` | Budget | Token、时间、成本预算 |
| `metadata` | JSON | 扩展元数据 |

#### 2. TaskStatus 状态机

```text
CREATED
  ↓
AUTHORIZING         # 权限校验
  ↓
PLANNING            # 生成计划
  ↓
WAITING_APPROVAL    # 等待人工确认计划
  ↓
PREPARING_WORKSPACE # 创建工作区和分支
  ↓
EXECUTING           # Worker 执行中
  ↓
VALIDATING          # 测试和质量检查
  ↓
CREATING_PR         # 生成 Pull Request
  ↓
WAITING_REVIEW      # 等待代码评审
  ↓
COMPLETED           # 完成

任意状态可转向：
  → PAUSED          # 暂停
  → CANCELLED       # 取消
  → FAILED          # 失败
```

#### 3. Action

每个 Agent 或 Worker 的一次工具调用。

| 字段 | 类型 | 说明 |
|------|------|------|
| `action_id` | UUID | 唯一标识 |
| `task_id` | UUID | 所属任务 |
| `workflow_id` | UUID | 所属 Workflow 实例 |
| `worker_id` | String | 发起的 Worker 类型 |
| `parent_step_id` | UUID? | 父步骤 ID（DAG 依赖） |
| `type` | ActionType | READ / ANALYZE / WRITE / EXECUTE / DELEGATE / REQUEST_APPROVAL / REPORT |
| `tool_name` | String | 工具名称 |
| `arguments` | JSON | 工具参数 |
| `target_resources` | Array<String> | 目标资源（文件路径、分支等） |
| `source_revision` | String | 代码版本（Git commit） |
| `expected_observation` | String | 预期结果 |
| `risk_level` | RiskLevel | 风险等级 |
| `requires_approval` | Boolean | 是否需要人工审批 |
| `budget_cost` | BudgetCost | Token、时间消耗预估 |
| `idempotency_key` | String | 幂等键（防重复执行） |
| `proposed_at` | Timestamp | 提议时间 |
| `authorized_at` | Timestamp? | 授权时间 |
| `executed_at` | Timestamp? | 执行时间 |
| `completed_at` | Timestamp? | 完成时间 |
| `status` | ActionStatus | PROPOSED / AUTHORIZED / REJECTED / EXECUTING / SUCCEEDED / FAILED |

#### 4. PolicyDecision

每次 Action 的策略判断结果。

| 字段 | 类型 | 说明 |
|------|------|------|
| `decision_id` | UUID | 唯一标识 |
| `action_id` | UUID | 关联的 Action |
| `policy_version` | String | 策略版本 |
| `decision` | DecisionType | ALLOW / DENY / REQUIRE_APPROVAL |
| `reason` | String | 判断理由 |
| `matched_rules` | Array<String> | 命中的规则 ID |
| `required_approver_role` | String? | 需要的审批角色 |
| `decided_at` | Timestamp | 判断时间 |

#### 5. Artifact

Worker 之间传递的结构化产物。

| 字段 | 类型 | 说明 |
|------|------|------|
| `artifact_id` | UUID | 唯一标识 |
| `task_id` | UUID | 所属任务 |
| `worker_id` | String | 生产者 Worker |
| `type` | ArtifactType | PLAN / CODE_CHANGES / TEST_RESULTS / DIFF / REVIEW_FINDINGS |
| `source_revision` | String | 基于的代码版本 |
| `content` | JSON | 结构化内容 |
| `storage_url` | String? | 大型产物存储位置 |
| `created_at` | Timestamp | 创建时间 |
| `metadata` | JSON | 扩展元数据 |

#### 6. Evidence

任务执行的可验证证据。

| 字段 | 类型 | 说明 |
|------|------|------|
| `evidence_id` | UUID | 唯一标识 |
| `task_id` | UUID | 所属任务 |
| `type` | EvidenceType | TEST_PASSED / SCAN_CLEAN / REVIEW_APPROVED / APPROVAL_GRANTED |
| `source` | String | 证据来源（工具名、Worker ID） |
| `artifact_id` | UUID? | 关联产物 |
| `content` | JSON | 证据内容 |
| `verified_at` | Timestamp | 验证时间 |
| `verifier` | String | 验证者（系统或用户 ID） |

#### 7. Trace

跨模块追踪标识。

| 字段 | 类型 | 说明 |
|------|------|------|
| `trace_id` | UUID | 全局 Trace ID |
| `task_id` | UUID | 任务 ID |
| `workflow_id` | UUID? | Workflow 实例 ID |
| `worker_id` | String? | Worker ID |
| `action_id` | UUID? | Action ID |
| `tool_call_id` | UUID? | 工具调用 ID |
| `model_request_id` | UUID? | 模型请求 ID |
| `parent_span_id` | UUID? | 父 Span ID |
| `span_id` | UUID | 当前 Span ID |

### 事件模型

所有状态变化必须写入不可变事件流。

#### 事件基础结构

```json
{
  "event_id": "uuid",
  "event_type": "WorkflowStarted | ActionProposed | ToolExecuted | ...",
  "event_version": "v1",
  "task_id": "uuid",
  "trace_id": "uuid",
  "actor": {
    "type": "user | worker | system",
    "id": "uuid or worker_name"
  },
  "timestamp": "ISO8601",
  "payload": { ... },
  "metadata": {
    "idempotency_key": "string",
    "causation_id": "uuid",
    "correlation_id": "uuid"
  }
}
```

#### 必需事件类型

- `TaskCreated`
- `TaskAuthorized`
- `WorkflowStarted`
- `StepReady`
- `WorkerStarted`
- `ActionProposed`
- `ActionAuthorized`
- `ActionRejected`
- `ToolStarted`
- `ToolObserved`
- `EvidenceProduced`
- `ApprovalRequested`
- `ApprovalResolved`
- `WorkerCompleted`
- `WorkerFailed`
- `RetryScheduled`
- `ContextCondensed`
- `WorkflowPaused`
- `WorkflowResumed`
- `WorkflowCompleted`
- `WorkflowFailed`
- `WorkflowCancelled`

## 三、设计约束

### 1. 不可变事件

- 事件只追加，不覆盖、不删除
- 任务当前状态由事件投影生成
- 事件包含版本号、时间戳和幂等键
- 支持从事件历史重放和恢复

### 2. 幂等保证

- 每个 Action 拥有唯一 `idempotency_key`
- 重试前检查是否已执行
- 写操作必须先检查工作区状态
- 相同 Action 不得重复产生不可逆副作用

### 3. 版本兼容

- 事件 Schema 包含版本号
- 新版本必须能读取旧版本事件
- 提供事件迁移工具
- 版本变更必须记录和审计

### 4. 引用完整性

- 所有 `task_id`、`worker_id`、`action_id`、`artifact_id` 必须可追溯
- Trace 必须能关联到具体任务、用户、策略版本
- 删除任务时，事件和审计日志不能级联删除

## 四、交付物清单

### Phase 1: 数据模型定义

- [ ] 完整 Schema（SQL DDL 或 ORM 模型）
- [ ] 状态迁移表和约束
- [ ] 枚举类型定义
- [ ] 索引策略
- [ ] 数据留存策略

### Phase 2: 事件系统

- [x] 事件 Schema（JSON Schema 语义，具体承载待冻结）
- [x] 事件版本策略（`REQ-RT-003 v0.1-designed`）
- [ ] 事件存储实现（PostgreSQL / Kafka / EventStore）
- [ ] 事件投影器（从事件重建状态）
- [ ] 幂等处理器

### Phase 3: 检查点与恢复

- [x] Checkpoint Schema 与恢复语义，详见 `REQ-RT-005`
- [x] 检查点保存前置条件、完整性校验和事件绑定，详见 `REQ-RT-005`
- [ ] 失败场景下的保存时机、保留和清理策略，详见 `REQ-REL-004`
- [x] 恢复协议（从检查点 + 事件重放），详见 `REQ-RT-005`
- [ ] 失败分类下的恢复决策与补偿，详见 `REQ-REL-005`、`REQ-REL-007`
- [ ] 恢复测试用例

### Phase 4: 版本与迁移

- [ ] Schema 版本管理
- [ ] 向后兼容测试
- [ ] 迁移脚本
- [ ] 迁移回滚方案

### Phase 5: 审计与追踪

- [ ] Trace ID 传播规则
- [ ] 审计日志 Schema
- [ ] 审计日志与事件日志分离
- [ ] 查询 API
- [ ] 数据脱敏规则

## 五、验收标准

### 功能验收

- [ ] 创建任务后能生成完整事件链
- [ ] 任务暂停后能从最后检查点恢复
- [ ] 相同 Action 重试时不会重复执行
- [ ] 能从事件历史回放任务执行过程
- [ ] 能查询某个文件修改来自哪个任务、哪个 Action、由谁授权
- [ ] Worker 崩溃后能从检查点继续，而不是从头执行
- [ ] 能统计每个任务的 Token、成本、时间和工具调用次数

### 性能验收

- [ ] 单任务事件写入延迟 < 100ms（p95）
- [ ] 检查点恢复时间 < 5s（p95）
- [ ] 支持 1000 并发任务
- [ ] 事件存储支持至少 1 年数据量

### 安全验收

- [ ] 事件不能被篡改或删除
- [ ] 审计日志与普通业务日志物理隔离
- [ ] 只有授权用户能查询敏感任务事件
- [ ] 事件中的敏感字段已脱敏

## 六、风险与依赖

### 技术风险

- 事件存储选型影响性能和成本
- 检查点过大影响恢复速度
- 高并发场景下幂等键冲突

### 组织依赖

- 需要明确审计日志保留策略
- 需要明确数据驻留要求
- 需要与安全团队确认脱敏规则

### 后续依赖模块

本模块一旦冻结，以下模块都必须遵循：

- Worker 执行引擎
- Policy Gateway
- 沙箱执行器
- 评估平台
- 可观测性
- UI 和 API

## 七、参考资料

- Event Sourcing Pattern (Martin Fowler)
- CQRS and Event Sourcing
- OpenTelemetry Trace Specification
- Temporal Workflow State Management
- LangGraph Checkpointing

## 八、下一步行动

1. 召集架构评审会议
2. 确定事件存储技术栈
3. 编写 Schema 初稿
4. 实现事件写入和投影 PoC
5. 验证恢复性能
6. 冻结 v1 契约并发布
