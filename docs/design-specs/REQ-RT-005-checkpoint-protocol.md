# REQ-RT-005 Checkpoint Protocol 详细设计

> 所属基线：`Runtime Contract v1`（已冻结，2026-10-07）
> 需求编号：`REQ-RT-005`
> 优先级：P0
> 设计版本：`v0.1-frozen`
> 设计状态：已冻结，可作为实现基线（跨模块评审通过，2026-10-07）
> 前置依赖：`REQ-RT-001`、`REQ-RT-002`、`REQ-RT-003`、`REQ-RT-004`
> 设计范围：Workflow 检查点语义、Schema、保存、校验、恢复、版本和安全边界
> 不包含：Failure Taxonomy、RetryPolicy、Action 幂等算法、外部副作用补偿、数据库 DDL

---

## 1. 需求定义

### 1.1 需求目标

建立面向 Workflow 运行恢复的不可变检查点协议，使任务能够在 Worker 崩溃、节点故障、用户暂停、审批等待、沙箱异常和事件历史过长等场景下，回到最近的安全一致边界。

检查点的定义是：

> 检查点是绑定已确认事件序列和运行资产版本的恢复优化快照，不是新的事实来源。

### 1.2 目标场景

- Worker 进程崩溃后恢复；
- 用户暂停后继续；
- 高风险 Action 审批后继续；
- Kill Switch 或系统故障后恢复；
- 检查点损坏后回退到更早边界；
- 长事件历史分段后增量恢复；
- 运行时版本升级后的兼容恢复。

### 1.3 非目标

本需求不负责：

- 替代 Event Store、状态投影或状态机；
- 决定哪些失败可以重试；
- 定义 Action 幂等键和外部副作用保护；
- 保存长期记忆、模型隐藏思维链或长期凭据；
- 定义完整上下文压缩算法；
- 定义数据库、队列或对象存储的具体实现。

---

## 2. 公开方案调研与采用原则

### 2.1 Temporal

Temporal 的官方资料将 Event History 定义为持久执行和恢复的事实依据，Worker 崩溃后通过回放重建状态；已完成 Activity 的结果来自历史，不在回放时重复执行。对于长历史，Continue-As-New 通过新运行承接显式状态。

采用原则：

- 检查点必须绑定 `workflow_id`、事实 `sequence` 和事件哈希；
- 恢复时使用检查点重建状态，再重放增量事件；
- 检查点不能删除或覆盖原始事件；
- 长历史必须有分段和保留边界。

来源：

- <https://docs.temporal.io/workflow-execution/event>
- <https://docs.temporal.io/workflows>
- <https://docs.temporal.io/workflow-execution/continue-as-new>

### 2.2 LangGraph

LangGraph 的官方资料将 Checkpointer 定义为线程级运行状态持久化机制，使用稳定的 `thread_id` 支持中断、恢复和时间回溯；已完成节点结果可以复用，但未完成节点可能重新执行，因此外部副作用必须具备幂等保护。

采用原则：

- 本项目使用 `workflow_id` 作为稳定运行身份；
- 恢复点必须明确，不能把任意内存位置当作安全边界；
- “已完成”“未开始”和“结果未知”的 Action 必须区分；
- 检查点不直接证明外部副作用已完成。

来源：

- <https://docs.langchain.com/oss/python/langgraph/checkpointers>
- <https://docs.langchain.com/oss/python/langgraph/persistence>
- <https://docs.langchain.com/oss/python/langgraph/interrupts>

### 2.3 OpenHands

OpenHands 的官方 SDK 将基础状态、追加式事件、Action 和 Observation 分开持久化，并支持识别没有对应 Observation 的未匹配 Action。

采用原则：

- 检查点只保存恢复引用和必要状态，不复制完整事件历史；
- 未匹配 Action 必须进入副作用核查流程；
- 恢复前必须检查工具集和运行配置兼容性；
- 暂停和恢复是正式运行语义，不是异常补丁。

来源：

- <https://docs.openhands.dev/sdk/guides/convo-persistence>
- <https://docs.openhands.dev/sdk/guides/convo-pause-and-resume>
- <https://docs.openhands.dev/sdk/arch/events>

公开资料只证明工程原则，不证明本项目已经达到相同的性能、可靠性或安全结果。

---

## 3. 最终推荐方案

采用：

> **事件事实源 + 不可变 Workflow Checkpoint + 事件增量重放 + Action 副作用核查 + 受控恢复协议。**

