# REQ-REL-003 重试决策引擎详细设计

> 版本：v0.2-designed
> 优先级：P0
> 状态：详细设计已完成，待跨模块评审与冻结；未实现、未验证
> 所属模块：可靠性（REL）
> 前置依赖：REQ-REL-001（失败分类）、REQ-REL-002（重试策略）、REQ-RT-007（幂等键与副作用边界）、REQ-SEC-003（Policy Gateway）、REQ-SEC-009（Kill Switch）
> 下游依赖：REQ-REL-004/005/006/007/008/009、REQ-HAR-003、REQ-OBS-003
> 用户确认日期：2026-09-24（采用三分支待决队列、分层计数器、Policy Gateway 预裁决、三值对账状态机）

---

## 1. 目标与范围

### 1.1 核心目标

实现确定性重试决策引擎，将 REL-001 的失败症状分类结果与 REL-002 的重试策略配置转化为可执行的重试/降级/升级/终止指令。

**核心价值主张**：
- **拒绝优于猜测**：不确定性时默认拒绝，绝不依赖模糊推理
- **决策原子且不可变**：每次决策独立，决策结果不可撤销
- **幂等键决定一切**：重试身份由幂等键确定，不依赖参数或上下文
- **先写日志后执行**：所有决策必须先持久化，再执行副作用
- **每步都有明确失败分支**：决策流程的每一步都必须有预定义的失败处理

### 1.2 设计边界

**包含**：
- 11 步确定性决策流程
- 症状-策略匹配与优先级路由
- 三层存储熔断器（进程内缓存 + Redis + PostgreSQL）
- 双层阈值全局预算（告警阈值 vs 拒绝阈值）
- 声明式降级链配置与 privilege_monotone 约束
- 分档审批 SLA 与超时默认拒绝
- 分检测器置信度校准与风险分层决策档位
- 幂等闸门三分支、IN_DOUBT 锁键与待决队列
- 连续失败与窗口失败率分离，按 downstream × action_type × tenant 隔离
- Policy Gateway 预裁决、低优先级提前限流和网关独立有限重试
- 三值对账状态机、独立只读探测、权威真相源前置校验与风险分档 SLA
- 幂等键从签发到归档的完整生命周期治理

**不包含**：
- 决策引擎自身的故障恢复（由基础设施保障）
- LLM/ML 辅助的动态决策（纯规则引擎）
- 跨区域全局预算同步（V2+ 特性）

---

## 2. 设计原则与铁律

### 2.1 决策引擎铁律

| 铁律 | 说明 | 违反后果 |
|------|------|---------|
| **拒绝优于猜测** | 不确定性时默认拒绝，绝不依赖模糊推理或模型猜测 | 未知错误触发重试雪崩 |
| **决策原子且不可变** | 每次决策独立，决策结果不可撤销 | 决策链路无法审计 |
| **幂等键决定一切** | 重试身份由幂等键确定，不依赖参数或上下文 | 同键异参被误去重 |
| **先写日志后执行** | 所有决策必须先持久化，再执行副作用 | 决策链路丢失 |
| **每步都有明确失败分支** | 决策流程每步必须预定义失败处理 | 异常处理不一致 |

### 2.2 降级铁律（privilege_monotone）

| 铁律 | 说明 | 违反后果 |
|------|------|---------|
| **privilege_monotone** | 降级只能收窄能力或增加人工环节，绝不能横向扩权 | 配置错误导致提权漏洞 |
| **降级链耗尽 ≠ 静默成功** | 必须返回明确错误码与用户可见原因，绝不静默成功 | 合规事故、用户欺骗 |
| **降级抑制（throttle）** | 同一会话/租户在窗口内降级 N 次后停止自动降级，转人工 | 降级链成为热点 |
| **降级服务自身不可用** | fail-closed + 快速失败，但不等于全平台停摆 | 降级系统成为单点 |

### 2.3 幂等闸门与待决队列铁律

1. 幂等闸门必须先判断是否存在合法幂等键，以及目标下游是否支持幂等重放；两者决定后续路径，不得统一套用单一超时策略。
2. `IN_DOUBT` 期间必须锁定幂等键。同一键在结果查明前不得产生任何新尝试；锁的释放只能由权威账本确认、人工处置或明确终态驱动。
3. 幂等查询超时进入待决队列，返回可区分的冲突/等待语义。对外幂等请求的并发占用可返回 `409 Conflict` 与 `retry_after`；内部决策服务故障不得伪装成 409，必须 fail-closed 并记录依赖故障。
4. 本地裁决缓存只能命中明确的 `DENY`，TTL 不超过 30 秒；`ALLOW`、`REQUIRE_APPROVAL`、缓存缺失或缓存失效必须回源，缓存只能收紧不能放宽。

### 2.4 计数器作用域铁律

1. 连续失败计数器与窗口失败率计数器职责互斥，不得用一个计数器同时承担永久失败识别和下游退化识别。
2. 两类计数器的稳定主键均为 `schema_version + namespace + downstream + action_type + tenant`；用户输入资源必须先规范化，不能直接作为桶键。
3. `task_id` 只作为单任务快速失败与逃生阈值，不替代租户/下游/动作作用域。
4. 连续失败命中永久性失败模式时直接中止当前同类重试；窗口失败率命中退化阈值时触发熔断、切流或限流。两者状态和告警必须分开记录。

### 2.5 Policy Gateway 超时铁律

1. Policy Gateway 默认 fail-closed；网关自身最多进行两次、仅针对瞬态故障的独立重试，且不计入业务 Action 的重试预算，也不允许业务层再次包装重试。
2. 当网关延迟进入黄色区间时，提前限制批处理和非实时连接器等低优先级动作，保护核心路径；达到超时后受保护动作快速拒绝或挂起。
3. 预裁决只能用于限流、排队和容量保护，不能作为最终执行许可；副作用发生前必须取得当前有效 Policy Decision。

### 2.6 对账铁律

1. 只有存在可查询的权威真相源、事件日志或审计轨迹的动作才允许自动对账；否则直接 `ESCALATE`，不做乐观假设。
2. 对账探测必须与执行通道、凭据和速率限制桶正交，且只读；不得由同一故障路径自证恢复。
3. 对账状态只有 `CONFIRMED_EXECUTED`、`CONFIRMED_NOT_EXECUTED`、`IN_DOUBT` 三值；`IN_DOUBT` 冻结原键和所有依赖写操作，查不明则人工升级。
4. 对账窗口按风险分档，不能使用单一默认值；执行日志、快照和幂等账本保留期必须覆盖对账窗口，至少与运营档 90 天、取证档冷存 180 天的适用下限协调。

### 2.7 幂等键生命周期铁律

幂等键必须经历签发、绑定主体/工具/规范化参数摘要/策略版本、有效期控制、`pending`/`executing`/`failed`/`in_doubt` 状态迁移、最终态不可变和到期归档。TTL 到期、缓存丢失或租约过期都不能证明副作用未发生。

### 2.8 审批铁律

| 铁律 | 说明 |
|------|------|
| **超时默认拒绝** | 审批超时默认行为永远是「拒绝/挂起」，绝不能是「默认批准」 |
| **真重试判据** | 这次重试必须是同一个幂等键、同一参数、同一审批上下文 |
| **幂等键决定一切** | 重试身份由幂等键确定，不依赖参数或上下文 |

