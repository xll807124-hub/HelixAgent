# 持久执行、失败恢复与重试设计规范

> 优先级：P0 - 阻塞可靠闭环  
 > 状态：部分完成（REQ-RT-005、REQ-REL-001/REL-002/REL-003/REL-004/REL-005 已完成独立详细设计；本文件保留总体说明和实现阶段待办）  
> 依赖：运行时基础契约  
> 阻塞：可靠执行、生产可用性

> **详细设计请参阅**：
> - [`REQ-REL-001-failure-taxonomy.md`](./REQ-REL-001-failure-taxonomy.md)：三维正交分类模型（症状/阶段/根因）
> - [`REQ-REL-002-retry-policy.md`](./REQ-REL-002-retry-policy.md)：时限预算推导、Full Jitter、熔断器、DLQ、全局重试预算
> - [`REQ-REL-003-retry-decision-engine.md`](./REQ-REL-003-retry-decision-engine.md)：11 步决策流程、幂等闸门三分支与待决队列、IN_DOUBT 锁键、连续失败/窗口失败率双计数器、Policy Gateway 预裁决与分级保护、三值对账、三层存储熔断器、双层阈值预算、声明式降级链 privilege_monotone、审批分档、置信度分桶校准
> - [`REQ-REL-005-recovery-decision-failure-handling.md`](./REQ-REL-005-recovery-decision-failure-handling.md)：污染半径恢复点、Effect Log 三段式契约、Pivot、补偿独立治理、恢复期保护和九态状态机

## 一、设计目标

确保 AI Agent 任务能够从失败中恢复、支持暂停与恢复、避免重复执行副作用。

### 核心问题

当前已有总体原则，但缺少可实现细节：

- 什么样的失败应该重试？什么样的失败不应该重试？
- 如何避免重试时重复执行写操作？
- 如何保存检查点？检查点应该包含什么？
- Worker 崩溃后如何恢复？
- 用户暂停任务后如何恢复？
- 网络超时、模型限流、工具错误如何区分？
- 测试失败和工具异常如何区分？
- 如何保证状态一致性？

如果这些问题不明确，系统可能出现：

- 重试时重复创建 PR 或发送通知
- 权限拒绝被错误地重试多次
- 测试失败被当作临时故障自动重跑
- 检查点不完整导致恢复后状态错误
- 无法定位失败的根因

## 二、失败分类（Failure Taxonomy）

### 类别 1：确定性失败（不应重试）

#### 1.1 权限拒绝

**场景**：
- 用户无权访问仓库
- Worker 试图读取未授权文件
- Policy Gateway 拒绝高风险操作

**处理**：
- 不重试
- 标记为 `AUTHORIZATION_FAILED`
- 记录拒绝原因
- 通知用户修正权限

**理由**：权限配置不会因为重试而改变。

#### 1.2 输入验证失败

**场景**：
- 任务参数格式错误
- 文件路径不存在
- Git 分支名不合法
- 工具参数类型错误

**处理**：
- 不重试
- 标记为 `INVALID_INPUT`
- 返回详细错误信息
- 引导用户修正输入

**理由**：错误输入不会因为重试而变正确。

#### 1.3 业务逻辑失败

**场景**：
- 测试执行后结果为失败
- 代码编译失败
- Linter 检查不通过
- 代码审查拒绝

**处理**：
- 不重试
- 标记为 `VALIDATION_FAILED`
- 保存失败证据（日志、输出）
- 进入诊断流程或请求人工介入

**理由**：测试失败是有效反馈，不是系统故障。重试会掩盖真实问题。

#### 1.4 资源不存在

**场景**：
- Git 仓库不存在
- 目标文件已被删除
- Docker 镜像不存在

**处理**：
- 不重试（除非是已知的最终一致性延迟）
- 标记为 `RESOURCE_NOT_FOUND`
- 检查资源是否曾经存在
- 如果是用户错误，通知修正；如果是系统问题，告警