```text
Event Store
  -> 已确认的 Workflow sequence
  -> Checkpoint Builder
  -> 不可变 Workflow Checkpoint
  -> 校验 checkpoint hash
  -> 从 sequence + 1 重放事件
  -> 核查未完成 Action 的副作用
  -> 重新授权、校验预算和资源
  -> 继续执行或进入人工处理
```

核心决策：

1. Event Store 是唯一事实来源。
2. Checkpoint 只用于恢复优化，不能替代事件。
3. Checkpoint 创建后不可修改。
4. 恢复必须先校验检查点，再重放事件。
5. 未完成 Action 不得自动视为成功或未执行。
6. 外部副作用状态未知时，不得盲目重放。
7. 恢复可以创建新的 Worker attempt，但不能复用旧 Worker ID 覆盖历史。
8. 检查点恢复不得直接触发真实 Git Push、PR、通知或生产写操作。

---

## 4. Checkpoint Schema

以下为跨语言中立逻辑契约，不代表最终数据库或序列化实现。

### 4.1 检查点元数据

```text
WorkflowCheckpoint
- schema_version: "runtime.workflow-checkpoint.v1"
- checkpoint_id: CheckpointId
- task_id: TaskId
- workflow_id: WorkflowId
- organization_id: EntityId
- project_id: EntityId
- repository_id: EntityId
- created_at: Timestamp
- created_by: ActorRef
- checkpoint_reason: RUNNING | PAUSE | APPROVAL | RECOVERY | HISTORY_BOUNDARY
- checkpoint_status: CREATED | VERIFIED | INVALID | SUPERSEDED
- source_event_sequence: integer >= 0
- source_event_id: EventId
- source_event_hash: string
- event_stream_partition: string
- checkpoint_hash: string
- content_hash: string
- runtime_contract_version: string
- workflow_template_id: string
- workflow_template_version: string
- agent_profile_version: string
- toolset_version: string
```

### 4.2 状态快照

```text
StateSnapshot
- task_status: TaskStatus
- workflow_status: WorkflowStatus
- current_step_id: string?
- runnable_step_ids: string[]
- waiting_step_ids: string[]
- completed_step_ids: string[]
- failed_step_ids: string[]
- active_worker_refs: WorkerCheckpointRef[]
- completed_worker_refs: WorkerCheckpointRef[]
- pending_approval_refs: ApprovalRef[]
- unresolved_failure_refs: FailureRef[]
- required_artifact_refs: ArtifactId[]
- required_evidence_refs: EvidenceId[]
- base_revision: RevisionRef
- working_revision: RevisionRef?
- workspace_ref: WorkspaceRef?
```

状态快照必须能够由 `source_event_sequence` 重建，不能成为新的状态事实。`completed_step_ids` 不能单独证明外部副作用已完成。

### 4.3 Worker 恢复引用

```text
WorkerCheckpointRef
- worker_id: WorkerId
- step_id: string
- worker_type: WorkerType
- attempt: integer
- status: WorkerStatus
- source_revision: RevisionRef
- last_applied_event_sequence: integer
- last_completed_action_id: ActionId?
- pending_action_refs: ActionRef[]
- input_artifact_ids: ArtifactId[]
- output_artifact_ids: ArtifactId[]
- context_manifest_ref: ContentRef?
- worker_state_ref: ContentRef?
```

`worker_state_ref` 必须引用经过 Schema 校验的状态，不得保存模型隐藏推理、未脱敏环境变量或长期凭据。

### 4.4 Action 恢复引用

```text
ActionCheckpointRef
- action_id: ActionId
- worker_id: WorkerId
- attempt: integer
- action_type: ActionType
- tool_name: string
- tool_schema_version: string
- target_resource_hash: string
- source_revision: RevisionRef
- action_status: ActionStatus
- policy_decision_id: EntityId?
- idempotency_key_ref: string?
- observation_artifact_id: ArtifactId?
- side_effect_state: UNKNOWN | NOT_STARTED | IN_PROGRESS | CONFIRMED | FAILED
- recovery_action: VERIFY | REPLAY_SAFE | CREATE_NEW_ACTION | HUMAN_REVIEW
```

`side_effect_state` 只表达恢复决策所需的状态，不替代 `REQ-RT-007` 的幂等协议。

### 4.5 预算和资源引用

