# G05 遥测采集 — 下游消费接口参考

> 本文档从 `REQ-OBS-001` v0.1-designed 提炼，供 OBS-002~007、HAR-001、Worker Runtime、CTX、MEM、REL、SEC 等下游专项在设计/实现阶段直接引用。
> 文档定位为"消费侧接口表"，不替代源设计；若冲突以源设计为准。
>
> 来源：[REQ-OBS-001 OpenTelemetry 语义约定](REQ-OBS-001-opentelemetry-semantic-conventions.md)（v0.1-designed）

---

## 一、分层 Span 结构速查（OBS-001 §4，7 层分层结构）

```
Task / agent invocation (根 Span)
└── Workflow execution
    ├── Worker execution
    │   ├── Planning / reasoning operation（仅记录元数据）
    │   ├── Policy decision / human approval wait
    │   ├── Action
    │   │   ├── Tool execution
    │   │   ├── Model request（可含多次 attempt 子 Span）
    │   │   └── Sandbox operation
    │   └── Artifact / Evidence production
    └── Cross-service client operation
```

### Span 命名规范（下游必须遵守）

| 层级 | Span 名称格式 | 示例 |
|---|---|---|
| **Task** | `invoke_agent {task_id}` | `invoke_agent task_123456` |
| **Workflow** | `invoke_workflow {workflow_name}` | `invoke_workflow bug_fix_pipeline` |
| **Worker** | `{worker_type}.execute` | `planner.execute`, `coder.execute` |
| **Action** | `{action_type} {resource}` | `read_file main.py`, `execute_tool pytest` |
| **Tool** | `execute_tool {tool_name}` | `execute_tool git_commit` |
| **Model** | `chat {model_name}` | `chat gpt-4o` |
| **Sandbox** | `sandbox.{operation}` | `sandbox.create`, `sandbox.destroy` |

**命名原则**：
- 遵循 `verb_object` 或 `object.verb` 模式
- 工具执行必须包含 tool_name
- 模型调用必须包含 model_name
- Span 名称应简洁且具有区分度

---

## 二、标准属性集速查（OBS-001 §5，6 类必需属性）

### 2.1 所有 Span 必需属性（6 个）

| 属性名 | 类型 | 示例 | 说明 |
|---|---|---|---|
| `trace_id` | string | `4bf92f3577b34da6a3ce929d0e0e4736` | W3C Trace Context 格式（32 字符十六进制） |
| `span_id` | string | `00f067aa0ba902b7` | 16 字符十六进制 |
| `parent_span_id` | string | `00f067aa0ba902b6` | 父 Span ID，根 Span 为空 |
| `span.kind` | enum | `INTERNAL` | INTERNAL/CLIENT/SERVER/PRODUCER/CONSUMER |
| `service.name` | string | `ai-agent-platform` | 服务名称 |
| `gen_ai.operation.name` | string | `invoke_agent` | GenAI 操作类型 |

### 2.2 各层级特有必需属性汇总

| 层级 | 必需属性（✅） | 可选属性（❌） |
|---|---|---|
| **Task** | task.id, organization.id, project.id, repository.id, task.source_type, task.risk_level, task.status, user.id | user.role |
| **Workflow** | gen_ai.workflow.name, workflow.id, workflow.status | workflow.version, workflow.worker_count |
| **Worker** | gen_ai.agent.name, worker.type, worker.status | gen_ai.agent.id, gen_ai.agent.version |
| **Action** | action.id, action.type, action.risk_level, action.requires_approval, action.status, idempotency_key | — |
| **Tool** | gen_ai.tool.name, tool.status, tool.duration_ms | gen_ai.tool.version, tool.arguments (仅 FULL 模式), tool.result (仅 FULL 模式) |
| **Model** | gen_ai.request.model, gen_ai.provider.name, gen_ai.usage.input_tokens, gen_ai.usage.output_tokens, gen_ai.usage.total_tokens, gen_ai.response.finish_reason | gen_ai.usage.reasoning_tokens, gen_ai.prompt (仅 FULL 模式), gen_ai.completion (仅 FULL 模式) |
| **Sandbox** | sandbox.id, sandbox.type, sandbox.isolation_level, sandbox.operation, sandbox.status | — |

