# REQ-REL-002 RetryPolicy 详细设计

> 所属基线：`Runtime Contract v1-draft`  
> 需求编号：`REQ-REL-002`  
> 优先级：P0  
> 设计版本：`v0.1-designed`  
> 设计状态：详细设计已完成，待跨模块冻结  
> 前置依赖：`REQ-RT-007`（幂等键）、`REQ-REL-001`（失败分类）  
> 下游依赖：`REQ-REL-003`（重试决策引擎）、`REQ-REL-008`（测试失败分类）、`REQ-HAR-003`（Tool Adapter）、`REQ-OBS-003`（指标字典）  
> 用户确认日期：2026-09-23（Q1-Q5 方案已确认）

---

## 1. 需求定义

### 1.1 目标

为 AI Agent 平台定义可配置、可组合、可观测的重试策略体系，确保：

1. **瞬时故障自动恢复**：网络抖动、临时限流等瞬时问题通过重试自动恢复
2. **雪崩防护**：通过时限预算推导、全局重试预算、熔断器三层防护
3. **下游保护**：客户端令牌桶主动限流，避免触发服务端限流
4. **事件可靠**：关键事件（Policy 决策、审批、凭据签发）进入 DLQ 支持幂等重放
5. **可观测**：重试率、重试放大比、各下游 429 占比作为一级指标

### 1.2 核心设计原则

| 原则 | 说明 |
|-----|------|
| **时限预算优先** | 重试控制量是「总时限」，而非「次数」；次数仅为兜底下限 |
| **全栈单层重试** | 只允许在 Tool Adapter 层重试，禁止跨 Worker/Task 层重试 |
| **下游指示优先** | 服务端 Retry-After 头优先于客户端退避计算 |
| **Full Jitter** | 采用完整的全抖动算法，真正打散重试洪峰 |
| **主动限流优于被动重试** | 客户端令牌桶压制到下游配额 70-80% |
| **事件不丢失** | 关键事件进 DLQ，支持幂等重放 |
| **可观测优先** | 重试指标作为 SRE 一级指标 |

### 1.3 与竞品的设计差异

| 竞品 | 本设计差异 |
|-----|----------|
| Temporal | 引入时限预算推导、全局重试预算、DLQ；默认无限重试改为有界预算 |
| AWS Step Functions | 引入 Full Jitter 而非 Equal Jitter；叠加慢调用维度的熔断器 |
| Netflix Hystrix | 熔断阈值下调；引入重试放大比指标 |
| gRPC | 服务端指示头优先于退避公式 |

---

## 2. 竞品与行业研究摘要

### 2.1 Temporal RetryPolicy

**公开事实**：
- Activity 级别 RetryPolicy，默认指数退避系数 2.0，初始间隔 1s，最大间隔 100s
- 默认无限最大重试次数，直到 Schedule-To-Close Timeout
- 支持 Non-Retryable Errors 显式声明

**设计推断**：Temporal 的"无限重试直到超时"模式适合长时间运行任务，但 AI Agent 的 Task 通常有时限约束，需要更保守的预算控制。

