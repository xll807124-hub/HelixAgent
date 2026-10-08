# REQ-RT-004 状态投影与一致性规则

> 所属基线：`Runtime Contract v1`（已冻结，2026-10-07）
> 需求编号：`REQ-RT-004`
> 优先级：P0
> 设计版本：`v0.1-frozen`
> 设计状态：已冻结，可作为实现基线（跨模块评审通过，2026-10-07）
> 前置依赖：`REQ-RT-001` 核心实体 Schema、`REQ-RT-002` 状态机与迁移约束、`REQ-RT-003` Event Schema 与版本策略
> 设计范围：事件到查询状态的投影模型、顺序校验、幂等消费、重建、一致性和故障处理
> 不包含：Checkpoint 字节格式、Action 外部副作用幂等、RetryPolicy、数据库 DDL、UI 实现

---

## 1. 需求定义

### 1.1 需求目标

建立统一的状态投影机制，将 `REQ-RT-003` 的不可变事件事实转换为可查询、可分页、可授权读取的 Task、Workflow、Worker、Action 当前视图，同时保证：

- 投影永远不能反向修改或替代事件事实；
- 同一事实流按服务端分配的 `sequence` 有序应用；
- 至少一次投递、重复消费、消费者重启不会产生重复状态效果；
- 乱序、序列缺口、版本不兼容和引用冲突不会被静默吞掉；
- 投影可以从零开始重建，并与在线投影结果进行一致性校验；
- 投影延迟、失败、死信和重建过程可观测、可审计；
- 查询状态只能作为当前视图，不能被当作历史事实、授权依据或副作用完成证明。

### 1.2 必须回答的问题

1. 一个事件如何更新 Task、Workflow、Worker 和 Action 的当前状态？
2. 并行 Worker 的局部事件如何安全汇聚到 Workflow 和 Task？
3. 重复、乱序、缺口、未知事件和历史版本如何处理？
4. 投影器崩溃或投影表损坏后如何恢复？
5. 查询 API 如何避免读到跨组织、跨仓库或未授权敏感内容？
6. 如何判断投影已经追上事实流，且没有悄悄丢失事件？
7. 哪些查询可以使用最终一致的投影，哪些操作必须重新验证事实？

### 1.3 设计价值

| 使用方 | 依赖的投影能力 |
|---|---|
| Web/API | 查询任务当前状态、等待原因、进度和时间线 |
| Coordinator | 判断可调度节点和父级状态 |
| Recovery | 定位最后应用序列、缺口和恢复边界 |
| Audit | 按权限查询事实引用和状态变化摘要 |
| Evaluation | 对在线视图与事件重建结果进行对比 |
| SRE | 监控投影延迟、失败、积压和重建状态 |
| Policy Gateway | 读取上下文状态，但不能仅凭投影替代实时授权 |

---

## 2. 公开方案调研与可借鉴原则

本节只使用公开官方资料确认工程原则，不推断厂商内部实现，也不把公开方案等同于本项目已验证的最优解。

### 2.1 Temporal：事件历史驱动恢复，状态不是独立事实

Temporal 官方文档将 Workflow Event History 定义为持久化的追加式事件序列，用于在 Worker 崩溃后通过回放恢复 Workflow 状态；事件历史还存在数量和大小边界，需要通过 Continue-As-New 等机制控制历史增长。

对本需求的借鉴：

1. 投影状态必须能够由有序事件重新生成。
2. 内存缓存只能是性能优化，不能成为恢复依据。
3. 事件历史增长、分段和归档必须有明确边界。
4. 回放时应区分状态重建与重新执行外部活动，不能因为重建状态而重复真实副作用。