#### 1.5 配额超限

**场景**：
- Token 预算耗尽
- 费用预算超限
- 任务数达到上限

**处理**：
- 不重试
- 标记为 `QUOTA_EXCEEDED`
- 暂停任务
- 通知用户增加配额或清理资源

### 类别 2：瞬时失败（应该重试，有退避）

#### 2.1 网络瞬断

**场景**：
- API 请求超时
- 连接重置
- DNS 解析失败（临时）

**处理**：
- 重试最多 3 次
- 指数退避（1s、2s、4s）
- 超过重试次数后标记为 `NETWORK_ERROR`

#### 2.2 模型限流

**场景**：
- 429 Too Many Requests
- Rate limit exceeded

**处理**：
- 重试最多 5 次
- 遵循 `Retry-After` 头
- 指数退避，上限 60s
- 切换到备用模型（如果配置）
- 超过重试次数后标记为 `MODEL_THROTTLED`

#### 2.3 服务临时不可用

**场景**：
- 503 Service Unavailable
- 外部工具返回 500
- 数据库连接池耗尽

**处理**：
- 重试最多 3 次
- 指数退避（2s、4s、8s）
- 超过重试次数后标记为 `SERVICE_UNAVAILABLE`

#### 2.4 最终一致性延迟

**场景**：
- GitHub 创建分支后立即读取返回 404
- 对象存储上传后立即下载失败

**处理**：
- 重试最多 3 次
- 固定间隔 2s
- 如果确认是一致性问题，可适当增加重试次数

### 类别 3：持久性失败（应该升级或告警）

#### 3.1 Worker 崩溃

**场景**：
- 进程 OOM 被杀
- 沙箱超时被强制终止
- 段错误

**处理**：
- 保存最后检查点和日志
- 标记为 `WORKER_CRASHED`
- 如果有检查点，尝试在新 Worker 中恢复
- 恢复失败则标记为 `UNRECOVERABLE`
- 通知开发者和用户

#### 3.2 存储失败

**场景**：
- 检查点写入失败
- 审计日志丢失
- 工作区卷损坏

**处理**：
- 不重试
- 立即暂停任务
- 标记为 `STORAGE_FAILURE`
- 告警运维
- 保护现场，防止数据丢失

#### 3.3 不可恢复的状态不一致

**场景**：
- 检查点版本不兼容
- 事件序列损坏
- 工作区被外部修改

**处理**：
- 不重试
- 标记为 `STATE_CORRUPTED`
- 保存现场快照
- 通知用户和开发者
- 手动介入恢复或重新开始

### 类别 4：用户主动操作（不是失败）

#### 4.1 用户取消

**场景**：
- 用户点击取消按钮
- API 调用取消任务

**处理**：
- 立即停止执行
- 撤销未完成的 Action
- 清理临时资源
- 标记为 `CANCELLED`
- 保存取消前状态

#### 4.2 用户暂停

**场景**：
- 用户暂停任务等待审查
- 系统暂停等待人工审批

**处理**：
- 保存检查点
- 撤销短期凭据
- 标记为 `PAUSED`
- 等待用户恢复

#### 4.3 等待审批

**场景**：
- 高风险操作需要人工批准
- 需要用户提供额外信息

**处理**：
- 保存检查点
- 标记为 `WAITING_APPROVAL`
- 发送通知
- 设置审批超时（如 24 小时）
- 超时后标记为 `APPROVAL_TIMEOUT`

## 三、重试策略（RetryPolicy）

> **重要更新**：重试策略的详细设计已移至独立专项文档 [`REQ-REL-002-retry-policy.md`](./REQ-REL-002-retry-policy.md)。本节保留草案级概述作为快速参考，正式实现必须以专项文档为准。

### 3.1 核心设计原则

