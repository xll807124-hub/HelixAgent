# REQ-OBS-002 Trace/Event/Evidence Schema 详细设计

> 所属基线：`Observability Baseline v0.1`  
> 需求编号：`REQ-OBS-002`  
> 优先级：P0  
> 设计版本：`v0.1-designed`  
> 设计状态：详细设计已完成，待跨模块冻结  
> 前置依赖：`REQ-RT-001`、`REQ-RT-003`、`REQ-RT-006`、`REQ-OBS-001`  
> 关键决策：分层数据模型（Trace/Span/Event/Evidence）；30+ EventType 枚举；Evidence 独立建模；多维关联模型；分层存储策略

---

## 1. 需求定义

### 1.1 目标

为 AI Agent 平台建立完整的 Trace/Event/Evidence 分层数据模型，定义标准化的 Event 类型体系，设计 Evidence 聚合与关联机制，并提供可查询的字段定义与索引策略。确保可观测性数据在跨模块、跨时间的场景下保持一致性、可追溯性和可聚合性。

### 1.2 用户价值

- **开发人员**：快速定位问题、追溯执行路径、分析性能瓶颈、调试任务失败
- **安全审计员**：完整审计追踪、证据固化、合规报告、操作溯源
- **平台运营**：成本分析、资源优化、SLA 监控、容量规划
- **AI 研究员**：行为分析、模型评估、策略优化、效果归因
- **SRE**：故障排查、关联分析、延迟定位、可用性监控

### 1.3 范围

**包含**：
- Trace 数据模型定义（结构、字段、状态机）
- Event 类型枚举与属性定义（30+ EventType）
- Evidence 数据模型定义（类型、敏感度、签名）
- 关联模型设计（Trace↔Span↔Event↔Evidence）
- 查询字段定义与索引策略
- 数据流转与状态管理
- 分层存储策略（热/温/冷）

**不包含**：
- Span 属性详细定义（由 `REQ-OBS-001` 定义）
- 指标聚合规则（由 `REQ-OBS-003` 定义）
- 脱敏实现细节（由 `REQ-OBS-004` 定义）
- 告警规则配置（由 `REQ-OBS-005` 定义）
- 审计查询 API 实现（由 `REQ-OBS-006` 定义）
- 审计留存和完整性机制（由 `REQ-OBS-007` 定义）


---

## 2. 共享契约与术语

本设计复用 `REQ-RT-001` 定义的核心实体（TaskId、WorkflowId、WorkerId、ActionId）、`REQ-RT-003` 定义的 Event Schema 基础、`REQ-RT-006` 定义的 Trace 传播基础（TraceId、SpanId、TraceContext），以及 `REQ-OBS-001` 定义的 Span 属性体系。

### 2.1 核心术语

| 术语 | 定义 |
|------|------|
| **Trace** | 同一因果执行链的 Span 集合，代表一次完整的 Agent 执行 |
| **Span** | 具有开始、结束、父子关系的操作观测单元（见 REQ-OBS-001） |
| **Event** | 特定时刻发生的离散事件，关联到 Span 或 Trace |
| **Evidence** | 可追溯内容的固化，用于审计和合规，包含内容哈希和签名 |
| **EventType** | 事件类型枚举，覆盖 Agent 全生命周期 |
| **Correlation** | 数据间的关联关系（父子、引用、时序） |
| **Orphan Data** | 无法找到父节点的孤儿数据（Span/Event/Evidence） |

---

## 3. 行业调研与可借鉴原则

### 3.1 OpenTelemetry GenAI SIG

**来源**：[OpenTelemetry GenAI Agent Spans](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-agent-spans.md)  
**访问日期**：2026-10-03

**关键发现**：
- 分层 Span 类型：Agent、Tool、Workflow、LLM、Retrieval
- 属性前缀统一为 `gen_ai.*`
- 区分 client/internal Span 类型
- 必选/可选/条件必选三级属性要求

**借鉴点**：采用 OTel GenAI 标准化属性体系；保持与行业标准兼容。

