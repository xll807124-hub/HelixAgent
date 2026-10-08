# REQ-OBS-003 指标字典详细设计

> 所属基线：`Observability Baseline v0.1`  
> 需求编号：`REQ-OBS-003`  
> 优先级：P0  
> 设计版本：`v0.1-designed`  
> 设计状态：详细设计已完成，待跨模块冻结  
> 前置依赖：`REQ-RT-001`、`REQ-EVA-005`、`REQ-OBS-001`  
> 关键决策：采用 OpenTelemetry GenAI 语义约定；四类指标类型；高基数控制算法；SemVer 版本管理

---

## 1. 需求定义

### 1.1 目标

为 AI Agent 平台建立标准化、可扩展的指标字典体系，定义所有业务和系统指标的元数据规范，支持多维度性能分析、成本监控和质量评估。确保跨模块指标的可聚合性和可分析性。

### 1.2 用户价值

- **SRE/运维**：实时监控服务健康，快速定位性能瓶颈
- **AI 研究员**：评估模型效果，优化模型选择和 Prompt 策略
- **平台运营**：分析成本消耗，优化资源配置
- **安全审计员**：追踪关键操作，生成合规报告
- **开发人员**：调试性能问题，分析执行路径

### 1.3 范围

**包含**：
- 指标命名规范和层级结构
- 指标类型定义（Counter/Gauge/Histogram/Summary）
- 指标单位和聚合规则
- 指标分组维度定义
- 高基数控制策略
- 指标版本管理

**不包含**：
- 具体的告警规则配置（由 `REQ-OBS-005` 定义）
- 脱敏实现细节（由 `REQ-OBS-004` 定义）
- 审计查询 API 实现（由 `REQ-OBS-006` 定义）
- 时序数据库选型和部署

---

## 2. 共享契约与术语

本设计复用 `REQ-RT-001` 定义的核心实体（TaskId、WorkflowId、WorkerId、ActionId）和 `REQ-OBS-001` 定义的语义约定（`gen_ai.*` 前缀、属性命名）。

### 2.1 核心术语

| 术语 | 定义 |
|------|------|
| **Metric** | 可量化的业务或系统指标，包含名称、类型、值和维度 |
| **Metric Dictionary** | 指标元数据的集合，定义指标名称、类型、单位、描述 |
| **Cardinality** | 指标维度组合的基数，影响存储和查询成本 |
| **Aggregation** | 指标在时间窗口内的聚合计算（sum/avg/min/max/percentile） |
| **Dimension** | 指标的分组维度（org/project/model/tool 等） |
| **Metric Type** | 指标类型（Counter/Gauge/Histogram/Summary） |

---

## 3. 行业调研与可借鉴原则

### 3.1 OpenTelemetry GenAI SIG