| 原则 | 说明 |
|-----|------|
| **时限预算优先** | 重试控制量是「总时限」，而非「次数」；次数仅为兜底下限 |
| **全栈单层重试** | 只允许在 Tool Adapter 层重试，禁止跨 Worker/Task 层重试 |
| **服务端指示优先** | 服务端 Retry-After 头优先于客户端退避计算 |
| **Full Jitter** | 采用完整的全抖动算法（jitter=1.0），真正打散重试洪峰 |
| **主动限流优于被动重试** | 客户端令牌桶压制到下游配额 70-80% |
| **事件不丢失** | Policy/审批/凭据类事件进入 DLQ，支持幂等重放 |
| **可观测优先** | 重试率、重试放大比、各下游 429 占比作为一级指标 |

### 3.2 RetryBudget（重试预算）

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

### 3.3 BackoffStrategy（退避策略）

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

### 3.4 CircuitBreaker（熔断器）

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
```

### 3.5 全局重试预算

```text
GlobalRetryBudget：
├── org_id: string                 # 组织标识
├── window_size_seconds: int       # 统计窗口（默认：60s）
├── max_retry_rate: float         # 最大重试率（默认：0.10，即10%）
├── max_retries_in_window: int    # 窗口内最大重试数

# 告警规则：
# - retry_rate < 5%：INFO 记录
# - 5% ≤ retry_rate < 15%：WARNING 评估扩容
# - retry_rate ≥ 15%：CRITICAL 自动降级/切流
```

### 3.6 DLQ 策略

```text
DLQPolicy 定义：
├── enabled: bool                   # 是否启用 DLQ
├── trigger_conditions: string[]   # 触发 DLQ 的条件
│   # 例：["POLICY_DECISION", "APPROVAL_REQUIRED", "CREDENTIAL_ISSUED"]
├── retention_ms: int              # DLQ 保留时间（默认：7天）
├── max_size: int                  # DLQ 最大容量
├── replay_mode: enum [idempotent_only, all] # 重放模式

# 关键原则：
# - Policy 决策、审批流转、凭据签发类事件必须进 DLQ
# - DLQ 事件必须支持幂等重放（依赖 RT-007 幂等键）
# - 次数耗尽不等于事件可丢弃
```

### 3.7 预定义策略模板

#### 网络请求策略

```json
{
  "policy_id": "network_request",
  "action_type": "HTTP_REQUEST",
  "budget": {
    "time_budget_ms": 30000,
    "cooldown_base_ms": 1000,
    "hard_cap_attempts": 5
  },
  "backoff": {
    "type": "exponential",
    "initial_interval_ms": 1000,
    "max_interval_ms": 30000,
    "jitter": "full"
  },
  "circuit_breaker": {
    "failure_threshold": 0.3,
    "slow_call_threshold_ms": 5000,
    "slow_call_rate_threshold": 0.2
  },
  "rate_limit": {
    "enabled": true,
    "refill_rate": "downstream_quota * 0.75"
  }
}
```

#### 模型调用策略

```json
{
  "policy_id": "model_completion",
  "action_type": "MODEL_COMPLETION",
  "budget": {
    "time_budget_ms": 120000,
    "cooldown_base_ms": 2000,
    "hard_cap_attempts": 5
  },
  "backoff": {
    "type": "server_guided",
    "initial_interval_ms": 2000,
    "max_interval_ms": 30000,
    "jitter": "full"
  },
  "circuit_breaker": {
    "failure_threshold": 0.3,
    "slow_call_threshold_ms": 60000,
    "slow_call_rate_threshold": 0.3
  },
  "rate_limit": {
    "enabled": true,
    "refill_rate": "model_quota * 0.7"
  }
}
```

### 3.8 重试决策流程（更新）

```text
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

### 3.9 一级可观测指标