来源：[Temporal Events and Event History](https://docs.temporal.io/workflow-execution/event)、[Temporal Workflow Execution](https://docs.temporal.io/workflow-execution)。

### 2.2 LangGraph：检查点保存运行快照，但仍需要稳定运行身份

LangGraph 官方文档将 Checkpointer 定义为按 `thread_id` 保存图状态快照，用于人工中断、恢复、时间回溯和故障容错；生产环境应使用持久化 Checkpointer。时间回溯会重新执行检查点之后的节点，因此节点和外部副作用必须考虑重复执行。

对本需求的借鉴：

1. 投影查询状态与 Checkpoint 快照应分工，不能混成同一事实源。
2. `workflow_id` 是本项目的稳定运行身份，投影器不得用进程 ID 或消息队列分区替代。
3. 从检查点恢复时必须校验其最后应用事件序列和哈希。
4. 投影回放和业务恢复都必须明确是否会触发外部副作用；状态投影本身禁止触发副作用。

来源：[LangGraph Checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers)、[LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)。

### 2.3 OpenHands：追加式、不可变、类型化事件

OpenHands 官方 SDK 将事件定义为类型化、不可变、追加式对象，并区分 Action 和 Observation。该模式使状态观察、执行结果和控制事件可以被多个消费者独立使用。

对本需求的借鉴：

1. 投影器只消费已提交的类型化事件，不解析自由文本日志。
2. Action 的状态不能仅由 Tool Observation 字段猜测，必须遵循事件目录和状态机规则。
3. 不同投影可以服务 UI、审计、指标和评估，但共享同一事件事实源。

来源：[OpenHands Events](https://docs.openhands.dev/sdk/arch/events)、[OpenHands Agent](https://docs.openhands.dev/sdk/arch/agent)。

### 2.4 本项目的收敛结论

采用：

> **按 Workflow 事实流分区的事件驱动投影 + 事件序列校验 + 消费者幂等 + 可重建查询模型 + 投影健康状态独立记录。**

不采用：

- API 直接更新 `status_projection`；
- 以普通日志或最后一条消息推断当前状态；
- 以消息到达顺序代替事实 `sequence`；
- 用缓存或 Checkpoint 代替事件历史；
- 投影失败后静默跳过事件；
- 通过多数投影结果覆盖事实冲突。

---

## 3. 设计边界与共享坐标

### 3.1 本需求包含

- 投影器、投影分区和投影状态；
- Task、Workflow、Worker、Action 当前视图；
- 状态事件的确定性应用规则；
- 事件序列、重复、乱序、缺口和冲突处理；
- 投影事务、幂等记录和版本校验；
- 从零重建、增量重建和一致性核验；
- 投影延迟、失败、死信和修复边界；
- 查询权限、数据敏感级别和最终一致性提示；
- MVP 验收、回放和故障注入场景。

### 3.2 本需求不包含

| 内容 | 归属需求 |
|---|---|
| 核心实体字段和引用 | `REQ-RT-001` |
| 合法状态集合和状态迁移 | `REQ-RT-002` |
| Event Envelope、事件版本和事实存储 | `REQ-RT-003` |
| Checkpoint 字节格式、保存时机和恢复协议 | `REQ-RT-005`、`REQ-REL-004/005` |
| Trace/Span 传播和 OpenTelemetry 映射 | `REQ-RT-006`、`REQ-OBS-001` |
| Action 和外部副作用幂等 | `REQ-RT-007`、`REQ-REL-006` |
| 资源授权、Policy DSL 和审批矩阵 | `REQ-SEC-002/003` |
| 查询 API 路由和前端页面 | 实现设计阶段 |

### 3.3 共享坐标

投影器必须复用以下坐标，不得创建平行 ID：

- `organization_id`、`project_id`、`repository_id`
- `task_id`、`workflow_id`、`worker_id`、`action_id`
- `step_id`、`attempt`
- `event_id`、`event_type`、`event_type_version`
- `sequence`、`trace_id`、`causation`、`correlation_id`
- `artifact_id`、`evidence_id`
- `source_revision`、`base_revision`、`working_revision`

投影表可以有自己的数据库主键或索引键，但对外关联必须使用上述业务坐标。

### 3.4 事实流分区与序列语义

为避免 `REQ-RT-003` 中“Workflow 主流”和“Worker 局部流”的序列语义产生歧义，本需求规定：

- `partition_key` 的规范格式为 `workflow:{workflow_id}`；MVP 的 Task、Workflow、Worker、Action 当前投影均以该 Workflow 主流作为唯一事实顺序。
- `sequence` 只在同一 `partition_key` 内要求连续、单调递增和唯一；不同 Workflow 之间没有全局顺序要求。
- Worker/Action 事件即使由不同执行进程产生，也必须先进入所属 Workflow 主流，由事实存储分配该主流序列；消费者不得按消息到达顺序或 Worker 本地时钟应用。
- `worker_id`、`step_id` 和 `attempt` 用于区分并行执行实例，不构成第二套可替代事实顺序。
- 若未来引入 Worker 局部优化流，局部流只能作为只读辅助索引；在进入 Task/Workflow/Worker/Action 权威投影前，必须通过 `workflow_id`、因果引用和主流序列校验，不能直接推进父级状态。

### 3.5 父子投影与汇聚规则

Task、Workflow、Worker、Action 投影采用“局部事实应用、父级确定性汇聚”的边界：

1. Action 事件只能直接更新对应 Action 投影及其可追溯的 Worker 活跃计数。
2. Worker 生命周期事件只能直接更新对应 Worker 投影；Workflow 的 Worker 计数和可调度状态由已应用的 Worker 投影集合按固定规则重算。
3. Workflow 生命周期事件只能直接更新对应 Workflow 投影；Task 的当前 Workflow、阶段和完成摘要由 Workflow 投影及必需 Artifact/Evidence 引用汇聚。
4. 汇聚规则必须是确定性的、可重建的，并以同一事实流中已应用的事件为输入；不能由任意子投影直接写入父级状态。
5. 发现父子事件引用不一致、父级尚未存在或汇聚输入缺失时，相关分区进入 `BLOCKED` 或等待补齐，不得用默认状态、最后已知值或多数结果猜测。
6. “计数一致”只表示查询视图一致，不代表满足状态机完成条件；调度、审批、恢复和交付仍需按 `REQ-RT-002` 重新校验事实、策略和证据。

---

## 4. 总体架构

```text
Event Store / Outbox
        |
        v
Projection Dispatcher
        |
        +--> Task/Workflow Projection
        +--> Worker/Action Projection
        +--> Timeline Projection
        +--> Artifact/Evidence Projection
        +--> Audit Summary Projection
        |
        v
Projection Health / Consumer Offset / Dead Letter
        |
        v
Authorized Query API
```

### 4.1 责任分层

- **Event Store**：保存不可变事实，拥有事件顺序和事实哈希的权威性。
- **Projection Dispatcher**：读取已提交事件，按事实流分发，处理重试和积压。
- **Projection Handler**：校验版本、引用和序列，并在一个事务中更新查询模型与消费进度。
- **Projection Health**：记录最后成功序列、缺口、失败、积压、重建和版本状态。
- **Authorized Query API**：在组织、项目、仓库、任务和敏感级别授权后读取投影。
- **Audit/Evaluation Consumers**：独立消费事件或投影，不反向写入业务状态。

### 4.2 事实与投影的单向约束

```text
事实事件 -> 投影状态 -> 授权查询
```

禁止以下路径：

```text
API/Worker -> 直接修改投影状态
投影状态 -> 修改事实事件
查询缓存 -> 作为状态迁移事实
投影器 -> 触发工具、模型、Git、PR 或通知副作用
```

---

## 5. 投影模型

### 5.1 ProjectionCheckpoint

`ProjectionCheckpoint` 是消费者进度记录，不是 `REQ-RT-005` 的业务恢复 Checkpoint。它只回答“某个投影消费者已经安全应用到哪里”。

```text
ProjectionCheckpoint
- schema_version: string = "runtime.projection-checkpoint.v1"
- projection_name: string
- projection_version: string
- partition_key: string
- last_applied_sequence: integer >= 0
- last_applied_event_id: EventId?
- last_applied_event_hash: string?
- pending_gap_from: integer?
- pending_gap_to: integer?
- status: HEALTHY | CATCHING_UP | BLOCKED | REBUILDING | FAILED
- updated_at: Timestamp
- failure_ref: string?
```

约束：

1. `last_applied_sequence` 只能前进，不能回退覆盖。
2. 只有事件和投影更新在同一提交边界成功后，才能推进该值。
3. Checkpoint 记录损坏或哈希不一致时，投影器必须进入 `FAILED` 或 `REBUILDING`，不能继续静默应用。
4. 该对象不包含模型上下文、工具副作用或可直接恢复执行的凭据。

### 5.2 TaskProjection

```text
TaskProjection
- task_id: TaskId
- organization_id: EntityId
- project_id: EntityId
- repository_id: EntityId
- creator_id: EntityId
- current_workflow_id: WorkflowId?
- status: TaskStatus
- status_reason: string?
- risk_level: RiskLevel
- base_revision: string
- working_revision: string?
- current_step_id: string?
- required_approval_count: integer >= 0
- unresolved_failure_count: integer >= 0
- artifact_count: integer >= 0
- evidence_count: integer >= 0
- completion_summary: JsonObject?
- last_event_id: EventId
- last_sequence: integer
- last_event_type: string
- projection_version: string
- created_at: Timestamp
- started_at: Timestamp?
- completed_at: Timestamp?
- updated_at: Timestamp
```

`completion_summary` 只能是查询摘要，不能单独证明 Task 已满足 `REQ-RT-002` 的完成条件。完成或交付命令必须重新读取相关事实、Evidence 和策略结果。

### 5.3 WorkflowProjection

```text
WorkflowProjection
- workflow_id: WorkflowId
- task_id: TaskId
- organization_id: EntityId
- project_id: EntityId
- repository_id: EntityId
- status: WorkflowStatus
- status_reason: string?
- workflow_template_id: string
- workflow_template_version: string
- agent_profile_version: string
- toolset_version: string
- base_revision: string
- working_revision: string?
- runnable_worker_count: integer >= 0
- running_worker_count: integer >= 0
- waiting_approval_count: integer >= 0
- failed_worker_count: integer >= 0
- completed_worker_count: integer >= 0
- required_worker_count: integer >= 0
- active_attempt_count: integer >= 0
- last_event_id: EventId
- last_sequence: integer
- projection_version: string
- created_at: Timestamp
- started_at: Timestamp?
- completed_at: Timestamp?
- updated_at: Timestamp
```

并行 Worker 的计数必须根据 Worker 投影计算，不能由单个 Worker 直接写入 Workflow 汇总字段。

### 5.4 WorkerProjection

```text
WorkerProjection
- worker_id: WorkerId
- workflow_id: WorkflowId
- task_id: TaskId
- step_id: string
- worker_type: WorkerType
- attempt: integer >= 1
- status: WorkerStatus
- status_reason: string?
- source_revision: string
- input_artifact_ids: ArtifactId[]
- output_artifact_ids: ArtifactId[]
- active_action_count: integer >= 0
- waiting_action_count: integer >= 0
- failed_action_count: integer >= 0
- last_action_id: ActionId?
- last_event_id: EventId
- last_sequence: integer
- projection_version: string
- created_at: Timestamp
- started_at: Timestamp?
- completed_at: Timestamp?
- updated_at: Timestamp
```

不同 `attempt` 必须保留不同 `worker_id` 或明确的独立运行实例，不能用更新旧行覆盖上一次尝试的历史含义。

### 5.5 ActionProjection

```text
ActionProjection
- action_id: ActionId
- task_id: TaskId
- workflow_id: WorkflowId
- worker_id: WorkerId
- step_id: string
- attempt: integer >= 1
- type: ActionType
- tool_name: string
- tool_schema_version: string
- target_resource_hash: string
- source_revision: string
- risk_level: RiskLevel
- status: ActionStatus
- policy_decision_id: EntityId?
- approval_id: EntityId?
- observation_artifact_id: ArtifactId?
- failure_ref: string?
- last_event_id: EventId
- last_sequence: integer
- projection_version: string
- proposed_at: Timestamp
- started_at: Timestamp?
- completed_at: Timestamp?
- updated_at: Timestamp
```

默认不把完整参数、Shell 输出、敏感代码和凭据写入查询投影；使用经过脱敏和授权的 `ContentRef` 或摘要引用。

### 5.6 TimelineProjection

时间线用于用户查看和审计导航，不作为状态机输入。每条记录至少包含：

```text
TimelineEntry
- timeline_id: EntityId
- task_id: TaskId
- workflow_id: WorkflowId?
- worker_id: WorkerId?
- action_id: ActionId?
- event_id: EventId
- sequence: integer
- event_type: string
- actor: ActorRef
- summary: RedactedSummary
- content_refs: ContentRef[]
- occurred_at: Timestamp
- recorded_at: Timestamp
- visibility: VisibilityClass
```

同一事件重复投递不得产生第二条时间线记录。时间线顺序使用 `sequence`，显示时间只用于辅助展示。

---

## 6. 事件应用规则

### 6.1 通用处理流程

```text
收到事件
  -> 校验 Event Envelope 和事件版本
  -> 校验租户、父级实体和引用关系
  -> 查询投影消费者进度
  -> 判断重复、下一序列或序列缺口
  -> 按事件类型执行纯函数式状态转换
  -> 校验转换后的状态机不变量
  -> 在同一事务中写入投影、去重记录和消费者进度
  -> 提交后发布投影更新通知
```

状态转换函数必须满足：

```text
next_projection = apply(previous_projection, normalized_event)
```

在相同投影版本、相同事件序列和相同迁移器版本下，结果必须确定。

### 6.2 重复事件

满足以下条件时视为重复投递：

- `event_id` 已被同一投影消费者处理；
- 事件规范化内容哈希与已记录哈希一致。

处理方式：返回 `DUPLICATE_IGNORED`，不更新业务投影，但允许刷新消费监控时间。若相同 `event_id` 的内容哈希不同，必须进入 `CONFLICT`，停止该分区并告警。

### 6.3 下一序列事件

当事件 `sequence = last_applied_sequence + 1` 时：

1. 校验事件父级和当前状态；
2. 应用事件转换；
3. 写入投影和消费进度；
4. 提交后标记成功。

如果状态机约束不满足，不能用投影字段强行推进，应进入 `BLOCKED` 并产生结构化失败记录。

### 6.4 乱序与序列缺口

当事件序列大于期望值时：

- 不应用当前事件；
- 记录 `pending_gap_from` 和 `pending_gap_to`；
- 尝试从事实存储或 Outbox 重取缺失区间；
- 达到等待阈值后进入死信/人工处理；
- 缺口补齐后按序应用，不按到达顺序重排事实。

当事件序列小于或等于已应用序列时：

- 若 `event_id` 已知且哈希一致，视为重复；
- 若序列相同但 `event_id` 或哈希冲突，停止分区并告警；
- 禁止直接覆盖已应用事件。

### 6.5 未知事件和未知版本

- 已知事件类型、可迁移旧版本：先通过显式迁移器规范化，再应用并保存来源版本。
- 已知事件类型、未知主版本：暂停相关投影分区，保留原事件，不能按字段猜测。
- 未注册事件类型：进入隔离队列并告警，不得当作无害事件跳过，除非该投影版本明确声明可忽略该类别。
- 仅与当前投影无关的事件可记录为已检查但不改变业务状态；仍必须推进该投影消费者的序列并保留事件审计引用。

### 6.6 并行 Worker 汇聚

Worker 局部事件流可以并行应用到 Worker/Action 投影，但 Workflow/Task 汇聚必须满足：

1. 汇聚事件或输入事件的依赖关系已满足；
2. 所有相关 Worker 投影已经应用到相应序列；
3. 使用 `step_id`、`attempt` 和 Artifact/Evidence 引用区分并行实例；
4. 汇聚只生成当前视图，不修改任何局部历史；
5. 发现两个 Worker 对同一不可变资源或 revision 产生冲突时，状态进入 `BLOCKED`，交给 Coordinator/Reviewer，不自动投票或覆盖。

---

## 7. 一致性模型

### 7.1 一致性层级

| 层级 | 语义 | 使用范围 |
|---|---|---|
| 事实一致 | 事件已成功追加且序列唯一 | 状态迁移、恢复、审计根依据 |
| 投影一致 | 投影已应用到指定事实序列 | 查询、调度候选、UI 展示 |
| 跨投影一致 | 多个投影已追上同一序列或边界 | 交付摘要、评估报告 |
| 外部系统一致 | GitHub、模型、对象存储等已确认结果 | 由 Action/副作用模块负责 |

投影一致不等于外部系统一致。查询页面必须能够显示 `projection_lag` 或“状态可能尚未更新”的信息。

### 7.2 事务边界

MVP 采用以下事务边界：

```text
事实事件提交
  -> Outbox 发布
  -> 投影事务：业务投影 + event_id 去重记录 + consumer offset
  -> 提交
  -> 投影通知和指标异步发送
```

禁止在投影事务内调用模型、Shell、Git Push、PR、邮件、Webhook 或其他不可回滚外部服务。

### 7.3 乐观并发控制

每个投影分区使用：

- `partition_key`；
- `last_applied_sequence`；
- 投影版本号；
- 条件更新或等价的单分区串行消费。

如果两个消费者同时应用同一分区，只有满足期望序列的事务可以提交；另一个必须重新读取进度并按重复/下一序列规则处理。不得使用“最后写入覆盖”。

### 7.4 投影可见性

查询响应应至少能表达：

```text
projection_status: FRESH | LAGGING | BLOCKED | REBUILDING
as_of_sequence: integer
latest_known_sequence: integer?
lag_events: integer?
```

当投影为 `BLOCKED` 或 `REBUILDING` 时：

- 可以提供明确标记的历史查询结果；
- 不得把不完整视图作为“当前已确认状态”；
- 调度、审批和交付命令必须回到事实存储和状态机进行重新校验。

---

## 8. 投影重建与修复

### 8.1 从零重建

从零重建用于新投影版本、投影表损坏、迁移验证和离线评估：

1. 创建带唯一 `rebuild_id` 的临时投影命名空间；
2. 固定事实流起点、终点、事件版本迁移器和投影版本；
3. 从最早保留事件开始按 `sequence` 应用；
4. 对每个分区记录应用进度、失败和输入哈希；
5. 完成后执行实体引用、状态机不变量和摘要校验；
6. 与在线投影做差异比较；
7. 通过校验后原子切换查询别名；
8. 保留旧投影和重建报告，直到观察期结束。

重建不能修改事实事件，不能发送业务副作用，不能生成生产状态迁移事件。

### 8.2 从 ProjectionCheckpoint 增量重建

增量重建可以从已验证的投影消费者进度继续，但必须：

- 校验 Checkpoint 的 `last_applied_event_id`、序列和哈希；
- 校验投影版本与 Checkpoint 兼容；
- 从下一个序列开始应用事件；
- 发现事件哈希或实体快照不匹配时，放弃该 Checkpoint 并回退到更早可信边界或从零重建。

### 8.3 修复原则

- 投影错误通过重建、投影版本升级或补正事件解决；
- 禁止直接编辑生产投影表来“修正”历史事实；
- 紧急人工修复必须形成独立的系统审计记录，包含前后摘要、操作者、理由和后续重建计划；
- 事实数据错误只能由 `EventCorrection`、`EvidenceRevoked` 等显式事件表达，不能修改原事件。

### 8.4 历史增长和归档

投影层不自行删除事实事件。事件保留、分段、归档和法律留存由 `REQ-RT-003` 与安全/数据治理专项负责。投影可以：

- 按时间和任务范围建立归档查询模型；
- 在冷数据上使用只读投影；
- 记录归档事件流的起止序列和摘要；
- 在查询响应中说明数据是否来自归档投影。

---

## 9. 权限、安全和数据边界

### 9.1 查询权限

查询必须同时校验：

1. `organization_id` 和用户组织归属；
2. 项目、仓库、任务和分支访问范围；
3. 事件或投影的 `data_classification`；
4. 角色是否可以读取执行参数、错误内容、Diff 或敏感产物；
5. 导出、回放和批量查询是否需要额外审批。

投影数据库的内部表权限不能替代业务授权。跨组织查询必须在服务层和数据层双重隔离。

### 9.2 敏感信息

投影禁止保存或返回：

- API Key、Git Token、OAuth Refresh Token、密码和私钥；
- 模型隐藏思维链；
- 未经允许的完整敏感代码和完整环境变量；
- 可直接复用的长期凭据。

允许保存：

- 脱敏摘要、错误分类和内容哈希；
- 带敏感级别和访问控制的 `ContentRef`；
- Action 参数摘要和目标资源哈希；
- 事件、Artifact、Evidence 和 Trace 的稳定引用。

### 9.3 投影不能授予权限

投影中的 `status`、`allowed_tools`、`policy_decision_id`、Evidence 计数和完成摘要均不能单独授予工具、文件、网络或生产资源权限。执行前必须重新经过 Policy Gateway 和执行器侧检查。

---

## 10. 失败、重试和恢复边界

### 10.1 可重试失败

以下失败可以由投影基础设施有限重试：

- 临时数据库连接失败；
- 消息拉取或发布超时；
- 读取事实存储的暂时错误；
- 投影事务发生可识别的并发冲突。

重试必须使用同一事件和消费者幂等记录，不能创建新业务事件。

### 10.2 不应盲目重试的失败

以下情况必须进入 `BLOCKED`、死信或人工处理：

- Schema 校验失败；
- 未知主版本；
- 事件引用跨组织或跨 Workflow；
- 序列冲突或同序列内容冲突；
- 状态机前置条件不满足；
- 投影转换代码检测到不可恢复不变量破坏；
- 敏感信息校验失败。

### 10.3 投影器崩溃

若投影器在事务提交前崩溃，事件将被重新投递并正常应用；若事务已提交但响应丢失，重复投递通过 `event_id` 和序列检查被忽略。投影器不能根据内存中的“已处理”标记跳过未提交事务。

### 10.4 投影滞后期间的业务控制

- UI/API 可以展示最后一个已确认视图，并标记滞后；
- Coordinator 不得仅依据过期投影推进高风险状态；
- 审批、取消、恢复、PR 创建和完成判断必须读取事实序列并重新校验；
- 若投影健康状态为 `BLOCKED`，应暂停依赖该投影的自动调度，避免在不完整状态上产生新的业务 Action。

---

## 11. MVP 范围和非目标

### 11.1 MVP 必须包含

- Task、Workflow、Worker、Action 四类当前投影；
- 基于 `REQ-RT-003` 的事件消费接口；
- 同一事实流按 `sequence` 有序应用；
- `event_id` 去重和消费者 offset；
- 乱序、缺口、未知版本、冲突和死信处理；
- 从零重建和重建差异报告；
- 投影健康状态、积压和延迟指标；
- 组织/项目/仓库/任务级查询权限；
- 投影不触发外部副作用；
- Issue 到 PR 流程所需的等待、审批、暂停、失败、恢复和完成状态查询。

### 11.2 MVP 不包含

- 多区域主动-主动投影冲突合并；
- 跨 Workflow 的全局强一致查询；
- 投影层自动修复事实事件；
- 用投影直接完成外部 GitHub、Git、模型或通知操作；
- 复杂 BI 数仓和长期指标聚合；
- Checkpoint 的业务快照格式；
- 数据库、队列和 API 的具体实现代码。

---

## 12. 验收与评测方案

### 12.1 契约测试

至少验证：

1. 合法事件按序更新正确的投影实体；
2. 缺少父级引用、跨组织引用和错误 attempt 被拒绝；
3. 同一事件重复投递只产生一次投影效果；
4. 相同事件 ID 的不同内容进入冲突状态；
5. 序列缺口不会推进投影状态；
6. 事件乱序补齐后可以按序完成应用；
7. 未知主版本不会被静默解析；
8. 投影事务失败时业务投影和 offset 不会只提交一半；
9. Action 成功不会直接推导 Worker、Workflow 或 Task 完成；
10. 投影器不会调用任何外部副作用工具。

### 12.2 重建与一致性测试

至少覆盖：

- 在线投影与从零重建结果一致；
- 投影器在每类事件提交前后崩溃都能恢复；
- 重建中途失败后可安全重启或清理临时命名空间；
- Checkpoint 序列/哈希不匹配时不会继续增量恢复；
- 旧事件通过显式迁移器重建结果稳定；
- 并行 Worker 汇聚结果与串行事件回放结果一致；
- 投影落后时高风险调度被阻止或重新验证；
- 事实历史不受投影重建、切换和查询影响。

### 12.3 安全测试

- 未授权用户无法查询其他组织、仓库或敏感投影；
- 投影查询不能取得长期凭据和隐藏思维链；
- 投影表直接写入尝试被数据库或服务层阻止并审计；
- 伪造事件、跨任务事件和非法序列不能推进投影；
- 脱敏失败的事件进入隔离路径；
- 回放和重建不会产生 Git Push、PR、通知或生产访问。

### 12.4 目标指标

以下是实现和评测目标，不是当前已达成的运行结果：

- 合法事件投影结果确定性：100%；
- 重复事件产生重复业务效果：0；
- 序列缺口静默推进：0；
- 在线投影与从零重建的核心字段一致率：100%；
- 投影引用完整性错误可定位到事件和字段的比例：不低于 95%；
- 投影确认延迟 p95：目标小于 2 秒，不含事实写入和外部工具执行；
- 投影器重启后自动恢复成功率：目标不低于 99%；
- 未授权查询成功率：0；
- 投影重建不产生外部副作用：100%。

正式阈值需在 `REQ-EVA-*` 和故障注入评测中校准，不能把候选目标宣称为已验证结果。

---

## 13. 方案比较与最终选择

### 方案 A：API 直接维护当前状态表

不选择原因：

- 容易绕过事件事实和状态机；
- 并发更新和重复请求可能覆盖历史；
- 无法从历史重建和定位投影错误；
- 审计、评估和 UI 会形成不同状态来源。

### 方案 B：每次查询实时扫描完整事件历史

不选择原因：

- 查询延迟和成本随历史长度增长；
- 难以支持列表页、聚合和高并发控制台；
- 不能替代投影健康、权限过滤和版本迁移机制。

### 方案 C：事件驱动查询投影 + 可重建投影模型

**最终选择：方案 C。**

选择理由：

1. 保持 `REQ-RT-003` 事实先提交、再消费的边界；
2. 与 `REQ-RT-002` 的状态机和 `status_projection` 语义一致；
3. 吸收 Temporal 的事件历史、回放和历史增长治理原则；
4. 吸收 LangGraph 的稳定运行身份、持久快照和人工中断边界；
5. 吸收 OpenHands 的类型化事件和观察者解耦原则；
6. 支持至少一次投递、幂等消费、乱序检测和从零重建；
7. 允许 UI、审计、评估和调度使用各自查询模型而不篡改事实。

该方案是当前推荐基线，不代表未经本项目压测、故障注入和安全测试的全局最优解。

---

## 14. 与其他需求的接口约束

### `REQ-RT-001`

投影必须使用其 Task、Workflow、Worker、Action、Artifact、Evidence、Trace 和 Revision 坐标。投影不得重新定义业务主键或用投影内部 ID 替代共享 ID。

### `REQ-RT-002`

投影器只能应用合法状态迁移事件。投影状态不合法时必须阻塞并报告，不得通过修改状态字段绕过迁移前置条件。`status_projection` 是查询结果，不是迁移命令。

### `REQ-RT-003`

投影器必须：

- 只消费事实存储已确认的事件；
- 使用 `sequence` 处理顺序、缺口和乱序；
- 使用 `event_id` 和内容哈希实现消费者幂等；
- 保留来源事件、事件版本、迁移器版本和最后应用序列；
- 支持投影重建和死信处理；
- 不把投影更新写回旧事件。

### `REQ-RT-005`

业务 Checkpoint 可以引用投影进度，但必须区分：

- `ProjectionCheckpoint`：某个消费者应用到哪里；
- `Workflow Checkpoint`：业务运行如何从一致边界恢复。

二者不能互相替代。

### `REQ-RT-006` 和 `REQ-OBS-*`

投影日志、指标和 Trace 必须引用 `workflow_id`、`projection_name`、`partition_key`、`event_id`、`sequence` 和 `trace_id`。指标和日志不能反向改变业务状态。

### `REQ-REL-*`

投影基础设施的短暂读取/事务错误可以有限重试；事件协议错误、状态不变量破坏和版本未知必须进入阻塞/死信。投影器不负责 Action 的外部副作用重试。

### `REQ-SEC-*`

所有投影查询必须执行租户、项目、仓库、任务和敏感级别授权。投影状态不能授予工具、文件、网络、凭据或生产资源权限。

---

## 15. 设计决策记录

```text
需求编号：REQ-RT-004
功能点：状态投影与一致性规则
当前状态：详细设计已完成，待跨模块冻结
前置依赖：REQ-RT-001、REQ-RT-002、REQ-RT-003
候选方案：
  A. API 直接维护当前状态表
  B. 每次查询实时扫描完整事件历史
  C. 事件驱动查询投影 + 可重建投影模型
公开证据等级：A
推荐基线：方案 C
选择理由：
  1. 事实与查询状态单向分离
  2. 支持至少一次投递、幂等、乱序检测和缺口处理
  3. 支持从零重建、版本迁移和投影差异校验
  4. 支持 UI、审计、评估和调度使用不同查询模型
适用边界：
  单组织、单仓库、Issue 到 PR、有限 Workflow/Worker 并行
替代方案：
  Temporal Event History/Replayer、LangGraph Checkpointer，或专用 CQRS/Event Store
安全约束：
  默认拒绝跨租户读取；投影不能授予权限；敏感字段脱敏；
  重建和回放禁止外部副作用；投影表禁止普通业务直接写入
失败与恢复：
  重复事件幂等；序列缺口阻塞；版本未知隔离；
  投影可从零重建；ProjectionCheckpoint 只记录消费进度
验收指标：
  投影确定性、重建一致性、重复无副作用、缺口不静默推进、
  未授权查询拦截、投影延迟、重启恢复和安全回放
目标版本：REQ-RT-004 v0.1-designed
```

---

## 16. 设计冻结条件

升级到 `v1.0-frozen` 前必须完成：

1. 与 `REQ-RT-001/002/003/004` 的实体、状态、事件和投影引用交叉评审；
2. 事件存储、Outbox、消费者 offset 和死信处理 PoC；
3. Task/Workflow/Worker/Action 投影 Schema 契约测试；
4. 重复、乱序、缺口、冲突、版本迁移和崩溃恢复故障注入测试设计；
5. 从零重建与在线投影差异校验工具设计；
6. 权限、脱敏、跨租户和审计读取测试设计；
7. 与 Checkpoint、Trace、RetryPolicy 和副作用边界完成评审；
8. 确定投影保留、归档、版本升级和查询兼容策略；
9. 解决“最终一致查询”和“高风险控制必须重新验证”的使用边界；
10. 发布 `Runtime Contract v1.0-frozen` 所需的投影契约版本。

---

## 17. 设计结论

`REQ-RT-004` 采用：

> **事件事实源之上的按流有序、幂等、可重建状态投影；投影状态只服务查询和观察，不替代事实、状态机、授权或外部副作用确认。**

该方案补齐了 `REQ-RT-003` 明确留出的投影边界，使 Task、Workflow、Worker 和 Action 能够在不覆盖历史的前提下提供高效查询、恢复定位、审计导航和评估回放。它是专项设计完成，不代表事件存储、投影器、重建工具或运行指标已经实现或验证。

---

## 18. 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| `v0.1-designed` | 2026-09-22 | 基于 REQ-RT-001/002/003 与 Temporal、LangGraph、OpenHands 官方资料，完成投影模型、事件应用、顺序/幂等、一致性、重建、权限、故障和验收设计 |
