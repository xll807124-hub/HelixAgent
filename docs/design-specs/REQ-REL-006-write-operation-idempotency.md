# REQ-REL-006 写操作幂等封装详细设计

> 需求编号：`REQ-REL-006`  
> 模块：可靠性（REL）  
> 优先级：P0  
> 版本：`v0.1-designed`  
> 状态：详细设计已完成，待跨模块评审与冻结；未实现、未验证  
> 前置依赖：`REQ-RT-007`、`REQ-REL-001`、`REQ-REL-003`、`REQ-SEC-003`、`REQ-SEC-005`  
> 协同依赖：`REQ-REL-005`、`REQ-REL-007`、`REQ-RT-003`、`REQ-RT-006`、`REQ-RT-008`  
> 设计日期：2026-09-25

---

## 1. 结论摘要

本方案符合 Stripe、Temporal、Durable Task、Saga 以及成熟 Agent Harness 的共同工程基线，适合本平台的 Issue 到 PR 场景。行业公开资料共同支持以下事实：工作活动通常是至少一次执行；执行者可能在外部副作用完成后、回执上报前崩溃；幂等键必须由服务端或下游强制执行；补偿不是数据库回滚；持久编排逻辑必须可确定性重放。

本专项不采用以下替代方案：

- 不承诺跨 PostgreSQL、队列、Worker 和第三方 API 的端到端 exactly-once；
- 不以 Worker ID、容器实例、attempt、Trace ID 或时间戳作为幂等身份；
- 不以 Redis 作为唯一正确性来源；
- 不以固定“重试三次”作为通用安全判据；
- 不让 LLM 直接决定是否重放写操作；
- 不把读回成功或租约过期推断为外部写入未发生。

最终采用：**稳定逻辑意图键 + JCS/类型化规范化摘要 + 服务端上下文复核 + PostgreSQL 权威账本 + 租约 epoch/fencing + Effect Log/Outbox 原子边界 + 结果未知隔离 + 时间预算/SLA 对账 + 工具能力分级包装器**。

## 2. 目标、范围与非目标

### 2.1 目标

1. 同一逻辑写意图在重试、恢复、并发投递和 Worker 替换时最多产生一次可确认的正向副作用；
2. 对不支持幂等键的下游，使用条件写入、唯一业务键或独立权威查询降低重复风险；
3. 将租户、主体、策略、参数和资源版本绑定到结果复用条件，防止跨租户或过期授权重放；
4. 让文件、Git、PR、通知及未来连接器共享一致的包装器生命周期和审计格式；
5. 把“未知”作为一等状态，使系统宁可暂停或升级，也不盲目重放不可逆写入。

### 2.2 范围

覆盖文件写入、分支创建、commit、push、PR 创建/更新、通知发送、凭据撤销和任务专属资源清理。包装器负责意图身份、规范化、策略闸门、账本、租约、调用、结果确认、对账和证据关联；连接器负责具体协议和业务语义。

### 2.3 非目标

不定义通用数据库事务、第三方系统回滚、任意通知撤回、自动合并生产代码、支付/资金类操作或所有外部 API 的统一 exactly-once。`REQ-REL-007` 负责补偿工作流，不由本专项扩大补偿边界。

## 3. 行业基准与适配判断

| 基准 | 可确认原则 | 本平台采用方式 |
|---|---|---|
| Stripe | 同键重试返回原结果；同键参数不一致必须拒绝；键可能过期 | 账本保存请求摘要并做冲突拒绝；热缓存 TTL 仅为 24 小时，权威账本依恢复/审计/合规保留 |
| Temporal | Activity 至少一次；执行成功但回执丢失时会再次执行；写 Activity 应幂等 | 写入包装器在 Activity/Tool 边界强制复用逻辑键；Workflow 只编排，模型调用放在 Activity |
| Durable Task | Orchestrator 必须确定性；Activity 可能重复；工具应使用稳定 ID、upsert 或条件写入 | 规则、预算、状态迁移由版本化确定性规则集完成；LLM 只输出结构化失败分类与置信度 |
| Saga | 补偿需在正向动作前登记；补偿必须幂等，正向动作未发生时可 no-op | Effect Log 先登记；正向与补偿使用独立键、独立预算和审计；补偿失败升级人工 |
| Agent Harness | 状态、权限、工具和证据需持久化；外部副作用不能等同于对话恢复 | 以 Action/Effect Log/Policy/Evidence 作为共享锚点，Worker 身份不参与幂等键 |

结论：本平台应采用“幂等键 + 结果核查 + 补偿/人工接管”的组合，而不是试图建设一个跨边界的全局事务系统。额外增强点是 Agent 场景必须绑定授权上下文和资源版本，并防止同参数但不同业务意图被误合并。

