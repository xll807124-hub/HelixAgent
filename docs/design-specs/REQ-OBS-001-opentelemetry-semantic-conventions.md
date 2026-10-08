# REQ-OBS-001 OpenTelemetry 语义约定详细设计

> 所属基线：`Observability Baseline v0.1`  
> 需求编号：`REQ-OBS-001`  
> 优先级：P0  
> 设计版本：`v0.1-designed`  
> 设计状态：详细设计已完成，待跨模块冻结  
> 前置依赖：`REQ-RT-001`、`REQ-RT-006`  
> 关键决策：采用 OpenTelemetry GenAI 语义约定；默认采样率 15%；内容捕获默认关闭；受信任边界内跨服务传播

---

## 1. 需求定义

### 1.1 目标

为 AI Agent 平台建立符合 OpenTelemetry GenAI 语义约定的标准化可观测性规范，包括 Span 命名规范、属性定义、父子关系、采样策略和数据保护原则。确保追踪数据在跨模块、跨服务的场景下保持一致性和可聚合性。

### 1.2 用户价值

- **开发人员**：通过完整 Span 树快速定位失败与延迟来源，减少调试时间
- **安全审计员**：追溯操作历史，生成合规审计报告
- **平台运营**：监控服务健康，分析成本消耗，优化资源配置
- **AI 研究员**：评估 Agent 行为，优化模型选择和 Prompt 策略

### 1.3 范围

**包含**：
- Task/Workflow/Worker/Action/Model/Tool/Sandbox 的分层 Span 结构定义
- OpenTelemetry GenAI 语义约定的属性映射
- 采样决策算法和优先级映射
- 内容捕获策略和数据保护规则
- 跨服务 Trace Context 传播边界

**不包含**：
- 完整的 Trace/Event/Evidence Schema（由 `REQ-OBS-002` 定义）
- 指标字典和聚合规则（由 `REQ-OBS-003` 定义）
- 脱敏实现细节（由 `REQ-OBS-004` 定义）
- 审计查询 API（由 `REQ-OBS-006` 定义）
- 审计留存和完整性机制（由 `REQ-OBS-007` 定义）

---

## 2. 共享契约与术语

本设计复用 `REQ-RT-001` 定义的核心实体（TaskId、WorkflowId、WorkerId、ActionId）和 `REQ-RT-006` 定义的 Trace 传播基础（TraceId、SpanId、TraceContext、采样率、留存目标）。

### 2.1 核心术语

| 术语 | 定义 |
|------|------|
| **Span** | 具有开始、结束、父子关系的操作观测单元 |
| **Trace** | 同一因果执行链的 Span 集合 |
| **Semantic Convention** | OpenTelemetry 定义的标准化命名和属性规范 |
| **GenAI Span** | 特定于生成式 AI 场景的 Span 类型（Agent、Model、Tool） |
| **Sampling** | 选择性记录 Trace 以控制遥测成本 |
| **Content Capture** | 记录 Prompt、工具参数等敏感内容 |
| **Baggage** | 跨服务传播的键值对元数据 |

---

## 3. 行业调研与可借鉴原则

### 3.1 OpenTelemetry GenAI SIG

