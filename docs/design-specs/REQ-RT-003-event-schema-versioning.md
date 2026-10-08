# REQ-RT-003 Event Schema 与版本策略详细设计

> 所属基线：`Runtime Contract v1`（已冻结，2026-10-07）
> 需求编号：`REQ-RT-003`
> 优先级：P0
> 设计版本：`v0.1-frozen`
> 设计状态：已冻结，可作为实现基线（跨模块评审通过，2026-10-07）
> 前置依赖：`REQ-RT-001` 核心实体 Schema、`REQ-RT-002` 状态机与迁移约束
> 设计范围：事件信封、事件载荷、顺序、幂等、版本兼容、迁移和安全边界
> 不包含：状态投影实现、Checkpoint 格式、RetryPolicy、Action 幂等算法、数据库 DDL 和具体消息中间件实现

---

## 1. 需求定义

### 1.1 需求目标

建立平台统一的不可变事件契约，使每次 Agent 任务的状态变化、Action 生命周期、工具结果、审批、产物、证据和控制操作都能够：

- 追加保存，不覆盖历史事实；
- 关联到统一的 `task_id`、`workflow_id`、`worker_id`、`action_id` 和 `trace_id`；
- 按任务执行范围确定性排序和回放；
- 在重复投递、进程崩溃和消费者重启后保持幂等；
- 支持事件 Schema 的向后兼容、迁移和版本审计；
- 为状态投影、Checkpoint、审计、评估和 UI 提供同一事实来源。

本需求解决的问题是：**系统如何记录“发生了什么”，以及不同版本的运行时如何安全地读取这些事实。**

### 1.2 用户和系统价值

| 使用方 | 依赖能力 |
|---|---|
| Workflow Runtime | 按事件恢复任务和执行边界 |
| State Projector | 从事件重建 Task、Workflow、Worker、Action 当前状态 |
| Policy/Audit | 追踪授权、拒绝、审批和高风险操作 |
| Recovery | 判断最后一个一致边界和未完成副作用 |
| Evaluation | 对任务进行回放、归因和版本对比 |
| UI/API | 展示时间线、等待原因、工具结果和证据 |
| SRE/Security | 查询故障、检测异常事件和验证日志完整性 |

### 1.3 设计完成的最低条件

1. 明确事件信封的必填字段和字段语义。
2. 明确领域事件与运行控制事件的分类。
3. 明确事件顺序、因果关系、并发和乱序处理规则。
4. 明确事件生产、持久化、消费和重复投递边界。
5. 明确 Schema 版本、事件类型版本和迁移兼容规则。
6. 明确敏感数据、模型输出、工具结果和外部内容的存储边界。
7. 能够覆盖 MVP 的 Issue 到 PR、审批、暂停、恢复、失败和取消流程。
8. 为 `REQ-RT-004` 状态投影、`REQ-RT-005` Checkpoint 和 `REQ-RT-006` Trace 设计稳定接口。

---

## 2. 公开旗舰 Agent 与成熟系统调研

本节只采用公开官方资料能够证明的工程原则，不推断厂商内部实现，也不把公开先例等同于本项目已经达到同等可靠性。

### 2.1 OpenHands：不可变、类型化、追加式事件

OpenHands 官方 SDK 将 Event System 定义为类型安全、不可变、追加式事件框架。事件既作为 Agent 执行状态的历史，也作为辅助服务的集成入口；ActionEvent 表达工具调用，ObservationEvent 表达工具结果，PauseEvent 和压缩事件表达运行控制。

对本项目的借鉴：

- 事件必须是独立的一等对象，不能只存在于模型消息或日志文本中；
- Action 与 Observation 分离，不能用一个“工具调用完成”事件同时替代提议、授权和结果；
- 事件应区分“来源归属”和“面向模型的消息角色”；
- 事件流可被只读观察者消费，用于监控、可视化和审计；
- 运行控制事件不能被误当成业务完成事件。

来源：