---

## 3. 系统架构

### 3.1 整体架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           决策引擎入口                                   │
│                    receive DecisionRequest                               │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Step 1: 输入验证                                                          │
│ - 验证必填字段存在                                                        │
│ - 验证 symptom 格式合规                                                   │
│ - 验证 idempotency_key 有效性                                           │
│ ✗ VALIDATION_ERROR → TERMINATE                                         │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Step 2: 幂等闸门与待决队列                                               │
│ - 先判断合法幂等键、下游幂等重放能力和账本状态                           │
│ - 已确认成功 → 复用结果；明确未执行 → 进入后续闸门                       │
│ - 结果未知/查询超时 → 锁定原键，进入待决队列，不产生新尝试               │
│ - 无合法键或下游不支持重放 → 仅允许可验证条件写入，否则升级人工         │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Step 3: 症状匹配                                                         │
│ - 检查 symptom 是否在 retryable_symptoms                                 │
│ - 检查 symptom 是否在 non_retryable_symptoms                             │
│ - non_retryable 优先                                                    │
│ ✗ 无匹配策略 → TERMINATE (拒绝优于猜测)                                  │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Step 4: 置信度校验                                                       │
│ - 分检测器校准（Platt scaling / isotonic regression）                    │
│ - 证据充分性门控（evidence_count / detector_tier）                       │
│ - 置信度低于阈值 → ESCALATE                                             │
│ ✗ 置信度不足 → ESCALATE (拒绝优于猜测)                                  │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Step 5: Policy Gateway 预裁决与最终校验                                  │
│ - 读取预裁决健康状态，仅用于低优先级限流/排队和容量保护                 │
│ - Gateway 自身最多两次、仅瞬态错误重试，独立于业务预算                   │
│ - 副作用前必须取得当前有效最终裁决；超时默认 DENY/挂起                 │
│ - 无有效审批 → ESCALATE                                                  │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Step 6: 分离计数器与熔断器检查（Redis + PostgreSQL + 进程内缓存）        │
│ - 连续失败计数器：识别永久性失败并中止同类重试                         │
│ - 窗口失败率计数器：识别下游退化并触发熔断/切流/限流                   │
│ - Key = schema_version + namespace + downstream + action_type + tenant │
│ - OPEN → CIRCUIT_OPEN；HALF_OPEN → 仅允许受控探测                     │
│ ✗ 熔断器打开 → CIRCUIT_OPEN (拒绝优于猜测)                             │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Step 7: 预算推导                                                         │
│ - 计算 time_budget_ms / cooldown_base_ms                                 │
│ - effective_max = min(calculated, hard_cap)                             │
│ ✗ current_attempt >= effective_max → BUDGET_EXHAUSTED                   │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Step 8: 全局重试预算检查（双层阈值 + 双轨窗口）                          │
│ - 告警阈值：retry_rate > 10% → 记录 WARNING                            │
│ - 拒绝阈值：retry_rate > 15% → BUDGET_EXHAUSTED                       │
│ ✗ 预算耗尽 → BUDGET_EXHAUSTED (拒绝优于猜测)                           │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Step 9: 降级链检查（声明式配置 + privilege_monotone）                   │
│ - 检查降级链声明                                                        │
│ - 验证降级不扩权（属性测试证明）                                        │
│ - 检查降级抑制（throttle 窗口）                                         │
│ ✗ 降级不可用 → fail-closed                                              │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Step 10: 决策路由                                                        │
│                                                             │
│ ┌─────────────────┐    ┌─────────────────┐               │
│ │ 可重试 + 预算足 │ → │ RETRY + 计算延迟 │               │
│ └─────────────────┘    └─────────────────┘               │
│                                                             │
│ ┌─────────────────┐    ┌─────────────────┐               │
│ │ 有降级链 + throttle未触发│ → │ FALLBACK         │               │
│ └─────────────────┘    └─────────────────┘               │
│                                                             │
│ ┌─────────────────┐    ┌─────────────────┐               │
│ │ 高风险 + 无审批  │ → │ ESCALATE         │               │
│ └─────────────────┘    └─────────────────┘               │
│                                                             │
│ ┌─────────────────┐    ┌─────────────────┐               │
│ │ 预算耗尽/熔断开  │ → │ TERMINATE        │               │
│ └─────────────────┘    └─────────────────┘               │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Step 11: 先写日志后执行                                                  │
│ - 发布 RetryDecisionMade 事件到事件流                                    │
│ - 等待事件持久化确认                                                    │
│ - 更新熔断器计数器（如适用）                                            │
│ - 更新全局重试预算（如适用）                                            │
│ ✗ 事件发布失败 → fail-closed，决策无效                                  │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                           决策引擎出口                                   │
│                    return DecisionResponse                               │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 4. 权威决策补充规则

### 4.1 幂等闸门三分支与待决队列

幂等闸门不把所有超时归入同一种结果，而是依据两个事实分流：是否存在合法幂等键，以及下游是否支持同键幂等重放。

| 分支 | 必要条件 | 自动行为 | 超时行为 |
|---|---|---|---|
| A：可安全重放 | 合法幂等键；下游支持同键重放；账本确认未执行或失败且无副作用 | 通过后进入熔断、预算和策略闸门，重试复用原键 | 原键锁定，进入待决队列；不生成新键 |
| B：可验证但不支持重放 | 合法幂等键或稳定业务唯一标识；下游不支持同键重放，但存在条件写入或权威查询 | 只能先核查/条件写入；未取得验证不得自动重试 | `IN_DOUBT`，冻结原键和依赖写步骤；超过风险窗口升级 |
| C：不可安全重放 | 无合法键，或下游既不支持重放也没有权威查询/事件轨迹 | 禁止自动重试，直接升级人工 | 不返回“可重试”语义；保全现场并保持未知 |

查询超时本身不等于副作用未知，但如果原操作可能已到达下游，则账本状态必须进入 `IN_DOUBT`。对外幂等入口发生同键并发占用时可返回 `409 Conflict` 与 `retry_after`；内部决策引擎不可用时必须使用内部依赖故障语义，不能伪装成幂等冲突。

待决队列至少记录原键、租户、下游、Action、请求摘要、策略版本、锁定时间、风险级别、下次探测时间、探测通道、保留截止时间和升级责任方。待决期间同键的新请求只读已有状态或返回等待，不得创建新执行者。

### 4.2 三值对账状态机

对账只读、独立于执行通道，并且必须在进入自动对账前验证下游存在可查询的权威真相源。状态迁移为：

- `IN_DOUBT` → `CONFIRMED_EXECUTED`：取得下游资源 ID、事件或审计证据，且与原请求摘要和主体绑定事实一致。
- `IN_DOUBT` → `CONFIRMED_NOT_EXECUTED`：权威真相源确认请求未生效；重新检查 Policy、审批、预算和原键有效期后，才可复用原键恢复。
- `IN_DOUBT` → `ESCALATED`：超过风险分档对账窗口、探测通道不可用、证据冲突或不存在权威真相源。

`CONFIRMED_EXECUTED` 和 `CONFIRMED_NOT_EXECUTED` 是正向对账结论，不覆盖原始 `IN_DOUBT` 事实。不能查询的动作直接进入 `ESCALATED`，不得使用乐观“未执行”假设。