**来源**：[OpenTelemetry AI Agent Observability](https://opentelemetry.io/blog/2025/ai-agent-observability/)  
**访问日期**：2026-10-04

**关键发现**：
- GenAI SIG 定义了六大层次：LLM、Agent、Tool、Workflow、Memory、Content
- 指标命名遵循 `gen_ai.*` 前缀模式
- 属性采用 `verb_object` 模式
- gen_ai.provider.name 作为多供应商兼容的鉴别器

**借鉴点**：采用 `gen_ai.*` 前缀统一命名；六层层次结构；供应商无关设计。

**证据等级**：A（官方文档）

---

### 3.2 Cursor Enterprise

**来源**：[Cursor OpenTelemetry Export](https://cursor.com/docs/enterprise/opentelemetry-export)  
**访问日期**：2026-10-04

**关键发现**：
- 指标类型：
  - `cursor.token.usage`：按 token 类型区分（input/output/cache_read/cache_creation）
  - `cursor.tool.calls`：内置工具和 MCP 工具调用
  - `cursor.cost.usage`：USD 成本估算（尽力而为，非发票）
- 指标采用至多一次传送（at-most-once）
- 指标数据点不携带关联 ID，降低基数

**借鉴点**：分层指标设计（token/tool/cost）；尽力而为的估算与精确计费分离；指标基数控制。

**证据等级**：A（官方文档）

---

### 3.3 Prometheus 指标类型标准

**来源**：行业标准实践  
**访问日期**：2026-10-04

**关键发现**：
- Counter：只增不减的累计值
- Gauge：可增可减的瞬时值
- Histogram：分布值的分桶统计
- Summary：服务端计算的分位值

**借鉴点**：四类指标类型清晰定义；命名约定（_total、_count、_sum 后缀）。

**证据等级**：A（行业标准）

---

### 3.4 Microsoft Copilot Studio

**来源**：[Microsoft Copilot Studio Telemetry](https://learn.microsoft.com/en-us/microsoft-copilot-studio/telemetry-overview)  
**访问日期**：2026-10-04

**关键发现**：
- 两层遥测架构：Agent-level（事件驱动）vs Environment-level（Trace/Span）
- 评估结果：`gen_ai.evaluation.result`（分数、标签、解释）
- 集中式托管配置策略

**借鉴点**：两层指标架构分离；评估结果结构化追踪。

**证据等级**：A（官方文档）

---

## 4. 指标分类体系

### 4.1 指标类型定义

#### 4.1.1 Counter（计数器）

**定义**：只增不减的累计值，用于计数类指标。

**语义**：
- 值单调递增
- 适用于累计请求数、成功次数、失败次数
- 通常以 `_total` 或 `_count` 结尾

**示例**：
```yaml
gen_ai.task.completed.total:
  type: Counter
  unit: "{task}"
  description: "Total number of completed tasks"
  dimensions: [organization_id, project_id, status]

gen_ai.tool.calls.total:
  type: Counter
  unit: "{call}"
  description: "Total number of tool calls"
  dimensions: [organization_id, tool_name, tool_kind]
```

---

#### 4.1.2 Gauge（仪表）

**定义**：可增可减的瞬时值，用于状态类指标。

**语义**：
- 值可升可降
- 适用于当前队列长度、活跃连接数、资源使用率
- 采样时刻的快照值

**示例**：
```yaml
gen_ai.task.queue.size:
  type: Gauge
  unit: "{task}"
  description: "Current number of tasks in queue"
  dimensions: [organization_id, queue_name]

gen_ai.worker.active.count:
  type: Gauge
  unit: "{worker}"
  description: "Number of active workers"
  dimensions: [organization_id, worker_type]
```

---

#### 4.1.3 Histogram（直方图）

**定义**：分布值的分桶统计，用于延迟和大小类指标。

**语义**：
- 值按预定义桶边界分组
- 提供 count、sum、bucket 三个时间序列
- 适用于请求延迟、响应大小、token 数量

**示例**：
```yaml
gen_ai.task.duration:
  type: Histogram
  unit: "ms"
  description: "Task execution duration distribution"
  dimensions: [organization_id, task_type]
  buckets: [100, 500, 1000, 5000, 10000, 30000, 60000]

gen_ai.token.usage:
  type: Histogram
  unit: "{token}"
  description: "Token usage distribution per request"
  dimensions: [organization_id, model, token_type]
  buckets: [100, 500, 1000, 5000, 10000, 50000, 100000]
```

---

#### 4.1.4 Summary（摘要）

**定义**：服务端计算的分位值，用于精确分位数分析。

**语义**：
- 在采集端计算分位值
- 提供 count、sum、quantile 三个时间序列
- 适用于 API 延迟、响应时间

**示例**：
```yaml
gen_ai.api.latency:
  type: Summary
  unit: "ms"
  description: "API request latency summary"
  dimensions: [organization_id, provider, model]
  quantiles: [0.5, 0.9, 0.95, 0.99]
```

---

## 5. 指标命名规范

### 5.1 命名约定

**格式**：`{namespace}.{component}.{metric_name}.{suffix}`

**规则**：
- `namespace`：固定为 `gen_ai`（对齐 OpenTelemetry GenAI SIG）
- `component`：组件名称（task/workflow/worker/action/tool/model/sandbox）
- `metric_name`：指标名称（描述性、小写、下划线分隔）
- `suffix`：类型后缀（total/count/sum/duration/size/rate）

**示例**：
```
gen_ai.task.completed.total        # Task 完成总数（Counter）
gen_ai.tool.calls.total            # 工具调用总数（Counter）
gen_ai.model.latency.duration      # 模型延迟（Histogram）
gen_ai.token.usage.total           # Token 使用总数（Counter）
gen_ai.cost.usage.sum              # 成本累计（Counter）
```

---

### 5.2 命名层级

```
gen_ai.*
├── task.*                 # 任务级指标
│   ├── completed.total
│   ├── failed.total
│   ├── cancelled.total
│   ├── duration.histogram
│   └── queue.size
├── workflow.*             # 工作流级指标
│   ├── started.total
│   ├── completed.total
│   ├── failed.total
│   └── duration.histogram
├── worker.*               # Worker 级指标
│   ├── active.count
│   ├── started.total
│   ├── completed.total
│   └── duration.histogram
├── action.*               # Action 级指标
│   ├── proposed.total
│   ├── authorized.total
│   ├── rejected.total
│   └── duration.histogram
├── tool.*                 # 工具级指标
│   ├── calls.total
│   ├── success.total
│   ├── failure.total
│   ├── timeout.total
│   └── duration.histogram
├── model.*                # 模型级指标
│   ├── requests.total
│   ├── errors.total
│   ├── latency.histogram
│   └── ttft.histogram
├── token.*                # Token 级指标
│   ├── usage.total
│   ├── input.total
│   ├── output.total
│   ├── cache_read.total
│   └── cache_creation.total
├── cost.*                 # 成本级指标
│   ├── usage.total
│   └── estimated.gauge
└── security.*             # 安全级指标
    ├── policy_denied.total
    ├── injection_detected.total
    └── credential_access.total
```

---

## 6. 指标维度定义

### 6.1 核心维度

| 维度名 | 类型 | 基数 | 说明 | 示例 |
|--------|------|------|------|------|
| `organization_id` | string | 低 | 组织标识 | `org_123` |
| `project_id` | string | 中 | 项目标识 | `proj_456` |
| `repository_id` | string | 中 | 仓库标识 | `repo_789` |
| `user_id` | string | 高 | 用户标识 | `user_001` |
| `task_type` | enum | 低 | 任务类型 | `bug_fix` / `feature` |
| `worker_type` | enum | 低 | Worker 类型 | `planner` / `coder` |
| `tool_name` | string | 中 | 工具名称 | `git_commit` / `pytest` |
| `tool_kind` | enum | 低 | 工具类型 | `builtin` / `mcp` |
| `model` | string | 低 | 模型名称 | `gpt-4o` / `claude-opus-4` |
| `provider` | string | 低 | 模型供应商 | `openai` / `anthropic` |
| `token_type` | enum | 低 | Token 类型 | `input` / `output` / `cache_read` |
| `status` | enum | 低 | 状态 | `success` / `failure` / `timeout` |
| `risk_level` | enum | 低 | 风险级别 | `low` / `medium` / `high` |

---

### 6.2 维度基数控制策略

**基数分类**：
- **低基数**（< 100）：允许作为维度，无限制
- **中基数**（100 - 10,000）：允许作为维度，需审批
- **高基数**（> 10,000）：禁止作为维度，或降级处理

**控制算法**：
```python
def check_cardinality(dimensions: List[str]) -> bool:
    """检查维度组合基数是否超限"""
    cardinality = 1
    for dim in dimensions:
        cardinality *= get_dimension_cardinality(dim)
        if cardinality > CARDINALITY_THRESHOLD:
            return False
    return True

def register_metric(metric_name: str, dimensions: List[str]):
    """注册指标，检查基数"""
    if not check_cardinality(dimensions):
        raise HighCardinalityError(
            f"Metric {metric_name} has high cardinality: {dimensions}"
        )
    # 注册指标
```

**降级策略**：
- 高基数维度（如 user_id）默认不作为维度
- 如需按用户分析，通过日志事件关联
- 提供聚合维度（如 user_count）代替

---

## 7. 指标字典定义

### 7.1 任务级指标

```yaml
# 任务完成总数
gen_ai.task.completed.total:
  type: Counter
  unit: "{task}"
  description: "Total number of completed tasks"
  dimensions:
    - organization_id
    - project_id
    - task_type
    - status
  labels:
    status: [success, failure]
    task_type: [bug_fix, feature, test, refactor]

# 任务失败总数
gen_ai.task.failed.total:
  type: Counter
  unit: "{task}"
  description: "Total number of failed tasks"
  dimensions:
    - organization_id
    - project_id
    - task_type
    - failure_category

# 任务取消总数
gen_ai.task.cancelled.total:
  type: Counter
  unit: "{task}"
  description: "Total number of cancelled tasks"
  dimensions:
    - organization_id
    - project_id
    - task_type

# 任务执行时长分布
gen_ai.task.duration:
  type: Histogram
  unit: "ms"
  description: "Task execution duration distribution"
  dimensions:
    - organization_id
    - project_id
    - task_type
  buckets: [1000, 5000, 10000, 30000, 60000, 300000, 600000]

# 任务队列大小
gen_ai.task.queue.size:
  type: Gauge
  unit: "{task}"
  description: "Current number of tasks in queue"
  dimensions:
    - organization_id
    - queue_name
```

---

### 7.2 工具级指标

```yaml
# 工具调用总数
gen_ai.tool.calls.total:
  type: Counter
  unit: "{call}"
  description: "Total number of tool calls"
  dimensions:
    - organization_id
    - tool_name
    - tool_kind
  labels:
    tool_kind: [builtin, mcp]

# 工具成功总数
gen_ai.tool.success.total:
  type: Counter
  unit: "{call}"
  description: "Total number of successful tool calls"
  dimensions:
    - organization_id
    - tool_name
    - tool_kind

# 工具失败总数
gen_ai.tool.failure.total:
  type: Counter
  unit: "{call}"
  description: "Total number of failed tool calls"
  dimensions:
    - organization_id
    - tool_name
    - tool_kind
    - error_type

# 工具超时总数
gen_ai.tool.timeout.total:
  type: Counter
  unit: "{call}"
  description: "Total number of tool timeouts"
  dimensions:
    - organization_id
    - tool_name

# 工具执行时长分布
gen_ai.tool.duration:
  type: Histogram
  unit: "ms"
  description: "Tool execution duration distribution"
  dimensions:
    - organization_id
    - tool_name
    - tool_kind
  buckets: [10, 50, 100, 500, 1000, 5000, 10000]
```

---

### 7.3 模型级指标

```yaml
# 模型请求总数
gen_ai.model.requests.total:
  type: Counter
  unit: "{request}"
  description: "Total number of model requests"
  dimensions:
    - organization_id
    - provider
    - model

# 模型错误总数
gen_ai.model.errors.total:
  type: Counter
  unit: "{request}"
  description: "Total number of model errors"
  dimensions:
    - organization_id
    - provider
    - model
    - error_type

# 模型延迟分布
gen_ai.model.latency:
  type: Histogram
  unit: "ms"
  description: "Model request latency distribution"
  dimensions:
    - organization_id
    - provider
    - model
  buckets: [100, 500, 1000, 2000, 5000, 10000, 30000]

# 首 Token 时间分布（TTFT）
gen_ai.model.ttft:
  type: Histogram
  unit: "ms"
  description: "Time to first token distribution"
  dimensions:
    - organization_id
    - provider
    - model
  buckets: [100, 300, 500, 1000, 2000, 5000]
```

---

### 7.4 Token 级指标

```yaml
# Token 使用总数
gen_ai.token.usage.total:
  type: Counter
  unit: "{token}"
  description: "Total number of tokens used"
  dimensions:
    - organization_id
    - provider
    - model
    - token_type
  labels:
    token_type: [input, output, cache_read, cache_creation, reasoning]

# 输入 Token 总数
gen_ai.token.input.total:
  type: Counter
  unit: "{token}"
  description: "Total number of input tokens"
  dimensions:
    - organization_id
    - provider
    - model

# 输出 Token 总数
gen_ai.token.output.total:
  type: Counter
  unit: "{token}"
  description: "Total number of output tokens"
  dimensions:
    - organization_id
    - provider
    - model

# 缓存读取 Token 总数
gen_ai.token.cache_read.total:
  type: Counter
  unit: "{token}"
  description: "Total number of cache read tokens"
  dimensions:
    - organization_id
    - provider
    - model

# 缓存创建 Token 总数
gen_ai.token.cache_creation.total:
  type: Counter
  unit: "{token}"
  description: "Total number of cache creation tokens"
  dimensions:
    - organization_id
    - provider
    - model
```

---

### 7.5 成本级指标

```yaml
# 成本累计（尽力而为估算）
gen_ai.cost.usage.total:
  type: Counter
  unit: "USD"
  description: "Total estimated cost (best-effort, not invoice)"
  dimensions:
    - organization_id
    - provider
    - model

# 成本实时估算值
gen_ai.cost.estimated.gauge:
  type: Gauge
  unit: "USD"
  description: "Current estimated cost rate"
  dimensions:
    - organization_id
    - provider
```

---

### 7.6 安全级指标

```yaml
# 策略拒绝总数
gen_ai.security.policy_denied.total:
  type: Counter
  unit: "{event}"
  description: "Total number of policy denials"
  dimensions:
    - organization_id
    - policy_name
    - action_type

# Prompt 注入检测总数
gen_ai.security.injection_detected.total:
  type: Counter
  unit: "{event}"
  description: "Total number of detected injection attempts"
  dimensions:
    - organization_id
    - injection_type

# 凭据访问总数
gen_ai.security.credential_access.total:
  type: Counter
  unit: "{event}"
  description: "Total number of credential access operations"
  dimensions:
    - organization_id
    - credential_type
```

---

## 8. 聚合规则定义

### 8.1 时间窗口

| 窗口大小 | 用途 | 保留期 |
|---------|------|--------|
| **1m** | 实时监控 | 1 天 |
| **5m** | 近期分析 | 7 天 |
| **15m** | 趋势分析 | 30 天 |
| **1h** | 历史分析 | 90 天 |
| **1d** | 长期趋势 | 1 年 |

### 8.2 聚合函数

| 函数 | 适用类型 | 说明 |
|------|---------|------|
| `sum` | Counter, Histogram | 累加值 |
| `avg` | Gauge, Histogram | 平均值 |
| `min` | Gauge, Histogram | 最小值 |
| `max` | Gauge, Histogram | 最大值 |
| `percentile(p)` | Histogram, Summary | 分位值（p50/p90/p95/p99） |
| `rate` | Counter | 变化率（per second） |
| `increase` | Counter | 增量值 |

### 8.3 预聚合视图

```yaml
# 组织级 Token 使用日报
gen_ai.token.usage.daily:
  source: gen_ai.token.usage.total
  window: 1d
  aggregation: sum
  dimensions: [organization_id, model, token_type]

# 项目级任务成功率小时报
gen_ai.task.success_rate.hourly:
  source: gen_ai.task.completed.total
  window: 1h
  aggregation: rate(sum(status="success") / sum(*))
  dimensions: [organization_id, project_id]
```

---

## 9. 指标采集与导出

### 9.1 采集流程

```
业务事件发生
  ↓
指标采集器 (SDK)
  ↓
本地缓冲 (10s / 1000 点)
  ↓
OTLP 导出器
  ↓
OpenTelemetry Collector
  ↓
时序数据库 (Prometheus / VictoriaMetrics / InfluxDB)
```

### 9.2 采集延迟要求

| 指标类别 | 采集延迟 | 导出延迟 |
|---------|---------|---------|
| 关键路径 | < 1ms (p99) | < 100ms (p95) |
| 非关键路径 | < 10ms (p99) | < 1s (p95) |
| 批量聚合 | < 100ms (p99) | < 10s (p95) |

### 9.3 导出配置

```yaml
# OpenTelemetry Collector 配置示例
receivers:
  otlp:
    protocols:
      http:
        endpoint: 0.0.0.0:4318

processors:
  batch:
    timeout: 10s
    send_batch_size: 1000
  
  # 高基数维度过滤
  filter:
    metrics:
      exclude:
        match_type: strict
        metric_names:
          - gen_ai.*.user_id  # 排除高基数维度

exporters:
  prometheus:
    endpoint: "0.0.0.0:8889"
    namespace: "gen_ai"
  
  influxdb:
    endpoint: "http://influxdb:8086"
    database: "gen_ai_metrics"

service:
  pipelines:
    metrics:
      receivers: [otlp]
      processors: [batch, filter]
      exporters: [prometheus, influxdb]
```

---

## 10. 版本管理与演进

### 10.1 版本策略

**版本号格式**：`MAJOR.MINOR.PATCH`（SemVer）

**版本规则**：
- **MAJOR**：不兼容的指标废弃或重命名
- **MINOR**：新增指标或维度
- **PATCH**：文档修正或说明更新

**当前版本**：`0.1.0`

### 10.2 指标废弃流程

**废弃流程**：
1. 标记为 `@deprecated`，在文档和代码中注明
2. 提前 90 天公告废弃计划
3. 提供迁移指南和替代指标
4. 下个 MAJOR 版本正式移除

**示例**：
```yaml
# 已废弃（v0.1.0 标记，v1.0.0 移除）
gen_ai.task.count.total:
  deprecated: true
  deprecated_since: "0.1.0"
  removed_in: "1.0.0"
  replacement: "gen_ai.task.completed.total"
  reason: "Renamed for clarity"
```

### 10.3 演进路径

**Phase 1（v0.1.0）**：基础指标
- 任务、工具、模型、Token、成本指标
- 核心维度（org/project/model/tool）

**Phase 2（v0.2.0）**：扩展指标
- Worker、Workflow、Action 指标
- 安全、质量、评估指标

**Phase 3（v0.3.0）**：自定义指标
- 用户自定义指标注册
- 插件化指标扩展
- 动态维度配置

---

## 11. 异常与失败处理

### 11.1 指标采集失败

**症状**：指标采集器异常或超时

**处理**：
1. 本地缓冲重试（最多 3 次，指数退避）
2. 超过阈值后丢弃并记录 `obs.metrics.drop.count`
3. 不阻塞业务主路径

### 11.2 OTLP 导出失败

**症状**：OTLP 导出返回 503 或连接超时

**处理**：
1. 本地缓冲队列保存（最大 10,000 点）
2. 指数退避重试（1s、2s、4s、8s、16s）
3. 超过重试次数后丢弃，记录 `obs.metrics.export.drop.count`

### 11.3 高基数指标检测

**症状**：维度组合基数超过阈值（10,000）

**处理**：
1. 拒绝注册新指标，抛出 `HighCardinalityError`
2. 记录拒绝事件到 `obs.metrics.high_cardinality.rejected`
3. 触发告警通知管理员

### 11.4 指标定义冲突

**症状**：尝试注册已存在的指标名称

**处理**：
1. 拒绝注册，抛出 `MetricConflictError`
2. 提示已有同名指标
3. 建议使用不同名称或维度

---

## 12. 性能与成本考量

### 12.1 性能目标

| 指标 | 目标 | 测量方法 |
|------|------|---------|
| 指标采集延迟 | < 1ms (p99) | 微基准测试 |
| 指标导出吞吐 | > 10,000 点/秒 | 压力测试 |
| 时序数据库写入延迟 | < 50ms (p95) | 端到端测量 |
| 查询延迟（30 天） | < 500ms (p95) | 查询基准测试 |

### 12.2 成本控制

**存储成本**：
- 热存储（1 天）：< $0.01/百万数据点
- 温存储（30 天）：< $0.001/百万数据点
- 冷存储（1 年）：< $0.0001/百万数据点

**基数控制**：
- 单指标最大基数：10,000
- 组织级指标总数：< 100
- 平台级指标总数：< 500

**降采样策略**：
- 1m 窗口：100% 保留
- 5m 窗口：聚合后保留
- 1h 窗口：仅保留聚合结果
- 1d 窗口：仅保留聚合结果

---

## 13. 可观测性与评估指标

### 13.1 指标字典质量指标

| 指标名 | 定义 | 目标 | 告警条件 |
|--------|------|------|---------|
| `obs.metrics.dictionary.coverage` | 已定义指标数 / 应有指标数 | ≥ 90% | < 80% |
| `obs.metrics.documented.ratio` | 已文档化指标数 / 已定义指标数 | 100% | < 100% |
| `obs.metrics.emitted.ratio` | 实际采集数 / 计划采集数 | ≥ 99% | < 95% |

### 13.2 指标导出质量指标

| 指标名 | 定义 | 目标 | 告警条件 |
|--------|------|------|---------|
| `obs.metrics.export.success.rate` | 成功导出率 | ≥ 99.9% | < 99% |
| `obs.metrics.export.latency.p95` | 导出延迟 p95 | < 100ms | > 500ms |
| `obs.metrics.export.drop.count` | 丢弃的数据点数 | < 0.1% | > 1% |
| `obs.metrics.high_cardinality.rejected` | 拒绝的高基数指标数 | < 10/天 | > 50/天 |

---

## 14. 验收标准

### 14.1 功能性验收

| # | 验收项 | 验收方法 |
|---|--------|---------|
| 1 | 指标字典覆盖所有业务关键路径 | 代码审查 + 测试覆盖 |
| 2 | 指标命名符合 `gen_ai.*` 前缀规范 | 正则匹配验证 |
| 3 | 每条指标有完整元数据 | Schema 验证 |
| 4 | 高基数指标有防护机制 | 压力测试 + 监控告警 |
| 5 | 指标采集不阻塞业务主路径 | 性能测试 < 1ms |
| 6 | 支持多维度聚合查询 | 集成测试 |
| 7 | 指标数据按组织隔离 | 安全测试 |

### 14.2 性能验收

| # | 验收项 | 目标 | 验收方法 |
|---|--------|------|---------|
| 8 | 指标采集延迟 | < 1ms (p99) | 微基准测试 |
| 9 | 指标导出吞吐 | > 10,000 点/秒 | 压力测试 |
| 10 | 时序数据库写入延迟 | < 50ms (p95) | 端到端测量 |
| 11 | 查询延迟（30 天） | < 500ms (p95) | 查询基准测试 |

### 14.3 质量验收

| # | 验收项 | 目标 | 验收方法 |
|---|--------|------|---------|
| 12 | 指标采集成功率 | ≥ 99% | 监控统计 |
| 13 | 指标导出成功率 | ≥ 99.9% | 监控统计 |
| 14 | 高基数拒绝率 | < 1% | 监控统计 |

---

## 15. 依赖与跨模块边界

### 15.1 前置依赖

| 需求 | 依赖内容 | 边界 |
|------|---------|------|
| `REQ-RT-001` | 核心实体定义（TaskId、WorkflowId、ActionId） | 维度字段来源 |
| `REQ-EVA-005` | 回归流水线 | 指标用于质量评估 |
| `REQ-OBS-001` | OpenTelemetry 语义约定 | 命名和属性规范 |

### 15.2 下游依赖

| 需求 | 本设计提供的内容 | 边界 |
|------|---------------|------|
| `REQ-OBS-004` | 指标维度和敏感度定义 | 由 OBS-004 实现脱敏 |
| `REQ-OBS-005` | 指标和阈值定义 | 由 OBS-005 配置告警 |
| `REQ-OBS-006` | 指标查询字段 | 由 OBS-006 实现查询 API |

---

## 16. 实现指导

### 16.1 推荐技术栈

**指标采集 SDK**：
- Python：`opentelemetry-api`, `opentelemetry-sdk`
- Node.js：`@opentelemetry/api`, `@opentelemetry/sdk-metrics`
- Go：`go.opentelemetry.io/otel/metric`

**OTLP Collector**：
- OpenTelemetry Collector（推荐）
- Grafana Agent
- Datadog Agent

**时序数据库**：
- Prometheus（推荐）
- VictoriaMetrics
- InfluxDB
- Datadog APM

### 16.2 实现检查清单

- [ ] 定义指标字典 YAML 配置文件
- [ ] 实现指标采集 SDK 封装
- [ ] 实现高基数检测算法
- [ ] 配置 OTLP Collector
- [ ] 部署时序数据库
- [ ] 实现预聚合视图
- [ ] 配置监控面板
- [ ] 编写单元测试和集成测试
- [ ] 编写运维文档

---

## 17. 版本与变更记录

### 17.1 当前状态

`REQ-OBS-003` 当前版本为 `v0.1-designed`：本专项详细设计已完成，待与 Runtime Contract、可观测性其他专项交叉评审后冻结。设计完成不代表已实现或运行指标已经验证。

### 17.2 冻结条件

1. 与 `REQ-RT-001` 完成核心实体、维度字段交叉评审
2. 与 `REQ-OBS-001` 对齐语义约定和命名规范
3. 与 `REQ-OBS-002` 对齐 Event 字段和指标来源
4. 与 `REQ-OBS-004/005/006` 确认脱敏、告警、查询接口边界
5. 完成指标字典文档验证和基数控制测试

### 17.3 变更记录

| 版本 | 日期 | 变更 |
|------|------|------|
| `v0.1-designed` | 2026-10-04 | 基于 OpenTelemetry GenAI SIG、Cursor Enterprise、Prometheus 标准、Microsoft Copilot 公开资料，完成指标分类、命名规范、维度定义、聚合规则、版本管理设计 |

---

**文档维护**：架构组  
**最后更新**：2026-10-04