- [OpenHands Events](https://docs.openhands.dev/sdk/arch/events)
- [OpenHands Agent](https://docs.openhands.dev/sdk/arch/agent)

### 2.2 LangGraph：Checkpoint、线程标识和中断恢复

LangGraph 官方文档将 Checkpointer 作为线程级状态持久化机制，使用稳定的 `thread_id` 关联一条运行轨迹；中断会保存状态，恢复时使用同一运行标识继续。官方同时明确，节点恢复可能从节点开头重新执行，因此副作用必须具备幂等性。

对本项目的借鉴：

- 事件和运行状态必须绑定稳定的 Workflow 运行身份；
- 审批、人工介入和暂停必须由可持久化事实表达；
- Event Log 与 Checkpoint 是互补关系，Checkpoint 不能取代事件事实源；
- 事件消费和状态恢复必须预设重复执行、重复观察和幂等处理。

来源：

- [LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [LangGraph Checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers)
- [LangGraph Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)

### 2.3 Temporal：Event History、回放和运行版本

Temporal 官方文档将 Workflow Event History 作为持久执行和故障恢复的基础；事件历史同时用于回放和调试。Temporal 还提供 Worker Versioning，使运行中的 Workflow 可以固定在启动时的 Worker 版本，或按明确策略升级。

对本项目的借鉴：

- 事件历史必须是任务运行的事实依据，而不是普通日志的附属品；
- 事件历史需要有大小、数量和归档边界，不能无限增长；
- 运行时版本必须进入事件或运行上下文，避免新代码静默改变旧任务的解释方式；
- 长任务需要明确历史压缩、分段或 Continue-As-New 类似的迁移边界。

来源：

- [Temporal Events and Event History](https://docs.temporal.io/workflow-execution/event)
- [Temporal Workflow Execution](https://docs.temporal.io/workflow-execution)
- [Temporal Worker Versioning](https://docs.temporal.io/production-deployment/worker-deployments/worker-versioning)

### 2.4 Google Jules：活动事件与计划审批

Google Jules API 将 Session 内的工作表示为 Activity，并公开 `planGenerated`、`planApproved`、进度、完成和失败等活动；Session 状态明确区分规划、等待计划审批、执行、暂停和完成。

对本项目的借鉴：

- 计划生成和计划批准必须是两个可查询的事实；
- “等待人工”不能压缩成普通失败或空闲；
- 活动、产物和状态应通过稳定 ID 关联；
- UI 可使用事件流重建任务时间线，而不依赖 Agent 当前内存。

来源：

- [Jules Sessions API](https://developers.google.com/jules/api/reference/rest/v1alpha/sessions)
- [Jules Activities API](https://developers.google.com/jules/api/reference/rest/v1alpha/sessions.activities)

### 2.5 GitHub Copilot Cloud Agent 与 Codex Cloud：可审查异步交付

GitHub Copilot Cloud Agent 公开支持研究仓库、生成计划、在临时环境中修改分支、运行测试和 Lint、查看 Diff 并创建 Pull Request。Codex Cloud 公开强调隔离环境、后台并行任务、环境复现和提交前查看摘要与 Diff。

对本项目的借鉴：

- 事件模型必须覆盖研究、计划、执行、验证和交付阶段；
- 分支、Revision、环境、Diff、测试结果和 PR 应通过产物/证据引用关联，而不是塞入 Task 自由文本；
- 后台运行不降低可观测和可审查要求；
- 任务停止、执行完成和 PR 可审查是不同事实。

来源：

- [GitHub Copilot Cloud Agent](https://docs.github.com/en/copilot/concepts/agents/cloud-agent/about-cloud-agent)
- [OpenAI Codex Cloud](https://developers.openai.com/codex/cloud)

### 2.6 调研结论

本需求采用的公开证据共性为：

1. 事件是不可变的类型化事实，不是自由文本日志。
2. 事件历史、状态投影、Checkpoint 和观测订阅职责分离。
3. 运行标识、Schema 版本、工作区/Revision 和产物引用必须稳定可追踪。
4. 计划审批、暂停、失败和完成必须有不同事件语义。
5. 重放和恢复必须面对重复执行、乱序、版本变化和历史增长。
6. Agent 输出不能直接成为完成事实，必须由工具结果、Artifact、Evidence 和策略共同确认。

这些是本项目的推荐工程基线，不是对任一厂商内部实现的复制，也不是未经评测的全局最优算法。

---

## 3. 设计边界与共享坐标

### 3.1 本需求包含

- Event Envelope 通用信封；
- 领域事件、控制事件和执行结果事件分类；
- 事件载荷与 `REQ-RT-001` 实体的引用规则；
- 事件序列、因果关系和并发处理；
- 生产、持久化、消费和回放语义；
- Schema 版本、事件类型版本和迁移策略；
- 事件幂等、重复投递和未知事件处理；
- 敏感数据、内容引用和审计完整性边界；
- MVP 事件目录和验收指标。

### 3.2 本需求不包含

| 内容 | 归属需求 |
|---|---|
| Task、Workflow、Worker、Action 核心实体字段 | `REQ-RT-001` |
| 状态集合和合法迁移 | `REQ-RT-002` |
| 状态投影表、查询 API 和重建实现 | `REQ-RT-004` |
| Checkpoint 字节格式、保存时机和恢复流程 | `REQ-RT-005`、`REQ-REL-004/005` |
| Action 幂等键生成和外部副作用保护 | `REQ-RT-007`、`REQ-REL-006` |
| Trace/Span 传播和 OpenTelemetry 映射 | `REQ-RT-006`、`REQ-OBS-001` |
| 权限 DSL、审批矩阵和策略判断 | `REQ-SEC-002/003` |
| 失败分类、重试次数、退避和熔断 | `REQ-REL-001/002/003` |
| 数据库 DDL、队列和消息中间件部署 | 实现设计阶段 |

### 3.3 共享坐标

所有事件必须复用 `REQ-RT-001` 已定义的坐标，不得建立替代 ID：

- `event_id`
- `task_id`
- `workflow_id`
- `worker_id`
- `action_id`
- `step_id`
- `attempt`
- `artifact_id`
- `evidence_id`
- `trace_id`
- `span_id`
- `source_revision`
- `base_revision`
- `working_revision`
- `policy_decision_id`
- `idempotency_key`

事件是事实坐标；实体中的 `status_projection` 是查询投影，不能反向替代事件。

---

## 4. 事件分类和生命周期

### 4.1 事件分类

| 类别 | 说明 | 示例 |
|---|---|---|
| `DOMAIN` | 业务事实变化 | TaskCreated、ArtifactProduced、EvidenceProduced |
| `LIFECYCLE` | 实体生命周期变化 | WorkerStarted、WorkerCompleted、WorkflowFailed |
| `ACTION` | Action/工具生命周期 | ActionProposed、ActionAuthorized、ToolObserved |
| `CONTROL` | 人工或系统控制 | WorkflowPaused、ApprovalRequested、KillSwitchActivated |
| `OBSERVATION` | 执行结果和外部观察 | ToolObserved、TestFinished、ScanFinished |
| `AUDIT` | 安全、策略和审计事实 | PolicyEvaluated、CredentialIssued、AccessDenied |
| `SYSTEM` | 运行时基础设施事实 | CheckpointCreated、ProjectionRebuilt、EventMigrated |

分类用于检索、权限和保留策略，不改变事件不可变性。

### 4.2 事件生命周期

```text
事件提议
  -> 载荷 Schema 校验
  -> 身份、父级和 Trace 校验
  -> 事件 ID / 幂等键校验
  -> 追加到事实存储
  -> 发布可观察通知
  -> 投影器消费
  -> 审计、指标和评估消费者异步消费
```

关键顺序：事件必须先被事实存储确认，再对外发布“已发生”。投影失败、通知失败或某个异步消费者失败，不能删除或回写事实事件。

### 4.3 生产者边界

事件生产者分为：

- `USER`：创建任务、审批、暂停、恢复、取消、反馈；
- `WORKER`：提议 Action、报告结构化结果、生成 Artifact；
- `TOOL`：工具启动、完成、失败和执行产物；
- `SYSTEM`：状态迁移、策略决策、投影、恢复和运行时事件；
- `EXTERNAL_PROVIDER`：GitHub、模型供应商或其他连接器回调。

生产者只能写入其声明允许的事件类型。模型文本不能直接写入状态事实事件；必须由 Coordinator、Policy Gateway 或运行时把模型输出转换为经过校验的事件。

---

## 5. Event Envelope Schema

以下为跨语言中立表示。实现可以使用 JSON Schema、Protobuf 或等价强类型承载，但语义必须保持一致。

```text
EventEnvelope
- schema_version: string = "runtime.event-envelope.v1"
- event_id: EventId
- event_type: string
- event_type_version: string
- event_category: EventCategory
- task_id: TaskId
- organization_id: EntityId
- project_id: EntityId
- repository_id: EntityId
- workflow_id: WorkflowId?
- worker_id: WorkerId?
- action_id: ActionId?
- step_id: string?
- attempt: integer >= 1?
- trace_id: TraceId
- span_id: SpanId?
- parent_span_id: SpanId?
- source_revision: string?
- actor: ActorRef
- occurred_at: Timestamp
- recorded_at: Timestamp
- sequence: EventSequence
- causation: CausationRef
- correlation_id: string
- idempotency_key: string?
- payload_schema: string
- payload: JsonObject
- data_classification: DataSensitivity
- content_refs: ContentRef[]
- redaction: RedactionInfo?
- producer: ProducerRef
- extensions: SafeMetadata
```

### 5.1 字段语义

| 字段 | 约束 |
|---|---|
| `schema_version` | 信封结构版本；不表示业务事件版本 |
| `event_id` | UUIDv7，创建后不可变；重复事件不得生成新事实 |
| `event_type` | 稳定的语义名称，如 `ActionProposed` |
| `event_type_version` | 当前事件载荷版本，如 `v1` |
| `organization_id` | 必填，事件不可跨组织归属 |
| `task_id` | 所有任务范围事件必填 |
| `trace_id` | 所有运行事件必填；控制台查询和审计关联使用 |
| `occurred_at` | 事实发生时间，来自受控服务时钟 |
| `recorded_at` | 事实写入存储时间，不作为业务顺序依据 |
| `sequence` | 事实存储分配的单调序列，不能由模型或客户端指定 |
| `causation` | 触发当前事件的上游事件或请求 |
| `correlation_id` | 关联同一用户操作、Workflow 或外部回调的一组事件 |
| `payload` | 必须符合 `payload_schema`；不允许未声明的任意字段 |
| `content_refs` | 大型输出、日志或 Diff 的对象存储引用；不得把密钥写入对象 |
| `producer` | 记录生产组件及其版本，便于回放和归因 |

### 5.2 时间和顺序

- `occurred_at` 用于显示和跨系统近似排序，允许存在时钟偏差；
- `recorded_at` 用于存储审计；
- `sequence` 用于同一事实流的确定性重放；
- 不允许用 UUID 时间部分、客户端时间或 `occurred_at` 推断业务先后；
- 同一 `workflow_id` 的事件必须拥有一个可比较的 Workflow 序列；
- 并行 Worker 的局部事件可以拥有各自的 Worker 序列，但汇聚事件必须声明依赖的事件或 Artifact；
- 事件乱序到达时，消费者按序列缓冲或进入待处理状态，不能静默重排事实。

### 5.3 因果和关联

```text
CausationRef
- causation_type: EVENT | COMMAND | EXTERNAL_CALLBACK | SYSTEM_RECOVERY
- causation_id: string
- parent_event_id: EventId?
- root_event_id: EventId?
```

- `causation_id` 表示“为什么产生此事件”；
- `correlation_id` 表示“属于哪组业务交互”；
- `trace_id/span_id` 表示“如何观察这次执行”；
- 三者语义不能互相替代；
- 外部回调必须保存供应商事件 ID，防止重复回调产生重复事实。

---

## 6. MVP 事件目录

### 6.1 Task 和 Workflow

| 事件 | 必要载荷 | 触发条件 |
|---|---|---|
| `TaskCreated` | Task 引用、来源快照、`base_revision` | Task Schema 校验通过 |
| `TaskAuthorized` | 授权范围、策略版本、预算引用 | 任务授权完成 |
| `WorkflowStarted` | Workflow 模板和版本、运行配置引用 | Workflow 创建并启动 |
| `WorkflowPaused` | 原因、操作者、暂停范围 | Workflow 主动暂停或 Kill Switch |
| `WorkflowResumed` | 恢复点、重新校验结果 | 恢复条件满足 |
| `WorkflowCompleted` | 完成条件摘要、Evidence 引用 | Workflow 级完成条件满足 |
| `WorkflowFailed` | 失败层级、失败引用、可恢复性 | Workflow 无法继续 |
| `WorkflowCancelled` | 操作者、取消原因、补偿引用 | Workflow 被取消 |

### 6.2 Step 和 Worker

| 事件 | 必要载荷 | 触发条件 |
|---|---|---|
| `StepReady` | `step_id`、依赖、输入 Artifact | DAG 节点可调度 |
| `WorkerStarted` | Worker 配置版本、`attempt`、`source_revision` | Worker 开始执行 |
| `WorkerPaused` | 原因、待处理 Action | Worker 暂停 |
| `WorkerCompleted` | 输出 Artifact/Evidence 引用 | Worker 契约和验证条件满足 |
| `WorkerFailed` | 失败引用、部分产物、恢复建议 | Worker 无法继续 |
| `WorkerCancelled` | 操作者、清理结果 | Worker 被取消 |

### 6.3 Action、Policy 和工具

| 事件 | 必要载荷 | 触发条件 |
|---|---|---|
| `ActionProposed` | Action 引用、工具版本、目标资源、参数摘要 | Worker 提出结构化 Action |
| `PolicyEvaluated` | PolicyDecision、规则版本、结果 | Policy Gateway 完成判断 |
| `ActionAuthorized` | PolicyDecision 引用、授权范围、有效期 | 策略允许执行 |
| `ApprovalRequested` | Action/资源、风险、审批角色、撤销方式 | 策略要求人工审批 |
| `ApprovalResolved` | 审批人、结果、覆盖范围、原因 | 审批完成 |
| `ActionRejected` | 拒绝原因、命中规则 | 策略拒绝或校验失败 |
| `ToolStarted` | Tool Call 引用、执行环境、输入摘要 | 执行器接受 Action |
| `ToolObserved` | 返回码、输出引用、执行摘要、错误分类引用 | 工具返回结果 |
| `ActionSucceeded` | Tool Observation、产物引用 | Action 执行成功 |
| `ActionFailed` | Observation、部分副作用、失败引用 | Action 执行失败 |

### 6.4 Artifact、Evidence 和上下文控制

| 事件 | 必要载荷 | 触发条件 |
|---|---|---|
| `ArtifactProduced` | Artifact ID、类型、哈希、`source_revision` | 产物完成并存储 |
| `EvidenceProduced` | Evidence ID、验证方式、结果、验证者 | 证据完成并验证 |
| `EvidenceRevoked` | 原 Evidence、撤销原因、操作者 | 证据失效或被撤销 |
| `ContextLoaded` | ContextManifest 引用、来源数量、预算 | 上下文载入完成 |
| `ContextCondensed` | 压缩版本、被摘要内容引用、恢复引用 | 上下文压缩完成 |

### 6.5 控制和系统事件

| 事件 | 必要载荷 | 触发条件 |
|---|---|---|
| `TaskPaused` | 操作者、原因、范围 | Task 暂停 |
| `TaskResumed` | 恢复点、权限和版本复核 | Task 恢复 |
| `TaskCancelled` | 操作者、原因、补偿引用 | Task 取消 |
| `TaskCompleted` | 最终 Artifact/Evidence、完成条件摘要 | Task 最终完成 |
| `RetryScheduled` | 原事件/Action、失败分类、策略引用、下一次时间 | 后续可靠性模块安排重试 |
| `CheckpointCreated` | Checkpoint 引用、对应序列、范围 | Checkpoint 保存完成 |
| `EventMigrated` | 原版本、新版本、迁移器版本、哈希 | 读取或归档迁移完成 |
| `KillSwitchActivated` | 触发层级、范围、操作者、撤销结果 | 系统停止能力触发 |

说明：`RetryScheduled` 和 `CheckpointCreated` 在 MVP 事件目录中保留接口，但具体语义分别由 `REQ-REL-*` 和 `REQ-RT-005` 冻结。事件目录不预先定义重试算法或 Checkpoint 格式。

---

## 7. 事件不变量和校验规则

### 7.1 身份和引用

1. `task_id`、`organization_id`、`project_id`、`repository_id` 必须能相互校验归属。
2. `workflow_id` 存在时必须属于 `task_id`；`worker_id` 存在时必须属于 `workflow_id`。
3. `action_id` 存在时必须属于 Worker 的当前 `attempt`；不能把不同 attempt 的 Action 合并。
4. Artifact/Evidence 事件必须带来源 ID、`source_revision` 和内容哈希或 ContentRef。
5. 状态迁移事件必须同时表达 `from_state`、`to_state`、实体 ID、原因和 Actor。
6. 事件的 `trace_id` 不能替代业务实体归属；缺少业务父级时必须明确标记为平台事件。

### 7.2 不可变和事实源

1. 已追加事件不得更新或删除。
2. 事件中的事实载荷不得使用“当前值”覆盖历史版本。
3. 修正错误必须产生新的补正、撤销或迁移事件。
4. 投影字段更新、缓存失效和通知失败不能修改事实流。
5. 事件追加成功前不能对外宣称状态迁移成功。

### 7.3 数据边界

事件不得明文保存：

- API Key、OAuth Refresh Token、Git Token、Private Key 和密码；
- 模型隐藏思维链或内部推理令牌；
- 未经数据策略允许的完整敏感代码；
- 可直接复用的长期凭据；
- 不受控的完整 Shell 环境变量。

允许保存：

- 凭据引用、短期令牌的不可逆标识和生命周期结果；
- 脱敏后的错误摘要；
- Artifact/Evidence 的哈希、敏感级别和对象存储引用；
- 用户审查所必需且受策略保护的 Diff 引用；
- Prompt/Context 的版本和摘要，不保存未受控原文。

---

## 8. 顺序、并发和投递语义

### 8.1 事实流分区

MVP 采用以下事实流分区逻辑：

```text
organization_id / task_id / workflow_id
```

- Task/Workflow 主流负责跨 Worker 的生命周期和汇聚事实；
- Worker 局部流负责 Worker、Action 和 Tool 事件；
- 所有局部流通过 `causation`、`correlation_id` 和全局 `sequence` 建立可回放关系；
- 事件存储必须保证同一事实流内的追加序列单调递增；
- 不要求并行 Worker 的局部事件拥有全局实时顺序，但必须能确定性地表达依赖和汇聚。

### 8.2 至少一次投递与幂等消费

MVP 采用“事实追加成功 + 至少一次消费”的语义：

1. 生产者先写入事实存储；
2. 发布器或 Outbox 将已提交事件发送给消费者；
3. 消费者可能收到重复事件；
4. 消费者以 `event_id` 和消费者名称建立去重记录；
5. 投影器还必须校验事件序列，不能仅依赖去重；
6. 消费失败进入重试或死信队列，不能丢弃事实；
7. 死信处理结果必须可审计并支持人工重放。

本需求不把“恰好一次”作为跨系统承诺。对于文件、Git、PR 和外部 API 等副作用，必须由 `REQ-RT-007`/`REQ-REL-006` 单独定义幂等和补偿。

### 8.3 事件重复与冲突

- 相同 `event_id`、相同内容哈希：视为重复投递，返回已处理结果；
- 相同幂等键、不同内容哈希：视为协议冲突，拒绝并告警；
- 相同业务动作产生不同 `event_id`：不能自动判断为重复事实，交给 Action 幂等模块；
- 事件序列缺口：消费者进入等待或重取状态，不能用空事件填补；
- 事件序列倒退：拒绝当前消息并记录异常；
- 外部回调重复：使用 `provider + external_event_id` 去重。

### 8.4 事务边界

事件事实和投影更新不要求共享一个数据库事务。推荐边界：

```text
业务命令
  -> 事实事件事务提交
  -> Outbox 发布
  -> 投影器更新查询模型
  -> 异步消费者处理
```

事实存储是权威源；投影延迟必须可观测，投影异常不能导致事实回滚。需要跨资源一致性的动作，应使用明确的 Saga/补偿设计，而不是伪造分布式事务已完成。

---

## 9. Schema 版本与兼容策略

### 9.1 三种版本必须分离

| 版本 | 作用 | 示例 |
|---|---|---|
| `schema_version` | Event Envelope 结构版本 | `runtime.event-envelope.v1` |
| `event_type_version` | 某类事件载荷版本 | `ActionProposed.v1` |
| `producer_version` | 生产组件、Workflow 或 Agent 资产版本 | `worker-runtime@1.4.0` |

此外，事件载荷应通过 `workflow_template_version`、`agent_profile_version`、`toolset_version`、`policy_version` 和模型资产引用说明运行时行为版本。不能把所有版本压缩成一个字符串。

### 9.2 兼容规则

- 新增可选字段：同一事件类型小版本兼容升级；
- 新增消费者可忽略字段：生产者可以先发布，但必须通过契约测试；
- 新增枚举值：先确认所有消费者的未知值处理策略；
- 修改字段含义、类型、单位或必填性：升级事件类型主版本；
- 删除字段：先标记弃用，至少经过一个保留周期后再删除；
- 改变 ID、来源、顺序、幂等或安全语义：必须升级主版本并进行全链路评审；
- 事件名称重命名：保留旧名称映射，不得静默改变历史含义；
- 旧版本事件读取：消费者优先使用显式迁移器，不允许按“猜测字段”兼容；
- 未知主版本：拒绝进入投影和执行路径，保留原始事件并告警。

### 9.3 读兼容和写兼容

采用“旧事件可读，新事件受控写入”的策略：

- 生产者只能写入已注册、已审核的事件类型和版本；
- 新消费者必须能够读取 MVP 保留期内的旧事件版本；
- 迁移后的对象必须保留原始版本、原始哈希和迁移器版本；
- 不在事实存储中原地改写旧事件；
- 投影器可以将多个历史版本归一为同一查询模型，但必须保存来源版本。

### 9.4 迁移策略

事件迁移分为三类：

1. **读取时迁移**：回放或投影读取旧事件时，在内存中转换为当前内部模型，不改事实存储。
2. **归档迁移**：对冷数据生成新版本归档副本，原始事件仍保留可验证引用。
3. **显式补正事件**：历史事实不准确或需要撤销时追加补正/撤销事件，不能修改旧事件。

每个迁移器必须声明：

- `from_event_type_version`；
- `to_event_type_version`；
- 迁移器版本和内容哈希；
- 是否幂等；
- 是否有信息损失；
- 可回滚方式或不可逆说明；
- 契约测试和代表性历史样本。

### 9.5 长事件历史

MVP 初始采用事件分段和 Checkpoint 引用预留：

- 单 Workflow 事件数量、单事件大小和总历史大小必须有配置上限；
- 接近上限时产生告警和 `CheckpointCreated`/压缩请求事件；
- 压缩不能删除审计必须保留的原始事件；
- 运行时恢复可使用 Checkpoint 加事件增量，但回放工具必须能够验证 Checkpoint 对应的事件序列和哈希；
- 具体 Checkpoint 格式和保留策略由 `REQ-RT-005` 冻结。

---

## 10. 安全、审计和权限边界

### 10.1 事件写入授权

事件写入必须校验：

1. Actor 是否属于事件声明的组织和任务范围；
2. Actor 是否有权生产该事件类型；
3. 事件引用的父级实体是否存在且版本一致；
4. 事件载荷是否包含禁止的敏感字段；
5. `trace_id`、`causation` 和 `correlation_id` 是否可关联；
6. 事件是否违反当前状态机、策略或 Kill Switch 约束。

Worker 不能直接写入 `TaskCompleted`、`WorkflowCompleted`、`PolicyEvaluated` 或高权限审计事件；这些事件必须由相应的系统服务或确定性验证器产生。

### 10.2 读取权限

- 查询必须强制带 `organization_id` 和授权范围；
- 事件读取、回放和导出按任务、仓库、数据敏感级别和角色授权；
- 审计管理员可查询安全事件，但不自动获得原始代码和凭据内容；
- 事件订阅者只能接收被授权的字段或脱敏投影；
- 外部连接器不得通过事件订阅绕过 Repository/Path 权限；
- 删除任务不能级联删除法定审计记录，删除协议由数据治理专项定义。

### 10.3 完整性保护

MVP 采用以下完整性基线：

- 事件使用服务端生成的时间、序列和 ID；
- 事实存储采用追加权限，不允许普通业务账号 UPDATE/DELETE；
- 每个事件保存规范化载荷哈希；
- 定期对事件序列计算链式摘要或分段 Merkle 摘要；
- 审计导出包含起止序列、事件数量和摘要；
- 完整性校验失败必须阻断回放和高风险交付，并生成安全告警。

链式哈希/Merkle 摘要是完整性校验方案，不替代访问控制，也不等于不可篡改存储；最终防篡改存储方式由 `REQ-SEC-*` 和部署设计确定。

---

## 11. 失败、恢复和回放边界

### 11.1 事件写入失败

- 事实写入失败：不对外确认状态变化，命令进入可重试或失败路径；
- 事实已提交但响应丢失：使用命令幂等键查询结果，不盲目再次产生业务副作用；
- Outbox 发布失败：事实保留，发布器重试；
- 投影更新失败：事实保留，投影器从最后成功序列继续；
- 事件校验失败：拒绝写入，记录结构化错误，不进入普通重试；
- 存储不可用：暂停依赖事实确认的业务 Action，不能仅靠内存状态继续执行。

### 11.2 回放语义

回放必须明确三种模式：

1. **状态重建回放**：只应用事件到投影，不执行工具、模型和外部副作用。
2. **诊断回放**：重建上下文、Action 和策略决策，所有外部工具调用默认为模拟或只读。
3. **评估回放**：使用固定模型、Prompt、Toolset、Policy 和索引版本进行对比，不产生真实 PR、推送或通知副作用。

默认禁止通过回放重新执行真实写操作。回放输出必须标记为 `REPLAY`，不能伪装成生产事件。

### 11.3 与 Checkpoint 的边界

- Event Log 是事实来源；
- Checkpoint 是恢复优化和状态快照；
- Checkpoint 必须绑定最后应用事件的 `sequence` 和哈希；
- 恢复时先校验 Checkpoint 完整性，再应用之后的事件；
- Checkpoint 与事件不一致时，丢弃该 Checkpoint 并从更早边界或完整事件流恢复；
- 具体保存时机、字段和损坏修复由 `REQ-RT-005` 设计。

### 11.4 与 RetryPolicy 的边界

事件记录失败结果、失败分类引用和重试安排事实，但不决定：

- 哪些错误可重试；
- 重试次数和退避算法；
- 是否创建新 Worker attempt；
- 如何保护外部副作用；
- 如何执行补偿。

这些行为由 `REQ-REL-001` 至 `REQ-REL-007` 负责。

---

## 12. MVP 范围与非目标

### 12.1 MVP 必须包含

- JSON Schema 语义的 Event Envelope 和核心事件 Payload；
- Task、Workflow、Worker、Action、Artifact、Evidence、Trace 引用；
- 追加式事实存储接口；
- 同一 Workflow 内的单调序列；
- Event ID、命令幂等键和消费者去重接口；
- 至少一次投递、Outbox/重发和死信处理边界；
- 事件类型版本和读取时迁移器接口；
- Issue 到 PR 的事件目录；
- 暂停、恢复、审批、取消、失败和 Kill Switch 事件；
- 敏感字段过滤、事件哈希和审计访问控制；
- 状态投影和 Checkpoint 模块的接口约束。

### 12.2 MVP 不包含

- 恰好一次跨系统交付；
- 任意事件动态注册；
- 自由文本事件作为跨模块协议；
- 回放时真实执行 Shell、Git Push、PR、通知或生产访问；
- 多区域主动-主动事件冲突合并；
- 自动推断缺失事件；
- 事件历史无限保留；
- 复杂跨 Workflow 分布式事务；
- 代码实现、部署实现和性能结果。

---

## 13. 验收与评测方案

### 13.1 Schema 契约测试

至少验证：

1. 缺少 `event_id`、`event_type`、`task_id`、`trace_id`、`sequence` 或 `payload_schema` 时拒绝；
2. 非法 ID、时间、枚举、序列和版本格式时拒绝；
3. 事件载荷不符合事件类型 Schema 时拒绝；
4. 跨组织、跨 Task、跨 Workflow 的引用不一致时拒绝；
5. 状态迁移事件缺少 `from_state`、`to_state`、Actor 或原因时拒绝；
6. Artifact/Evidence 事件缺少来源 Revision、内容哈希或 ContentRef 时拒绝；
7. 事件包含明显 Token、Private Key、密码或长期凭据模式时拒绝或脱敏；
8. 未知主版本不会被静默当作旧版本读取；
9. 迁移器输入输出版本不匹配时拒绝；
10. 同一事件重复提交不会产生第二条事实。

### 13.2 顺序和恢复测试

至少覆盖：

- 事件乱序到达时不会错误推进投影；
- 事件序列存在缺口时进入等待或告警；
- Outbox 重发不产生重复事件；
- 消费者崩溃后从最后成功序列继续；
- 投影损坏后可从事件流重建；
- Checkpoint 与事件哈希不一致时不会直接恢复执行；
- 事实提交成功但客户端超时时，重试命令返回原结果；
- 同一 Action 的不同 attempt 保留独立历史；
- 回放模式不会执行真实外部副作用；
- 未授权用户无法读取其他组织事件。

### 13.3 版本兼容测试

- 旧事件由新消费者读取结果与兼容基线一致；
- 新增可选字段不破坏旧消费者；
- 新增枚举值触发兼容性检查；
- 主版本不兼容事件被隔离而非静默解析；
- 读取时迁移是幂等的；
- 迁移保留原始版本、原始哈希和迁移器版本；
- 同一历史任务在固定迁移器和运行资产版本下能够复现到足够诊断的状态。

### 13.4 设计目标指标

以下为实现和评测目标，不是当前已达成的运行结果：

- 合法/非法事件 Schema 判断确定性：100%；
- 同一事实流序列唯一性：100%；
- 重复事件不产生重复投影效果：100%；
- 事件引用完整性错误可定位到具体字段的比例：不低于 95%；
- 典型事件写入确认 p95：目标小于 100ms，不含外部工具执行；
- 单任务事件回放结果与在线投影一致率：100%；
- 关键敏感字段拦截率：100%；
- 事件完整性校验失败能够阻断高风险回放和交付：100%。

正式阈值必须在 `REQ-RT-004`、`REQ-RT-005`、`REQ-REL-*` 和 `REQ-EVA-*` 完成后由统一评测集验证。

---

## 14. 方案比较与最终选择

### 方案 A：普通应用日志 + 当前状态表

不选择原因：

- 日志不是强类型事实源；
- 事件顺序、幂等和回放语义不明确；
- 状态表更新容易覆盖历史；
- 无法可靠支持暂停、恢复、审批和跨版本重放。

### 方案 B：消息队列作为唯一事实源

不选择原因：

- 消费保留和查询能力依赖具体中间件；
- 事件历史、审计留存、回放和投影边界容易混淆；
- 不能自动解决外部副作用幂等；
- 中间件替换会直接改变业务事实模型。

### 方案 C：追加式事实事件 + Outbox + 投影/订阅分离

**最终选择：方案 C。**

选择理由：

1. 与 `REQ-RT-001` 的实体和 Trace 坐标一致；
2. 与 `REQ-RT-002` 的状态事实/投影边界一致；
3. 吸收 OpenHands 的类型化追加事件和 Action/Observation 分离；
4. 吸收 LangGraph 的稳定运行标识、中断持久化和幂等恢复原则；
5. 吸收 Temporal 的 Event History、回放和运行版本治理原则；
6. 吸收 Jules 的 Activity、计划审批和异步状态表达；
7. 支持 MVP 先用 PostgreSQL + Outbox/队列实现，同时保留迁移到专用 Workflow Runtime 的接口；
8. 允许状态投影、审计、评估和 UI 独立演进，而不改变事实历史。

这只是基于公开证据和本项目约束的推荐基线，不代表未经本项目压力、故障注入和安全评测的全局最优解。

---

## 15. 与后续需求的接口约束

### `REQ-RT-004` 状态投影

必须：

- 只从事实事件更新 `status_projection`；
- 按事件序列、Schema 版本和父级引用校验；
- 支持从零重建和从 Checkpoint 增量重建；
- 保留最后应用的事件 ID、序列和版本；
- 不把投影修复写回旧事件。

### `REQ-RT-005` Checkpoint Protocol

必须使用：

- `workflow_id`、`worker_id`、`attempt`；
- 最后应用事件 `sequence`；
- 事件流或分段哈希；
- Artifact、Evidence、Revision 和预算引用。

Checkpoint 不能定义另一种事件或任务事实源。

### `REQ-RT-006` Trace 与审计关联

必须使用 Event Envelope 的 `trace_id`、`span_id`、`causation` 和 `correlation_id`，不得用审计日志另造一套执行 ID。

### `REQ-RT-007` Action 幂等

必须区分：

- 事件写入幂等；
- Action 提议幂等；
- 工具执行幂等；
- 外部副作用幂等。

Event ID 去重不能替代 Git、PR、通知、凭据和文件写操作的副作用保护。

### `REQ-REL-*`

失败事件、RetryScheduled、恢复和补偿事件必须引用本需求的 Event ID、Action ID、Worker attempt 和失败分类，但重试决策由可靠性模块负责。

### `REQ-OBS-*`

观测层可以异步订阅事件，但必须区分事实事件、运行日志、指标和 Trace；不得将指标回写为业务事实。

---

## 16. 设计决策记录

```text
需求编号：REQ-RT-003
功能点：Event Schema 与版本策略
当前状态：详细设计已完成，待跨模块冻结
前置依赖：REQ-RT-001、REQ-RT-002
候选方案：
  A. 普通应用日志 + 当前状态表
  B. 消息队列作为唯一事实源
  C. 追加式事实事件 + Outbox + 投影/订阅分离
公开证据等级：A
推荐基线：方案 C
选择理由：
  1. 支持不可变历史、状态重建、回放和审计
  2. 支持至少一次投递下的幂等消费
  3. 支持事件类型版本、读取时迁移和运行版本追踪
  4. 兼容 MVP 的 PostgreSQL + 队列实现方向
适用边界：
  单组织、单仓库、Issue 到 PR、有限 Workflow/Worker 并行
替代方案：
  Temporal Event History、LangGraph Checkpointer 或专用 Event Store
安全约束：
  默认拒绝跨组织读取；事件追加权限；敏感字段过滤；
  事件完整性校验；回放禁止真实外部副作用
失败与恢复：
  事实优先；Outbox 可重发；投影可重建；乱序和缺口不静默处理；
  Checkpoint 只作为恢复优化；失败分类和重试由 REQ-REL-* 负责
验收指标：
  Schema 确定性、引用完整性、序列唯一性、重复消费无重复效果、
  版本迁移可回放、敏感字段拦截、投影重建一致性
目标版本：REQ-RT-003 v0.1-designed
```

---

## 17. 版本和冻结条件

### 17.1 当前版本

`REQ-RT-003` 当前版本为 `v0.1-designed`。本需求已经完成事件信封、事件目录、顺序、投递、版本兼容、迁移、安全和验收设计，但仍需跨模块评审后才能升级为 `v1.0-frozen`。

### 17.2 升级到 `v1.0-frozen` 的条件

必须完成：

1. 与 `REQ-RT-001` 核心实体 Schema 的引用一致性评审；
2. 与 `REQ-RT-002` 状态迁移和完成条件的交叉评审；
3. 与 `REQ-RT-004` 状态投影、重建和乱序处理评审；
4. 与 `REQ-RT-005` Checkpoint 和恢复边界评审；
5. 与 `REQ-RT-006` Trace/审计字段映射评审；
6. 与 `REQ-RT-007` 和 `REQ-REL-006` 幂等边界评审；
7. JSON Schema/Protobuf 的承载方式和注册流程明确；
8. 事件存储、Outbox、消费者去重和死信机制完成 PoC；
9. Schema 契约、版本迁移、故障注入、权限和敏感数据测试设计完成；
10. 所有事件目录、字段和保留策略冲突解决后发布 `Runtime Contract v1.0-frozen`。

### 17.3 兼容规则

- 新增可选字段：小版本升级；
- 修改事件事实含义：主版本升级；
- 修改序列、因果、幂等或安全语义：主版本升级并全链路评审；
- 删除事件类型：先弃用，完成保留周期和消费者迁移后执行；
- 任何历史迁移都必须保留原始版本、哈希和迁移证据。

---

## 18. 设计结论

本需求最终采用：

> **类型化、不可变、追加式事件事实源 + 同一事实流单调序列 + 至少一次投递和幂等消费 + 显式版本迁移 + 状态投影/Checkpoint 分离。**

该方案能够覆盖 MVP 的任务创建、计划审批、Worker 执行、Action 授权、工具观察、测试验证、暂停恢复、失败取消、Diff/PR 交付和审计回放，并与 `REQ-RT-001`、`REQ-RT-002` 的共享坐标保持一致。

当前结论是推荐设计基线，不代表代码已经实现、事件存储已经部署、回放已经验证或指标已经达成。后续所有专项模块必须引用本需求的事件 ID、序列、版本、因果和 Trace 语义，不得重新建立平行事件模型。

---

## 19. 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| `v0.1-designed` | 2026-09-22 | 基于统一设计基线、REQ-RT-001/002 和 OpenHands、LangGraph、Temporal、Google Jules、GitHub Copilot Cloud Agent、OpenAI Codex Cloud 官方资料，完成 Event Schema、事件目录、顺序/投递、版本兼容、迁移、安全和验收设计 |