| 指标名称 | 定义 | 告警阈值 |
|---------|------|---------|
| `retry_rate` | 重试次数/总请求数 | > 15% |
| `retry_amplification_ratio` | 实际请求数/用户请求数 | > 1.5 |
| `downstream_429_rate` | 各下游 429 占比（按下游分） | > 5% |
| `circuit_breaker_open_total` | 熔断器打开次数 | > 10/小时 |
| `dlq_size` | DLQ 当前大小 | > 100 |
| `dlq_replay_success_rate` | DLQ 重放成功率 | < 95% |
| `retry_latency_p95` | 重试引入的额外延迟 | > 60s |

### 3.10 正式文档引用

> **详细设计请参阅**：[`REQ-REL-002-retry-policy.md`](./REQ-REL-002-retry-policy.md)

该文档包含完整的：
- RetryPolicy Schema 定义
- 各策略模板详细配置
- 熔断器状态机
- DLQ 处理流程
- 验收标准（12 项）
- 参考资料与来源

## 四、检查点（Checkpoint）

### 检查点设计原则

> 本节仅保留失败恢复领域的使用约束。Checkpoint 的正式 Schema、事件绑定、保存协议、恢复流程和 Action 副作用边界以 [`REQ-RT-005 Checkpoint Protocol`](./REQ-RT-005-checkpoint-protocol.md) 为准；本文件不得重新定义另一套 Checkpoint Schema。

1. **粒度**：在可安全恢复的边界保存检查点
2. **频率**：重要状态变化后保存，避免过于频繁
3. **不可变**：检查点只追加，不修改
4. **版本化**：包含 Schema 版本，支持迁移
5. **压缩**：上下文可以压缩，但必须可还原

### 检查点时机

> 以下时机为失败恢复草案建议；正式保存边界和状态语义以 `REQ-RT-005` 为准，检查点保留与容量策略由 `REQ-REL-004` 冻结。

必须保存检查点的时机：

- Workflow 启动后
- 每个 Worker 启动前
- 每个高风险 Action 执行前
- 用户暂停时
- Worker 正常完成时
- 每处理 N 个 Action（如 10）后
- 达到时间阈值（如每 5 分钟）

### 检查点内容（历史草案，非正式契约）

> 以下内容保留用于说明失败恢复领域的历史输入，不是正式 Schema。实现和跨模块评审必须以 [`REQ-RT-005 Checkpoint Protocol`](./REQ-RT-005-checkpoint-protocol.md) 为准；本节中的 `Checkpoint` 接口、`latest` 符号链接、保留数字和对话历史保存方式不应直接作为实现契约。

```typescript
interface Checkpoint {
  checkpoint_id: string;
  task_id: string;
  workflow_id: string;
  sequence_number: number;
  created_at: string;
  checkpoint_version: string;
  
  // 状态快照
  state: {
    task_status: TaskStatus;
    current_worker_id?: string;
    completed_actions: string[];
    pending_actions: string[];
    artifacts: Record<string, ArtifactReference>;
    source_revision: string;
    workspace_snapshot?: string;
  };
  
  // 执行上下文
  context: {
    conversation_history: Message[];
    compressed_context?: string;
    active_memory: MemoryItem[];
    tool_states: Record<string, any>;
  };
  
  // 资源状态
  resources: {
    working_branch?: string;
    pr_number?: number;
    temporary_files: string[];
    allocated_resources: ResourceAllocation[];
  };
  
  // 预算消耗
  budget_consumed: {
    tokens: number;
    cost_usd: number;
    time_seconds: number;
  };
  
  // 恢复提示
  recovery_hints: {
    last_successful_action?: string;
    next_planned_action?: string;
    known_issues?: string[];
  };
}
```

### 检查点存储（历史草案，非正式选型）

> 正式存储定位、不可变对象命名、事件发布顺序和保留边界以 `REQ-RT-005` 与后续 `REQ-REL-004` 评审结果为准。

**存储选型：**
- PostgreSQL JSONB（< 1MB）
- 对象存储（> 1MB）

**命名规范**：
```text
checkpoints/{task_id}/{sequence_number}.json
checkpoints/{task_id}/latest -> symlink
```