---

## 三、采样策略速查（OBS-001 §6，7 种优先级场景）

### 3.1 采样决策算法（伪代码）

```
base_rate = org_config.default_sampling_rate  // 默认 15%
priority = NORMAL

// 高风险任务提高采样
if risk_level in [HIGH, CRITICAL]:
    priority = HIGH
    rate = 1.0

// 安全相关操作必采样
if operation_type in [POLICY_DENY, APPROVAL_REQUEST, CREDENTIAL_ACCESS]:
    priority = ALWAYS
    rate = 1.0

// 失败操作提高采样
if operation_type == FAILURE:
    priority = HIGH
    rate = 1.0

// 诊断请求覆盖
if has_diagnostic_request():
    rate = 1.0

return {rate, priority, content_allowed}
```

### 3.2 采样优先级映射表

| 场景 | 采样率 | 优先级 | 说明 |
|---|---|---|---|
| **正常任务** | 15% | NORMAL | 默认采样率 |
| **高风险任务** | 100% | HIGH | risk_level=HIGH/CRITICAL |
| **安全拒绝** | 100% | ALWAYS | Policy Gateway 拒绝操作 |
| **审批等待** | 100% | ALWAYS | 人工审批流程 |
| **任务失败** | 100% | HIGH | 任务最终状态=FAILED |
| **诊断请求** | 100% | HIGH | 用户发起 debug=true |
| **Kill Switch** | 100% | ALWAYS | 紧急暂停操作 |

---

## 四、内容捕获策略速查（OBS-001 §7，三级模式）

### 4.1 三级内容捕获模式

| 模式 | 捕获内容 | 适用场景 | MVP 默认 |
|---|---|---|---|
| **DISABLED** | 仅元数据（模型名、Token 数、耗时） | 生产环境 | ✅ 默认 |
| **FEEDBACK_ONLY** | 元数据 + 评分结果 + 失败归因 | 质量监控 | ❌ |
| **FULL** | 元数据 + Prompt + Tool Args + Tool Results | 调试与开发 | ❌ |

### 4.2 默认不捕获内容（7 项红线）

```
❌ 隐藏思维链（模型内部推理过程）
❌ 完整 Prompt 和 System Prompt
❌ 模型原始请求/响应 JSON
❌ 工具完整参数和结果
❌ 完整代码文件内容
❌ 凭据值和环境变量
❌ 用户个人敏感信息
```

### 4.3 可选捕获内容（FULL 模式，必须先脱敏）

| 字段 | 条件 | 脱敏规则 |
|---|---|---|
| `gen_ai.prompt` | content_capture=FULL | 必须先脱敏 |
| `gen_ai.completion` | content_capture=FULL | 必须先脱敏 |
| `tool.arguments` | content_capture=FULL | 必须先脱敏 |
| `tool.result` | content_capture=FULL | 必须先脱敏 |
| `code.snippet` | content_capture=FULL | 仅捕获相关行 |

### 4.4 内容保护五原则

```
1. 默认最小化：MVP 默认 DISABLED 模式
2. 显式启用：需组织级配置或任务级显式标记
3. 先脱敏后捕获：脱敏失败则跳过捕获
4. 审计追踪：记录内容捕获启用/禁用操作
5. 时限控制：FULL 模式有效期不超过 7 天
```

---

## 五、跨服务传播边界速查（OBS-001 §8）

### 5.1 受信任边界定义

