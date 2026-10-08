# G01 运行时核心契约 — 下游消费接口参考

> 本文档不是新设计，而是对已完成设计（`REQ-RT-001` v0.2-designed、`REQ-RT-002` v0.1-designed、
> `REQ-RT-003` v0.1-designed）的**消费侧提炼**：把 G02~G24 组件在对接 G01 时真正需要的
> ID/枚举/状态表/事件目录抽出来放在一处，减少每个下游团队重复翻阅三份长文档。
>
> 若本文档内容与三份源设计冲突，以源设计为准；本文档任何修改不构成对源设计的变更。
>
> 来源：
> - [REQ-RT-001 核心运行时实体 Schema](REQ-RT-001-core-runtime-entities.md)（v0.2-designed）
> - [REQ-RT-002 状态机与迁移约束](REQ-RT-002-state-machines.md)（v0.1-designed）
> - [REQ-RT-003 Event Schema 与版本策略](REQ-RT-003-event-schema-versioning.md)（v0.1-designed）
> - 关联：[组件边界统一方案](COMPONENT-BOUNDARIES-UNIFIED.md) G01

---

## 一、核心实体与 ID 速查表

| 实体 | ID 类型 | 创建后不可变字段 | 可变投影字段 | 来源章节 |
|---|---|---|---|---|
| `AgentTask` | `TaskId`(UUIDv7) | `organization_id`/`project_id`/`repository_id`/`creator_id`/`base_revision`/`workflow_template_id+version` | `status_projection`/`working_revision`/`workflow_id` | RT-001 §5.1 |
| `Workflow` | `WorkflowId` | `task_id`/`workflow_template_id+version`/`agent_profile_version`/`toolset_version`/`base_revision` | `status_projection`/`working_revision` | RT-001 §5.2 |
| `Worker` | `WorkerId` | `workflow_id`/`task_id`/`step_id`/`worker_type`/`attempt`/`source_revision` | `status_projection` | RT-001 §5.3 |
| `Action` | `ActionId` | `task_id`/`workflow_id`/`worker_id`/`step_id`/`tool_name`/`source_revision` | `status_projection`/`policy_decision_id` | RT-001 §5.4 |
| `Artifact` | `ArtifactId` | 全部字段（内容变化=新ID） | 无 | RT-001 §5.5 |
| `Evidence` | `EvidenceId` | 全部字段（修正=新Evidence） | `expires_at` 相关撤销状态走事件 | RT-001 §5.6 |
| `TraceContext` | `TraceId`+`SpanId` | 全部 | 无 | RT-001 §5.7 |

**下游组件使用这些 ID 时的硬性约束**（RT-001 §8 不变量汇总）：
- 禁止重新发明替代 ID（如用自己的 `request_id` 代替 `action_id`）。
- 禁止用 UUID 的时间部分推断业务顺序 —— 业务顺序必须用 RT-003 的 `sequence`。
- Artifact/Evidence 内容变化 = 新对象，不允许原地修改。
- `source_revision` 必须是具体 commit SHA，不能是 `"latest"`/`"main"` 等动态引用。

---

## 二、四层状态机速查（RT-002）

### 2.1 状态集合对照表

| 层级 | 状态集合 | 终态 | 关键非终态语义 |
|---|---|---|---|
| **Task** | CREATED→AUTHORIZING→PLANNING→WAITING_APPROVAL→PREPARING_WORKSPACE→EXECUTING→VALIDATING→CREATING_PR→WAITING_REVIEW→COMPLETED；旁路 PAUSED/CANCELLED/FAILED | COMPLETED/CANCELLED/FAILED | VALIDATING 可退回 EXECUTING（Resolver 修复路径） |
| **Workflow** | CREATED→READY→RUNNING→WAITING_APPROVAL→PAUSED→COMPLETED/FAILED/CANCELLED | COMPLETED/FAILED/CANCELLED | 一个 Task 当前只允许一个活跃 Workflow（MVP 产品层限制，底层 Schema 保留历史多实例能力） |
| **Worker** | CREATED→READY→RUNNING→WAITING_APPROVAL→PAUSED→COMPLETED/FAILED/CANCELLED | COMPLETED/FAILED/CANCELLED | `attempt` 从 1 递增，新 attempt 不覆盖旧 Worker |
| **Action** | PROPOSED→AUTHORIZED/WAITING_APPROVAL/REJECTED→EXECUTING→SUCCEEDED/FAILED/CANCELLED | SUCCEEDED/FAILED/REJECTED/CANCELLED | `EXECUTING→SUCCEEDED` 仅代表工具执行层面成功，**不**代表 Worker/Workflow/Task 完成 |