**保留策略**：
- 保留所有检查点直到任务完成
- 任务完成后保留最后 3 个检查点
- 30 天后归档或删除

### 检查点压缩

> 以下为历史候选策略，不构成正式检查点格式；压缩与恢复语义由 `REQ-HAR-002` 设计。

当对话历史过长时：

1. 保留最近 N 轮完整对话（如最近 10 轮）
2. 压缩更早的对话为摘要
3. 保留所有 Action 和 Evidence 的索引
4. 压缩后的检查点必须能恢复核心状态

## 五、恢复协议

### 恢复触发场景

1. Worker 进程崩溃
2. 节点故障
3. 用户点击恢复暂停的任务
4. 审批通过后继续
5. 手动从历史检查点恢复

### 恢复流程

> 正式恢复协议和 Action 副作用状态分类以 `REQ-RT-005` 为准；本文件只负责失败分类、恢复决策和补偿策略。

```text
1. 定位最新有效检查点
   ↓
2. 验证检查点版本和完整性
   ↓
3. 恢复工作区状态
   - 切换到 source_revision
   - 恢复工作分支
   - 验证工作区未被外部修改
   ↓
4. 恢复执行上下文
   - 加载对话历史（或压缩版本）
   - 加载 Artifacts
   - 恢复记忆状态
   ↓
5. 重新验证权限
   - 用户权限是否仍然有效
   - 仓库访问是否仍然可用
   ↓
6. 决定恢复点
   - 从下一个待执行 Action 开始
   - 或从失败的 Action 重试
   ↓
7. 签发新的短期凭据
   ↓
8. 创建新 Worker 实例
   ↓
9. 加载检查点状态到 Worker
   ↓
10. 继续执行
   ↓
11. 记录恢复事件
```

### 恢复验证

恢复后必须验证：

- [ ] `task_id` 和 `workflow_id` 一致
- [ ] 工作区 Git 状态与 `source_revision` 一致
- [ ] 已完成的 Action 不会重复执行
- [ ] 预算消耗正确累加
- [ ] Trace 链路完整
- [ ] 权限仍然有效

### 恢复失败处理

如果恢复失败：

1. 记录恢复失败原因
2. 尝试从更早的检查点恢复（最多回退 3 个）
3. 如果所有检查点都失败，标记为 `UNRECOVERABLE`
4. 保存现场快照
5. 通知用户和开发者
6. 提供选项：
   - 从头开始新任务
   - 手动修复后重试恢复
   - 放弃任务

## 六、幂等性保证

> **正式设计请参阅**：[`REQ-REL-006-write-operation-idempotency.md`](./REQ-REL-006-write-operation-idempotency.md)

该文档包含完整的：
- 确定性逻辑幂等键（排除运行时不稳定字段：`worker_id`、容器ID、尝试计数、客户端时间戳、span/trace ID）
- 确定性参数规范化（RFC 8785 JCS / Typed Schema）
- 六状态 Action 生命周期（`PROCESSING` → `SUCCEEDED` / `FAILED_RETRYABLE` / `FAILED_PERMANENT` / `IN_DOUBT` / `EXPIRED`）
- Fencing Lease Token 锁与原子事务边界
- 动态上下文重放闸门与 Header（`X-Idempotent-Replay: true`）
- SLA 驱动的 Read-Back Probe（替代固定重试次数）
- 确定性 Temporal Workflow / Activity 分离
- 保留与 GC 不变式（热 Redis 24h / 冷 PostgreSQL ≥ 180 天）
- 连接器能力层级 A-D 与性能要求
- 12 项验收标准

以下为历史草案示例，非正式规范：

### 幂等键（Idempotency Key）（历史草案）

每个 Action 拥有唯一幂等键：

```text
idempotency_key = hash(task_id + action_type + target_resources + arguments)
```

### 幂等性检查（历史草案）

执行 Action 前：

1. 查询该幂等键是否已成功执行
2. 如果已执行且成功，直接返回之前的结果
3. 如果已执行但失败，根据重试策略决定是否重试
4. 如果未执行，标记为执行中，执行后更新状态