```text
BudgetSnapshot
- max_input_tokens: integer
- max_output_tokens: integer
- max_total_tokens: integer
- max_cost_microusd: integer
- max_duration_seconds: integer
- max_tool_calls: integer
- consumed_input_tokens: integer
- consumed_output_tokens: integer
- consumed_total_tokens: integer
- consumed_cost_microusd: integer
- elapsed_duration_seconds: integer
- completed_tool_calls: integer

ResourceSnapshot
- workspace_id: string
- workspace_image_version: string
- workspace_state_hash: string
- base_revision: RevisionRef
- working_revision: RevisionRef?
- branch_ref: ResourceRef?
- uncommitted_change_manifest_ref: ContentRef?
- generated_artifact_refs: ContentRef[]
- temporary_resource_refs: ResourceRef[]
- network_policy_version: string
- credential_refs: CredentialRef[]
```

`credential_refs` 只能是不可逆引用，不能保存凭据值。工作区必须通过 Revision、变更清单和哈希验证，不能仅凭路径恢复信任。

---

## 5. 检查点类型与保存时机

### 5.1 检查点类型

- `RUNNING`：Workflow 启动、Worker 启动前、Worker 完成后、周期性 Action 边界或事件历史接近上限时保存。
- `PAUSE`：用户暂停、系统暂停或 Kill Switch 时保存。
- `APPROVAL`：计划审批或高风险 Action 审批时保存。
- `RECOVERY`：恢复流程完成并形成新的安全边界后保存。
- `HISTORY_BOUNDARY`：事件历史分段或运行历史切换时保存。

### 5.2 保存前置条件

1. 获取 Workflow 最新事实序列；
2. 确认事件序列无缺口；
3. 确认状态投影不是不可恢复的 `BLOCKED`；
4. 确认父子实体引用完整；
5. 确认 Artifact/Evidence 可解析且版本一致；
6. 确认 Workspace 和 `working_revision` 可验证；
7. 执行敏感字段检测和脱敏；
8. 生成规范化内容并计算哈希；
9. 持久化检查点并验证哈希；
10. 追加 `CheckpointCreated` 事件。

`CheckpointCreated` 事件不能早于检查点内容持久化和校验成功。

### 5.3 原子性和存储定位

- 检查点写入成功但事件追加失败：标记为未发布，不得作为正式恢复点；
- 事件追加成功但客户端超时：通过命令幂等关联查询原结果；
- 检查点哈希校验失败：标记为 `INVALID`；
- 写入期间崩溃：不影响之前的有效检查点；
- 不使用覆盖 `latest` 文件或符号链接表达协议语义。

建议使用不可变对象路径：

```text
checkpoints/{organization_id}/{workflow_id}/{checkpoint_id}/manifest
checkpoints/{organization_id}/{workflow_id}/{checkpoint_id}/state
checkpoints/{organization_id}/{workflow_id}/{checkpoint_id}/content
```

最新检查点通过数据库索引或事实事件定位。

---

## 6. 恢复协议

### 6.1 恢复流程

```text
恢复请求
  -> 验证用户、任务和 Workflow 权限
  -> 读取候选 Checkpoint
  -> 校验 Schema、Hash、source_event_id 和 sequence
  -> 校验事件仍存在且哈希一致
  -> 校验 Workflow、Agent、Toolset 和 Sandbox 版本
  -> 恢复状态快照
  -> 从 sequence + 1 重放事件
  -> 核查未完成 Action 的副作用
  -> 重新校验权限、预算、策略和 Workspace
  -> 记录恢复事件
  -> 继续执行或进入人工处理
```

### 6.2 恢复前重新验证

至少验证：

- 用户、组织、项目、仓库和分支权限；
- Policy、Workflow、Agent Profile 和 Toolset 版本；
- Sandbox 镜像和网络策略版本；
- `base_revision`、`working_revision` 和 Workspace 哈希；
- 剩余 Token、费用、时间和工具预算；
- Artifact/Evidence 是否撤销或过期；
- 审批是否仍然有效；
- Kill Switch 状态；
- 凭据是否需要重新签发。

### 6.3 恢复点选择

候选检查点必须同时满足：

1. 状态为 `VERIFIED`；
2. 事件序列和哈希一致；
3. Schema 和运行资产版本兼容；
4. Workspace 状态可验证；
5. Task/Workflow 未进入不可恢复终态；
6. 未存在取消、Kill Switch 或权限撤销；
7. 未完成 Action 可以被安全分类。

最新检查点不满足条件时，标记为 `INVALID` 并回退到更早有效检查点。所有候选失败时，进入 `UNRECOVERABLE` 或人工处理，不能使用未验证的“latest”。

### 6.4 Worker Attempt

恢复可以继续原 Worker，也可以创建新的 Worker attempt：

- 原 Worker 状态和执行环境仍可验证时，可以继续；
- Worker 崩溃、环境销毁、Action 状态未知或配置不兼容时，创建新 Worker attempt；
- 新 attempt 必须保留原 Worker、Action、Artifact 和 Evidence 历史；
- 新 attempt 必须重新进行 Policy Gateway 授权；
- 不得复用旧 Worker ID 覆盖历史。