探测必须使用与执行正交的只读通道、不同的凭据作用域和独立限流桶；探测失败不得触发执行通道重试。对账窗口按风险分档配置，具体数值需由基准评测冻结，且执行日志、Checkpoint、事件和幂等账本的保留期必须覆盖该窗口。

### 4.3 分离计数器与作用域

连续失败计数器用于快速识别稳定的永久性失败模式；窗口失败率用于识别下游退化和抖动。两者必须独立清零、独立告警、独立审计，不能互相覆盖。

- 连续失败计数器：同一稳定键下，同一永久性失败模式连续出现即中止同类重试；成功或明确换用新配置后按规则清零。
- 窗口失败率计数器：按滑动时间/请求窗口统计失败比例和慢调用比例；达到阈值时触发熔断、切流或限流，不直接判断单次失败是否永久。
- 统一稳定键：`schema_version + namespace + downstream + action_type + tenant`。资源标识如参与细分，必须先按连接器规范化；`task_id` 仅用于单任务逃生阈值。
- 计数器状态必须绑定算法/Schema 版本。版本变更不能静默复用旧桶，旧桶进入迁移或自然过期流程。

### 4.4 Policy Gateway 预裁决、快速失败与独立重试

预裁决是容量与优先级保护信号，不是授权结果。Gateway 健康进入黄色区间时，调度器提前降低批处理、非实时 Connector 和可延迟任务的并发或进入排队，核心路径保持额度；进入超时/不可用区间后，受保护动作快速拒绝或挂起。

Policy Gateway 自身的重试只在 Gateway 适配层执行，最多两次，仅覆盖明确瞬态失败；它拥有独立预算和独立指标，不计入业务 Action 重试次数。业务层不得再次包装 Gateway 请求形成嵌套重试。任何 ALLOW 必须在副作用前由当前有效最终裁决确认，预裁决、旧缓存和超时结果均不得单独放行。

### 4.5 本地缓存与健康 SLO

幂等闸门热路径允许本地缓存，但只缓存明确 `DENY` 裁决，TTL 不超过 30 秒；缓存命中不能绕过主体、租户、策略版本、Kill Switch 和幂等账本校验。`ALLOW`、审批许可和未知结果不进入可放行缓存。

`idempotency_gate_latency`、`idempotency_gate_timeout_rate`、待决队列深度和锁持有时长是一级健康指标。p99 不超过 50ms、超时率 1% 告警、5% 进入限流模式属于候选 SLO，必须通过实现基准测试后冻结；超时率上升时先保护核心路径，不能通过缓存 ALLOW 规避 fail-closed。

### 4.6 幂等键生命周期与留存

幂等键从签发开始绑定租户、主体、工具、规范化参数摘要、Policy/审批版本、下游能力和有效期；经历 `PENDING`、`EXECUTING`、`FAILED_RETRYABLE`、`IN_DOUBT`、`SUCCEEDED`、`FAILED_FINAL`、`ESCALATED` 等状态，终态事实不可变。Redis 热缓存 TTL 仍遵循 RT-007 的 24 小时约束；PostgreSQL 权威账本不能早于恢复窗口、对账窗口及审计/合规要求清理。

对账和复盘需要的事件、Checkpoint 和证据保留期必须与 RT-008、SEC-009 对齐：运营档至少覆盖 90 天适用窗口，取证冷档至少覆盖 180 天适用下限；更长的 Legal Hold 或租户规则从严执行。该表述是保留约束与反向依赖，不将 90/180 天误写为所有场景的统一法规要求。

## 5. 核心数据模型

### 4.1 决策请求（DecisionRequest）

```typescript
interface DecisionRequest {
    // 身份标识
    task_id: string;                    // 任务标识
    workflow_id: string;                // 工作流标识
    action_id: string;                 // 失败 Action 标识
    idempotency_key: string;            // 幂等键（决定一切）
    
    // 分类结果（来自 REL-001）
    symptom: FailureSymptom;            // 症状分类
    stage: ExecutionStage;              // 失败阶段
    root_cause: RootCause;              // 根因分析
    confidence: ConfidenceScore;        // 置信度（分检测器校准后）
    evidence_count: int;                // 证据数量
    detector_tier: DetectorTier;        // 检测器层级
    
    // 策略配置（来自 REL-002）
    action_type: string;               // Action 类型
    priority: int;                     // 策略优先级
    retryable_symptoms: string[];       // 可重试症状
    non_retryable_symptoms: string[];   // 不可重试症状
    retry_policy: RetryPolicy;          // 完整策略配置
    fallback_chain: FallbackChain;       // 降级链声明
    
    // 预算与状态
    circuit_state: CircuitState;        // 当前熔断器状态
    global_retry_budget: GlobalBudget;  // 全局重试预算
    attempt_count: int;                // 当前尝试次数
    failure_counter_scope: FailureCounterScope; // 稳定作用域与版本
    consecutive_failure_state: CounterState;    // 永久失败检测
    window_failure_rate_state: CounterState;    // 退化/抖动检测

    // 幂等闸门与对账
    downstream_idempotency_capability: IdempotencyCapability;
    idempotency_gate_state: IdempotencyGateState;
    reconcile_state: ReconcileState;
    reconcile_authority: AuthorityReference;
    reconcile_deadline: timestamp;
    pending_queue_reference: string;
    
    // 安全上下文
    security_context: SecurityContext;  // 安全上下文
    requires_approval: bool;           // 是否需要审批
    approval_status: ApprovalStatus;    // 审批状态
    approval_deadline: timestamp;       // 审批截止时间
    
    // Trace 上下文
    trace_context: TraceContext;        // Trace 链路
    trace_id: string;
    span_id: string;
}
```

### 4.2 决策响应（DecisionResponse）