### 写操作幂等性（历史草案）

#### 文件写入（历史草案）

```text
1. 检查目标文件当前内容
2. 如果内容已经是目标内容，跳过写入
3. 如果内容不同，执行写入
4. 记录写入前后的文件哈希
```

#### Git 操作（历史草案）

```text
# 创建分支
1. 检查分支是否已存在
2. 如果存在且指向正确 commit，跳过
3. 如果不存在，创建分支

# Commit
1. 检查是否有待提交的更改
2. 如果没有更改，跳过 commit
3. 如果有更改，创建 commit

# 推送
1. 检查远程是否已有相同 commit
2. 如果已存在，跳过推送
3. 如果不存在，推送
```

#### PR 创建（历史草案）

```text
1. 检查是否已存在相同源分支和目标分支的 PR
2. 如果存在且未关闭，返回现有 PR 编号
3. 如果不存在，创建新 PR
4. 记录 PR 编号到任务状态
```

#### 通知发送

```text
1. 通知必须包含幂等键
2. 通知系统去重
3. 或者通知失败只记录，不影响任务成功
```

### 不可幂等操作

以下操作天然不可幂等，必须特殊处理：

- **时间戳**：记录到 Action 元数据，不影响幂等性
- **随机数**：使用任务或 Action 级别的种子
- **外部 API 调用**：要么幂等（如 PUT），要么人工确认
- **审计日志**：允许重复，或包含幂等键去重

## 七、补偿工作流（Compensation）

### 补偿场景

当任务取消或失败时，需要清理：

- 临时分支
- 工作区
- 临时文件
- 短期凭据
- 未完成的 PR
- 分配的资源

### 补偿策略

```typescript
interface CompensationAction {
  action_id: string;
  compensation_for: string; // 原 Action ID
  type: "DELETE_BRANCH" | "CLOSE_PR" | "CLEANUP_WORKSPACE" | "REVOKE_CREDENTIAL";
  best_effort: boolean; // 如果失败是否继续
  timeout_ms: number;
}
```

### 补偿执行顺序

按相反顺序执行补偿：

```text
Action A (创建分支)
Action B (写入文件)
Action C (Commit)
Action D (创建 PR)

失败 → 补偿

Compensation D (关闭 PR，如果已创建)
Compensation C (无需补偿，commit 已存在)
Compensation B (可选：恢复文件，或依赖分支删除)
Compensation A (删除分支)
```

### 补偿失败处理

- 记录补偿失败日志
- 如果是 `best_effort`，继续下一个补偿
- 如果是关键资源（如凭据），告警人工介入
- 定期扫描孤立资源并清理

## 八、测试失败与工具异常的区分

> **正式设计请参阅**：[`REQ-REL-008-test-failure-tool-error-classification.md`](./REQ-REL-008-test-failure-tool-error-classification.md)

该文档包含完整的：
- 工具分波上线策略（W1 只读观测 + 可逆写入 + 测试执行器 → W2 原子化命令 → W3 审计 Shell）
- 工具注册表 7 件必填事项（Allowlist/Denylist、超时与资源上限、输出上限、幂等故事、可逆性标注、Pivot 标注、补偿与对账探针接口）
- 分类器设计（校准分数 + 证据，不含裁决阈值）
- 版本化配置契约（tool-registry-v1.yaml）
- 与 REL-003 重试决策引擎的集成
- 12 项验收标准

以下为历史草案示例，非正式规范：

### 测试失败（业务反馈）

**特征**：
- 测试工具本身成功执行
- 返回明确的测试结果（通过/失败）
- 有失败的测试用例和错误信息

**处理**：
- 不重试
- 保存测试报告为 Evidence
- 进入诊断流程
- Worker 分析失败原因
- 生成修复建议或请求人工介入

### 工具异常（系统故障）