## 4. 幂等身份与规范化

### 4.1 逻辑键组成

幂等键由服务端在首次派发前签发并持久化。`worker_id`、容器 ID、attempt、Trace ID、随机重试号和时间戳不参与身份。

```text
intent_scope = tenant_id + namespace + intent_invariant + action_class + intent_instance_id
key_material = intent_scope + server_nonce + schema_version
idempotency_key = UUIDv7(public_id) + HMAC(server_key, key_material)[0:n]
```

`intent_invariant` 表示稳定的业务意图，例如“为本任务创建目标 PR”，不是模型自然语言原文。不同独立意图即使参数相同也必须有不同 `intent_instance_id`。同一意图在 Worker 重启、Workflow 恢复和连接器切换时复用同一键。

### 4.2 请求规范化

规范化采用 RFC 8785 JCS 或等价的类型化 Schema 序列化，并固定 schema 版本、字段类型、Unicode、数字精度、集合排序和空值语义。

必须明确：

- **包含集**：租户、主体、动作、目标资源、源 revision、条件版本、业务唯一键、正文/内容摘要和影响范围；
- **排除集**：时间戳、Trace/Span、Worker/attempt、随机 nonce、重试原因、网络连接信息和易变展示字段；
- **等价类**：无序集合排序、字段缺省与显式默认值、大小写和路径规则必须按连接器 Schema 定义；
- **不可静默归一化**：业务上有意义的大小写、路径、数字精度或空值差异必须造成摘要变化并触发新意图或冲突。

账本保存 `params_hash`、规范化 Schema 版本、敏感字段摘要和必要的字段级证据，不在公开键和指标中暴露业务明文。

### 4.3 上下文复核闸门

命中既有结果前必须重新校验：`tenant_id`、`principal`、`resource_scope`、`policy_version`、`approval_ref/version`、`params_hash`、`source_revision`、连接器能力版本和 Kill Switch 状态。任何不一致均不得返回旧结果，按 `CONFLICT`、`REAUTH_REQUIRED` 或 `ESCALATED` 处理。

## 5. 六态账本与状态不变量

本专项的核心生命周期为：

- `PROCESSING`：已有有效租约，可能正在调用下游；
- `SUCCEEDED`：副作用有响应或可验证证据，结果可复用；
- `FAILED_RETRYABLE`：确认未产生副作用，且规则集允许在预算内复用原键；
- `FAILED_PERMANENT`：确定失败、权限/参数错误或策略禁止重试；
- `IN_DOUBT`：可能已到达下游但无法确认，冻结原键及依赖写操作；
- `EXPIRED`：达到策略有效期且已满足终结、归档、Legal Hold 和未决检查条件；过期不表示未执行。

`CONFLICT`、`RECONCILING`、`ESCALATED`、`COMPENSATING` 等作为账本事件/控制子状态记录，不覆盖六态正向事实。正向成功事实不得被补偿状态覆盖；`IN_DOUBT` 不得自动转换为失败。

终态不变量：`SUCCEEDED`、`FAILED_PERMANENT`、`EXPIRED` 的事实不可覆盖，只能追加后续补偿、对账或人工处置事件。存在 active lease、未解决 `IN_DOUBT`、Effect Log 未收敛、活动审批或 Legal Hold 时禁止 GC。

## 6. 租约、fencing 与原子边界

PostgreSQL 是权威账本。首次预留、Effect Log 登记、Outbox 派发意图和租约领取必须在一个事务边界内完成，或通过等价的事务消息协议保证可恢复性。

租约字段至少包括：`lease_owner`、`lease_expires_at`、单调递增 `fencing_token`、`lease_epoch` 和 `attempt_id`。所有状态写入、完成回执和连接器更新都必须携带当前 fencing token；旧 Worker 即使恢复联网，也不能覆盖新租约或推进状态。租约过期只允许触发核查，不允许直接接管写操作。

并发领取采用唯一约束、条件更新/CAS 和事务锁；第二个调用者只能读取已有状态、等待、返回处理中或进入对账，不能绕过领取执行。

## 7. 统一包装器流程

```text
Action 提议
  -> Policy Gateway 最终裁决与审批复核
  -> 类型化规范化 + params_hash
  -> 服务端签发/加载逻辑幂等键
  -> PostgreSQL 原子预留 + Effect Log + Outbox
  -> lease_epoch/fencing 领取
  -> 连接器执行（原键/业务唯一键/条件写入）
  -> 保存响应、下游 ID、Evidence、事件
  -> SUCCEEDED / FAILED_RETRYABLE / FAILED_PERMANENT / IN_DOUBT
  -> 同键请求做上下文复核并返回结果或等待
```