**来源**：[OpenTelemetry AI Agent Observability](https://opentelemetry.io/blog/2025/ai-agent-observability/)  
**访问日期**：2026-09-30

**关键发现**：
- GenAI SIG 定义了六大层次：LLM、Agent、Tool、Workflow、Memory、Content
- 操作命名遵循 `verb_object` 模式：invoke_agent、execute_tool、invoke_workflow
- gen_ai.provider.name 作为多供应商兼容的鉴别器
- 属性当前处于 `Development` 状态，需关注稳定性演进

**借鉴点**：采用标准化语义约定而非私有属性；操作命名遵循统一模式。

**证据等级**：A（官方文档）

---

### 3.2 Cursor Enterprise

**来源**：[Cursor OpenTelemetry Export](https://cursor.com/docs/enterprise/opentelemetry-export)  
**访问日期**：2026-09-30

**关键发现**：
- 服务端集中导出，管理员在 Team Settings 配置 OTLP endpoint
- 分层内容策略：model_usage、tool_calls、conversation_content（可选）
- conversation_content 默认关闭，需显式 opt-in
- OTLP 路径约定：自动追加 `/v1/metrics` 和 `/v1/logs`

**借鉴点**：分层遥测导出策略；服务端集中配置模式；对话内容隐私保护默认关闭。

**证据等级**：A（官方文档）

---

### 3.3 DeepSeek Harness

**来源**：[dsh-plugin](https://github.com/loongsuite/dsh-plugin)  
**访问日期**：2026-09-30

**关键发现**：
- Span 树结构：ENTRY → AGENT → STEP → LLM/TOOL
- 三级内容捕获策略：FULL、FEEDBACK_ONLY、DISABLED
- 每个真实的 LLM attempt 产生独立 span，重试可见
- 子 Agent 创建独立 trace，携带 parent-session 属性

**借鉴点**：三级内容捕获策略；重试作为独立 span；子 Agent 独立 trace + 属性关联。

**证据等级**：A（开源实现）

---

### 3.4 LangSmith

**来源**：[LangSmith Trace LangGraph](https://docs.langchain.com/langsmith/trace-with-langgraph)  
**访问日期**：2026-09-30

**关键发现**：
- 环境变量启用：LANGSMITH_TRACING=true
- @traceable 装饰器包装自定义函数
- 支持自定义 anonymizer 脱敏
- Messages View 与 Details View 分离

**借鉴点**：追踪配置与业务逻辑分离；脱敏匿名化机制；框架无关设计。

**证据等级**：A（官方文档）

---

### 3.5 Microsoft Copilot / Azure Agent

**来源**：[Microsoft Copilot Studio Telemetry](https://learn.microsoft.com/en-us/microsoft-copilot-studio/telemetry-overview)  
**访问日期**：2026-09-30

**关键发现**：
- 两层遥测架构：Agent-level（事件驱动）vs Environment-level（Trace/Span）
- Environment-level 与 OTel 语义对齐，写入 dependencies 表
- 托管配置：企业通过 MDM/策略集中下发 OTEL 配置
- Agent-level 与 Environment-level 不可混用同一 Application Insights 实例

**借鉴点**：集中式托管配置；分层遥测架构；Agent 视图即开即用。

**证据等级**：A（官方文档）

---

## 4. 分层 Span 结构设计

### 4.1 Span 层级定义

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

### 4.2 Span 命名规范

| 层级 | Span 名称格式 | 示例 |
|------|--------------|------|
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

## 5. 标准属性集定义

### 5.1 必需属性（所有 Span）

| 属性名 | 类型 | 示例 | 说明 |
|--------|------|------|------|
| `trace_id` | string | `4bf92f3577b34da6a3ce929d0e0e4736` | W3C Trace Context 格式 |
| `span_id` | string | `00f067aa0ba902b7` | 16 字符十六进制 |
| `parent_span_id` | string | `00f067aa0ba902b6` | 父 Span ID，根 Span 为空 |
| `span.kind` | enum | `INTERNAL` | INTERNAL/CLIENT/SERVER/PRODUCER/CONSUMER |
| `service.name` | string | `ai-agent-platform` | 服务名称 |
| `gen_ai.operation.name` | string | `invoke_agent` | GenAI 操作类型 |

### 5.2 Task Span 属性

| 属性名 | 类型 | 必需 | 示例 |
|--------|------|------|------|
| `task.id` | string | ✅ | `task_123456` |
| `organization.id` | string | ✅ | `org_789` |
| `project.id` | string | ✅ | `proj_456` |
| `repository.id` | string | ✅ | `repo_123` |
| `task.source_type` | enum | ✅ | `ISSUE` / `PR_REVIEW` / `NATURAL_LANGUAGE` |
| `task.risk_level` | enum | ✅ | `LOW` / `MEDIUM` / `HIGH` / `CRITICAL` |
| `task.status` | enum | ✅ | `RUNNING` / `COMPLETED` / `FAILED` / `CANCELLED` |
| `user.id` | string | ✅ | `user_001` |
| `user.role` | string | ❌ | `developer` |

### 5.3 Workflow Span 属性

| 属性名 | 类型 | 必需 | 示例 |
|--------|------|------|------|
| `gen_ai.workflow.name` | string | ✅ | `bug_fix_pipeline` |
| `workflow.id` | string | ✅ | `wf_789` |
| `workflow.version` | string | ❌ | `v1.2.0` |
| `workflow.worker_count` | int | ❌ | `3` |
| `workflow.status` | enum | ✅ | `RUNNING` / `COMPLETED` / `FAILED` |

### 5.4 Worker Span 属性

| 属性名 | 类型 | 必需 | 示例 |
|--------|------|------|------|
| `gen_ai.agent.name` | string | ✅ | `planner` / `coder` / `tester` |
| `gen_ai.agent.id` | string | ❌ | `worker_instance_123` |
| `gen_ai.agent.version` | string | ❌ | `v2.1.0` |
| `worker.type` | enum | ✅ | `PLANNER` / `CODER` / `TESTER` / `REVIEWER` |
| `worker.status` | enum | ✅ | `RUNNING` / `COMPLETED` / `FAILED` |

### 5.5 Action Span 属性

| 属性名 | 类型 | 必需 | 示例 |
|--------|------|------|------|
| `action.id` | string | ✅ | `action_456` |
| `action.type` | enum | ✅ | `READ` / `WRITE` / `EXECUTE` / `DELEGATE` |
| `action.risk_level` | enum | ✅ | `LOW` / `MEDIUM` / `HIGH` |
| `action.requires_approval` | boolean | ✅ | `true` / `false` |
| `action.status` | enum | ✅ | `AUTHORIZED` / `REJECTED` / `SUCCEEDED` / `FAILED` |
| `idempotency_key` | string | ✅ | `idem_789` |

### 5.6 Tool Span 属性

| 属性名 | 类型 | 必需 | 示例 |
|--------|------|------|------|
| `gen_ai.tool.name` | string | ✅ | `git_commit` / `pytest` |
| `gen_ai.tool.version` | string | ❌ | `v1.0.0` |
| `tool.status` | enum | ✅ | `SUCCESS` / `FAILURE` / `TIMEOUT` |
| `tool.duration_ms` | int | ✅ | `1250` |
| `tool.arguments` | string | ❌ | `{"message": "Fix bug"}` (仅 FULL 模式) |
| `tool.result` | string | ❌ | `{"stdout": "..."}` (仅 FULL 模式) |

### 5.7 Model Span 属性

| 属性名 | 类型 | 必需 | 示例 |
|--------|------|------|------|
| `gen_ai.request.model` | string | ✅ | `gpt-4o` / `claude-opus-4` |
| `gen_ai.provider.name` | string | ✅ | `openai` / `anthropic` |
| `gen_ai.usage.input_tokens` | int | ✅ | `1024` |
| `gen_ai.usage.output_tokens` | int | ✅ | `512` |
| `gen_ai.usage.total_tokens` | int | ✅ | `1536` |
| `gen_ai.usage.reasoning_tokens` | int | ❌ | `256` |
| `gen_ai.response.finish_reason` | enum | ✅ | `stop` / `length` / `tool_calls` |
| `gen_ai.prompt` | string | ❌ | `{"role": "user", "content": "..."}` (仅 FULL 模式) |
| `gen_ai.completion` | string | ❌ | `{"role": "assistant", "content": "..."}` (仅 FULL 模式) |

### 5.8 Sandbox Span 属性

| 属性名 | 类型 | 必需 | 示例 |
|--------|------|------|------|
| `sandbox.id` | string | ✅ | `sb_123` |
| `sandbox.type` | enum | ✅ | `DOCKER` / `GVISOR` / `KATA` |
| `sandbox.isolation_level` | enum | ✅ | `LEVEL_1` / `LEVEL_2` / `LEVEL_3` |
| `sandbox.operation` | enum | ✅ | `CREATE` / `EXECUTE` / `DESTROY` |
| `sandbox.status` | enum | ✅ | `SUCCESS` / `FAILURE` |

---

## 6. 采样策略设计

### 6.1 采样决策算法

```
输入：task_context, org_config, risk_level, operation_type
输出：sampling_decision {rate, priority, content_allowed}

1. base_rate = org_config.default_sampling_rate  // 默认 15%
2. priority = NORMAL
3. 
4. // 高风险任务提高采样
5. if risk_level in [HIGH, CRITICAL]:
6.     priority = HIGH
7.     rate = 1.0
8. 
9. // 安全相关操作必采样
10. if operation_type in [POLICY_DENY, APPROVAL_REQUEST, CREDENTIAL_ACCESS]:
11.     priority = ALWAYS
12.     rate = 1.0
13. 
14. // 失败操作提高采样
15. if operation_type == FAILURE:
16.     priority = HIGH
17.     rate = 1.0
18. 
19. // 诊断请求覆盖
20. if has_diagnostic_request():
21.     rate = 1.0
22. 
23. // 内容捕获决策
24. content_allowed = org_config.content_capture_enabled AND 
25.                   operation_type not in [CREDENTIAL_ACCESS, SENSITIVE_DATA]
26. 
27. return {rate, priority, content_allowed}
```

### 6.2 采样优先级映射

| 场景 | 采样率 | 优先级 | 说明 |
|------|--------|--------|------|
| **正常任务** | 15% | NORMAL | 默认采样率 |
| **高风险任务** | 100% | HIGH | risk_level=HIGH/CRITICAL |
| **安全拒绝** | 100% | ALWAYS | Policy Gateway 拒绝操作 |
| **审批等待** | 100% | ALWAYS | 人工审批流程 |
| **任务失败** | 100% | HIGH | 任务最终状态=FAILED |
| **诊断请求** | 100% | HIGH | 用户发起 debug=true |
| **Kill Switch** | 100% | ALWAYS | 紧急暂停操作 |

### 6.3 采样配置示例

```yaml
sampling:
  default_rate: 0.15  # 15%
  
  priority_rules:
    - condition: risk_level == HIGH
      rate: 1.0
      priority: HIGH
    
    - condition: operation_type == POLICY_DENY
      rate: 1.0
      priority: ALWAYS
    
    - condition: task_status == FAILED
      rate: 1.0
      priority: HIGH
  
  content_capture:
    enabled: false  # 默认关闭
    allow_list:
      - DIAGNOSTIC_SESSION
    deny_list:
      - CREDENTIAL_ACCESS
      - SENSITIVE_DATA
```

---

## 7. 内容捕获策略

### 7.1 三级内容捕获模式

| 模式 | 说明 | 捕获内容 | 适用场景 |
|------|------|----------|----------|
| **DISABLED** | 完全关闭 | 仅元数据（模型名、Token 数、耗时） | 生产环境默认 |
| **FEEDBACK_ONLY** | 仅评估反馈 | 元数据 + 评分结果 + 失败归因 | 质量监控 |
| **FULL** | 完整捕获 | 元数据 + Prompt + Tool Args + Tool Results | 调试与开发 |

### 7.2 默认不捕获内容

- ❌ 隐藏思维链（模型内部推理过程）
- ❌ 完整 Prompt 和 System Prompt
- ❌ 模型原始请求/响应 JSON
- ❌ 工具完整参数和结果
- ❌ 完整代码文件内容
- ❌ 凭据值和环境变量
- ❌ 用户个人敏感信息

### 7.3 可选捕获内容（FULL 模式）

| 字段 | 条件 | 脱敏规则 |
|------|------|----------|
| `gen_ai.prompt` | content_capture=FULL | 必须先脱敏 |
| `gen_ai.completion` | content_capture=FULL | 必须先脱敏 |
| `tool.arguments` | content_capture=FULL | 必须先脱敏 |
| `tool.result` | content_capture=FULL | 必须先脱敏 |
| `code.snippet` | content_capture=FULL | 仅捕获相关行 |

### 7.4 内容保护原则

1. **默认最小化**：MVP 默认 DISABLED 模式
2. **显式启用**：需组织级配置或任务级显式标记
3. **先脱敏后捕获**：脱敏失败则跳过捕获
4. **审计追踪**：记录内容捕获启用/禁用操作
5. **时限控制**：FULL 模式有效期不超过 7 天

---

## 8. 跨服务传播边界

### 8.1 受信任边界定义

**内部受信任服务**：
- 控制平面（Task Manager、Workflow Coordinator）
- Worker Runtime
- 工具/模型网关（Tool Gateway、Model Gateway）
- 沙箱管理组件（Sandbox Manager）
- 内部遥测/审计服务（OTLP Collector、Audit Service）

**外部第三方服务**：
- GitHub API
- MCP 服务器（需逐个登记）
- 模型供应商（OpenAI、Anthropic）
- 外部工具服务

### 8.2 传播规则

| 目标服务 | 传播策略 | 说明 |
|---------|---------|------|
| **内部受信任服务** | 完整传播 | 传播 traceparent + tracestate |
| **已登记的 MCP 服务** | 受控传播 | 仅在策略批准时传播 |
| **模型供应商** | 不传播 | 创建 client span + request_id |
| **GitHub API** | 不传播 | 创建 client span + request_id |
| **未登记的第三方** | 拒绝传播 | 创建新根 trace |

### 8.3 Baggage 白名单

**允许的 Baggage 字段**：
```yaml
baggage_allowlist:
  - organization_id  # 低基数，非敏感
  - project_id       # 低基数，非敏感
  - environment      # 低基数（dev/staging/prod）
```

**禁止的 Baggage 字段**：
- ❌ 凭据（credentials、api_key、token）
- ❌ 个人信息（user_email、user_name、user_ip）
- ❌ 高基数值（file_path、code_content、task_description）
- ❌ 任意用户文本（prompt、tool_arguments）

---

## 9. Span 父子关系定义

### 9.1 严格父子关系（包含）

| 子 Span | 父 Span | 说明 |
|---------|---------|------|
| Workflow | Task | Workflow 由 Task 触发 |
| Worker | Workflow | Worker 由 Workflow 调度 |
| Action | Worker | Action 由 Worker 执行 |
| Policy Decision | Action | 决策发生在 Action 执行前 |
| Tool | Action | 工具由 Action 调用 |
| Model | Action | 模型由 Action 调用 |
| Sandbox | Action | 沙箱由 Action 使用 |

### 9.2 Span Link（因果关联）

| 场景 | Link 类型 | 说明 |
|------|-----------|------|
| **重试** | FOLLOWS_FROM | 新 attempt 链接原始操作 |
| **恢复** | FOLLOWS_FROM | 恢复后的 Workflow 链接原 Checkpoint |
| **并行分支** | CHILD_OF | 并行 Worker 链接同一 Workflow |
| **子 Agent** | FOLLOWS_FROM | 子 Agent 链接父 Agent Task |
| **跨服务调用** | FOLLOWS_FROM | 外部调用链接 client span |

### 9.3 孤儿 Span 处理

**定义**：无法找到父 Span 的 Span（parent_span_id 不存在）

**处理策略**：
1. 保留 Span 数据，不丢弃
2. 记录 `orphan=true` 标记
3. 通过 correlation_id 或 task_id 关联
4. 计量孤儿 Span 比例，目标 < 1%

---

## 10. 异常与失败处理

### 10.1 Collector 不可用

**症状**：OTLP 导出返回 503 或连接超时

**处理**：
1. 本地缓冲队列保存 Span（最大 10000 个）
2. 指数退避重试（1s、2s、4s、8s、16s）
3. 超过重试次数后丢弃，记录 `export_drop_count`
4. **不阻塞 Agent 主执行路径**

### 10.2 采样配置无效

**症状**：采样率配置超出 [0, 1] 范围

**处理**：
1. 回退到默认采样率（15%）
2. 记录配置错误事件到 Audit Log
3. 通知管理员检查配置

### 10.3 属性超限

**症状**：Span 属性值长度超过 1KB

**处理**：
1. 截断超长字符串到 1KB
2. 添加 `truncated=true` 标记
3. 记录原始长度到 `original_length` 属性

### 10.4 父 Span 缺失

**症状**：parent_span_id 指向不存在的 Span

**处理**：
1. 创建 orphan span 标记
2. 通过 correlation_id 或 task_id 关联
3. 计量孤儿 Span 比例
4. **不伪造父 Span**

### 10.5 内容捕获失败

**症状**：脱敏器执行失败或内容格式无效

**处理**：
1. 跳过内容捕获
2. 记录 `content_capture_error=true`
3. 记录失败原因到 `capture_error_reason`
4. 保留元数据属性

### 10.6 跨服务传播被拒

**症状**：第三方服务拒绝接受 traceparent

**处理**：
1. 创建 client span 记录调用
2. 通过 request_id 或 correlation_id 关联
3. 不影响业务逻辑执行
4. 记录传播拒绝事件

---

## 11. 性能与成本考量

### 11.1 性能目标

| 指标 | 目标 | 测量方法 |
|------|------|----------|
| Span 创建开销 | < 1ms (p99) | 微基准测试 |
| 追踪 SDK CPU 开销 | < 5% (p95) | CPU profiling |
| 异步导出延迟 | < 100ms (p95) | OTLP 端到端测量 |
| 内存占用 | < 50MB | 常驻内存监控 |

### 11.2 成本控制

**Span 数量限制**：
- 单个 Trace 最多 100 个 Span
- 超过限制后拒绝创建新 Span，记录 `span_limit_exceeded`

**属性数量限制**：
- 每个 Span 最多 50 个属性
- 超过限制后拒绝添加属性，记录 `attribute_limit_exceeded`

**属性值长度限制**：
- 单个属性值最多 1KB
- 超过限制后截断，添加 `truncated=true`

**Span 大小限制**：
- 单个 Span 序列化后最多 100KB
- 超过限制后拒绝导出，记录 `span_too_large`

### 11.3 成本预估

**假设**：
- 每日任务数：10,000
- 每个 Task 平均 Span 数：20
- 单个 Span 大小：2KB
- 采样率：15%

**预估**：
```
日均 Span 数 = 10,000 × 20 × 15% = 30,000
日均数据量 = 30,000 × 2KB = 60MB
月均数据量 = 60MB × 30 = 1.8GB
```

---

## 12. 可观测性与评估指标

### 12.1 追踪质量指标

| 指标名 | 定义 | 目标 | 告警条件 |
|--------|------|------|----------|
| `obs.trace.root_span.rate` | 每分钟创建的根 Span 数量 | 基准指标 | N/A |
| `obs.trace.complete.ratio` | 完整 Trace 占比 | ≥ 95% | < 90% |
| `obs.trace.parent_linked.ratio` | 父 Span 关联成功率 | ≥ 99% | < 95% |
| `obs.span.orphan.count` | 孤儿 Span 数量 | < 1% | > 5% |
| `obs.span.count_per_trace` | 每 Trace 平均 Span 数 | < 100 | > 150 |

### 12.2 遥测导出指标

| 指标名 | 定义 | 目标 | 告警条件 |
|--------|------|------|----------|
| `obs.otel.export.success.rate` | OTLP 导出成功率 | ≥ 99.9% | < 99% |
| `obs.otel.export.latency.p95` | 导出延迟 p95 | < 100ms | > 500ms |
| `obs.otel.export.backlog.size` | 待导出队列大小 | < 1000 | > 5000 |
| `obs.otel.export.drop.count` | 丢弃的 Span 数量 | < 0.1% | > 1% |

### 12.3 审计覆盖指标

| 指标名 | 定义 | 目标 | 告警条件 |
|--------|------|------|----------|
| `obs.audit.critical.event.rate` | 关键操作审计覆盖率 | 100% | < 100% |
| `obs.audit.completeness.ratio` | 审计记录完整性 | ≥ 99.99% | < 99.9% |
| `obs.audit.privacy.rejected.count` | 敏感内容拦截次数 | 监控指标 | N/A |

---

## 13. 验收标准

### 13.1 功能性验收

| # | 验收项 | 验收方法 |
|---|--------|----------|
| 1 | Task 创建后生成有效的 TraceId | 单元测试：验证 TraceId 格式符合 UUID v4 |
| 2 | Workflow Span 作为并行 Worker Span 的父节点 | 集成测试：验证 parent_span_id 关联正确 |
| 3 | Worker 崩溃后 Span 设置 error 状态 | 故障注入测试：模拟 Worker 崩溃 |
| 4 | Action Span 包含必需属性 | Schema 验证：action_id、action_type、risk_level |
| 5 | LLM Span 包含必需属性 | Schema 验证：model_name、input_tokens、output_tokens |
| 6 | Tool Span 包含必需属性 | Schema 验证：tool_name、duration_ms、status |
| 7 | 重试 attempt 创建独立 span | 集成测试：验证 span.links 关联原始操作 |
| 8 | 跨服务调用注入/提取 traceparent | 集成测试：验证 W3C Trace Context 传播 |

### 13.2 采样验收

| # | 验收项 | 验收方法 |
|---|--------|----------|
| 9 | 默认采样率为 15% | 配置测试：验证默认配置 |
| 10 | 高风险任务采样率自动提升到 100% | 单元测试：模拟 risk_level=HIGH |
| 11 | Policy 拒绝、审批请求强制采样 | 集成测试：验证 priority=ALWAYS |
| 12 | 诊断请求覆盖采样率 | 集成测试：验证 debug=true 场景 |

### 13.3 内容保护验收

| # | 验收项 | 验收方法 |
|---|--------|----------|
| 13 | 默认不记录 Prompt、Tool Arguments | 集成测试：验证 DISABLED 模式 |
| 14 | 凭据值不会出现在任何 Span 属性 | 安全测试：搜索敏感字符串 |
| 15 | 脱敏规则按组织配置生效 | 集成测试：验证脱敏器输出 |
| 16 | Baggage 仅允许白名单字段 | 单元测试：验证 Baggage 过滤 |

### 13.4 传播验收

| # | 验收项 | 验收方法 |
|---|--------|----------|
| 17 | W3C Trace Context 在受信任边界内正确传播 | 集成测试：跨服务追踪验证 |
| 18 | 第三方服务不支持时创建 client span | 集成测试：模拟不支持场景 |
| 19 | 来自不可信源的 traceparent 被拒绝 | 安全测试：注入恶意 traceparent |

### 13.5 性能验收

| # | 验收项 | 验收方法 |
|---|--------|----------|
| 20 | Span 创建开销 < 1ms (p99) | 性能测试：微基准测试 |
| 21 | OTLP 导出成功率 ≥ 99.9% | 稳定性测试：长时间运行监控 |
| 22 | 导出失败不阻塞 Agent 执行 | 故障注入测试：模拟 Collector 不可用 |

---

## 14. 依赖与跨模块边界

### 14.1 前置依赖

| 需求 | 依赖内容 | 边界 |
|------|---------|------|
| `REQ-RT-001` | 核心实体定义（TaskId、WorkflowId、ActionId） | 不重新定义 |
| `REQ-RT-006` | Trace 传播、采样率、留存目标 | 继承基础契约 |
| `REQ-SEC-001` | 威胁模型、风险等级定义 | 引用 risk_level |
| `REQ-SEC-003` | Policy Gateway、PolicyDecision | 关联决策事件 |

### 14.2 下游依赖

| 需求 | 本设计提供的内容 | 边界 |
|------|---------------|------|
| `REQ-OBS-002` | Span 属性定义 | 由 OBS-002 冻结完整 Schema |
| `REQ-OBS-003` | 指标聚合来源 | 由 OBS-003 定义聚合规则 |
| `REQ-OBS-004` | 可捕获字段列表 | 由 OBS-004 定义脱敏实现 |
| `REQ-OBS-005` | Span 状态属性 | 由 OBS-005 定义告警规则 |
| `REQ-OBS-006` | Trace 结构定义 | 由 OBS-006 定义查询 API |
| `REQ-OBS-007` | 审计覆盖率定义 | 由 OBS-007 定义完整性机制 |

---

## 15. 实现指导

### 15.1 推荐技术栈

**OTel SDK**：
- Python：`opentelemetry-sdk`, `opentelemetry-exporter-otlp`
- Node.js：`@opentelemetry/sdk-node`, `@opentelemetry/exporter-trace-otlp-http`
- Go：`go.opentelemetry.io/otel`, `go.opentelemetry.io/otel/exporters/otlp/otlptrace`

**OTLP Collector**：
- OpenTelemetry Collector（推荐）
- Grafana Agent
- Datadog Agent

**Trace Backend**：
- Jaeger
- Tempo
- Azure Monitor
- Datadog APM

### 15.2 实现检查清单

- [ ] 安装 OTel SDK 并配置 OTLP exporter
- [ ] 实现 Span 创建辅助函数（create_task_span、create_workflow_span 等）
- [ ] 实现采样决策器（SamplingDecider）
- [ ] 实现内容捕获控制器（ContentCaptureController）
- [ ] 实现 Baggage 白名单过滤器（BaggageFilter）
- [ ] 实现 Trace Context 注入/提取（W3C Trace Context）
- [ ] 配置 Collector 和 Backend
- [ ] 编写单元测试和集成测试
- [ ] 配置监控告警规则
- [ ] 编写运维文档

---

## 16. 版本与变更记录

### 16.1 当前状态

`REQ-OBS-001` 当前版本为 `v0.1-designed`：本专项详细设计已完成，待与 Runtime Contract、安全、审计查询专项交叉评审后冻结。设计完成不代表已实现或运行指标已经验证。

### 16.2 冻结条件

1. 与 `REQ-RT-001/006` 完成实体、Trace 传播交叉评审
2. 与 `REQ-OBS-002/003/004/006/007` 对齐 Schema、指标、脱敏、查询、留存边界
3. 与 `REQ-SEC-001/003` 完成风险等级、决策关联评审
4. 完成 Span 层级、采样策略、内容保护、传播边界契约测试设计
5. 用代表性 Agent 运行验证追踪开销、审计覆盖率和默认采样策略

### 16.3 变更记录

| 版本 | 日期 | 变更 |
|------|------|------|
| `v0.1-designed` | 2026-10-02 | 基于 OpenTelemetry GenAI SIG、Cursor、DeepSeek Harness、LangSmith、Microsoft Copilot 公开资料，完成分层 Span 结构、标准属性集、采样策略、内容保护、传播边界设计；采样率、内容捕获、MVP 跨服务追踪范围按用户确认收敛 |

---

**文档维护**：架构组  
**最后更新**：2026-10-02
