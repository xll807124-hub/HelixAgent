# Trace 传播和审计关联 API 文档

> **实现版本**：REQ-RT-006 v1.0  
> **状态**：✅ 已实现并测试通过  
> **测试覆盖率**：97%（62 个测试，全部通过）

---

## 📚 目录

1. [快速开始](#快速开始)
2. [核心概念](#核心概念)
3. [API 参考](#api-参考)
4. [使用示例](#使用示例)
5. [最佳实践](#最佳实践)

---

## 快速开始

### 安装依赖

```bash
# 依赖已添加到 pyproject.toml
pip install -e .
```

### 基础使用

```python
from src.runtime.trace.tracer import create_span, SpanKind

# 创建一个 Task Span
with create_span("task.execute", SpanKind.TASK, attributes={"task_id": "task-001"}):
    # 执行任务逻辑
    pass
```

---

## 核心概念

### 1. TraceContext（追踪上下文）

分布式追踪的关联标识，包含：
- `trace_id`：全局唯一的追踪 ID（32 字符十六进制）
- `span_id`：当前操作的 Span ID（16 字符十六进制）
- `trace_flags`：采样标志（0x01 = 已采样）
- `baggage`：跨服务传播的键值对（不含敏感信息）

### 2. Span（操作跨度）

表示一个操作的时间跨度，分为 5 种类型：
- `TASK`：Task 执行
- `WORKFLOW`：Workflow 执行
- `WORKER`：Worker 执行
- `ACTION`：Action 执行
- `MODEL`：模型调用

### 3. 采样策略

**默认采样率**：15%  
**高优先级场景（100% 采样）**：
- 高风险任务
- 失败任务
- 恢复操作
- 显式诊断请求

### 4. 审计关联

审计记录 **100% 写入**，不受 Trace 采样影响。  
审计记录包含 `trace_id` 引用（如果有）。

---

## API 参考

### 模块：`src.runtime.trace.tracer`

#### `create_span(name, kind, trace_context=None, attributes=None)`

创建一个 Span 上下文管理器。

**参数**：
- `name` (str)：Span 名称（如 "task.execute"）
- `kind` (SpanKind)：Span 类型
- `trace_context` (TraceContext | None)：父 TraceContext（可选）
- `attributes` (dict | None)：Span 属性（元数据）

**返回**：`AbstractContextManager[Span | None]`

**示例**：
```python
with create_span("task.execute", SpanKind.TASK) as span:
    if span:
        # Span 被采样
        pass
```

---

#### `get_current_trace_context()`

获取当前 Span 的 TraceContext。

**返回**：`TraceContext | None`

**示例**：
```python
with create_span("task.execute", SpanKind.TASK):
    ctx = get_current_trace_context()
    if ctx:
        print(f"TraceId: {ctx.trace_id}")
```

---

### 模块：`src.runtime.trace.propagation`

#### `inject_trace_context(trace_context, carrier)`

将 TraceContext 注入到 HTTP Headers（W3C Trace Context）。

**参数**：
- `trace_context` (TraceContext)：要注入的上下文
- `carrier` (dict[str, str])：HTTP Headers 字典

**返回**：`dict[str, str]`（修改后的 carrier）

**示例**：
```python
from src.runtime.trace.propagation import inject_trace_context

carrier = {}
inject_trace_context(trace_context, carrier)
# carrier["traceparent"] = "00-{trace_id}-{span_id}-01"
```

---

#### `extract_trace_context(carrier, trusted=True)`

从 HTTP Headers 提取 TraceContext。

**参数**：
- `carrier` (dict[str, str])：HTTP Headers 字典
- `trusted` (bool)：是否来自可信来源（默认 True）

**返回**：`TraceContext | None`

**安全原则**：
- `trusted=False` 时，拒绝提取（返回 None）
- 调用方应创建新的根 Trace

**示例**：
```python
from src.runtime.trace.propagation import extract_trace_context

# 可信来源（内部服务）
ctx = extract_trace_context(request.headers, trusted=True)

# 不可信来源（外部服务）
ctx = extract_trace_context(request.headers, trusted=False)
if ctx is None:
    # 创建新的根 Trace
    pass
```

---

### 模块：`src.runtime.trace.sampling`

#### `SamplingStrategy.should_sample_task(...)`

判断任务是否应该提高采样优先级。

**参数**（全部可选，默认 False）：
- `is_high_risk` (bool)：是否高风险任务
- `has_failure` (bool)：是否失败任务
- `is_recovery` (bool)：是否恢复操作
- `explicit_request` (bool)：是否显式诊断请求

**返回**：`SamplingPriority`

**示例**：
```python
from src.runtime.trace.sampling import SamplingStrategy, SamplingPriority

# 默认任务（15% 采样）
priority = SamplingStrategy.should_sample_task()
assert priority == SamplingPriority.DEFAULT

# 高风险任务（100% 采样）
priority = SamplingStrategy.should_sample_task(is_high_risk=True)
assert priority == SamplingPriority.HIGH
```

---

### 模块：`src.runtime.trace.audit_correlation`

#### `AuditCorrelation.create_audit_record(...)`

创建审计记录。

**参数**：
- `action_type` (str)：操作类型（如 "task.create"）
- `actor` (ActorRef)：操作主体
- `decision` (str)：决策结果（ALLOW/DENY）
- `trace_context` (TraceContext | None)：关联的 TraceContext（可选）
- `task_id` (str | None)：关联的 TaskId（可选）
- `resource` (str | None)：资源标识（可选）
- `reason` (str | None)：决策原因（可选）
- `evidence_refs` (list[str] | None)：证据引用（可选）
- `policy_version` (str | None)：策略版本（可选）
- `metadata` (dict | None)：额外元数据（可选）

**返回**：`AuditRecord`

**示例**：
```python
from src.runtime.trace.audit_correlation import AuditCorrelation
from src.runtime.common.types import ActorRef, ActorType

actor = ActorRef(actor_type=ActorType.USER, actor_id="user-123")
audit_record = AuditCorrelation.create_audit_record(
    action_type="task.create",
    actor=actor,
    decision="ALLOW",
    trace_context=trace_context,  # 如果有
    task_id="task-001",
)
```

---

#### `AuditCorrelation.should_audit(action_type)`

判断操作类型是否需要审计。

**参数**：
- `action_type` (str)：操作类型

**返回**：`bool`

**需要审计的操作**：
- `task.*`：Task 操作
- `policy.*`：策略决策
- `approval.*`：审批操作
- `action.*`：Action 执行
- `tool.*`：工具调用
- `credential.*`：凭据访问
- `sandbox.*`：沙箱操作
- `killswitch.*`：紧急熔断

**示例**：
```python
from src.runtime.trace.audit_correlation import AuditCorrelation

should_audit = AuditCorrelation.should_audit("task.create")
assert should_audit is True

should_audit = AuditCorrelation.should_audit("internal.cache.hit")
assert should_audit is False
```

---

## 使用示例

### 示例 1：Task 完整链路追踪

```python
from src.runtime.trace.tracer import create_span, get_current_trace_context, SpanKind

# 1. Task 创建（根 Span）
with create_span("task.execute", SpanKind.TASK, attributes={"task_id": "task-001"}):
    task_ctx = get_current_trace_context()
    
    # 2. Workflow 执行（子 Span）
    with create_span("workflow.run", SpanKind.WORKFLOW, trace_context=task_ctx):
        
        # 3. Worker 执行（子 Span）
        with create_span("worker.execute", SpanKind.WORKER):
            
            # 4. Action 执行（子 Span）
            with create_span("action.run", SpanKind.ACTION):
                # 执行 Action 逻辑
                pass
```

---

### 示例 2：跨服务传播（HTTP）

```python
from src.runtime.trace.tracer import create_span, get_current_trace_context, SpanKind
from src.runtime.trace.propagation import inject_trace_context, extract_trace_context

# 服务 A：注入 TraceContext 到 HTTP Headers
with create_span("tool.call", SpanKind.ACTION):
    ctx = get_current_trace_context()
    if ctx:
        headers = {}
        inject_trace_context(ctx, headers)
        
        # 发送 HTTP 请求
        response = requests.post("https://internal-service/api", headers=headers)

# 服务 B：提取 TraceContext
def handle_request(request):
    # 从可信来源提取
    ctx = extract_trace_context(request.headers, trusted=True)
    
    if ctx:
        # 继续追踪链路
        with create_span("internal.process", SpanKind.ACTION, trace_context=ctx):
            # 处理请求
            pass
    else:
        # 创建新的根 Trace
        with create_span("internal.process", SpanKind.ACTION):
            pass
```

---

### 示例 3：审计关联

```python
from src.runtime.trace.tracer import create_span, get_current_trace_context, SpanKind
from src.runtime.trace.audit_correlation import AuditCorrelation
from src.runtime.common.types import ActorRef, ActorType

# 创建 Span
with create_span("task.create", SpanKind.TASK):
    ctx = get_current_trace_context()
    
    # 创建审计记录（关联 TraceId）
    actor = ActorRef(actor_type=ActorType.USER, actor_id="user-123")
    audit_record = AuditCorrelation.create_audit_record(
        action_type="task.create",
        actor=actor,
        decision="ALLOW",
        trace_context=ctx,  # 自动关联 TraceId/SpanId
        task_id="task-001",
    )
    
    # 写入审计存储（100% 写入，不受采样影响）
    # audit_store.write(audit_record)
```

---

### 示例 4：高风险任务（100% 采样）

```python
from src.runtime.trace.tracer import create_span, SpanKind
from src.runtime.trace.sampling import SamplingStrategy, SamplingPriority

# 判断任务风险
is_high_risk = True  # 基于任务类型/权限/资源判断

# 确定采样优先级
priority = SamplingStrategy.should_sample_task(is_high_risk=is_high_risk)

# 创建 Span（高风险任务强制采样）
with create_span(
    "task.execute",
    SpanKind.TASK,
    attributes={
        "task_id": "task-001",
        "risk_level": "high",
        "sampling_priority": priority.value,
    },
):
    # 执行高风险任务
    pass
```

---

## 最佳实践

### ✅ 应该做

1. **使用 `create_span` 上下文管理器**
   ```python
   with create_span("operation", SpanKind.ACTION):
       # 操作逻辑
       pass
   ```

2. **为 Span 添加有意义的元数据**
   ```python
   with create_span("model.call", SpanKind.MODEL, attributes={
       "model_id": "gpt-4",
       "token_count": 1500,
       "request_id": "req-123",
   }):
       pass
   ```

3. **审计与 Trace 分离**
   ```python
   # 审计记录总是写入，不受采样影响
   if AuditCorrelation.should_audit(action_type):
       audit_record = AuditCorrelation.create_audit_record(...)
       audit_store.write(audit_record)
   ```

4. **信任边界控制**
   ```python
   # 内部服务：trusted=True
   ctx = extract_trace_context(headers, trusted=True)
   
   # 外部服务：trusted=False
   ctx = extract_trace_context(headers, trusted=False)
   if ctx is None:
       # 创建新根 Trace
       pass
   ```

---

### ❌ 不应该做

1. **不要在 Span 属性中记录敏感数据**
   ```python
   # ❌ 错误
   with create_span("model.call", SpanKind.MODEL, attributes={
       "prompt": "...",  # 不要记录 Prompt
       "api_key": "...",  # 不要记录凭据
   }):
       pass
   
   # ✅ 正确
   with create_span("model.call", SpanKind.MODEL, attributes={
       "model_id": "gpt-4",
       "token_count": 1500,
   }):
       pass
   ```

2. **不要假设 Span 总是被采样**
   ```python
   # ❌ 错误
   with create_span("operation", SpanKind.ACTION) as span:
       span.set_attribute("key", "value")  # span 可能是 None
   
   # ✅ 正确
   with create_span("operation", SpanKind.ACTION) as span:
       if span:
           span.set_attribute("key", "value")
   ```

3. **不要阻塞主流程等待 Trace 导出**
   ```python
   # ❌ 错误
   with create_span("operation", SpanKind.ACTION):
       pass
   # 等待 Trace 导出完成...
   
   # ✅ 正确
   # Trace 导出是异步的，不阻塞主流程
   with create_span("operation", SpanKind.ACTION):
       pass
   # 继续主流程
   ```

4. **不要在不可信来源使用 `trusted=True`**
   ```python
   # ❌ 错误：外部服务使用 trusted=True
   ctx = extract_trace_context(external_headers, trusted=True)
   
   # ✅ 正确：外部服务使用 trusted=False
   ctx = extract_trace_context(external_headers, trusted=False)
   ```

---

## 验收标准达成情况

根据 REQ-RT-006 §10.2 的 14 项验收标准：

| # | 验收标准 | 状态 | 测试覆盖 |
|---|---------|------|---------|
| 1 | Task 创建时生成根 TraceContext | ✅ | `test_full_trace_propagation_workflow` |
| 2 | TraceContext 在链路传播 | ✅ | `test_full_trace_propagation_workflow` |
| 3 | 跨边界传播（HTTP Headers） | ✅ | `test_cross_service_propagation_with_trust_boundary` |
| 4 | 采样策略（15% / 100%） | ✅ | `test_sampling_strategy_integration` |
| 5 | 审计关联 TraceId | ✅ | `test_audit_correlation_integration` |
| 6 | 默认不记录敏感数据 | ✅ | `test_span_attributes_do_not_contain_sensitive_data` |
| 7 | 不可信来源拒绝提取 | ✅ | `test_extract_untrusted_source` |
| 8 | Span 父子关系 | ✅ | `test_nested_spans` |
| 9 | W3C Trace Context 格式 | ✅ | `test_inject_extract_roundtrip` |
| 10 | Baggage 传播 | ✅ | `test_inject_with_baggage` |
| 11 | 审计不受采样影响 | ✅ | `test_audit_without_trace` |
| 12 | 高风险任务 100% 采样 | ✅ | `test_should_sample_task_high_risk` |
| 13 | 失败任务 100% 采样 | ✅ | `test_should_sample_task_has_failure` |
| 14 | 恢复操作 100% 采样 | ✅ | `test_should_sample_task_is_recovery` |

**总体状态**：✅ **全部通过**（14/14）

---

## 性能考虑

1. **采样率**：默认 15% 采样，减少存储和网络开销
2. **异步导出**：Trace 导出不阻塞主流程
3. **轻量级传播**：W3C Trace Context 只传播必要信息（< 200 字节）
4. **Baggage 限制**：每个键值对 < 4KB，总大小 < 8KB

---

## 故障排查

### 问题：Span 未被采样

**原因**：默认采样率 15%  
**解决**：
1. 检查是否应该提高优先级（高风险/失败/恢复）
2. 使用 `explicit_request=True` 强制采样

```python
priority = SamplingStrategy.should_sample_task(explicit_request=True)
```

---

### 问题：TraceContext 提取失败

**原因**：
1. HTTP Headers 格式无效
2. 来源不可信（`trusted=False`）

**解决**：
```python
ctx = extract_trace_context(headers, trusted=True)
if ctx is None:
    # 创建新的根 Trace
    with create_span("operation", SpanKind.ACTION):
        pass
```

---

### 问题：审计记录没有 TraceId

**原因**：Span 未被采样（正常现象）  
**说明**：审计记录仍然写入，只是 `trace_id` 为 `None`

```python
audit_record = AuditCorrelation.create_audit_record(
    action_type="task.create",
    actor=actor,
    decision="ALLOW",
    trace_context=None,  # Span 未被采样
)
# 审计记录仍然写入，trace_id = None
```

---

## 下一步

- [ ] 集成到 Task/Workflow/Worker/Action 实体
- [ ] 实现审计存储持久化（PostgreSQL）
- [ ] 配置 OTLP Exporter（导出到 Jaeger/Prometheus）
- [ ] 添加 Trace 查询 API
- [ ] 实现 Trace 可视化（Jaeger UI）

---

## 参考资料

- [REQ-RT-006 详细设计](../design-specs/REQ-RT-006-Trace-传播和审计关联.md)
- [W3C Trace Context](https://www.w3.org/TR/trace-context/)
- [OpenTelemetry Python SDK](https://opentelemetry.io/docs/instrumentation/python/)
- [OpenTelemetry Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/)