响应命中既有成功记录时必须带 `X-Idempotent-Replay: true`，并传播 `idempotency_key` 的不可逆引用、结果状态和 Evidence 引用。该头用于计费、重复投递和重试放大指标去耦，不作为授权依据。

## 8. 连接器能力分级

| 能力级别 | 下游条件 | 自动行为 |
|---|---|---|
| A：原生幂等 | 支持同键并返回原结果 | 同键重试；同键异参拒绝 |
| B：可验证条件写 | 不支持同键，但支持唯一业务键、版本前置条件或 upsert | 先查/条件写；读回确认；未知时冻结 |
| C：可查询不可幂等 | 有权威查询但无条件写 | 仅允许核查和受控恢复；不得盲写 |
| D：不可安全重放 | 无幂等、无唯一约束、无权威查询 | 禁止自动重试；人工审批和现场保全 |

连接器能力、查询权威源、条件写语义、结果保留期和风险等级必须版本化注册。切换供应商不能天然消除未知状态；只有共享同一去重语义并通过策略验证时才允许切换。

### 8.1 文件

以 workspace、路径、目标内容 hash、当前 revision 和 owner 组成条件。目标内容已存在则安全 no-op；当前 revision 与预期不符则冲突，不覆盖外部修改。保存前后 hash、文件范围和 Evidence。

### 8.2 Git

分支创建使用任务/意图级唯一业务键并校验指针；commit 使用 tree hash、父 commit 和受控消息摘要；push 使用 expected remote revision/compare-and-swap，远程已存在目标 commit 时返回复用结果，分叉时进入冲突或人工处理。

### 8.3 PR

以仓库、源分支、目标分支和逻辑意图绑定的业务键查询现有 PR。标题或描述变化不能覆盖既有意图；实质变化建立新意图。创建、更新、关闭分别使用独立 Action 键并保存远程 PR ID。

### 8.4 通知

通知服务优先使用平台键；否则使用收件人、模板版本、业务事件 ID 和正文摘要的去重键。无法证明去重时不得把通知重试伪装成成功；通知是否阻断主流程由 Policy 明确声明。发送后无回执进入 `IN_DOUBT`，不得仅因客户端超时再次发送。

## 9. 失败、对账与 Temporal 规则

LLM/模型可在 Activity 中提供结构化失败分类、证据和置信度，但不能决定是否执行写重放。重试由确定性、版本化规则集消费 `time_budget_ms`、`cost_budget`、`hard_cap_attempts`、风险等级、连接器能力、审批有效期和全局预算后决定。`hard_cap_attempts` 只是保险丝，不能替代时间预算。

`IN_DOUBT` 时：

1. 冻结原键、相关资源和依赖写步骤；
2. 通过与执行通道、凭据和限流桶正交的只读通道查询权威真相源；
3. 使用风险分档 `reconcile_deadline`、总 time budget 和服务端 Retry-After 安排探测；
4. 确认已执行则转 `SUCCEEDED`，确认未执行且授权仍有效才可复用原键；
5. 超出预算、证据冲突或无权威源则保持未知并 `ESCALATED`；
6. 不因 lease 过期、Redis TTL 到期、查询失败或 Workflow 重放而新建键。

Temporal/持久工作流中的 Workflow 逻辑必须纯、确定性、可离线重放；时间、随机数、网络、LLM 和实际写入都在 Activity/Tool Adapter 中执行。每次预算消耗、状态迁移和对账决策都持久化，避免“恢复时重新计算出另一条写路径”。

## 10. 数据保留、GC 与安全

- Redis 仅保存 24 小时热索引/结果加速；丢失、驱逐或 TTL 到期不得判定未执行；
- PostgreSQL、Effect Log、事件、Checkpoint、Evidence 至少覆盖恢复窗口、对账窗口和审计要求；冷 retention 基线不低于 180 天；
- active lease、未解决 `IN_DOUBT`、未收敛 Effect Log、Legal Hold、活动审批或审计关联存在时禁止清理；
- 键不可作为访问凭证；所有查询按租户、主体和资源权限过滤；敏感参数只保存摘要或受控引用；
- 账本、审计、Trace 和指标分离，幂等键不作为高基数标签；
- PostgreSQL 不可用时，有副作用动作 fail-closed；Redis 不可用时回源 PostgreSQL。

## 11. 观测指标

至少包括：`idempotency_replay_total`、`same_key_conflict_total`、`duplicate_side_effect_total`、`in_doubt_total`、`in_doubt_duration`、`reconcile_confirmed_executed_rate`、`reconcile_confirmed_not_executed_rate`、`reconcile_escalation_rate`、`fencing_rejection_total`、`stale_lease_write_total`、`connector_capability_distribution`、`write_retry_amplification`、`gc_protection_block_total` 和按动作类别/租户聚合的失败率。