| 服务类型 | 传播策略 | 说明 |
|---|---|---|
| **内部受信任服务** | 完整传播 | 控制平面、Worker Runtime、工具/模型网关、沙箱管理、遥测/审计服务 |
| **已登记的 MCP 服务** | 受控传播 | 仅在策略批准时传播 traceparent + tracestate |
| **模型供应商** | 不传播 | 创建 client span + request_id |
| **GitHub API** | 不传播 | 创建 client span + request_id |
| **未登记的第三方** | 拒绝传播 | 创建新根 trace |

### 5.2 Baggage 白名单（3 项）

```yaml
baggage_allowlist:
  - organization_id  # 低基数，非敏感
  - project_id       # 低基数，非敏感
  - environment      # 低基数（dev/staging/prod）
```

### 5.3 Baggage 禁止字段（4 类）

```
❌ 凭据（credentials、api_key、token）
❌ 个人信息（user_email、user_name、user_ip）
❌ 高基数值（file_path、code_content、task_description）
❌ 任意用户文本（prompt、tool_arguments）
```

---

## 六、Span 父子关系速查（OBS-001 §9）

### 6.1 严格父子关系（包含）

| 子 Span | 父 Span | 说明 |
|---|---|---|
| Workflow | Task | Workflow 由 Task 触发 |
| Worker | Workflow | Worker 由 Workflow 调度 |
| Action | Worker | Action 由 Worker 执行 |
| Policy Decision | Action | 决策发生在 Action 执行前 |
| Tool | Action | 工具由 Action 调用 |
| Model | Action | 模型由 Action 调用 |
| Sandbox | Action | 沙箱由 Action 使用 |

### 6.2 Span Link（因果关联）

| 场景 | Link 类型 | 说明 |
|---|---|---|
| **重试** | FOLLOWS_FROM | 新 attempt 链接原始操作 |
| **恢复** | FOLLOWS_FROM | 恢复后的 Workflow 链接原 Checkpoint |
| **并行分支** | CHILD_OF | 并行 Worker 链接同一 Workflow |
| **子 Agent** | FOLLOWS_FROM | 子 Agent 链接父 Agent Task |
| **跨服务调用** | FOLLOWS_FROM | 外部调用链接 client span |

### 6.3 孤儿 Span 处理

```
定义：无法找到父 Span 的 Span（parent_span_id 不存在）

处理策略：
1. 保留 Span 数据，不丢弃
2. 记录 orphan=true 标记
3. 通过 correlation_id 或 task_id 关联
4. 计量孤儿 Span 比例，目标 < 1%
```

---

## 七、异常与失败处理速查（OBS-001 §10，6 种异常场景）

| 异常场景 | 症状 | 处理策略 | 不阻塞主路径 |
|---|---|---|---|
| **Collector 不可用** | OTLP 导出返回 503 或连接超时 | 本地缓冲队列保存（最大 10000 个）+ 指数退避重试 + 超限后丢弃并记录 `export_drop_count` | ✅ |
| **采样配置无效** | 采样率超出 [0, 1] 范围 | 回退到默认采样率（15%）+ 记录配置错误事件 + 通知管理员 | ✅ |
| **属性超限** | Span 属性值长度 > 1KB | 截断到 1KB + 添加 `truncated=true` + 记录原始长度到 `original_length` | ✅ |
| **父 Span 缺失** | parent_span_id 指向不存在的 Span | 创建 orphan span 标记 + 通过 correlation_id 关联 + 计量孤儿比例 | ✅ |
| **内容捕获失败** | 脱敏器执行失败或内容格式无效 | 跳过内容捕获 + 记录 `content_capture_error=true` + 保留元数据 | ✅ |
| **跨服务传播被拒** | 第三方服务拒绝接受 traceparent | 创建 client span 记录调用 + 通过 request_id 关联 + 记录传播拒绝事件 | ✅ |

**硬性约束**：所有异常处理均不得阻塞 Agent 主执行路径。

---

## 八、性能与成本约束速查（OBS-001 §11）

### 8.1 性能目标（4 项）