**证据等级**：A（官方文档）

---

### 3.2 LangSmith (LangChain)

**来源**：[LangSmith Query Traces API](https://docs.langchain.com/langsmith/smith-api/runs/query-traces)  
**访问日期**：2026-10-03

**关键发现**：
- Project→Trace→Run→Thread 四级层次
- Run 类型：llm、chain、tool、retriever、agent、embedding
- 事件系统：name（start/end/new_token）、time、kwargs（payload）
- 查询语法：`eq(run_type, "llm")`、`eq(status, "error")`

**借鉴点**：Run 类型枚举覆盖完整生命周期；事件系统支持 streaming 粒度；结构化查询过滤语法。

**证据等级**：A（官方文档）

---

### 3.3 Manus AI

**来源**：[Manus Task Lifecycle](https://open.manus.ai/docs/v2/task-lifecycle)  
**访问日期**：2026-10-03

**关键发现**：
- Event 类型：user_message、assistant_message、tool_used、plan_update、new_plan_step、explanation
- 状态转换：running → waiting → stopped/error
- 确认机制：waiting_for_event_id + confirmAction

**借鉴点**：plan_update/new_plan_step 支持计划可观测；等待确认机制（人类在环）。

**证据等级**：A（官方 API 文档）

---

### 3.4 Microsoft Copilot Studio / Azure Foundry

**来源**：[Agent Environment-level Telemetry](https://learn.microsoft.com/en-us/microsoft-copilot-studio/advanced-environment-level-agent-telemetry)  
**访问日期**：2026-10-03

**关键发现**：
- Span 类型：InvokeAgent（根）、ExecuteTool、OutputMessages
- 关联模型：operation_Id（根）、operation_ParentId（父子）
- 评估结果：gen_ai.evaluation.result（分数、标签、解释）

**借鉴点**：evaluation 结果结构化追踪；KQL 查询模式；集中托管配置。

**证据等级**：A（官方文档）

---

### 3.5 Dify

**来源**：[Dify Unified Tracing PR](https://github.com/langgenius/dify/pull/39451)  
**访问日期**：2026-10-03

**关键发现**：
- 内部保留 Dify-native 模型，外部投影到 OTel GenAI
- Agent ReAct 模式：AGENT span → STEP span → LLM/TOOL
- TTFT 追踪：gen_ai.response.time_to_first_token

**借鉴点**：内部模型与外部投影分离设计；ReAct 模式的 Span 层次映射；语义约定版本追踪。

**证据等级**：A（开源实现）


---

## 4. 数据模型设计

### 4.1 Trace 模型

**Trace 是同一因果执行链的 Span 集合，代表一次完整的 Agent 执行。**

``yaml
Trace:
  # === 标识字段 ===
  trace_id: string                     # 唯一标识 (UUID v4, W3C Trace Context)
  trace_version: string                # OTel 语义约定版本 (如 "gen_ai_v1.0")
  
  # === 根节点信息 ===
  root_span_id: string                 # 根 Span ID
  root_operation_type: enum            # invoke_agent / invoke_workflow
  
  # === 关联字段 ===
  task_id: string (nullable)           # 关联 Task (可选, 外部标识)
  workflow_id: string (nullable)       # 关联 Workflow
  conversation_id: string (nullable)   # 关联会话/对话
  organization_id: string              # 组织 ID (租户隔离)
  project_id: string (nullable)        # 项目 ID
  
  # === 统计聚合 ===
  span_count: int                      # Span 总数
  event_count: int                     # Event 总数
  evidence_count: int                  # Evidence 总数
  total_duration_ms: int               # 总耗时（根 Span 耗时）
  
  # === 时间戳 ===
  start_time: datetime                 # 最早 Span 开始时间
  end_time: datetime (nullable)        # 最晚 Span 结束时间（运行中为 null）
  
  # === 状态 ===
  status: enum                         # RUNNING / COMPLETED / FAILED / CANCELLED
  
  # === 标签与元数据 ===
  tags: list[string]                   # 可搜索标签（如 ["debug", "production"]）
  metadata: object                     # 任意键值对（如 {"user_id": "123"}）
  
  # === 采样信息 ===
  sampling_rate: float                 # 采样率 (0.0 ~ 1.0)
  sampling_priority: enum              # ALWAYS / HIGH / NORMAL
``

**Trace 状态机**：
``
CREATED → RUNNING → COMPLETED
              ↓
           FAILED
              ↓
         CANCELLED

状态转换规则：
- CREATED → RUNNING: 首个 Span 开始
- RUNNING → COMPLETED: 所有 Span 结束且无 ERROR
- RUNNING → FAILED: 任意 Span ERROR 且未恢复
- RUNNING → CANCELLED: 显式取消请求
``

---

### 4.2 Span 模型（继承 REQ-OBS-001）

**Span 是具有开始、结束、父子关系的操作观测单元。**

Span 的详细定义见 `REQ-OBS-001` 第 4-5 节，本设计仅补充与 Event/Evidence 的关联字段：

``yaml
Span:
  # === 核心字段（继承自 REQ-OBS-001）===
  span_id: string
  trace_id: string
  parent_span_id: string (nullable)
  span_kind: enum
  operation_name: string
  attributes: map[string, any]
  status: enum
  start_time: datetime
  end_time: datetime
  duration_ms: int
  
  # === 本设计新增：Event 关联 ===
  event_ids: list[string]              # 关联的 Event ID 列表
  
  # === 本设计新增：Evidence 关联 ===
  evidence_ids: list[string]           # 关联的 Evidence ID 列表
  
  # === 本设计新增：Span Link ===
  links: list[SpanLink]                # Span 间的关联
``

**SpanLink 定义**：
``yaml
SpanLink:
  linked_span_id: string               # 链接目标 Span ID
  link_type: enum                      # FOLLOWS_FROM / CHILD_OF / CAUSED_BY
  attributes: map[string, any]         # 链接元数据
``


---

### 4.3 Event 模型

**Event 是特定时刻发生的离散事件，关联到 Span 或 Trace。**

``yaml
Event:
  # === 标识字段 ===
  event_id: string                     # 唯一标识 (UUID v4)
  trace_id: string                     # 父 Trace
  span_id: string (nullable)           # 关联 Span（Trace-level Event 无 span_id）
  
  # === Event 类型 ===
  event_type: EventType                # 枚举值（见 4.4 节）
  event_name: string                   # 事件名称（如 "tool.started"）
  event_category: enum                 # LIFECYCLE / WORKFLOW / WORKER / ACTION / TOOL / MODEL / PLAN / ERROR / SECURITY / HUMAN / EVIDENCE
  
  # === 时间戳 ===
  timestamp: datetime                  # 事件发生时间（毫秒精度）
  
  # === Payload ===
  payload: object                      # 事件特定数据（JSON）
  payload_schema_version: string       # Payload Schema 版本
  
  # === 关联 ===
  correlated_event_ids: list[string]   # 关联 Event（如 request ↔ response）
  parent_event_id: string (nullable)   # 父 Event（如 Plan ↔ PlanStep）
  
  # === 溯源 ===
  source_service: string               # 事件来源服务（如 "worker-runtime"）
  source_component: string             # 事件来源组件（如 "tool-gateway"）
  
  # === 元数据 ===
  severity: enum (nullable)            # INFO / WARNING / ERROR / CRITICAL
  tags: list[string]                   # 可搜索标签
``

---

### 4.4 EventType 枚举

**EventType 覆盖 Agent 全生命周期，共 44 类型。**

``yaml
EventType:
  # ========== 生命周期事件 (LIFECYCLE) ==========
  TASK_CREATED: "task.created"              # 任务创建
  TASK_STARTED: "task.started"              # 任务开始
  TASK_COMPLETED: "task.completed"          # 任务正常完成
  TASK_FAILED: "task.failed"                # 任务失败
  TASK_CANCELLED: "task.cancelled"          # 任务取消
  TASK_WAITING: "task.waiting"              # 任务等待（如人工审批）
  
  # ========== 工作流事件 (WORKFLOW) ==========
  WORKFLOW_STARTED: "workflow.started"      # 工作流开始
  WORKFLOW_COMPLETED: "workflow.completed"  # 工作流完成
  WORKFLOW_FAILED: "workflow.failed"        # 工作流失败
  WORKFLOW_STEP_COMPLETED: "workflow.step.completed"  # 工作流步骤完成
  
  # ========== Worker 事件 (WORKER) ==========
  WORKER_STARTED: "worker.started"          # Worker 启动
  WORKER_COMPLETED: "worker.completed"      # Worker 完成
  WORKER_FAILED: "worker.failed"            # Worker 失败
  WORKER_DELEGATED: "worker.delegated"      # Worker 委托（子 Agent）
  
  # ========== Action 事件 (ACTION) ==========
  ACTION_AUTHORIZED: "action.authorized"    # Action 已授权
  ACTION_REJECTED: "action.rejected"        # Action 被拒绝
  ACTION_APPROVAL_REQUESTED: "action.approval_requested"  # 等待审批
  ACTION_APPROVAL_CONFIRMED: "action.approval_confirmed"  # 审批通过
  ACTION_APPROVAL_REJECTED: "action.approval_rejected"    # 审批拒绝
  
  # ========== Tool 事件 (TOOL) ==========
  TOOL_STARTED: "tool.started"              # Tool 开始执行
  TOOL_COMPLETED: "tool.completed"          # Tool 完成
  TOOL_FAILED: "tool.failed"                # Tool 失败
  TOOL_TIMEOUT: "tool.timeout"              # Tool 超时
  TOOL_RETRY: "tool.retry"                  # Tool 重试
  
  # ========== Model 事件 (MODEL) ==========
  MODEL_REQUEST_STARTED: "model.request.started"     # 模型请求开始
  MODEL_RESPONSE_RECEIVED: "model.response.received" # 模型响应接收
  MODEL_STREAMING_TOKEN: "model.streaming.token"     # 流式 Token
  MODEL_FAILED: "model.failed"                       # 模型调用失败
  
  # ========== 规划事件 (PLAN) ==========
  PLAN_CREATED: "plan.created"              # 计划创建
  PLAN_UPDATED: "plan.updated"              # 计划更新
  PLAN_STEP_STARTED: "plan.step.started"    # 计划步骤开始
  PLAN_STEP_COMPLETED: "plan.step.completed"  # 计划步骤完成
  
  # ========== 错误事件 (ERROR) ==========
  ERROR_OCCURRED: "error.occurred"          # 错误发生
  ERROR_RECOVERED: "error.recovered"        # 错误恢复
  ERROR_PROPAGATED: "error.propagated"      # 错误传播
  
  # ========== 安全事件 (SECURITY) ==========
  SECURITY_POLICY_DENIED: "security.policy.denied"  # 安全策略拒绝
  SECURITY_PROMPT_INJECTION_DETECTED: "security.injection.detected"  # 注入检测
  SECURITY_CREDENTIAL_ACCESS: "security.credential.access"  # 凭据访问
  
  # ========== 人类在环事件 (HUMAN) ==========
  HUMAN_APPROVAL_REQUESTED: "human.approval.requested"   # 请求人工审批
  HUMAN_APPROVAL_RECEIVED: "human.approval.received"     # 收到人工响应
  HUMAN_FEEDBACK_PROVIDED: "human.feedback.provided"     # 收到人工反馈
  
  # ========== Evidence 相关 (EVIDENCE) ==========
  EVIDENCE_CAPTURED: "evidence.captured"    # Evidence 已捕获
  EVIDENCE_SIGNED: "evidence.signed"        # Evidence 已签名
  EVIDENCE_CHALLENGED: "evidence.challenged"  # Evidence 被质疑
``

**EventType 分类统计**：
- 生命周期事件（LIFECYCLE）：6 项
- 工作流事件（WORKFLOW）：4 项
- Worker 事件（WORKER）：4 项
- Action 事件（ACTION）：5 项
- Tool 事件（TOOL）：5 项
- Model 事件（MODEL）：4 项
- 规划事件（PLAN）：4 项
- 错误事件（ERROR）：3 项
- 安全事件（SECURITY）：3 项
- 人类在环事件（HUMAN）：3 项
- Evidence 相关（EVIDENCE）：3 项
- **总计**：44 项


---

### 4.5 Evidence 模型

**Evidence 是可追溯内容的固化，用于审计和合规。**

``yaml
Evidence:
  # === 标识字段 ===
  evidence_id: string                  # 唯一标识 (UUID v4)
  trace_id: string                     # 关联 Trace
  evidence_type: enum                  # PROMPT / COMPLETION / TOOL_INPUT / TOOL_OUTPUT / ARTIFACT / DECISION / AUDIT
  
  # === 内容 ===
  content_hash: string                 # 内容哈希 (SHA-256)
  content_size_bytes: int              # 内容大小
  content_encoding: enum               # RAW / BASE64 / GZIP
  content_location: string             # 内容存储位置 (URI)
  
  # === 敏感度 ===
  sensitivity_level: enum              # PUBLIC / INTERNAL / CONFIDENTIAL / RESTRICTED
  contains_credentials: boolean        # 是否包含凭据
  contains_pii: boolean                # 是否包含 PII
  redacted: boolean                    # 是否已脱敏
  
  # === 溯源 ===
  captured_at: datetime                # 捕获时间
  captured_by: string                  # 捕获组件
  source_span_id: string               # 来源 Span
  source_event_id: string (nullable)   # 来源 Event
  
  # === 完整性 ===
  signature: string (nullable)         # 签名（高敏感 Evidence 必须）
  signature_algorithm: string (nullable)  # 签名算法 (如 "HMAC-SHA256")
  signed_at: datetime (nullable)       # 签名时间
  signed_by: string (nullable)         # 签名者
  
  # === 引用 ===
  referenced_by: list[string]          # 引用此 Evidence 的 Event
  
  # === 元数据 ===
  tags: list[string]                   # 可搜索标签
  metadata: object                     # 任意键值对
``

**Evidence 类型说明**：
| 类型 | 说明 | 示例 |
|------|------|------|
| PROMPT | 模型输入 Prompt | System prompt + User message |
| COMPLETION | 模型输出 Completion | Assistant response |
| TOOL_INPUT | 工具输入参数 | `{"file": "main.py", "line": 10}` |
| TOOL_OUTPUT | 工具输出结果 | `{"status": "success", "output": "..."}` |
| ARTIFACT | 生成的文件/产物 | 代码文件、图片、报告 |
| DECISION | 决策记录 | Policy 决策、审批记录 |
| AUDIT | 审计日志 | 操作审计、访问日志 |

---

## 5. 关联模型设计

### 5.1 关联路径定义

``
Trace ↔ Span ↔ Event ↔ Evidence

详细关联：
1. Trace.trace_id = Span.trace_id (1:N)
2. Span.span_id = Event.span_id (1:N)
3. Event.event_id ∈ Evidence.referenced_by (N:M)
4. Span.event_ids → Event.event_id (1:N)
5. Span.evidence_ids → Evidence.evidence_id (1:N)
6. Event.correlated_event_ids → Event.event_id (N:M)
7. Event.parent_event_id → Event.event_id (1:1)
``

**关联规则**：
- 每个 Span 必须有 trace_id
- Event 可以关联到 Span（span_id）或直接关联到 Trace（span_id=null）
- Evidence 必须有 trace_id，可选关联 source_span_id 和 source_event_id
- 孤儿数据处理：无法找到父节点的 Span/Event/Evidence 标记为 orphan，保留 90 天后清理

---

### 5.2 多维关联示例

**示例 1：Tool 执行关联**

``
Trace: trace-123
  ├─ Span: span-worker-456 (Worker ReAct)
  │   ├─ Event: event-tool-start-789 (TOOL_STARTED)
  │   │   └─ Evidence: evidence-input-abc (TOOL_INPUT)
  │   ├─ Span: span-tool-101 (Tool Execution)
  │   │   └─ Event: event-tool-complete-112 (TOOL_COMPLETED)
  │   │       └─ Evidence: evidence-output-def (TOOL_OUTPUT)
  │   └─ Event: event-tool-retry-113 (TOOL_RETRY)
``

**示例 2：人类在环关联**

``
Trace: trace-456
  ├─ Span: span-action-789 (Action Authorization)
  │   ├─ Event: event-approval-req-101 (ACTION_APPROVAL_REQUESTED)
  │   │   └─ Evidence: evidence-decision-ghi (DECISION)
  │   └─ Event: event-approval-conf-102 (HUMAN_APPROVAL_RECEIVED)
  │       └─ Evidence: evidence-audit-jkl (AUDIT)
``


---

## 6. 查询字段与索引策略

### 6.1 核心查询字段

**Trace 查询字段**：
- `trace_id` (PRIMARY KEY)
- `organization_id` (PARTITION KEY)
- `task_id`, `workflow_id`
- `status`
- `start_time`, `end_time`
- `tags` (支持数组包含查询)

**Event 查询字段**：
- `event_id` (PRIMARY KEY)
- `trace_id` (FOREIGN KEY)
- `span_id` (FOREIGN KEY)
- `event_type`, `event_category`
- `timestamp`
- `severity`
- `source_service`, `source_component`

**Evidence 查询字段**：
- `evidence_id` (PRIMARY KEY)
- `trace_id` (FOREIGN KEY)
- `evidence_type`
- `sensitivity_level`
- `captured_at`
- `content_hash`

---

### 6.2 索引策略

**PostgreSQL 索引（热存储）**：

``sql
-- Trace 索引
CREATE INDEX idx_trace_org_time ON traces(organization_id, start_time DESC);
CREATE INDEX idx_trace_task ON traces(task_id) WHERE task_id IS NOT NULL;
CREATE INDEX idx_trace_status ON traces(status, start_time DESC);
CREATE INDEX idx_trace_tags ON traces USING GIN(tags);

-- Event 索引
CREATE INDEX idx_event_trace ON events(trace_id, timestamp DESC);
CREATE INDEX idx_event_span ON events(span_id) WHERE span_id IS NOT NULL;
CREATE INDEX idx_event_type ON events(event_type, timestamp DESC);
CREATE INDEX idx_event_category ON events(event_category, timestamp DESC);
CREATE INDEX idx_event_severity ON events(severity, timestamp DESC) WHERE severity IN ('ERROR', 'CRITICAL');

-- Evidence 索引
CREATE INDEX idx_evidence_trace ON evidence(trace_id, captured_at DESC);
CREATE INDEX idx_evidence_type ON evidence(evidence_type, captured_at DESC);
CREATE INDEX idx_evidence_hash ON evidence(content_hash);
CREATE INDEX idx_evidence_sensitivity ON evidence(sensitivity_level, captured_at DESC);
``

**分区策略（时间分区）**：

``sql
-- 按月分区（热存储 30 天）
CREATE TABLE traces_2026_10 PARTITION OF traces
  FOR VALUES FROM ('2026-10-01') TO ('2026-11-01');

-- 按季度分区（温存储 180 天）
CREATE TABLE events_2026_q4 PARTITION OF events_archive
  FOR VALUES FROM ('2026-10-01') TO ('2027-01-01');
``

---

## 7. 数据流转与状态管理

### 7.1 写入流程

``
1. Trace 创建
   ├─ 生成 trace_id (UUID v4)
   ├─ 设置 status = CREATED
   └─ 记录 start_time

2. Span 写入
   ├─ 关联 trace_id
   ├─ 更新 Trace.span_count
   └─ 触发 status = RUNNING

3. Event 写入
   ├─ 关联 trace_id, span_id
   ├─ 更新 Span.event_ids
   └─ 更新 Trace.event_count

4. Evidence 捕获
   ├─ 计算 content_hash
   ├─ 存储内容到对象存储
   ├─ 写入 Evidence 元数据
   └─ 更新 Event.referenced_by

5. Trace 完成
   ├─ 等待所有 Span 结束
   ├─ 聚合统计信息
   └─ 设置 status = COMPLETED/FAILED
``

---

### 7.2 分层存储策略

| 存储层 | 保留期 | 存储介质 | 查询性能 | 用途 |
|--------|--------|---------|----------|------|
| **热存储** | 30 天 | PostgreSQL | p95 < 100ms | 实时查询、调试 |
| **温存储** | 180 天 | PostgreSQL (归档表) | p95 < 500ms | 历史分析、审计 |
| **冷存储** | 7 年 | S3 / Azure Blob | 分钟级 | 合规留存 |

**归档流程**：

``
热存储 (30 天)
   ↓ (每日批量归档)
温存储 (180 天)
   ↓ (每月批量归档)
冷存储 (7 年)
   ↓ (合规删除)
永久删除
``

**归档触发条件**：
- 热→温：`end_time < NOW() - INTERVAL '30 days'`
- 温→冷：`end_time < NOW() - INTERVAL '180 days'`
- 冷→删除：`end_time < NOW() - INTERVAL '7 years'` AND `legal_hold = false`

---

## 8. 验收标准

### 8.1 功能验收

| 编号 | 验收标准 | 验证方法 |
|------|---------|---------|
| AC-1 | Trace 模型包含所有必选字段 | Schema 验证 |
| AC-2 | EventType 枚举覆盖 40+ 类型 | 代码生成验证 |
| AC-3 | Evidence 支持 7 种类型 | 单元测试 |
| AC-4 | 关联查询支持 Trace→Span→Event→Evidence | 集成测试 |
| AC-5 | 孤儿数据标记并保留 90 天 | 数据治理测试 |

---

### 8.2 性能验收

| 指标 | 目标 | 验证方法 |
|------|------|---------|
| Trace 写入延迟 | p95 < 50ms | 压测 |
| Event 写入吞吐 | > 10,000 events/s | 压测 |
| 热存储查询延迟 | p95 < 100ms | 查询基准测试 |
| 温存储查询延迟 | p95 < 500ms | 查询基准测试 |
| 归档任务延迟 | < 1 小时/批次 | 批量归档测试 |

---

### 8.3 合规验收

| 编号 | 验收标准 | 验证方法 |
|------|---------|---------|
| CO-1 | Evidence 敏感字段签名 | 签名验证测试 |
| CO-2 | 租户隔离（organization_id） | 跨租户泄漏测试 |
| CO-3 | 冷存储保留 7 年 | 留存策略审计 |
| CO-4 | Legal Hold 阻止删除 | 合规删除测试 |


---

## 9. 依赖与跨模块边界

### 9.1 前置依赖

| 需求编号 | 依赖内容 | 使用方式 |
|---------|---------|---------|
| `REQ-RT-001` | TaskId、WorkflowId、ActionId | Trace 关联字段 |
| `REQ-RT-003` | Event Schema 基础 | Event 结构继承 |
| `REQ-RT-006` | TraceId、SpanId、TraceContext | Trace 传播协议 |
| `REQ-OBS-001` | Span 属性体系 | Span 字段继承 |

---

### 9.2 后续依赖

| 需求编号 | 依赖本设计内容 | 集成方式 |
|---------|---------------|---------|
| `REQ-OBS-003` | Event、Evidence 字段 | 指标聚合源 |
| `REQ-OBS-004` | Evidence.sensitivity_level | 脱敏规则输入 |
| `REQ-OBS-005` | Event.severity | 告警触发条件 |
| `REQ-OBS-006` | 查询字段和索引 | 审计查询 API |
| `REQ-OBS-007` | 分层存储策略 | 留存实现 |

---

## 10. 实现指导

### 10.1 技术选型建议

**存储层**：
- **热存储**：PostgreSQL 15+ (支持分区、JSONB、GIN 索引)
- **对象存储**：S3 / Azure Blob (Evidence 内容)
- **缓存**：Redis (Trace 聚合统计)

**查询层**：
- **实时查询**：PostgreSQL + 连接池
- **分析查询**：ClickHouse / TimescaleDB (可选)
- **全文搜索**：Elasticsearch (可选，用于 Payload 搜索)

**归档层**：
- **批量归档**：Airflow / Temporal
- **冷存储**：S3 Glacier / Azure Archive

---

### 10.2 代码生成建议

**生成 EventType 枚举**：

``python
# auto-generated from REQ-OBS-002 EventType definition
class EventType(str, Enum):
    TASK_CREATED = "task.created"
    TASK_STARTED = "task.started"
    # ... (44 项)
    EVIDENCE_CHALLENGED = "evidence.challenged"
``

**生成 Pydantic 模型**：

``python
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List, Dict

class Trace(BaseModel):
    trace_id: str = Field(..., description="唯一标识")
    trace_version: str
    root_span_id: str
    # ... (完整字段定义)
    
class Event(BaseModel):
    event_id: str
    trace_id: str
    span_id: Optional[str] = None
    event_type: EventType
    # ... (完整字段定义)
``

---

### 10.3 迁移路径

**Phase 1：基础模型（MVP）**
- 实现 Trace、Event、Evidence 核心模型
- PostgreSQL 热存储 (30 天)
- 基础查询 API

**Phase 2：分层存储**
- 实现温存储归档 (180 天)
- 冷存储归档 (7 年)
- 批量归档流程

**Phase 3：高级特性**
- ClickHouse 分析查询
- Elasticsearch 全文搜索
- 实时聚合仪表板

---

## 11. 变更记录

| 版本 | 日期 | 变更内容 | 作者 |
|------|------|---------|------|
| v0.1-designed | 2026-10-04 | 初始详细设计完成 | 架构组 |

---

## 12. 附录

### 12.1 完整 EventType 清单

见第 4.4 节（44 项事件类型）。

---

### 12.2 Evidence 签名示例

``python
import hashlib
import hmac

def sign_evidence(content: bytes, secret_key: bytes) -> str:
    content_hash = hashlib.sha256(content).hexdigest()
    signature = hmac.new(secret_key, content_hash.encode(), hashlib.sha256).hexdigest()
    return signature

def verify_evidence(content: bytes, signature: str, secret_key: bytes) -> bool:
    expected_signature = sign_evidence(content, secret_key)
    return hmac.compare_digest(signature, expected_signature)
``

---

### 12.3 孤儿数据检测查询

``sql
-- 检测孤儿 Span（无 Trace）
SELECT span_id, trace_id, created_at
FROM spans
WHERE trace_id NOT IN (SELECT trace_id FROM traces)
  AND created_at < NOW() - INTERVAL '24 hours';

-- 检测孤儿 Event（无 Span）
SELECT event_id, span_id, timestamp
FROM events
WHERE span_id IS NOT NULL
  AND span_id NOT IN (SELECT span_id FROM spans)
  AND timestamp < NOW() - INTERVAL '24 hours';

-- 检测孤儿 Evidence（无 Trace）
SELECT evidence_id, trace_id, captured_at
FROM evidence
WHERE trace_id NOT IN (SELECT trace_id FROM traces)
  AND captured_at < NOW() - INTERVAL '24 hours';
``

---

### 12.4 参考资源

- [OpenTelemetry GenAI Semantic Conventions](https://github.com/open-telemetry/semantic-conventions-genai)
- [LangSmith Tracing Documentation](https://docs.langchain.com/langsmith/)
- [Manus AI Task Lifecycle](https://open.manus.ai/docs/v2/task-lifecycle)
- [Microsoft Copilot Telemetry](https://learn.microsoft.com/en-us/microsoft-copilot-studio/)
- [Dify Unified Tracing PR](https://github.com/langgenius/dify/pull/39451)

---

**文档结束**