目标是重复正向副作用为 0、同键异参拦截率 100%、未知状态未经核查重放为 0。延迟、对账窗口和告警阈值需通过压测与故障注入后冻结，不以文档候选数值冒充实测 SLO。

## 12. 验收标准

1. Worker 替换、进程崩溃、重复消息和 Workflow 重放不会产生第二个有效写入者；
2. 同键同摘要且上下文有效时返回原结果并带 `X-Idempotent-Replay: true`；同键异摘要必拒绝并审计；
3. `worker_id`、attempt、Trace、时间戳和重试原因变化不改变逻辑键；不同意图不因参数相同而误合并；
4. JCS/类型化规范化的等价和非等价样例均通过契约测试；
5. 租约过期、fencing token 冲突和旧 Worker 回写均被拒绝；
6. PostgreSQL 原子边界保证账本、Effect Log 和 Outbox 不出现不可解释的半状态；
7. 文件、Git、PR、通知分别通过能力级别对应的条件写、查询或人工升级路径；
8. 下游回执丢失进入 `IN_DOUBT`，不因 TTL 或重启创建新键；
9. 对账遵循时间预算和风险 SLA，确认未执行后才允许原键恢复；
10. Temporal/持久 Workflow 离线重放结果稳定，LLM 不能改变写重放裁决；
11. 六态迁移、终态不可变、GC 保护谓词和 Legal Hold 均有契约测试；
12. 跨租户、主体、策略版本、参数摘要和资源 revision 不一致时旧结果不可复用；
13. 指标能够区分首次成功、幂等回放、重复投递、未知状态和人工升级；
14. 故障注入覆盖“外部成功后 Worker 崩溃”“连接超时”“响应丢失”“Redis 丢失”“数据库切换”“旧租约回写”和“连接器切换”。

## 13. MVP 与后续演进

MVP：PostgreSQL 权威账本、Redis 24 小时热层、服务端键签发、JCS/类型化规范化、上下文复核、租约 fencing、Effect Log/Outbox 原子边界、文件/Git/PR/通知四类包装器、A-D 能力目录、IN_DOUBT 对账与人工升级、180 天冷留存基线。

后续：跨 Workflow 业务唯一约束、更多连接器原生幂等、自动化对账适配器、租户级 SLA、Saga 补偿目录、跨区域账本和更丰富的结果证明。任何跨区域 exactly-once 或不可逆外部操作自动回滚都必须作为独立架构评审项。

## 14. 决策记录

| 决策 | 结论 |
|---|---|
| 身份 | `namespace + intent_invariant + server-signed fingerprint`；排除 Worker ID |
| 参数 | JCS/类型化 Schema，显式包含集/排除集/等价类 |
| 上下文 | tenant、principal、policy、approval、params、resource revision 必须复核 |
| 生命周期 | PROCESSING、SUCCEEDED、FAILED_RETRYABLE、FAILED_PERMANENT、IN_DOUBT、EXPIRED |
| 并发 | lease epoch + monotonic fencing token + CAS/唯一约束 |
| 存储 | PostgreSQL 权威；Redis 仅 24 小时热层 |
| 对账 | 时间预算、独立通道、风险 SLA；不以固定次数作为安全判据 |
| 编排 | Workflow 纯确定性；LLM 只在 Activity 分类；规则集决定重试 |
| 补偿 | 独立幂等键、预算、策略和审计；失败升级，不覆盖正向事实 |
| 留存 | 冷 retention 至少 180 天；活动租约、未决未知和 Legal Hold 禁止 GC |

## 15. 参考资料

- [Stripe Idempotent requests](https://docs.stripe.com/api/idempotent_requests)
- [Temporal Activity Definition](https://docs.temporal.io/activity-definition)
- [Temporal Error Handling](https://docs.temporal.io/best-practices/error-handling)
- [Temporal Saga Pattern](https://docs.temporal.io/design-patterns/saga-pattern)
- [Temporal Distributed Transaction Patterns](https://docs.temporal.io/design-patterns/distributed-transaction-patterns)
- [Durable Task Programming Model](https://learn.microsoft.com/en-us/azure/durable-task/common/programming-model-overview)
- [Durable Task Error Handling](https://learn.microsoft.com/en-us/azure/durable-task/common/durable-task-error-handling)
- 项目内：`REQ-RT-007`、`REQ-REL-003`、`REQ-REL-005`

## 16. 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| `v0.1-designed` | 2026-09-25 | 完成行业基准分析；采用稳定逻辑意图键、规范化摘要、上下文复核、六态生命周期、fencing lease、原子账本边界、能力分级、时间预算对账、确定性 Workflow 和 180 天冷留存基线 |