---

## 7. Action 副作用恢复边界

### 7.1 已确认成功

已有确定 Observation 或 Evidence 的 Action 不得重新执行，直接引用原结果并继续后续合法流程。

### 7.2 已确认未开始

可以创建新的 Action 或执行 attempt，但必须重新校验工具、目标资源、权限、预算和策略；原 Action 历史不得覆盖。

### 7.3 已开始但结果未知

必须按以下顺序处理：

1. 查询执行器或外部系统状态；
2. 使用幂等键查询已有结果；
3. 检查目标资源状态；
4. 检查 Git、文件、PR、通知或凭据副作用；
5. 能确认完成则引用原结果；
6. 能确认未完成则创建新 Action；
7. 无法确认则人工处理或审批；
8. 禁止盲目重放写操作。

只读 Action 可以在重新授权后重新执行，但仍须保留新的执行记录。文件写入、Commit、Push、PR、通知和凭据签发必须服从 `REQ-RT-007`、`REQ-REL-006` 的幂等与补偿协议。

---

## 8. 与其他需求的接口约束

### `REQ-RT-001`

必须复用 `task_id`、`workflow_id`、`worker_id`、`action_id`、`attempt`、Artifact、Evidence、Trace、Revision 和 Workspace 引用。

### `REQ-RT-002`

恢复必须回到合法状态：不能从 `COMPLETED` 或 `CANCELLED` 恢复执行；`PAUSED` 和部分 `FAILED` 状态必须重新校验后恢复；Action 成功不能直接推导 Task 完成。

### `REQ-RT-003`

`CheckpointCreated` 至少引用 `checkpoint_id`、`workflow_id`、`source_event_sequence`、`source_event_id`、`source_event_hash`、`checkpoint_hash`、原因、版本、ContentRef 和 Trace。检查点不能修改旧事件或生成替代事件流。

### `REQ-RT-004`

必须区分：

- `ProjectionCheckpoint`：投影消费者应用到的事件位置；
- `WorkflowCheckpoint`：Workflow 恢复所需的业务状态快照。

两者不能互相替代。

### `REQ-RT-007`、`REQ-REL-006`

本需求只保存幂等键引用和副作用状态，不定义幂等键算法、去重窗口、外部确认和补偿逻辑。

### `REQ-REL-004`、`REQ-REL-005`

`REQ-RT-005` 定义检查点协议和恢复边界；`REQ-REL-004` 负责失败场景下的保存时机、保留和清理策略；`REQ-REL-005` 负责失败分类下的恢复点判定和恢复失败处理。三者不得重复定义 Schema。

---

## 9. 安全、版本和数据治理

检查点禁止明文保存 API Key、Git Token、OAuth Refresh Token、私钥、密码、完整环境变量、模型隐藏思维链和未受控敏感代码。允许保存 CredentialRef、敏感级别、内容哈希、ContentRef、脱敏摘要、Artifact/Evidence 引用和运行资产版本。

检查点读取必须执行组织、项目、仓库、任务和敏感级别授权；检查点不能跨租户、跨 Workflow 或跨仓库迁移。

必须分离记录：

- `schema_version`：检查点结构版本；
- `runtime_contract_version`：运行时契约版本；
- `workflow_template_version`：工作流逻辑版本；
- `agent_profile_version`、`toolset_version`、`policy_version`、`sandbox_image_version` 和 `context_manifest_version`。

新增可选字段允许小版本升级；改变字段含义、状态语义、事件序列或哈希语义必须升级主版本并执行迁移评审。迁移不得修改原检查点，必须保留原始哈希、迁移器版本和结果哈希。

活跃任务保留最新有效检查点、暂停/审批/恢复检查点和未完成副作用相关检查点。完成任务可按数据治理策略归档，但事实事件、审计引用、恢复证据和迁移记录不能因清理检查点而丢失。

---

## 10. 故障处理

| 故障 | 处理原则 |
|---|---|
| 检查点写入失败 | 不确认 `CheckpointCreated`，保留上一有效点；必要时暂停任务 |
| 检查点哈希不一致 | 标记 `INVALID`，阻断恢复，回退并告警 |
| 事件已提交但检查点缺失 | 从上一检查点重放，不修改事实 |
| 检查点存在但事件缺失 | 检查点不可用，回退或从完整事件流恢复 |
| 工作区不一致 | 阻止写操作，重新创建或人工核查 |
| 运行资产不兼容 | 使用兼容版本、执行显式迁移或人工处理 |
| Action 副作用未知 | 幂等查询、资源核查或人工审批，禁止盲目重试 |