| 指标 | 目标 | 测量方法 |
|---|---|---|
| Span 创建开销 | < 1ms (p99) | 微基准测试 |
| 追踪 SDK CPU 开销 | < 5% (p95) | CPU profiling |
| 异步导出延迟 | < 100ms (p95) | OTLP 端到端测量 |
| 内存占用 | < 50MB | 常驻内存监控 |

### 8.2 成本控制限制（4 项）

| 限制项 | 阈值 | 超限处理 |
|---|---|---|
| **Span 数量限制** | 单个 Trace 最多 100 个 Span | 拒绝创建新 Span，记录 `span_limit_exceeded` |
| **属性数量限制** | 每个 Span 最多 50 个属性 | 拒绝添加属性，记录 `attribute_limit_exceeded` |
| **属性值长度限制** | 单个属性值最多 1KB | 截断，添加 `truncated=true` |
| **Span 大小限制** | 单个 Span 序列化后最多 100KB | 拒绝导出，记录 `span_too_large` |

### 8.3 成本预估公式

```
日均 Span 数 = 日均任务数 × 平均 Span 数/任务 × 采样率
日均数据量 = 日均 Span 数 × 单个 Span 大小
月均数据量 = 日均数据量 × 30

示例（10K 任务/日，20 Span/任务，15% 采样率，2KB/Span）：
= 10,000 × 20 × 15% × 2KB × 30 = 1.8GB/月
```

---

## 九、可观测性与评估指标速查（OBS-001 §12，3 类 11 项指标）

### 9.1 追踪质量指标（5 项）

| 指标名 | 定义 | 目标 | 告警条件 |
|---|---|---|---|
| `obs.trace.root_span.rate` | 每分钟创建的根 Span 数量 | 基准指标 | N/A |
| `obs.trace.complete.ratio` | 完整 Trace 占比 | ≥ 95% | < 90% |
| `obs.trace.parent_linked.ratio` | 父 Span 关联成功率 | ≥ 99% | < 95% |
| `obs.span.orphan.count` | 孤儿 Span 数量 | < 1% | > 5% |
| `obs.span.count_per_trace` | 每 Trace 平均 Span 数 | < 100 | > 150 |

### 9.2 遥测导出指标（4 项）

| 指标名 | 定义 | 目标 | 告警条件 |
|---|---|---|---|
| `obs.otel.export.success.rate` | OTLP 导出成功率 | ≥ 99.9% | < 99% |
| `obs.otel.export.latency.p95` | 导出延迟 p95 | < 100ms | > 500ms |
| `obs.otel.export.backlog.size` | 待导出队列大小 | < 1000 | > 5000 |
| `obs.otel.export.drop.count` | 丢弃的 Span 数量 | < 0.1% | > 1% |

### 9.3 审计覆盖指标（3 项）

| 指标名 | 定义 | 目标 | 告警条件 |
|---|---|---|---|
| `obs.audit.critical.event.rate` | 关键操作审计覆盖率 | 100% | < 100% |
| `obs.audit.completeness.ratio` | 审计记录完整性 | ≥ 99.99% | < 99.9% |
| `obs.audit.privacy.rejected.count` | 敏感内容拦截次数 | 监控指标 | N/A |

---

## 十、对下游各专项的具体接口契约