```typescript
interface DecisionResponse {
    // 决策结果
    decision: DecisionType;             // 决策类型
    action: ActionType;                // 建议的下一步操作
    reason: string;                   // 决策原因
    
    // 延迟与降级
    delay_ms: int64;                  // 退避延迟（毫秒）
    fallback_target: string;           // 降级目标（如有）
    fallback_chain_exhausted: bool;    // 降级链是否已耗尽
    
    // 预算快照
    next_retry_count: int;            // 剩余重试次数
    budget_remaining: BudgetSnapshot;  // 预算快照
    
    // 熔断器状态
    circuit_state: CircuitState;       // 更新后的熔断器状态
    circuit_next_check_ms: int64;     // 下次熔断器检查时间
    
    // 审批状态
    requires_approval: bool;          // 是否需要人工审批
    approval_sla: ApprovalSLA;        // 审批 SLA 配置
    approval_deadline: timestamp;      // 审批截止时间
    
    // 错误码（降级链耗尽时必须明确）
    error_code: ErrorCode;            // 明确错误码
    user_visible_message: string;      // 用户可见的错误信息
    
    // 事件追踪
    events: RetryEvent[];             // 决策相关事件
    trace_id: string;
    
    // 幂等与对账结果
    idempotency_gate_action: GateAction;
    key_lock_until: timestamp;
    retry_after_ms: int64;
    reconcile_action: ReconcileAction;

    // 元数据
    decision_id: string;               // 决策唯一标识
    decision_version: int;             // 决策版本（乐观锁）
    decided_at: timestamp;             // 决策时间
}

enum DecisionType {
    RETRY;              // 允许重试
    FALLBACK;           // 降级执行
    ESCALATE;           // 升级处理（人工介入）
    TERMINATE;          // 终止任务
    CIRCUIT_OPEN;       // 熔断器打开
    BUDGET_EXHAUSTED;   // 预算耗尽
    APPROVAL_REQUIRED;  // 需要审批
    IDEMPOTENCY_INVALID; // 幂等性无效
}

enum ActionType {
    EXECUTE_RETRY;      // 执行重试
    SWITCH_PROVIDER;    // 切换供应商
    SWITCH_MODEL;       // 切换模型
    USE_CACHE;          // 使用缓存
    EXECUTE_FALLBACK;   // 执行降级
    NOTIFY_USER;        // 通知用户
    REQUEST_APPROVAL;   // 请求审批
    SAVE_CHECKPOINT;    // 保存检查点
    PAUSE_TASK;         // 暂停任务
    TERMINATE_TASK;     // 终止任务
}

enum ErrorCode {
    // 成功/重试类
    ERR_RETRY_SCHEDULED = "RETRY_001";
    ERR_FALLBACK_SCHEDULED = "FALLBACK_001";
    
    // 失败类
    ERR_CIRCUIT_OPEN = "RETRY_101";
    ERR_BUDGET_EXHAUSTED = "RETRY_102";
    ERR_MAX_ATTEMPTS = "RETRY_103";
    ERR_APPROVAL_TIMEOUT = "RETRY_104";
    ERR_APPROVAL_DENIED = "RETRY_105";
    ERR_IDEMPOTENCY_CONFLICT = "RETRY_106";
    ERR_UNKNOWN_FAILURE = "RETRY_107";
    
    // 降级类
    ERR_FALLBACK_EXHAUSTED = "FALLBACK_101";
    ERR_FALLBACK_UNAVAILABLE = "FALLBACK_102";
    ERR_FALLBACK_THROTTLED = "FALLBACK_103";
    ERR_PRIVILEGE_ESCALATION_BLOCKED = "FALLBACK_104";
}
```

### 4.3 置信度评分（ConfidenceScore）

```typescript
interface ConfidenceScore {
    // 原始分数（分检测器校准前）
    raw_score: float;                 // [0, 1]
    detector_id: string;              // 检测器标识
    detector_tier: DetectorTier;       // 检测器层级
    
    // 校准后分数
    calibrated_score: float;          // [0, 1]，Platt scaling / isotonic regression 后
    calibration_method: string;       // 校准方法
    calibration_version: int;          // 校准版本
    
    // 证据充分性
    evidence_count: int;              // 证据数量
    evidence_sufficient: bool;        // 证据是否充分
    
    // 降档原因（如有）
    downgraded: bool;                 // 是否降档
    downgrade_reason: string;         // 降档原因
    final_score: float;               // 最终分数（可能因降档调整）
}

enum DetectorTier {
    TIER_1_STRUCTURAL = 1;   // 结构化错误（HTTP 状态码）
    TIER_2_SIGNATURE = 2;    // 签名匹配（已知错误模式）
    TIER_3_CONTEXTUAL = 3;   // 上下文分析（多信号组合）
    TIER_4_LLM_JUDGE = 4;    // LLM 评判（需要校准）
}

// 置信度阈值表（按风险等级 × Action 类型）
// 阈值不是标量，而是 (risk_level, action_class) 的二维表
interface ConfidenceThresholdTable {
    entries: ConfidenceThresholdEntry[];
}

interface ConfidenceThresholdEntry {
    risk_level: RiskLevel;            // 风险等级
    action_class: ActionClass;         // Action 类型
    escalate_threshold: float;         // ESCALATE 阈值
    retry_threshold: float;            // RETRY 阈值
    auto_threshold: float;             // 自动处理阈值
}

// 初始档位（上线首日使用，标记为「待校准」）
const INITIAL_THRESHOLDS: ConfidenceThresholdTable = {
    entries: [
        // 只读动作
        { risk_level: "LOW", action_class: "READ", escalate_threshold: 0.30, retry_threshold: 0.50, auto_threshold: 0.70 },
        // 普通写动作
        { risk_level: "MEDIUM", action_class: "WRITE", escalate_threshold: 0.50, retry_threshold: 0.70, auto_threshold: 0.85 },
        // 高风险写动作
        { risk_level: "HIGH", action_class: "HIGH_RISK_WRITE", escalate_threshold: 0.70, retry_threshold: 0.85, auto_threshold: 0.95 },
        // 关键操作
        { risk_level: "CRITICAL", action_class: "CRITICAL", escalate_threshold: 0.85, retry_threshold: 0.95, auto_threshold: 0.99 },
    ]
};
```

### 4.4 降级链声明（FallbackChain）

```typescript
interface FallbackChain {
    // 降级链标识
    chain_id: string;
    action_type: string;              // 绑定的 Action 类型
    version: int;                     // 版本（与策略一起版本化）
    
    // 降级步骤
    steps: FallbackStep[];            // 声明式降级链
    
    // privilege_monotone 约束
    privilege_monotone: bool;          // 必须为 true
    max_escalation_depth: int;        // 最大人工介入深度
    
    // 降级抑制配置
    throttle: ThrottleConfig;         // 降级抑制配置
    
    // 审批配置
    approval_required_at_depth: int[]; // 哪些深度需要审批
}

interface FallbackStep {
    step_id: int;                     // 降级步骤序号（0-indexed）
    target: FallbackTarget;            // 降级目标
    capability_profile: CapabilityProfile; // 降级后的能力配置
    
    // privilege_monotone 验证
    privilege_delta: PrivilegeDelta;   // 相对原操作的权限变化
    
    // 超时配置
    timeout_ms: int64;                // 降级步骤超时
    max_retries: int;                // 降级步骤最大重试
    
    // 条件判断
    trigger_condition: string;         // 触发条件（表达式）
}

interface FallbackTarget {
    type: FallbackTargetType;
    config: FallbackTargetConfig;
}

enum FallbackTargetType {
    ALTERNATIVE_PROVIDER;    // 备用供应商
    ALTERNATIVE_MODEL;       // 备用模型
    REDUCED_CAPABILITY;       // 降级能力集
    CACHED_RESULT;           // 缓存结果
    HUMAN_ASSISTED;          // 人工辅助
    DRY_RUN;                 // 干运行（仅验证，不执行）
}

interface CapabilityProfile {
    // 降级后的能力必须严格收窄
    allowed_operations: string[];     // 允许的操作
    denied_operations: string[];       // 拒绝的操作（相对于原操作）
    
    // 验证：denied_operations 必须包含原操作的所有高风险能力
    // 这通过属性测试证明
}

interface PrivilegeDelta {
    // 权限变化必须为负或零（privilege_monotone）
    read_scope_delta: int;            // 读取范围变化
    write_scope_delta: int;           // 写入范围变化
    network_delta: int;                // 网络权限变化
    exec_delta: int;                  // 执行权限变化
    
    // privilege_monotone 验证函数
    is_monotone_decreasing: bool;      // 必须为 true
}

interface ThrottleConfig {
    enabled: bool;                    // 是否启用抑制
    window_seconds: int;             // 统计窗口（默认：300s）
    max_fallbacks_per_window: int;   // 窗口内最大降级次数（默认：3）
    escalation_after_max: bool;       // 达到上限后转人工（默认：true）
    alert_threshold: int;            // 告警阈值（默认：2）
}
```