来源：[Temporal Retry Policy Documentation](https://docs.temporal.io/encyclopedia/retry-policies)，访问日期：2026-09-23

### 2.2 AWS SDK Waiter / Exponential Backoff And Jitter

**公开事实**：
- AWS SDK v3 Waiter 采用 `exponential(fullJitter)` 作为默认 Jitter 策略
- Full Jitter：`delay = random(0, min(maxDelay, base * 2^attempt))`
- 2015 年 AWS Architecture Blog 的经典分析证明了 Full Jitter 在打散重试洪峰上的优越性

**设计推断**：Full Jitter（1.0）而非 Equal Jitter（0.5）或固定因子（0.1）应是默认选择。

来源：[Exponential Backoff And Jitter](https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/)，访问日期：2026-09-23

### 2.3 本设计的核心结论

1. **重试次数由时限推导**：`max_attempts = floor(time_budget / avg_latency)`
2. **兜底次数作为硬上限**：`max_attempts = min(calculated, hard_cap)`
3. **服务端指示优先**：`delay = retry_after_value if present else calculated_delay`
4. **Full Jitter 必选**：`jitter = 1.0`（而非 0.1 或 0.5）
5. **全局预算约束**：`retry_rate = retries / total_requests ≤ 10%`
6. **DLQ 保底**：Policy/审批/凭据类事件不得静默丢弃

---

## 3. RetryPolicy Schema 定义

### 3.1 RetryBudget（重试预算）

```text
RetryBudget 定义：
├── time_budget_ms: int64          # 总时限预算（毫秒），真正的控制量
├── cost_budget_per_attempt: int64 # 单次尝试成本（Token/费用）
├── hard_cap_attempts: int         # 兜底硬上限次数（3-5次）
├── cooldown_base_ms: int          # 冷却基准时间（用于推导次数）
│
# 计算公式：
calculated_attempts = floor(time_budget_ms / cooldown_base_ms)
effective_max_attempts = min(calculated_attempts, hard_cap_attempts)
```

**说明**：
- `time_budget_ms` 是真正的控制量，次数只是其派生值
- `hard_cap_attempts` 是兜底下限，防止计算错误时无限重试
- 全栈只允许一层重试，禁止嵌套或跨 Task 重试

### 3.2 BackoffStrategy（退避策略）

```text
BackoffStrategy 定义：
├── type: enum [exponential, fixed, linear, server_guided]
├── initial_interval_ms: int       # 初始间隔（默认：网络1s，模型2s）
├── max_interval_ms: int           # 最大间隔（强制上限：30s）
├── multiplier: float              # 指数系数（默认：2.0）
├── jitter: enum [full, equal, none] # Jitter 类型（默认：full）
├── jitter_cap_multiplier: float   # Jitter 上限系数（默认：1.0，即 Full Jitter）
├── min_interval_ms: int           # 最小间隔下限（默认：initial_interval * 0.5）
│
# 服务端优先规则：
# 收到 429 时，优先使用 Retry-After / retry-after-ms / x-ratelimit-reset
# 禁止自行计算退避

# 计算公式（指数退避 + Full Jitter）：
raw_delay = initial_interval_ms * (multiplier ^ (attempt - 1))
capped_delay = min(raw_delay, max_interval_ms)
jittered_delay = random(min_interval_ms, capped_delay)  # Full Jitter
```

**说明**：
- Full Jitter：`delay ∈ [min_interval_ms, max_interval_ms]`
- Jitter 在应用 max_interval 之后施加
- 下限不低于 `initial_interval * 0.5`，避免首抖落回接近 0

### 3.3 CircuitBreaker（熔断器）

```text
CircuitBreaker 定义：
├── state: enum [closed, open, half_open]
├── failure_threshold: float        # 失败率阈值（默认：30%，下调自微服务惯例50%）
├── slow_call_threshold_ms: int    # 慢调用阈值（新增：默认5000ms）
├── slow_call_rate_threshold: float # 慢调用率阈值（新增：默认20%）
├── sliding_window_size: int        # 滑动窗口大小（请求数，默认：100）
├── minimum_number_of_calls: int    # 窗口最小调用数（默认：20）
├── wait_duration_in_open_ms: int   # Open 到 Half-Open 等待时间（默认：30s）
├── permitted_calls_in_half_open: int # Half-Open 允许的测试请求数（默认：5）
├── success_threshold: float        # Half-Open 成功阈值（默认：50%）
│
# 状态转换：
# closed → open：失败率 > failure_threshold 或 慢调用率 > slow_call_rate_threshold
# open → half_open：wait_duration_in_open_ms 超时
# half_open → closed：成功数 ≥ success_threshold * permitted_calls_in_half_open
# half_open → open：失败数 > permitted_calls_in_half_open - success_threshold
```

**说明**：
- 失败率阈值从微服务惯例的 50% 下调到 30%
- 叠加慢调用维度，防止慢请求拖垮系统
- AI Agent 的模型调用通常较慢，5s 作为慢调用阈值适合

### 3.4 RetryPolicy（完整策略定义）

```text
RetryPolicy 定义：
├── policy_id: string               # 策略唯一标识
├── action_type: string            # 绑定的 Action 类型
├── priority: int                  # 优先级（高优先级可覆盖低优先级）
│
├── budget: RetryBudget             # 重试预算
├── backoff: BackoffStrategy       # 退避策略
├── circuit_breaker: CircuitBreaker # 熔断器配置
│
├── retryable_symptoms: string[]   # 可重试的失败症状列表（来自 REL-001）
├── non_retryable_symptoms: string[] # 明确不可重试的症状列表
│
├── rate_limit: RateLimitConfig    # 客户端主动限流配置（新增）
├── dlq_policy: DLQPolicy          # 死信队列策略（新增）
│
├── created_at: timestamp
├── updated_at: timestamp
├── version: int
```

### 3.5 RateLimitConfig（客户端主动限流）

```text
RateLimitConfig 定义：
├── enabled: bool                   # 是否启用客户端限流
├── bucket_capacity: int          # 令牌桶容量
├── refill_rate: float             # 令牌填充速率（QPS）
├── max_burst: int                 # 最大突发量
│
# 配置建议：
# 将速率压制到下游服务配额的 70-80%
# 预留缓冲，避免触发服务端限流
```

**说明**：
- 主动限流优于被动重试
- 当客户端检测到接近配额时，主动排队而非触发 429 后重试

### 3.6 DLQPolicy（死信队列策略）

```text
DLQPolicy 定义：
├── enabled: bool                   # 是否启用 DLQ
├── trigger_conditions: string[]   # 触发 DLQ 的条件
│                                     # 例：["POLICY_DECISION", "APPROVAL_REQUIRED", "CREDENTIAL_ISSUED"]
├── retention_ms: int              # DLQ 保留时间（默认：7天）
├── max_size: int                  # DLQ 最大容量
├── replay_mode: enum [idempotent_only, all] # 重放模式
│
# 关键原则：
# - Policy 决策、审批流转、凭据签发类事件必须进 DLQ
# - DLQ 事件必须支持幂等重放（依赖 RT-007 幂等键）
# - 次数耗尽不等于事件可丢弃
```

---

## 4. 处理逻辑与流程

### 4.1 重试决策流程

```
Action 执行失败
    ↓
接收 FailureSymptom（来自 REL-001）
    ↓
Step 1: 症状匹配
    ├─ 症状在 retryable_symptoms 中？ → 否 → 进入 DLQ 判断流程
    └─ 是 → 继续
    ↓
Step 2: DLQ 判断
    ├─ 触发 DLQ 条件？ → 是 → 写入 DLQ，记录事件
    └─ 否 → 继续
    ↓
Step 3: 熔断器检查
    ├─ 熔断器状态 = Open？ → 返回 CircuitOpen，拒绝重试
    ├─ 熔断器状态 = Half-Open？ → 允许 1 个测试请求
    └─ 熔断器状态 = Closed？ → 继续
    ↓
Step 4: 预算推导
    ├─ 计算 max_attempts = floor(time_budget_ms / avg_latency)
    ├─ effective_max = min(calculated, hard_cap)
    └─ current_attempt >= effective_max？ → 否 → 继续
    ↓
Step 5: 全局重试预算检查
    ├─ 当前 retry_rate ≤ 10%？ → 是 → 继续
    └─ 否 → 拒绝重试，告警
    ↓
Step 6: 退避计算
    ├─ 收到服务端 Retry-After？ → delay = retry_after_value
    ├─ 服务端无指示？ → 计算指数退避 + Full Jitter
    └─ 应用 max_interval 上限（30s）
    ↓
Step 7: 幂等闸门检查
    ├─ 幂等键有效？ → 是 → 执行重试
    └─ 否 → 拒绝重试，要求幂等化
    ↓
Step 8: 执行重试
    ├─ 更新熔断器计数器
    ├─ 发布 RetryScheduled 事件
    └─ 执行 Action
```

### 4.2 DLQ 判断流程

```
重试被拒绝或次数耗尽
    ↓
检查 dlq_policy.trigger_conditions
    ↓
命中触发条件？
    ├─ 是 → 写入 DLQ
    │   ├─ 持久化事件和上下文
    │   ├─ 生成幂等重放键
    │   └─ 记录 DLQ 入队原因
    │
    └─ 否 → 正常终结
        ├─ 标记为 FAILED_FINAL
        ├─ 发布 RetryFailed 事件
        └─ 通知用户
```

### 4.3 熔断器状态机

```
                    ┌─────────────────────────────┐
                    │           CLOSED            │
                    │   正常请求，统计失败率/      │
                    │   慢调用率                   │
                    └─────────────┬───────────────┘
                                  │
                    ┌─────────────▼───────────────┐
                    │   失败率>30% 或              │
                    │   慢调用率>20%              │
                    │             → OPEN          │
                    └─────────────────────────────┘
                                  │
                    ┌─────────────▼───────────────┐
                    │           OPEN              │
                    │   拒绝请求，等待            │
                    │   wait_duration_in_open_ms  │
                    └─────────────┬───────────────┘
                                  │
                    ┌─────────────▼───────────────┐
                    │        wait 超时             │
                    │             → HALF_OPEN     │
                    └─────────────────────────────┘
                                  │
        ┌─────────────────────────┼─────────────────────────┐
        │                         │                         │
        │   成功≥50%             │   失败>50%             │
        │   → CLOSED             │   → OPEN               │
        │                         │                         │
        └─────────────────────────┴─────────────────────────┘
```

### 4.4 客户端限流流程

```
请求到达
    ↓
检查令牌桶
    ├─ 令牌充足？ → 消费令牌，执行请求
    │
    └─ 令牌不足？
        ├─ 进入排队队列
        ├─ 等待令牌填充
        └─ 队列超时 → 拒绝请求（早于触发服务端限流）
```

---

## 5. 预定义策略模板

### 5.1 网络请求策略

```text
Policy: network_request
├── action_type: HTTP_REQUEST
├── budget:
│   ├── time_budget_ms: 30000      # 30s 总时限
│   ├── cooldown_base_ms: 1000     # 估算单次1s
│   ├── hard_cap_attempts: 5       # 兜底5次
│   └── cost_budget_per_attempt: 1000 # Token预算
├── backoff:
│   ├── type: exponential
│   ├── initial_interval_ms: 1000  # 1s
│   ├── max_interval_ms: 30000     # 30s 上限
│   ├── multiplier: 2.0
│   ├── jitter: full               # Full Jitter
│   └── min_interval_ms: 500       # 最低0.5s
├── circuit_breaker:
│   ├── failure_threshold: 0.3     # 30%
│   ├── slow_call_threshold_ms: 5000
│   └── slow_call_rate_threshold: 0.2
├── retryable_symptoms:
│   - TRANSIENT_CONNECTIVITY
│   - DEPENDENCY_THROTTLED（无 Retry-After 时）
│   - DEPENDENCY_UNAVAILABLE
│   - OPERATION_TIMED_OUT
├── non_retryable_symptoms:
│   - REQUEST_REJECTED
│   - AUTHORIZATION_FAILED
│   - RESOURCE_LIMIT_REACHED
├── rate_limit:
│   ├── enabled: true
│   ├── refill_rate: 下游配额 * 0.75  # 压制到75%
```

### 5.2 模型调用策略

```text
Policy: model_completion
├── action_type: MODEL_COMPLETION
├── budget:
│   ├── time_budget_ms: 120000     # 120s 总时限
│   ├── cooldown_base_ms: 2000     # 估算单次2s
│   ├── hard_cap_attempts: 5       # 兜底5次
│   └── cost_budget_per_attempt: 50000
├── backoff:
│   ├── type: server_guided       # 优先使用服务端指示
│   ├── initial_interval_ms: 2000  # 2s
│   ├── max_interval_ms: 30000     # 30s 上限
│   ├── multiplier: 2.0
│   ├── jitter: full
│   └── min_interval_ms: 1000
├── circuit_breaker:
│   ├── failure_threshold: 0.3
│   ├── slow_call_threshold_ms: 60000  # 模型调用更慢
│   └── slow_call_rate_threshold: 0.3
├── retryable_symptoms:
│   - DEPENDENCY_THROTTLED（有 Retry-After 时优先）
│   - DEPENDENCY_UNAVAILABLE
├── non_retryable_symptoms:
│   - TRANSIENT_CONNECTIVITY（应走网络策略）
│   - REQUEST_REJECTED
│   - RESOURCE_LIMIT_REACHED
├── rate_limit:
│   ├── enabled: true
│   ├── refill_rate: 配额 * 0.7   # 模型配额更保守
```

### 5.3 文件操作策略

```text
Policy: file_operation
├── action_type: FILE_READ | FILE_WRITE
├── budget:
│   ├── time_budget_ms: 5000       # 5s 总时限
│   ├── cooldown_base_ms: 500
│   ├── hard_cap_attempts: 3
├── backoff:
│   ├── type: fixed
│   ├── initial_interval_ms: 500
│   ├── max_interval_ms: 2000
│   └── jitter: none               # 文件操作通常不需要抖动
├── retryable_symptoms:
│   - TRANSIENT_CONNECTIVITY
│   - OPERATION_TIMED_OUT
├── non_retryable_symptoms:
│   - REQUEST_REJECTED
│   - RESOURCE_NOT_FOUND
```

### 5.4 高风险操作策略

```text
Policy: high_risk_operation
├── action_type: PR_CREATE | PR_MERGE | CREDENTIAL_ISSUED
├── budget:
│   ├── time_budget_ms: 60000
│   ├── cooldown_base_ms: 5000
│   ├── hard_cap_attempts: 2       # 更保守
├── backoff:
│   ├── type: server_guided
│   ├── initial_interval_ms: 5000
│   ├── max_interval_ms: 30000
│   ├── jitter: full
├── dlq_policy:
│   ├── enabled: true              # 必须启用 DLQ
│   ├── trigger_conditions:
│     - CREDENTIAL_ISSUED          # 凭据签发必须进 DLQ
├── retryable_symptoms:
│   - DEPENDENCY_THROTTLED
├── non_retryable_symptoms:
│   - REQUEST_REJECTED
│   - SAFETY_CONTROL_BLOCKED
```

---

## 6. 全局重试预算

### 6.1 预算模型

```text
GlobalRetryBudget：
├── org_id: string                 # 组织标识
├── window_size_seconds: int       # 统计窗口（默认：60s）
├── max_retry_rate: float         # 最大重试率（默认：0.10，即10%）
├── max_retries_in_window: int    # 窗口内最大重试数
│
# 计算：
max_retries_in_window = floor(total_requests_in_window * max_retry_rate)
│
# 监控指标：
# - current_retry_rate = retries_in_window / total_requests_in_window
# - retry_amplification_ratio = retries / original_requests
```

### 6.2 信用额度模型（可选）

```text
RetryCredit：
├── org_id: string
├── total_credits: int             # 总信用额度
├── current_credits: int           # 当前信用
├── refill_rate: float             # 每秒恢复信用
├── zero_triggers_circuit: bool   # 归零是否触发熔断
│
# 规则：
# - 每次失败重试扣减信用
# - 每秒恢复 refill_rate 个信用
# - 归零时拒绝新重试，可能触发熔断
```

### 6.3 告警规则

| 级别 | 阈值 | 动作 |
|-----|------|-----|
| INFO | retry_rate < 5% | 记录 |
| WARNING | 5% ≤ retry_rate < 15% | 评估扩容 |
| CRITICAL | retry_rate ≥ 15% | 自动降级/切流 |

---

## 7. 可观测性

### 7.1 一级指标

| 指标名称 | 定义 | 类型 | 告警阈值 |
|---------|------|-----|---------|
| `retry_rate` | 重试次数/总请求数 | Gauge | > 15% |
| `retry_amplification_ratio` | 实际请求数/用户请求数 | Gauge | > 1.5 |
| `downstream_429_rate` | 各下游 429 占比 | Gauge（按下游分） | > 5% |
| `circuit_breaker_open_total` | 熔断器打开次数 | Counter | > 10/小时 |
| `dlq_size` | DLQ 当前大小 | Gauge | > 100 |
| `dlq_replay_success_rate` | DLQ 重放成功率 | Gauge | < 95% |
| `retry_latency_p95` | 重试引入的额外延迟 | Histogram | > 60s |

### 7.2 二级指标

| 指标名称 | 定义 |
|---------|------|
| `retry_by_symptom` | 按失败症状分布的重试次数 |
| `retry_by_action_type` | 按 Action 类型分布的重试次数 |
| `retry_success_rate` | 重试最终成功率 |
| `backoff_delay_actual` | 实际退避延迟分布 |
| `rate_limit_queue_depth` | 限流队列深度 |

### 7.3 Trace 关联

每条重试事件必须关联：
- `trace_id`：Trace 链路标识
- `span_id`：当前 Span
- `parent_span_id`：原始请求 Span
- `retry_attempt`：重试次数
- `retry_delay`：退避延迟
- `circuit_state`：熔断器状态
- `retry_reason`：重试原因（症状）

### 7.4 Dashboard 建议

1. **重试概览**：重试率趋势、重试放大比、全局健康状态
2. **下游健康**：各下游 429 占比热力图
3. **熔断器状态**：各服务熔断器开闭状态
4. **DLQ 健康**：DLQ 大小、重放成功率
5. **成本分析**：Token 消耗 vs 重试成功率

---

## 8. 异常处理

| 场景 | 处理策略 |
|-----|---------|
| RetryPolicy 不存在 | 使用组织级默认策略，记录配置缺失告警 |
| 幂等键不存在或无效 | 拒绝重试，要求先完成幂等化（依赖 RT-007） |
| 预算超限 | 拒绝重试，记录预算证据 |
| 熔断器 Open | 拒绝请求，返回 CircuitOpen 错误 |
| 熔断器状态查询失败 | 采用保守策略（拒绝），记录错误告警 |
| 退避计算溢出 | 使用 max_interval 上限 |
| DLQ 写入失败 | 降级为普通失败，记录严重告警 |
| 服务端 Retry-After 异常 | 使用本地退避，标记异常 |

---

## 9. 权限、安全与合规

### 9.1 权限控制

| 操作 | 所需角色 |
|-----|---------|
| 创建/修改 RetryPolicy | admin, policy_manager |
| 查看重试指标 | all |
| 手动旁路熔断器 | sre（需要审计记录） |
| 手动触发 DLQ 重放 | admin, ops |
| 查看 DLQ 内容 | admin, compliance（数据脱敏） |

### 9.2 安全约束

- 重试不得绕过安全策略检查（Policy Gateway）
- 幂等键必须在重试前验证
- DLQ 内容需符合数据脱敏要求（REQ-SEC-008）
- 凭据签发类事件必须加密存储

### 9.3 合规要求

- 所有重试决策需记录审计日志（REQ-RT-006）
- DLQ 事件需符合数据留存策略（REQ-RT-008）
- 重试失败根因需关联 REQ-REL-001

---

## 10. 依赖与接口

### 10.1 上游依赖

| 依赖 | 说明 |
|-----|------|
| REQ-REL-001 | Failure Taxonomy 提供失败症状分类 |
| REQ-RT-007 | 幂等键提供重试资格验证 |
| REQ-HAR-003 | Tool Adapter 提供 Action 执行能力 |
| REQ-SEC-003 | Policy Gateway 提供策略检查 |

### 10.2 下游接口

| 接口 | 说明 |
|-----|------|
| RetryPolicyService | 策略 CRUD、查询、绑定 |
| RetryExecutionService | 重试执行、状态追踪 |
| CircuitBreakerService | 熔断器状态管理 |
| DLQService | 死信队列写入、查询、重放 |
| RetryEventEmitter | 重试事件发布 |
| RateLimitBucketService | 令牌桶管理 |

### 10.3 事件契约

| 事件 | 说明 |
|-----|------|
| RetryScheduled | 重试调度 |
| RetryAttempted | 重试尝试 |
| RetrySucceeded | 重试成功 |
| RetryFailed | 重试最终失败 |
| RetryBudgetExhausted | 预算耗尽 |
| CircuitStateChanged | 熔断器状态变更 |
| DLQEventEnqueued | DLQ 入队 |
| DLQEventReplayed | DLQ 重放 |

---

## 11. 版本与演进

### 11.1 MVP（第一阶段）

- [ ] RetryPolicy Schema（含 Budget、Backoff、CircuitBreaker）
- [ ] 时限预算推导重试次数
- [ ] Full Jitter（jitter = 1.0）
- [ ] 服务端 Retry-After 优先
- [ ] 熔断器（失败率 + 慢调用）
- [ ] 客户端令牌桶限流
- [ ] 全局重试预算（≤10%）
- [ ] DLQ 基础功能
- [ ] 一级重试指标

### 11.2 后续版本

- [ ] 信用额度模型
- [ ] per-error 自定义退避（参考 Temporal）
- [ ] 自适应退避（根据历史成功率调整）
- [ ] 基于历史数据的策略优化
- [ ] 跨组织重试预算池

---

## 12. 决策记录

| 决策项 | 决策 | 依据 |
|-------|------|-----|
| 重试控制量 | 时限预算（time_budget）而非次数 | Q1 用户确认 |
| 次数上限 | 兜底下限，推导值取 min | 防止计算错误 |
| 全栈重试层数 | 只允许一层 | 防止嵌套重试雪崩 |
| 熔断失败率 | 30%（下调自50%） | Q2 用户确认；Agent场景更敏感 |
| 熔断叠加 | 失败率 + 慢调用率 | Q2 用户确认 |
| Jitter 类型 | Full Jitter（1.0） | Q4 AWS 最佳实践 |
| Jitter 下限 | initial_interval × 0.5 | 避免首抖接近0 |
| 服务端指示 | Retry-After 优先于退避公式 | Q3 用户确认 |
| max_interval | 强制上限 30s | Q3 用户确认 |
| 主动限流 | 压制到配额 70-80% | Q3 用户确认 |
| 全局重试预算 | ≤10% | Q5 用户确认 |
| DLQ 触发条件 | Policy/审批/凭据类事件 | Q5 用户确认 |

---

## 13. 验收标准

| 编号 | 验收项 | 验证方法 |
|-----|-------|---------|
| V1 | 时限推导 | 输入 time_budget=30s，验证 max_attempts 计算正确 |
| V2 | Full Jitter | 1000个并发重试，验证时间分布均匀 |
| V3 | 服务端优先 | 模拟 429+Retry-After，验证使用服务端值 |
| V4 | 熔断器打开 | 连续失败达到30%，验证熔断器打开 |
| V5 | 慢调用熔断 | 慢调用率>20%，验证熔断器打开 |
| V6 | 客户端限流 | 验证令牌桶压制到配额75% |
| V7 | 全局预算 | 验证 retry_rate>10% 时拒绝重试 |
| V8 | DLQ 入队 | 凭据签发失败，验证进入DLQ |
| V9 | DLQ 幂等重放 | 重复重放同一DLQ事件，验证只执行一次 |
| V10 | 指标埋点 | 验证重试率、重试放大比、429占比可采集 |
| V11 | 分级告警 | 模拟429>15%，验证触发降级 |
| V12 | 幂等闸门 | 幂等键无效时，验证拒绝重试 |

---

## 14. 参考资料

- [Temporal Retry Policy Documentation](https://docs.temporal.io/encyclopedia/retry-policies)，访问日期：2026-09-23
- [AWS Exponential Backoff And Jitter](https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/)，访问日期：2026-09-23
- [AWS SDK v3 Waiter](https://docs.aws.amazon.com/sdk-for-java/latest/developer-guide/waiter.html)，访问日期：2026-09-23
- [Netflix Hystrix Circuit Breaker](https://github.com/Netflix/Hystrix/wiki/Configuration)，访问日期：2026-09-23

---

## 15. 变更记录

| 版本 | 日期 | 变更 | 确认 |
|-----|------|-----|-----|
| `v0.1-designed` | 2026-09-23 | 初始版本，含时限预算推导、Full Jitter、熔断器、DLQ、全局预算 | Q1-Q5 用户确认 |