---

## 11. MVP 范围和验收标准

### 11.1 MVP 必须包含

- Workflow 级不可变检查点；
- 检查点与事实 `sequence`、事件 ID 和哈希绑定；
- Task、Workflow、Worker、Action 最小恢复状态；
- Artifact、Evidence、Revision 和 Workspace 引用；
- 完整性校验、失效和回退；
- 检查点到事件的增量重放；
- 暂停、审批、崩溃和恢复场景；
- 未完成 Action 的副作用状态分类；
- `CheckpointCreated` 事件；
- 检查点访问审计和故障注入测试。

### 11.2 验收标准

1. 检查点可以定位到唯一 Workflow 和事实序列。
2. 事件存在缺口时不能创建有效检查点。
3. 检查点被篡改后恢复被拒绝。
4. 恢复后可以正确重放 `sequence + 1` 之后的事件。
5. 已确认 Action 不因恢复而重复执行。
6. 状态未知 Action 进入副作用核查。
7. Worker 崩溃后可创建新 attempt 且历史不被覆盖。
8. 暂停恢复重新校验权限、版本、预算和 Workspace。
9. `ProjectionCheckpoint` 不会被当作业务恢复点。
10. 恢复和回放不产生真实 Git Push、PR、通知或生产副作用。
11. 检查点不包含明文凭据和模型隐藏思维链。
12. 未授权用户不能读取其他组织检查点。

目标指标，须经后续评测验证：

- 检查点 Schema 校验确定性：100%；
- 哈希篡改拦截率：100%；
- 已确认 Action 重复执行率：0；
- 检查点损坏安全回退率：100%；
- Worker 崩溃恢复成功率：目标不低于 99%；
- 检查点恢复耗时：p95 小于 5 秒；
- 检查点写入耗时：p95 小于 1 秒；
- 恢复产生未授权外部副作用：0。

### 11.3 必须评测的故障场景

- Worker 在检查点创建前后崩溃；
- 检查点写入成功但响应丢失；
- 检查点哈希被篡改；
- 事件序列存在缺口；
- Action 已开始但没有 Observation；
- Commit 或 PR 已产生但 Worker 在返回前崩溃；
- 用户暂停时存在运行中的 Shell；
- 恢复前权限、Toolset、Workspace 或凭据发生变化；
- 旧 Schema 检查点迁移；
- 投影检查点与 Workflow 检查点混淆；
- 恢复过程中触发 Kill Switch；
- 回放过程中禁止发送通知、Push 或创建 PR。

---

## 12. 设计决策记录

```text
需求编号：REQ-RT-005
功能点：Checkpoint Protocol
当前状态：详细设计已完成，待跨模块冻结
前置依赖：REQ-RT-001、REQ-RT-002、REQ-RT-003、REQ-RT-004
候选方案：
  A. 仅保存当前 Task/Worker JSON 状态
  B. 仅依赖完整事件历史
  C. 事件事实源 + 不可变 Workflow Checkpoint + 增量事件重放
公开证据等级：A
推荐基线：方案 C
适用边界：单组织、单仓库、Issue 到 PR、有限 Worker 并行
安全约束：默认拒绝；不保存长期凭据和隐藏思维链；未知副作用不得盲目重放
失败与恢复：按事件 sequence/hash 校验；损坏回退；工作区或副作用未知时核查或人工处理
验收指标：完整性、序列一致性、恢复成功率、重复副作用、恢复延迟和安全回放
目标版本：REQ-RT-005 v0.1-designed
```

---

## 13. 版本和冻结条件

升级到 `v1.0-frozen` 前必须完成：

1. 与 `REQ-RT-001/002/003/004` 的实体、状态、事件和投影交叉评审；
2. 与 `REQ-RT-006/007` 和 `REQ-REL-004/005/006` 的边界评审；
3. Checkpoint Schema、完整性、迁移和恢复契约测试；
4. 检查点损坏、事件缺口、Worker 崩溃和未知副作用故障注入设计；
5. 明确对象存储、数据库索引、归档和删除策略；
6. 验证恢复和回放不产生外部副作用；
7. 通过安全评审和统一评估门禁。

---

## 14. 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| `v0.1-designed` | 2026-09-22 | 基于统一设计基线以及 Temporal、LangGraph、OpenHands 官方资料，完成检查点 Schema、保存协议、恢复协议、Action 副作用边界、版本、安全和验收设计 |