---

## 5. 三层存储熔断器

### 5.1 存储架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           L1: 进程内缓存                                 │
│                    读写延迟 < 1ms，TTL = 5s                            │
│                    用途：热路径零开销，Redis 抖动时继续裁决              │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │ miss / invalid
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                           L2: Redis（热路径）                            │
│                    读写延迟 < 10ms，TTL = 熔断窗口 × 2                   │
│                    用途：跨实例状态共享，快速故障检测                     │
│                    选型：Redis Cluster（按 tenant 分片）                 │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │ miss / recovery / cold start
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                           L3: PostgreSQL（权威源）                       │
│                    写入延迟 < 100ms，用途：持久化、恢复、审计             │
│                    用途：状态权威源、实例冷启动回填、故障恢复             │
└─────────────────────────────────────────────────────────────────────────┘
```

### 5.2 隔离粒度

**熔断器 Key 设计：按 per-downstream × per-tenant 分片**

```
CircuitKey = {
    tenant_id: string,                // 租户维度
    downstream: string,               // 下游服务标识（provider/model/endpoint）
    region: string,                  // 区域维度（可选）
}
```

**目的**：避免某个 noisy tenant 或某个模型配额的 429 把其他无辜租户一起熔断。

### 5.3 熔断器状态机

```typescript
interface CircuitBreaker {
    // 身份
    key: CircuitKey;
    version: int64;                  // 乐观锁版本号
    
    // 状态
    state: CircuitState;
    state_since: timestamp;          // 状态开始时间
    
    // 统计（滑动窗口）
    window: SlidingWindow;
    
    // 配置
    config: CircuitBreakerConfig;
}

enum CircuitState {
    CLOSED = 0;     // 正常，允许请求
    OPEN = 1;       // 熔断，拒绝请求
    HALF_OPEN = 2;  // 半开，允许测试请求
}

interface CircuitBreakerConfig {
    // 失败率阈值
    failure_threshold: float = 0.30;      // 30%
    
    // 慢调用阈值
    slow_call_threshold_ms: int64 = 5000;  // 5s
    slow_call_rate_threshold: float = 0.20; // 20%
    
    // 滑动窗口
    sliding_window_size: int = 100;        // 请求数
    minimum_number_of_calls: int = 20;     // 最小调用数
    
    // 状态转换
    wait_duration_in_open_ms: int64 = 30000; // 30s
    permitted_calls_in_half_open: int = 5;  // 半开允许测试数
    success_threshold: float = 0.50;        // 50% 成功关闭
}

interface SlidingWindow {
    calls: RingBuffer[CallRecord];
    total_calls: int;
    failed_calls: int;
    slow_calls: int;
}

interface CallRecord {
    timestamp: timestamp;
    success: bool;
    duration_ms: int64;
    error_type: string;
}

// 状态转换规则
function transition(circuit: CircuitBreaker, event: CircuitEvent): CircuitState {
    switch (circuit.state) {
        case CLOSED:
            // 失败率超过阈值 OR 慢调用率超过阈值
            if (circuit.window.failure_rate > circuit.config.failure_threshold ||
                circuit.window.slow_call_rate > circuit.config.slow_call_rate_threshold) {
                return OPEN;
            }
            return CLOSED;
            
        case OPEN:
            // 等待超时
            if (now() - circuit.state_since >= circuit.config.wait_duration_in_open_ms) {
                return HALF_OPEN;
            }
            return OPEN;
            
        case HALF_OPEN:
            // 统计半开期间的测试请求
            if (half_open_successes >= circuit.config.permitted_calls_in_half_open * circuit.config.success_threshold) {
                return CLOSED;
            }
            if (half_open_failures > circuit.config.permitted_calls_in_half_open * (1 - circuit.config.success_threshold)) {
                return OPEN;
            }
            return HALF_OPEN;
    }
}
```

### 5.4 状态覆盖问题解决方案

**问题**：Redis + PostgreSQL 双写时，「快照回填」会把健康的当前状态覆盖成旧的熔断态。

**解决方案**：乐观锁 + 单调版本号

```typescript
interface CircuitStateWrite {
    // 必须携带当前版本号
    current_version: int64;
    new_version: int64;          // 必须 = current_version + 1
    
    // 更新逻辑
    // UPDATE circuit_breakers 
    // SET state = $new_state, version = $new_version
    // WHERE key = $key AND version = $current_version
    // RETURNING version;
    
    // 如果 version 不匹配，说明有并发更新，拒绝写入
}

// 降级服务健康检查
interface DegradationHealthCheck {
    downstream_id: string;
    health_status: HealthStatus;
    last_check: timestamp;
    consecutive_failures: int;
    
    // 降级服务自身不健康时
    // → fail-closed（拒绝降级请求）
    // → 不等于全平台停摆
}
```

### 5.5 冷启动回填

**问题**：实例重启或扩容时，从 PostgreSQL 回填最近窗口内的状态，避免重启瞬间「假装下游全部健康」而打爆下游。

```typescript
interface ColdStartRecovery {
    // 从 PostgreSQL 回填最近 window 内的状态
    async function recover(tenant_id: string, downstream: string): CircuitBreaker {
        // 1. 查询最近 window 内的状态
        recent_state = await postgres.query(`
            SELECT * FROM circuit_breaker_events
            WHERE tenant_id = $1 AND downstream = $2
            AND timestamp > NOW() - INTERVAL 'window_size'
            ORDER BY timestamp DESC
        `);
        
        // 2. 重建滑动窗口统计
        window = rebuild_sliding_window(recent_state);
        
        // 3. 计算当前状态
        current_state = compute_state(window);
        
        // 4. 写入 L1/L2
        await write_to_cache(current_state);
        
        return current_state;
    }
}

// 语义定义：熔断是软状态，Redis 丢失的后果是「短暂放过一批请求」，不是「永久放行」
// 因此 L1/L2 的 TTL 必须远小于熔断窗口
const L1_TTL_SECONDS = 5;      // 5s << 30s 熔断窗口
const L2_TTL_SECONDS = 60;     // 60s << 熔断窗口
```

---

## 6. 全局重试预算（双层阈值 + 双轨窗口）

### 6.1 预算模型

```typescript
interface GlobalRetryBudget {
    // 身份
    tenant_id: string;
    
    // 双层阈值
    alert_threshold: float = 0.10;     // 10% → 告警
    reject_threshold: float = 0.15;    // 15% → 拒绝
    
    // 双轨窗口
    fast_window: SlidingWindow;       // 60s，用于快速响应
    slow_window: SlidingWindow;       // 300s，用于趋势分析
    
    // 排除清单（不计入分子）
    exempt_classes: ExemptClass[];
}

enum ExemptClass {
    IDEMPOTENT_READ;                  // 幂等只读重试
    USER_EXPLICIT_RETRY;              // 用户显式触发的重试
    SERVICE_KNOWN_FAULT;              // 被分类器标记为「服务端已知故障正在修复」
}