**特征**：
- 测试工具崩溃或超时
- 无法解析测试输出
- 环境配置错误（如缺少依赖）

**处理**：
- 根据重试策略重试
- 如果是环境问题，尝试修复环境后重试
- 超过重试次数后标记为 `TOOL_ERROR`
- 记录工具日志和环境信息
- 通知开发者修复工具或环境

### 区分规则（历史草案）

```typescript
function classifyTestFailure(result: ToolResult): FailureType {
  if (result.exit_code === null || result.exit_code < 0) {
    return "TOOL_CRASHED";
  }
  if (result.timeout) {
    return "TOOL_TIMEOUT";
  }
  if (!result.output || result.output.includes("command not found")) {
    return "TOOL_NOT_FOUND";
  }
  if (result.exit_code > 0 && hasTestResults(result.output)) {
    return "TEST_FAILED"; // 业务失败，不重试
  }
  if (result.exit_code > 0) {
    return "TOOL_ERROR"; // 工具异常，可重试
  }
  return "SUCCESS";
}
```

## 九、故障注入测试

必须验证恢复机制的有效性。

### 测试场景

#### 1. Worker 崩溃

```bash
# 在任务执行中途杀死 Worker 进程
kill -9 <worker_pid>

# 验证
- 检查点已保存
- 新 Worker 启动
- 从检查点恢复
- 任务继续执行
- 已完成的 Action 不重复
```

#### 2. 网络瞬断

```bash
# 模拟网络延迟和丢包
tc qdisc add dev eth0 root netem delay 100ms loss 50%

# 验证
- API 请求自动重试
- 重试退避正确
- 超过重试次数后失败
```

#### 3. 模型限流

```bash
# 模拟 429 响应
mock_api_response(429, retry_after=5)

# 验证
- 遵循 Retry-After
- 重试次数递增
- 切换到备用模型（如配置）
```

#### 4. 检查点损坏

```bash
# 损坏最新检查点
corrupt_checkpoint(latest)

# 验证
- 自动回退到上一个检查点
- 恢复成功
- 记录检查点错误
```

#### 5. 存储失败

```bash
# 模拟磁盘满
dd if=/dev/zero of=/mnt/fill bs=1M

# 验证
- 检查点写入失败检测
- 任务暂停
- 告警触发
- 存储恢复后能继续
```

#### 6. 权限变更

```bash
# 任务执行中途撤销仓库访问权限
revoke_repo_access(user, repo)

# 验证
- 下一个操作被拒绝
- 不进入重试循环
- 标记为 AUTHORIZATION_FAILED
- 通知用户
```

#### 7. 时间跳跃

```bash
# 暂停任务，系统时间前进 24 小时，恢复任务
pause_task()
set_system_time(+24h)
resume_task()

# 验证
- 短期凭据已过期被更新
- 审批超时检测正确
- 预算时间统计正确
```

## 十、交付物清单

### Phase 1: 失败分类

- [ ] 完整的失败类型定义
- [ ] 每种失败的识别规则
- [ ] 每种失败的处理策略
- [ ] 决策树或流程图

### Phase 2: 重试策略与决策引擎

- [x] RetryPolicy Schema（详见 [`REQ-REL-002-retry-policy.md`](./REQ-REL-002-retry-policy.md)）
- [x] 预定义策略库（详见 [`REQ-REL-002-retry-policy.md`](./REQ-REL-002-retry-policy.md)）
- [x] 重试决策引擎（详见 [`REQ-REL-003-retry-decision-engine.md`](./REQ-REL-003-retry-decision-engine.md)，v0.2-designed；待跨模块评审与冻结）
- [x] 退避算法实现（详见 [`REQ-REL-002-retry-policy.md`](./REQ-REL-002-retry-policy.md)）
- [x] 重试监控指标（详见 [`REQ-REL-002-retry-policy.md`](./REQ-REL-002-retry-policy.md)）

### Phase 3: 检查点系统