| 下游专项 | 必须复用的 G05 坐标 | 禁止事项 |
|---|---|---|
| **OBS-002** Trace/Event Schema | 7 层 Span 结构、标准属性集、Span 命名规范 | 不得发明新的 Span 层级或属性前缀 |
| **OBS-003** 指标字典 | 11 项质量/导出/审计指标、采样率、孤儿 Span 比例 | 指标不得含未脱敏敏感内容 |
| **OBS-004** 脱敏 | 内容捕获三级模式、7 项红线内容、Baggage 白名单 | 脱敏失败时必须跳过捕获，不得降级保存 |
| **OBS-005** 告警 | 追踪质量指标告警条件、导出失败告警 | 告警不得因采样率低而漏报关键失败 |
| **OBS-006** 审计查询 | Trace 结构、parent_span_id 关联、orphan=true 标记 | 查询 API 不得绕过租户隔离 |
| **OBS-007** 审计留存 | 采样优先级（ALWAYS 必存）、内容捕获时限（FULL ≤ 7 天） | 不得因存储成本删除 ALWAYS 优先级 Trace |
| **HAR-001** Harness | Worker/Action/Tool/Model/Sandbox 层 Span 创建时机 | Harness 不得在未创建父 Span 前创建子 Span |
| **Worker Runtime** | Task/Workflow/Worker Span 生命周期、状态属性（status） | Worker 崩溃时必须设置 Span error 状态 |
| **CTX-004** 检索 | Action Span 含 `context.retrieval_latency` 等扩展属性 | 检索 Span 不得含原始代码内容 |
| **MEM-003** 记忆检索 | Action Span 含 `memory.retrieval_count` 等扩展属性 | 记忆检索 Span 不得含未脱敏记忆内容 |
| **REL-002** 重试 | 重试 attempt 创建独立 span + FOLLOWS_FROM link | 重试 Span 不得覆盖原始失败 Span |
| **REL-005** 恢复 | 恢复后 Workflow 链接原 Checkpoint（FOLLOWS_FROM） | 恢复 Span 必须保留原 trace_id |
| **SEC-003** 策略网关 | Policy Decision Span 作为 Action 子 Span | Policy 决策失败必须 100% 采样 |
| **SEC-009** KillSwitch | Kill Switch 操作 100% 采样 + ALWAYS 优先级 | Kill Switch Span 不得被采样率过滤 |

---

## 十一、验收标准摘要（OBS-001 §13，22 项）

| 类别 | 验收项 | 验收方法 |
|---|---|---|
| **功能性验收（8 项）** | 1. Task 创建生成有效 TraceId | 单元测试：UUID v4 格式 |
| | 2. Workflow Span 作为并行 Worker Span 父节点 | 集成测试：parent_span_id 关联 |
| | 3. Worker 崩溃后 Span 设置 error 状态 | 故障注入测试 |
| | 4. Action Span 包含必需属性 | Schema 验证 |
| | 5. LLM Span 包含必需属性 | Schema 验证 |
| | 6. Tool Span 包含必需属性 | Schema 验证 |
| | 7. 重试 attempt 创建独立 span | 集成测试：span.links 关联 |
| | 8. 跨服务调用注入/提取 traceparent | 集成测试：W3C Trace Context |
| **采样验收（4 项）** | 9. 默认采样率为 15% | 配置测试 |
| | 10. 高风险任务采样率自动提升到 100% | 单元测试：risk_level=HIGH |
| | 11. Policy 拒绝、审批请求强制采样 | 集成测试：priority=ALWAYS |
| | 12. 诊断请求覆盖采样率 | 集成测试：debug=true |
| **内容保护验收（4 项）** | 13. 默认不记录 Prompt、Tool Arguments | 集成测试：DISABLED 模式 |
| | 14. 凭据值不会出现在任何 Span 属性 | 安全测试 |
| | 15. 脱敏规则按组织配置生效 | 集成测试 |
| | 16. Baggage 仅允许白名单字段 | 单元测试 |
| **传播验收（3 项）** | 17. W3C Trace Context 在受信任边界内正确传播 | 集成测试 |
| | 18. 第三方服务不支持时创建 client span | 集成测试 |
| | 19. 来自不可信源的 traceparent 被拒绝 | 安全测试 |
| **性能验收（3 项）** | 20. Span 创建开销 < 1ms (p99) | 性能测试 |
| | 21. OTLP 导出成功率 ≥ 99.9% | 稳定性测试 |
| | 22. 导出失败不阻塞 Agent 执行 | 故障注入测试 |

---

## 十二、变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 本次生成 | 首次从 OBS-001 提炼下游消费接口参考，不改变任何源设计内容 |