// 双轨窗口统计
interface DualWindowStats {
    fast_stats: WindowStats;          // 60s 窗口
    slow_stats: WindowStats;          // 300s 窗口
    
    // 滞回（hysteresis）防止震荡
    hysteresis_margin: float = 0.02;   // 2% 滞回区间
}

interface WindowStats {
    total_requests: int;
    retry_requests: int;
    retry_rate: float;
    exempt_retries: int;             // 排除后的重试数
    effective_rate: float;            // 排除后的有效重试率
}

// 决策逻辑
function check_budget(budget: GlobalRetryBudget): BudgetCheckResult {
    fast_rate = budget.fast_window.effective_rate;
    slow_rate = budget.slow_window.effective_rate;
    
    // 滞回判断
    if (fast_rate > budget.reject_threshold + budget.hysteresis_margin) {
        return REJECT;               // 拒绝
    }
    if (fast_rate > budget.alert_threshold + budget.hysteresis_margin) {
        return WARN;                 // 告警
    }
    return ALLOW;                    // 允许
}

// 反向信号监控
interface ReverseSignalMonitor {
    // 重试率过低（接近 0）同样是告警项
    // 意味着客户端可能关闭了重试，或者失败被吞了
    low_retry_rate_threshold: float = 0.01;  // < 1% 触发告警
}
```

### 6.2 拒绝新重试 ≠ 丢弃

```typescript
interface RetryRejection {
    // 超限的请求必须进 DLQ + 支持幂等重放
    dlq_entry: DLQEntry;
    
    // 给用户明确的排队信息
    queue_position: int;             // 排队序号
    estimated_recovery_time_ms: int64; // 预计恢复时间
    user_visible_message: string;     // 用户可见的错误信息
    
    // 静默丢弃重试等于静默丢失用户动作
    // 必须生成明确的错误事件
}
```

---

## 7. 审批分档与超时

### 7.1 审批 SLA 分档

```typescript
interface ApprovalSLA {
    // 按阻塞性分档
    tier: ApprovalTier;
    timeout_seconds: int;             // 超时时间
    escalation_after_seconds: int;    // 自动升级时间
    auto_deny: bool;                 // 超时是否自动拒绝（必须为 true）
}

enum ApprovalTier {
    // 紧急：高风险操作，阻塞任务
    TIER_URGENT = 0;                 // timeout: 1h, escalation: 15m
    // 高优先级：写操作，阻塞单步骤
    TIER_HIGH = 1;                   // timeout: 4h, escalation: 30m
    // 标准：普通操作
    TIER_STANDARD = 2;               // timeout: 24h, escalation: 4h
    // 低优先级：只读操作
    TIER_LOW = 3;                    // timeout: 72h, escalation: 24h
}

// 审批 SLA 配置
const APPROVAL_SLA_CONFIG: Record<ApprovalTier, ApprovalSLA> = {
    TIER_URGENT: {
        tier: TIER_URGENT,
        timeout_seconds: 3600,           // 1h
        escalation_after_seconds: 900,    // 15m
        auto_deny: true
    },
    TIER_HIGH: {
        tier: TIER_HIGH,
        timeout_seconds: 14400,          // 4h
        escalation_after_seconds: 1800,   // 30m
        auto_deny: true
    },
    TIER_STANDARD: {
        tier: TIER_STANDARD,
        timeout_seconds: 86400,          // 24h
        escalation_after_seconds: 14400,  // 4h
        auto_deny: true
    },
    TIER_LOW: {
        tier: TIER_LOW,
        timeout_seconds: 259200,         // 72h
        escalation_after_seconds: 86400,  // 24h
        auto_deny: true
    }
};
```

### 7.2 真重试判据

```typescript
interface TrueRetryValidation {
    // 真重试判据：同一个幂等键、同一参数、同一审批上下文
    idempotency_key: string;          // 幂等键
    original_request_hash: string;     // 原始请求摘要
    original_approval_context: ApprovalContext; // 原始审批上下文
    
    // 验证函数
    function is_true_retry(candidate: RetryRequest, original: OriginalRequest): bool {
        return (
            candidate.idempotency_key == original.idempotency_key &&
            candidate.request_hash == original.request_hash &&
            candidate.approval_context == original.approval_context
        );
    }
}

// 批量审批 + 委托机制
interface ApprovalDelegation {
    // 一键继承上次审批
    inherit_last_approval: bool;      // 是否继承上次审批
    
    // 团队委托代理审批人
    delegated_approvers: string[];    // 委托的审批人列表
    delegation_scope: ApprovalScope;   // 委托范围
}

interface ApprovalScope {
    action_types: string[];           // 允许审批的 Action 类型
    max_risk_level: RiskLevel;       // 最高风险等级
    max_value: decimal;               // 最大价值
}
```

---

## 8. 降级链执行

### 8.1 降级执行流程

```typescript
async function execute_fallback_chain(
    request: DecisionRequest,
    chain: FallbackChain,
    context: ExecutionContext
): Promise<FallbackResult> {
    // 1. privilege_monotone 验证
    for (step in chain.steps) {
        if (!step.privilege_delta.is_monotone_decreasing) {
            return FallbackResult.Error(
                error_code: ERR_PRIVILEGE_ESCALATION_BLOCKED,
                message: "降级违反 privilege_monotone 约束"
            );
        }
    }
    
    // 2. 降级抑制检查
    throttle_key = build_throttle_key(request);
    throttle_count = await check_throttle(throttle_key, chain.throttle);
    
    if (throttle_count >= chain.throttle.max_fallbacks_per_window) {
        // 停止自动降级，转人工
        await trigger_escalation(request, chain);
        return FallbackResult.Escalated("降级抑制触发");
    }
    
    // 3. 顺序执行降级链
    for (step in chain.steps) {
        // 检查触发条件
        if (!evaluate_condition(step.trigger_condition, context)) {
            continue;
        }
        
        // 执行降级步骤
        result = await execute_fallback_step(step, request);
        
        if (result.success) {
            return FallbackResult.Success(result);
        }
        
        // 记录降级次数（用于 throttle）
        await increment_throttle_count(throttle_key);
        
        // 检查是否需要人工审批
        if (chain.approval_required_at_depth.includes(step.step_id)) {
            return FallbackResult.ApprovalRequired(step);
        }
    }
    
    // 4. 降级链耗尽 ≠ 静默成功
    return FallbackResult.Error(
        error_code: ERR_FALLBACK_EXHAUSTED,
        message: "降级链已耗尽，任务失败",
        user_visible_message: "操作无法完成，请联系管理员"
    );
}
```

### 8.2 降级服务不可用处理

```typescript
interface DegradationServiceFailure {
    // 降级服务自身不可用：fail-closed + 快速失败
    // 但不等于全平台停摆
    
    // 参考 Kill Switch 三态设计（SEC-009）
    kill_switch_state: KillSwitchState;
}

enum KillSwitchState {
    // 新任务拒绝
    NEW_TASKS_REJECTED;
    
    // 运行中任务用已持有短期令牌跑完不续期
    RUNNING_TASKS_COMPLETE_WITH_CURRENT_CREDENTIALS;
    
    // 只读动作可放行
    READ_ONLY_ALLOWED;
}