- [x] Checkpoint Schema，详见 `REQ-RT-005`
- [x] 检查点保存协议和恢复边界，详见 `REQ-RT-005`
- [ ] 检查点存储实现
- [ ] 检查点压缩与上下文分层，详见 `REQ-HAR-002`
- [ ] 检查点保留、清理和容量策略，详见 `REQ-REL-004`

### Phase 4: 恢复机制

- [x] 恢复协议文档，详见 `REQ-RT-005`
- [ ] 恢复流程实现
- [x] 失败分类下的恢复验证规则，详见 `REQ-REL-005`
- [x] 恢复失败降级方案设计，详见 `REQ-REL-005`、`REQ-REL-007`

### Phase 5: 幂等性

- [x] 幂等键生成规则（详见 [`REQ-REL-006-write-operation-idempotency.md`](./REQ-REL-006-write-operation-idempotency.md)）
- [x] 幂等性检查实现（详见 [`REQ-REL-006-write-operation-idempotency.md`](./REQ-REL-006-write-operation-idempotency.md)）
- [x] 写操作幂等封装（详见 [`REQ-REL-006-write-operation-idempotency.md`](./REQ-REL-006-write-operation-idempotency.md)）
- [ ] 幂等性测试用例

### Phase 6: 补偿工作流

- [ ] 补偿策略定义
- [ ] 补偿执行引擎
- [ ] 孤立资源扫描
- [ ] 补偿失败告警

### Phase 7: 故障注入

- [ ] 故障注入工具
- [ ] 故障场景库
- [ ] 自动化测试套件
- [ ] 混沌工程实践

## 十一、验收标准

### 功能验收

- [ ] Worker 崩溃后能从检查点恢复
- [ ] 网络瞬断自动重试成功
- [ ] 权限拒绝不会进入重试循环
- [ ] 测试失败进入诊断流程而不是重试
- [ ] 相同 Action 重试时不重复执行
- [ ] 用户暂停后能恢复并继续
- [ ] 补偿工作流正确清理资源
- [ ] 所有故障注入测试通过

### 性能验收

- [ ] 检查点保存时间 < 1s（p95）
- [ ] 检查点恢复时间 < 5s（p95）
- [ ] 重试不影响正常任务延迟
- [ ] 检查点存储成本可控

### 可靠性验收

- [ ] 99.9% 的任务能从崩溃中恢复
- [ ] 检查点损坏率 < 0.01%
- [ ] 无重复副作用（如重复创建 PR）

## 十二、监控指标

### 关键指标

- `task_retry_count`：任务重试次数分布
- `action_retry_count`：Action 重试次数分布
- `failure_type_distribution`：失败类型分布
- `checkpoint_save_duration`：检查点保存耗时
- `checkpoint_size`：检查点大小分布
- `recovery_duration`：恢复耗时
- `recovery_success_rate`：恢复成功率
- `compensation_failure_rate`：补偿失败率
- `orphaned_resources_count`：孤立资源数量

### 告警规则

- 恢复成功率 < 95%
- 检查点写入失败率 > 0.1%
- 单任务重试次数 > 10
- 孤立资源数量 > 100
- 补偿失败率 > 1%

## 十三、参考资料

- Temporal Workflow Error Handling
- AWS Step Functions Error Handling
- Kubernetes Job Backoff Policy
- Circuit Breaker Pattern
- Saga Pattern
- Event Sourcing Recovery

## 十四、下一步行动

> 本文件描述可靠性专项中待设计与待实现方向；`REQ-RT-005` 的检查点详细设计已完成，不能再作为待设计任务重复执行。正式设计以独立需求文档和 `PENDING-REQUIREMENTS.md` 为准。

1. 完成失败分类与 RetryPolicy 专项设计
2. 完成检查点保留策略和恢复决策专项设计
3. 实现检查点保存和恢复
5. 实现幂等性检查
6. 编写故障注入测试
7. 执行混沌工程验证
8. 建立监控和告警