### 2.2 跨层级下游组件必须遵守的"不能越级推断"规则

这是所有依赖 G01 的组件最容易犯错的地方（RT-002 §4、§10）：

```
Action=SUCCEEDED  ⇏  Worker=COMPLETED
Worker=COMPLETED  ⇏  Workflow=COMPLETED
Workflow=COMPLETED ⇏ Task=COMPLETED（Task 完成需额外满足 §2.3 的 9 条完成条件）
```

### 2.3 Task 完成条件（下游 G13/G19/G20/G23 判断"任务是否真正完成"时必须引用，不能自造判断逻辑）

1. 必需 Workflow 节点已结束
2. `source_revision` 可验证
3. 必需测试/质量检查已生成有效 Evidence
4. 所需审批已完成
5. Policy Gateway 无未解决拒绝
6. PR/交付 Artifact 已生成
7. 无未处理高风险问题/阻塞性评审意见
8. 预算/时间/范围未越界
9. 相关 Evidence 未撤销或过期

### 2.4 暂停/恢复/取消/失败的通用协议（所有组件对接审批、Kill Switch、恢复流程时的共同前提）

| 控制操作 | 允许来源状态 | 核心约束 |
|---|---|---|
| **暂停** PAUSED | 任意非终态（CREATED 除外，MVP不支持） | 阻止新业务 Action；保留全部引用；记录操作者+原因+trace_id |
| **恢复** | PAUSED → 原状态 | 必须重新校验：模板/Profile/Toolset 版本有效性、Policy、工作区版本、预算、Evidence 未失效；从**最近一致边界**继续，不得盲目回到起点 |
| **取消** CANCELLED | 任意非终态 | 不产生新业务 Action；允许受控清理/撤销凭据；历史不可覆盖；不能自动恢复 |
| **失败** FAILED | 恢复边界耗尽后 | 必须保留失败层级（Task→Workflow→Worker→Action→Tool/Env/Policy/Test），不能压缩成单一字符串；具体分类由 G04(REL-001) 负责 |

---

## 三、事件信封速查（RT-003）

### 3.1 Event Envelope 必填字段（所有组件产生/消费事件时的最小契约）

```
event_id (UUIDv7, 不可变) | event_type | event_type_version | event_category
task_id | organization_id | project_id | repository_id
workflow_id? | worker_id? | action_id? | step_id? | attempt?
trace_id (必填) | span_id? | parent_span_id?
source_revision?
actor (ActorRef) | occurred_at | recorded_at | sequence (服务端分配，单调递增)
causation (CausationRef) | correlation_id | idempotency_key?
payload_schema | payload (JsonObject)
data_classification | content_refs[] | redaction?
producer (ProducerRef) | extensions (SafeMetadata)
```

### 3.2 事件分类（7类，决定检索/权限/保留策略）

| 分类 | 用途 | 典型事件 |
|---|---|---|
| `DOMAIN` | 业务事实 | TaskCreated / ArtifactProduced / EvidenceProduced |
| `LIFECYCLE` | 实体生命周期 | WorkerStarted / WorkerCompleted / WorkflowFailed |
| `ACTION` | Action/工具生命周期 | ActionProposed / ActionAuthorized / ToolObserved |
| `CONTROL` | 人工/系统控制 | WorkflowPaused / ApprovalRequested / KillSwitchActivated |
| `OBSERVATION` | 执行结果 | ToolObserved / TestFinished / ScanFinished |
| `AUDIT` | 安全/策略/审计 | PolicyEvaluated / CredentialIssued / AccessDenied |
| `SYSTEM` | 运行时基础设施 | CheckpointCreated / ProjectionRebuilt / EventMigrated |

### 3.3 生产者权限边界（下游组件设计写事件接口时的强制约束）

| 生产者 | 允许写入 | 禁止写入 |
|---|---|---|
| `USER` | 创建/审批/暂停/恢复/取消/反馈 | 任何系统事实事件 |
| `WORKER` | ActionProposed / 结构化结果 / Artifact | `TaskCompleted`/`WorkflowCompleted`/`PolicyEvaluated` 等高权限事件 |
| `TOOL` | ToolStarted/ToolObserved | 状态迁移事实事件 |
| `SYSTEM` | 状态迁移/策略决策/投影/恢复/运行时事件 | — |
| `EXTERNAL_PROVIDER` | 外部回调（须用 `provider+external_event_id` 去重） | 直接写业务状态事实 |