// 降级服务的健康状态纳入熔断器自身监控
interface DegradationServiceMonitor {
    // 避免循环依赖
    monitor_degradation_service: CircuitBreaker;  // 监控降级服务的熔断器
}
```

---

## 9. 延迟计算算法

```typescript
function calculateDelay(
    request: DecisionRequest,
    attempt: int,
    retryPolicy: RetryPolicy
): DelayResult {
    // 1. 优先使用服务端 Retry-After
    if (request.retry_after_ms) {
        return DelayResult(
            delay_ms: min(request.retry_after_ms, retryPolicy.max_interval_ms),
            source: "server_retry_after"
        );
    }
    
    // 2. 服务端无指示，使用退避公式
    raw_delay = retryPolicy.initial_interval_ms * pow(retryPolicy.multiplier, attempt - 1);
    capped_delay = min(raw_delay, retryPolicy.max_interval_ms);
    
    // 3. 应用 Full Jitter
    min_delay = retryPolicy.initial_interval_ms * 0.5;
    jittered_delay = random(min_delay, capped_delay);
    
    return DelayResult(
        delay_ms: jittered_delay,
        source: "calculated_full_jitter"
    );
}
```

---

## 10. 事件契约

### 10.1 决策事件

```typescript
interface RetryDecisionRequested {
    event_type: "RetryDecisionRequested";
    event_id: string;
    timestamp: timestamp;
    version: int;
    
    // 身份
    task_id: string;
    workflow_id: string;
    action_id: string;
    idempotency_key: string;
    
    // 上下文
    symptom: string;
    action_type: string;
    trace_id: string;
}

interface RetryDecisionMade {
    event_type: "RetryDecisionMade";
    event_id: string;
    timestamp: timestamp;
    version: int;
    
    // 决策结果
    decision: DecisionType;
    action: ActionType;
    reason: string;
    error_code: ErrorCode;
    
    // 延迟
    delay_ms: int64;
    
    // 状态快照
    circuit_state: CircuitState;
    budget_remaining: BudgetSnapshot;
    
    // 幂等
    idempotency_key: string;
    
    // Trace
    trace_id: string;
    
    // 决策版本（乐观锁）
    decision_version: int;
}

interface CircuitStateChanged {
    event_type: "CircuitStateChanged";
    event_id: string;
    timestamp: timestamp;
    version: int;
    
    // 熔断器标识
    circuit_key: CircuitKey;
    
    // 状态变化
    previous_state: CircuitState;
    new_state: CircuitState;
    
    // 原因
    reason: string;
    failure_rate: float;
    slow_call_rate: float;
    
    // Trace
    trace_id: string;
}

interface FallbackExecuted {
    event_type: "FallbackExecuted";
    event_id: string;
    timestamp: timestamp;
    version: int;
    
    // 降级信息
    chain_id: string;
    step_id: int;
    target_type: FallbackTargetType;
    success: bool;
    error_code: ErrorCode;
    
    // Throttle
    throttle_count: int;
    throttle_triggered: bool;
    
    // Trace
    trace_id: string;
}

interface ApprovalRequired {
    event_type: "ApprovalRequired";
    event_id: string;
    timestamp: timestamp;
    version: int;
    
    // 审批信息
    approval_tier: ApprovalTier;
    timeout_seconds: int;
    escalation_after_seconds: int;
    
    // 原因
    reason: string;
    
    // Trace
    trace_id: string;
}
```

---

## 11. 可观测性指标

### 11.1 一级指标

| 指标名称 | 定义 | 类型 | 告警阈值 |
|---------|------|------|---------|
| `decision_latency_p99` | 决策延迟 P99 | Histogram | 候选 > 50ms，基准后冻结 |
| `idempotency_gate_latency_p99` | 幂等闸门 P99 延迟 | Histogram | 候选 > 50ms，基准后冻结 |
| `idempotency_gate_timeout_rate` | 幂等闸门超时率 | Gauge | 候选 > 1% 告警，> 5% 限流 |
| `pending_queue_depth` | 待决队列深度 | Gauge | 按容量基线告警 |
| `in_doubt_lock_duration` | IN_DOUBT 锁持有时长 | Histogram | 按风险档 SLA 告警 |
| `decision_rate` | 决策请求速率 | Gauge | - |
| `decision_by_type` | 各决策类型分布 | Counter | - |
| `retry_rate` | 重试率（全局） | Gauge | > 10% |
| `retry_rate_per_tenant` | 重试率（按租户） | Gauge | > 15% |
| `retry_success_rate` | 重试成功率 | Gauge | < 80% |
| `circuit_open_rate` | 熔断器打开率 | Gauge | > 5% |
| `consecutive_failure_abort_rate` | 连续永久失败中止率 | Gauge | 按动作类型基线 |
| `window_failure_rate` | 窗口失败率 | Gauge | 按下游基线 |
| `policy_gateway_predecision_yellow_rate` | Policy Gateway 黄色区间占比 | Gauge | 按容量基线 |
| `policy_gateway_timeout_rate` | Policy Gateway 超时率 | Gauge | > 0 触发分级保护 |
| `reconcile_confirmed_rate` | 对账确认率 | Gauge | 按风险档基线 |
| `reconcile_escalation_rate` | 对账升级率 | Gauge | 按风险档基线 |
| `fallback_rate` | 降级率 | Gauge | > 5% |
| `fallback_throttle_rate` | 降级抑制触发率 | Gauge | > 1% |
| `approval_timeout_rate` | 审批超时率 | Gauge | > 5% |
| `escalation_rate` | 升级率 | Gauge | > 5% |

### 11.2 决策命中率指标

| 指标名称 | 定义 | 目标 |
|---------|------|------|
| `retry_correct_rate` | 重试决策正确的比例 | > 85% |
| `fallback_success_rate` | 降级执行成功率 | > 70% |
| `unnecessary_retry_rate` | 不必要重试率 | < 10% |
| `missed_retry_rate` | 错过可恢复失败率 | < 5% |

### 11.3 置信度指标

| 指标名称 | 定义 | 告警阈值 |
|---------|------|---------|
| `confidence_calibration_error` | 置信度校准误差 | > 0.1 |
| `low_confidence_escalation_rate` | 低置信度升级率 | > 20% |
| `high_confidence_retry_rate` | 高置信度重试率 | < 50% |

### 11.4 熔断器指标

| 指标名称 | 定义 | 告警阈值 |
|---------|------|---------|
| `circuit_state_distribution` | 熔断器状态分布 | - |
| `circuit_transition_rate` | 熔断器状态转换率 | > 10/分钟 |
| `circuit_cold_start_recovery_rate` | 冷启动回填率 | > 5% |
| `circuit_version_conflict_rate` | 版本冲突率 | > 1% |

---

## 12. 验收标准

| 编号 | 验收项 | 验证方法 |
|------|--------|---------|
| V1 | 幂等闸门三分支 | 分别验证合法键/支持重放、可核查但不支持重放、不可安全重放三条路径；不得统一处理 |
| V2 | IN_DOUBT 锁键 | 结果未知或闸门超时后，同键并发请求只能读取状态/收到等待语义，不得产生新尝试 |
| V3 | 拒绝优于猜测 | 不确定场景，验证返回拒绝、挂起或人工升级而非盲目重试 |
| V4 | 对外冲突语义 | 同键并发占用可返回 409 与 retry_after；内部依赖超时不映射为 409 |
| V5 | 只严不松缓存 | DENY 缓存可快速失败；ALLOW、审批许可和未知结果缓存不得绕过回源校验 |
| V3 | 先写日志后执行 | 事件发布失败，验证决策无效 |
| V4 | 症状匹配 | 给定症状，验证返回匹配策略中的决策 |
| V5 | 置信度分桶校准 | 不同检测器置信度分别校准，验证映射正确 |
| V6 | 风险分层阈值 | 高风险操作低置信度触发 ESCALATE |
| V7 | 熔断器打开 | 连续失败达到阈值，验证熔断器打开 |
| V8 | 熔断器三层存储 | Redis 抖动时验证 L1 继续裁决 |
| V9 | 熔断器版本乐观锁 | 并发更新验证版本冲突拒绝 |
| V10 | 熔断器冷启动回填 | 实例重启验证状态回填正确 |
| V11 | 全局预算双层阈值 | 模拟重试率超 15%，验证拒绝 |
| V12 | 全局预算排除清单 | 幂等只读重试验证不计入分子 |
| V13 | 降级 privilege_monotone | 属性测试证明降级不扩权 |
| V14 | 降级链耗尽错误码 | 验证返回明确错误码和用户消息 |
| V15 | 降级抑制 | 窗口内降级 3 次后验证转人工 |
| V16 | 审批超时默认拒绝 | 审批超时验证自动拒绝 |
| V17 | 双计数器作用域 | 验证连续失败与窗口失败率使用不同计数器；主键含版本、命名空间、下游、动作和租户；资源规范化后入桶；task_id 仅作快逃 |
| V18 | Policy Gateway 保护 | Gateway 最多两次独立瞬态重试；黄色区间提前限制低优先级动作；超时 fail-closed；业务层无嵌套重试 |
| V19 | 三值对账 | 有权威真相源时验证已执行/未执行/未知三态；探测通道、凭据和限流桶与执行正交；无真相源直接升级 |
| V20 | 决策延迟与闸门 SLO | 记录 p99/超时率并验证候选 50ms、1%、5% 基线；最终数值经压测冻结，不以文档数值替代实测 |
| V21 | 阈值变更回放 | 阈值变更前用历史数据回放验证 |

---

## 13. 依赖与接口

### 13.1 上游依赖

| 依赖 | 说明 |
|------|------|
| REQ-REL-001 | 失败症状分类（症状、置信度、证据） |
| REQ-REL-002 | 重试策略配置（RetryPolicy、BackoffStrategy、CircuitBreaker） |
| REQ-RT-007 | 幂等键账本 |
| REQ-SEC-003 | Policy Gateway（安全策略检查） |
| REQ-RT-006 | Trace 上下文传播 |
| REQ-RT-003 | 事件 Schema 与版本策略 |

### 13.2 下游接口

| 接口 | 说明 |
|------|------|
| RetryExecutionService | 执行重试 |
| FallbackService | 执行降级 |
| ApprovalService | 触发人工审批 |
| CheckpointService | 保存检查点（RT-005） |
| EventEmitter | 发布决策事件 |
| MetricsCollector | 采集指标 |
| CircuitBreakerStore | 熔断器状态存储 |
| GlobalBudgetStore | 全局预算状态存储 |

---

## 14. 参考资料

以下为公开来源，访问日期均为 2026-09-24：

- AWS Well-Architected Agentic AI Lens: [Automatic Recovery](https://docs.aws.amazon.com/wellarchitected/latest/agentic-ai-lens/agentrel07-bp02.html)
- Claude Code Error Handling: [Error Documentation](https://code.claude.com/docs/en/errors)
- Claude Code withRetry: [Source Code](https://github.com/claude-code-best/claude-code/blob/91cffe16/src/services/api/withRetry.ts)
- LangGraph Fault Tolerance: [Fault Tolerance](https://docs.langchain.com/oss/python/langgraph/fault-tolerance)
- Temporal Retry Policies: [Retry Policies](https://docs.temporal.io/encyclopedia/retry-policies)
- Temporal Non-Retryable Errors: [Non-Retryable Errors](https://docs.temporal.io/design-patterns/non-retryable-errors)
- Cursor Agent Circuit Breaker: [Circuit Breaker Spec](https://geodocs.dev/ai-agents/agent-circuit-breaker-spec)
- OpenAI Agents SDK Retry: [Retry Reference](https://openai.github.io/openai-agents-python/ref/retry/)

---

## 15. 决策记录

| 决策项 | 决策 | 依据 |
|-------|------|------|
| 决策流程步数 | 11 步，每步有明确失败分支 | Q1 用户确认 |
| privilege_monotone | 必选项，属性测试证明 | Q2 用户确认 |
| 降级链耗尽 | 明确错误码，用户可见消息 | Q2 用户确认 |
| 降级抑制 | throttle 窗口，默认 3 次/5 分钟 | Q2 用户确认 |
| 降级服务不可用 | fail-closed + Kill Switch 三态 | Q2 用户确认 |
| 真重试判据 | 幂等键 + 参数 + 审批上下文 | Q3 用户确认 |
| 审批 SLA 分档 | 4 档（Urgent/High/Standard/Low） | Q3 用户确认 |
| 超时默认拒绝 | 必须为 true | Q3 用户确认 |
| 熔断器三层存储 | L1 进程内 + L2 Redis + L3 PostgreSQL | Q4 用户确认 |
| 熔断器隔离粒度 | per-downstream × per-tenant | Q4 用户确认 |
| 状态覆盖防护 | 乐观锁 + 单调版本号 | Q4 用户确认 |
| 冷启动回填 | 从 PostgreSQL 回填最近窗口状态 | Q4 用户确认 |
| 全局预算双层阈值 | 10% 告警 / 15% 拒绝 | Q5 用户确认 |
| 全局预算双轨窗口 | 60s 快速响应 / 300s 趋势分析 | Q5 用户确认 |
| 排除清单 | 幂等只读、用户显式、服务端已知故障 | Q5 用户确认 |
| 拒绝新重试 | 必须进 DLQ + 明确排队信息 | Q5 用户确认 |
| 反向信号监控 | 重试率 < 1% 触发告警 | Q5 用户确认 |
| 置信度分桶校准 | 按检测器分桶 Platt/isotonic 校准 | Q6 用户确认 |
| 证据充分性门控 | 分数高但证据少时降档 | Q6 用户确认 |
| 风险分层阈值 | (risk_level, action_class) 二维表 | Q6 用户确认 |
| 阈值变更管理 | 灰度 + 回放验证，差异 > 5% 需抽检 | Q6 用户确认 |

---

## 16. 变更记录

| 版本 | 日期 | 变更 | 确认 |
|-----|------|-----|----|
| v0.1-designed | 2026-09-24 | 初始版本，含 11 步决策流程、三层存储熔断器、双层预算、降级链、审批分档、置信度校准 | 初始确认 |
| v0.2-designed | 2026-09-24 | 纳入幂等闸门三分支与待决队列、IN_DOUBT 锁键、双计数器作用域、Policy Gateway 预裁决与分级保护、三值对账、独立探测、风险分档 SLA 和幂等键生命周期/留存联动；区分 409 冲突语义与内部依赖故障；待跨模块评审与冻结 | 用户确认 Q1-Q4 |