### 3.4 MVP 事件目录索引（完整列表见 RT-003 §6，此处仅列各组件最常引用的子集）

| 组件会用到 | 相关事件 |
|---|---|
| G07 授权策略 / G13 重试决策 | `PolicyEvaluated`、`ActionAuthorized`、`ActionRejected`、`ApprovalRequested`、`ApprovalResolved` |
| G09 检查点幂等 / G18 补偿 | `CheckpointCreated`、`ActionSucceeded`、`ActionFailed`、`RetryScheduled` |
| G19 工具治理 | `ToolStarted`、`ToolObserved` |
| G20 Harness / G21 遥测审计 | `EventMigrated`、`KillSwitchActivated` |
| G10/G11 CTX、G20 压缩 | `ContextLoaded`、`ContextCondensed` |

### 3.5 顺序与投递语义（三条红线，下游组件实现消费者时必须遵守）

1. **事实优先**：事件必须先被事实存储确认，才能对外发布"已发生"；投影/通知失败不能回滚事实。
2. **至少一次 + 幂等去重**：用 `event_id` + 消费者名建立去重记录；序列缺口必须等待或告警，不能静默重排或丢弃。
3. **主版本隔离**：未知 `event_type_version` 主版本必须拒绝进入投影和执行路径，不能"猜测字段"硬解析。

---

## 四、对下游各组件的具体接口契约摘要

| 下游组件 | 必须复用的 G01 坐标/语义 | 禁止事项 |
|---|---|---|
| **G07** 授权策略(SEC-002/003) | `organization_id`/`project_id`/`repository_id`、Worker `allowed_tools`/`allowed_resources`、Action `target_resources`/`risk_level`/`policy_decision_id` | 不能把能力声明直接解释为授权结果 |
| **G09** 检查点幂等(RT-005/007) | `workflow_id`/`worker_id`/`attempt`、Artifact 引用、`source_revision`、事件 `sequence` | 不能定义另一套任务/事件实体 |
| **G13** 重试决策(REL-002/003/005) | `action_id`/`worker_id`/`attempt`/`source_revision`，后续 `idempotency_key` | 不能通过覆盖原 Action/Artifact 表达重试 |
| **G04** 失败分类(REL-001) | Action/Worker 的 `FAILED` 状态与失败层级（Task→Workflow→Worker→Action→Tool/Env/Policy/Test） | 不能压缩失败原因为单一字符串 |
| **G20** Harness 平台 | 全部核心实体 ID + Event Envelope；Harness 状态机独立，不复用被测系统状态机 | 不能让 Harness 自身状态与 G01 状态机产生循环依赖 |
| **G21** 遥测审计(OBS-*) | `trace_id`/`span_id`/`causation`/`correlation_id` | 不能另造一套执行 ID 替代 Trace 坐标 |
| **G06** 评估数据集(EVA-*) | Task/Workflow/Artifact/Evidence/Trace 及资产版本引用 | 不能只凭模型文字声明判断任务成功 |

---

## 五、仍待跨模块冻结的开放项（不阻塞下游启动，但需要在各自里程碑前对齐）

这些是三份源设计里明确标注"待后续需求定义"的接口占位，下游组件在 mock 阶段可以先用占位实现，但正式对接前必须回查对应需求是否已冻结：

| 开放项 | 占位于 | 实际归属 | 影响的下游组件 |
|---|---|---|---|
| Action 幂等键具体算法 | RT-001 §4.2 `idempotency_key` 字段仅保留引用 | RT-007 / REL-006 | G09、G18 |
| Checkpoint 字节格式与保存时机 | RT-003 §11.3 仅定义接口边界 | RT-005 / REL-004/005 | G09、G13、G18 |
| 失败分类枚举与识别算法 | RT-002 §5.4/§9.4 仅保留失败分支 | REL-001 | G04、G13、G23 |
| Policy DSL 与审批矩阵细节 | RT-002 §14 仅消费 `policy_decision_id` | SEC-002/003 | G07、所有涉及审批的组件 |
| Trace→OpenTelemetry Span 字段映射 | RT-003 §15 仅约束字段存在性 | RT-006 / OBS-001 | G05、G14、G21 |

---

## 六、变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 本次生成 | 首次从 RT-001/002/003 提炼下游消费接口参考，不改变任何源设计内容 |
