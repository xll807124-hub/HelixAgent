# REQ-OBS-004 脱敏和高基数控制详细设计

> 所属基线：`Observability Baseline v0.1`  
> 需求编号：`REQ-OBS-004`  
> 优先级：P0  
> 设计版本：`v0.1-designed`  
> 设计状态：详细设计已完成，待跨模块冻结  
> 前置依赖：`REQ-SEC-008`、`REQ-OBS-001`、`REQ-OBS-002`、`REQ-OBS-003`  
> 关键决策：Fail-Closed 白名单策略；四层敏感度分级；Key Name 词素分词脚敏；32 层递归上限；调试模式 24h 失效

---

## 1. 需求定义

### 1.1 目标

为 AI Agent 平台建立日志、Trace、Metric 三类遥测数据的脱敏规则和高基数控制策略，确保：

1. **敏感信息不泄露**：凭据（API Key、Token、Password）、PII（Email、Phone、SSN、Credit Card）、商业数据不进入遥测后端
2. **度量维度基数受控**：防止时序数据库成本爆炸和查询性能下降
3. **可验证可审计**：脱敏执行有审计记录，效果可验证
4. **可扩展架构**：支持组织级自定义规则

### 1.2 用户价值

- **安全合规用户**：满足 GDPR/HIPAA/PCI 等合规要求，敏感数据不进入遥测后端
- **平台运营用户**：度量维度基数受控，存储和查询成本可预测
- **开发调试用户**：调试模式下可临时绕过脱敏（显式 opt-in，有审计）
- **AI 研究员**：脱敏后的聚合数据仍可用于模型效果分析

### 1.3 范围

**包含**：
- 敏感信息分类与分级（PII 五类、凭据、商业数据）
- 脱敏规则定义与执行引擎（采集端 + OTel Collector 端）
- 高基数度量维度控制策略
- 调试模式（临时 Full 模式）审批流程
- 脱敏审计记录与质量指标
- 可扩展规则架构

**不包含**：
- 具体的 PII 检测算法实现细节（使用第三方库）
- 时序数据库选型与部署
- 审计日志查询 API 实现（由 `REQ-OBS-006` 定义）
- 审计留存和完整性机制（由 `REQ-OBS-007` 定义）

---

## 2. 共享契约与术语

本设计复用 `REQ-RT-001` 定义的核心实体（TaskId、TraceId、SpanId）、`REQ-OBS-001` 定义的内容捕获模式（DISABLED/FEEDBACK_ONLY/FULL）、`REQ-OBS-002` 定义的 Evidence.sensitivity_level（PUBLIC/INTERNAL/CONFIDENTIAL/RESTRICTED）、`REQ-OBS-003` 定义的指标维度体系。

### 2.1 核心术语

| 术语 | 定义 |
|------|------|
| **脱敏（Redaction）** | 移除或遮蔽遥测数据中的敏感信息的过程 |
| **高基数（High Cardinality）** | 度量维度组合数量过多，导致时序数据库性能和成本问题 |
| **Fail-Closed** | 脱敏失败时拒绝数据采集，防止敏感信息泄露 |
| **Fail-Open** | 脱敏失败时允许数据通过，优先保障可用性 |
| **Redaction Rule** | 脱敏规则，定义目标字段、检测器、动作和失败模式 |
| **Cardinality Budget** | 基数预算，单指标允许的最大维度组合数 |
| **Overflow Bucket** | 溢出桶，超出基数预算的值归入的兜底值（如 `__overflow__`） |

---

## 3. 行业调研与可借鉴原则

### 3.1 OpenTelemetry 官方

**来源**：[Handling sensitive data | OpenTelemetry](https://opentelemetry.io/docs/security/handling-sensitive-data/)  
**访问日期**：2026-10-05

**关键发现**：
- 最佳实践："预防胜于治理"——仅收集可观测必需字段
- Collector 层提供 `redactionprocessor` + `transformprocessor` 组合
- `allowed_keys` 白名单 Fail-Closed 机制
- HMAC-SHA256 防低熵值碰撞
- URL Sanitizer 降低高基数

**借鉴点**：Collector 集中化脱敏架构；白名单强制 Fail-Closed；URL Sanitizer 双重降基数。

**证据等级**：A（官方文档）

---

### 3.2 Cursor Enterprise

**来源**：[Cursor OpenTelemetry Export](https://cursor.com/docs/enterprise/opentelemetry-export)  
**访问日期**：2026-10-05

**关键发现**：
- 内容捕获默认关闭（`conversation_content` 需显式 opt-in）
- 截断上限：消息正文 32KB
- 基于 key name 的词素分词脱敏（tokenize on `_/-/./space/camelCase`）
- 凭据 key 下的布尔值或 null 保留（避免误遮蔽合法配置）

**借鉴点**：key name 词素分词策略；凭据 key 下布尔值/null 保留；32KB 截断上限。

**证据等级**：A（官方文档）

---

### 3.3 LangSmith (LangChain)

**来源**：[Prevent logging of sensitive data in traces](https://docs.langchain.com/langsmith/mask-inputs-outputs)  
**访问日期**：2026-10-05

**关键发现**：
- `create_anonymizer()`：正则规则列表 + 替换值；或自定义函数
- JSON 遍历深度限制：默认 10 层（`max_depth` 参数可配置）
- 第三方 PII 检测集成：Microsoft Presidio（本地）、AWS Comprehend（云端）

**借鉴点**：深度限制防 CPU 爆炸；自定义函数扩展点；Presidio/Comprehend 集成。

**证据等级**：A（官方文档）

---

### 3.4 DeepSeek Harness

**来源**：[Data and Privacy | DeepSeek Harness](https://deepseekdocs.com/en/docs/user-guide/privacy)  
**访问日期**：2026-10-05

**关键发现**：
- 三级内容捕获：FULL / FEEDBACK_ONLY / DISABLED
- 无内置脱敏规则——`session-telemetry/record` 扩展点需部署者自挂规则
- 社区版 `dsh-telemetry-redactor` 插件：递归深度上限 64 层；仅处理出站副本，不改写规范会话日志

**借鉴点**：插件化扩展点；递归深度上限（64 层）；出站副本 vs 规范日志分离。

**证据等级**：A（官方文档/开源代码）

---

### 3.5 Microsoft Azure Foundry

**来源**：[PII Filter - Microsoft Foundry](https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/content-filter-personal-information)  
**访问日期**：2026-10-05

**关键发现**：
- PII 分类细化：个人身份信息、金融信息、政府 ID、Azure 相关、地理定位
- 双模式：`Annotate`（标注）/ `Annotate and Block`（阻断）
- 专用隔离表 `AppGenAIContent` + RBAC 特权读取

**借鉴点**：PII 分类细化；专用隔离表 + RBAC（超越字段级脱敏）；双模式适合强合规场景。

**证据等级**：A（官方文档）

---

### 3.6 Grafana Alloy / OpenTelemetry Collector

**来源**：[otelcol.processor.redaction | Grafana Alloy](https://grafana.com/docs/alloy/latest/reference/components/otelcol/otelcol.processor.redaction/)  
**访问日期**：2026-10-05

**关键发现**：
- URL Sanitizer：移除 URL 属性中的 UUID、时间戳等高基数片段
- `disable_high_cardinality_metrics` 特征门控
- Top-K 摘要：`otelcol-genai-sketches` 将 GenAI traces 转为有界 Prometheus 度量 + keyed Top-K 摘要
- `__overflow__` 兜底策略（不静默丢弃，不创建新标签值）

**借鉴点**：URL Sanitizer 双重作用（脱敏 + 降基数）；`__overflow__` 兜底；Top-K 摘要。

**证据等级**：A（官方文档）

---

### 3.7 API7 AISIX / Safeguard AI Gateway

**来源**：[PII Detection and Redaction | AISIX](https://docs.api7.ai/ai-gateway/traffic-controls/guardrails/pii)  
**访问日期**：2026-10-05

**关键发现**：
- PII Guardrail：`mask`（替换为令牌）/ `block`（拒绝 HTTP 422）
- 内部运行（不调用外部审核服务）
- `fail_open` 配置：默认 `false`（Fail-Closed）；无法扫描的内容拒绝（`unscannable_body`）
- 缓冲流式输出以支持跨 chunk 边界遮蔽

**借鉴点**：`fail_open` vs `fail_close` 双模式；内部 PII 检测；流式缓冲；Guardrail 事件元数据化。

**证据等级**：A（官方文档）

---

## 4. 敏感信息分类与分级

### 4.1 敏感信息分类（五大类）

| 分类 | 子类 | 示例 | 检测方法 |
|------|------|------|----------|
| **凭据（Credentials）** | API Key、Token、Password、SSH Key、OAuth Secret | `sk-...`、`Bearer ...`、`Basic ...`、PEM blocks | 模式匹配 + Key Name 检测 |
| **个人身份信息（PII）** | Email、Phone、SSN、驾照号码、护照号码、IP Address | `user@example.com`、`(555) 123-4567`、`123-45-6789` | 正则 + PII 检测器 |
| **金融信息（Financial）** | 信用卡号、银行账号、SWIFT Code、IBAN | `4111 1111 1111 1111`（Luhn 验证） | Luhn 算法 + 模式匹配 |
| **政府 ID（Government ID）** | SSN（US）、National ID（50+ 国家）、Tax ID | 各国格式 | 国家特定模式 |
| **商业数据（Business）** | 内部系统 ID、客户代码、订单号 | 组织自定义 | 自定义规则 |

### 4.2 敏感度分级（四层）

复用 `REQ-OBS-002` 的 `Evidence.sensitivity_level`：

| 级别 | 说明 | 脱敏策略 | 示例 |
|------|------|----------|------|
| **PUBLIC** | 公开数据 | 无需脱敏 | 模型名称、任务类型 |
| **INTERNAL** | 内部数据 | 移除凭据和 PII | 工具调用次数、Token 使用量 |
| **CONFIDENTIAL** | 机密数据 | 移除所有敏感信息 + 高基数维度 | Prompt 内容、工具参数 |
| **RESTRICTED** | 受限数据 | 拒绝内容捕获（除非调试模式且已审批） | 生产环境客户数据 |

---

## 5. 脱敏规则定义

### 5.1 RedactionRule 数据模型

```yaml
RedactionRule:
  rule_id: string                    # 规则唯一标识（如 "api_key_redaction"）
  name: string                      # 规则名称（如 "API Key Redaction"）
  priority: int                     # 优先级（数字越小越先执行，默认 100）
  scope: enum                       # LLM_INPUT / LLM_OUTPUT / TOOL_INPUT / TOOL_OUTPUT / LOG / METRIC / ALL
  target_fields: string[]            # 目标字段路径（如 ["gen_ai.prompt", "gen_ai.completion"]）
  detector: RedactionDetector       # 检测器定义
  action: enum                      # MASK / HASH / DROP / BLOCK
  replacement_token: string          # 掩码令牌（如 "[REDACTED:API_KEY]"）
  fail_mode: enum                   # FAIL_OPEN / FAIL_CLOSE
  enabled: boolean                  # 是否启用
  organization_overrides: map[string, boolean]  # 组织级覆盖

RedactionDetector:
  type: enum                        # PATTERN / KEY_NAME / PII_CATEGORY / CUSTOM
  patterns: PatternRule[]           # 正则规则
  key_words: string[]               # 凭据 key 词列表
  pii_categories: PIICategory[]     # PII 类别
  custom_detector: string           # 自定义检测器名称（引用已注册检测器）

PatternRule:
  regex: string                     # 正则表达式（RE2 语法）
  flags: string                     # 正则标志（i: 忽略大小写）
  timeout_ms: int                   # 超时（防 ReDoS，默认 100ms）
```

### 5.2 预置规则示例

```yaml
# 规则 1：API Key 脱敏
- rule_id: api_key_redaction
  name: API Key Redaction
  priority: 10
  scope: ALL
  target_fields: ["*"]  # 匹配所有字段
  detector:
    type: PATTERN
    patterns:
      - regex: '\bsk-[a-zA-Z0-9]{48}\b'
        flags: ""
        timeout_ms: 100
      - regex: '\bBearer\s+[a-zA-Z0-9\-._~+/]+=*'
        flags: "i"
        timeout_ms: 100
  action: MASK
  replacement_token: "[REDACTED:API_KEY]"
  fail_mode: FAIL_CLOSE
  enabled: true

# 规则 2：Email 脱敏
- rule_id: email_redaction
  name: Email Redaction
  priority: 20
  scope: ALL
  target_fields: ["*"]
  detector:
    type: PII_CATEGORY
    pii_categories: [EMAIL]
  action: MASK
  replacement_token: "[REDACTED:EMAIL]"
  fail_mode: FAIL_CLOSE
  enabled: true

# 规则 3：凭据 Key Name 检测
- rule_id: credential_key_name
  name: Credential Key Name Detection
  priority: 15
  scope: ALL
  target_fields: ["*"]
  detector:
    type: KEY_NAME
    key_words:
      - password
      - token
      - api_key
      - secret
      - credential
      - auth
      - apikey
      - accesstoken
      - privatekey
  action: MASK
  replacement_token: "[REDACTED:CREDENTIAL]"
  fail_mode: FAIL_CLOSE
  enabled: true

# 规则 4：信用卡号脱敏
- rule_id: credit_card_redaction
  name: Credit Card Redaction
  priority: 5  # 高优先级
  scope: ALL
  target_fields: ["*"]
  detector:
    type: PII_CATEGORY
    pii_categories: [CREDIT_CARD]
  action: BLOCK  # 信用卡号直接阻断
  fail_mode: FAIL_CLOSE
  enabled: true
```

---

## 6. 脱敏处理流程

### 6.1 采集端脱敏流程

```
输入：raw_telemetry（原始遥测数据）、content_capture_mode、org_config
输出：redacted_telemetry（脱敏后数据）、redaction_audit（审计记录）

步骤 1：模式检查
  if content_capture_mode == DISABLED:
    return {metadata_only, audit: {action: MODE_DISABLED}}
  if content_capture_mode == FEEDBACK_ONLY:
    仅保留评分结果、失败归因等元数据，跳过内容捕获

步骤 2：证据敏感度评估（复用 REQ-OBS-002）
  PUBLIC → 无需脱敏
  INTERNAL → 移除凭据和 PII
  CONFIDENTIAL → 移除所有敏感信息 + 高基数维度
  RESTRICTED → 拒绝内容捕获（除非调试模式且已审批）

步骤 3：字段路径匹配
  遍历 target_fields，对匹配字段应用规则

步骤 4：规则执行（按 priority 升序）
  for each rule in sorted_rules:
    检测器执行：
      PATTERN → 正则匹配
      KEY_NAME → key 词素分词匹配
      PII_CATEGORY → 预定义 PII 检测器
      CUSTOM → 调用已注册自定义检测器
    动作执行：
      MASK → 替换为 replacement_token
      HASH → HMAC-SHA256 哈希
      DROP → 删除整个字段
      BLOCK → 拒绝整个记录
    记录匹配次数和规则 ID

步骤 5：递归深度检查
  JSON 遍历深度上限：MAX_RECURSION_DEPTH = 32
  超出上限：记录 overflow，截断处理

步骤 6：流式输出缓冲（仅 LLM output streaming）
  缓冲直到流结束或达到 MAX_BUFFER_BYTES（默认 1MB）
  跨 chunk 边界模式匹配

步骤 7：审计记录生成
  ObsRedactionAuditEvent:
    trace_id, span_id, event_id
    rules_applied: string[]
    matches_count: int
    fields_redacted: int
    action: REDACTED / BLOCKED / FAILED
    fail_reason: string (if action == FAILED)
    content_capture_mode
    timestamp

步骤 8：脱敏统计指标发射
  gen_ai.obs.redaction.total{scope, rule_id, action}
  gen_ai.obs.redaction.matches_total{scope, rule_id, pii_category}
  gen_ai.obs.redaction.failed_total{scope, fail_reason}

返回：redacted_telemetry
```

### 6.2 OTel Collector 端脱敏（补充保护）

```
输入：otlp_spans_logs_metrics、collector_config
输出：sanitized_output

步骤 1：allowed_keys 白名单过滤（Fail-Closed）
  不在白名单的属性先删除

步骤 2：blocked_values 正则匹配
  匹配的值替换为 [REDACTED]

步骤 3：URL Sanitizer
  移除 http.url / url 中的 UUID、时间戳
  自动 Sanitize 含 "/" 的 Span 名称

步骤 4：Database Sanitizer
  仅对 db.system 属性生效
  移除 SQL 参数中的高基数值

步骤 5：溢出检测
  活跃序列数监控
  超限告警
  __overflow__ 兜底

步骤 6：导出前最终检查
  再次扫描敏感模式
```

---

## 7. Key Name 词素分词脱敏算法

借鉴 Cursor Enterprise 实践：

```
输入：key_name (string), key_words (string[])
输出：is_credential_key (boolean)

步骤 1：Tokenize key_name
  按 _ / - / . / 空格 / camelCase 分隔
  返回 tokens: string[]

步骤 2：Exact Match
  tokens ∩ key_words 非空？→ 返回 true

步骤 3：Qualifier Rule
  如果 key_name 以 qualifier (api/access/secret/private/account) 结尾
  且 token 包含 key_word → true

步骤 4：Metadata Exclusion
  如果 token 以 "_count" / "_type" / "_id" / "_url" 结尾
  且 token 不含 key_word → false（保留统计类字段）

步骤 5：Bare Key Rule
  如果 key_name == "key":
    value 形似 minted token → true
    value 形如 issue key → false

步骤 6：Boolean/Null Exclusion
  如果 value 是布尔值或 null
  且 key 在凭据 key 列表中 → false（不遮蔽合法配置值）
```

**示例**：

| key_name | key_words 命中 | is_credential_key | 原因 |
|----------|---------------|------------------|------|
| `api_key` | `[key]` | ✅ true | Exact Match |
| `x-api-key` | `[key]` | ✅ true | Tokenize → `[x, api, key]` |
| `token_count` | `[token]` | ❌ false | Metadata Exclusion（`_count` 后缀） |
| `access_token` | `[token]` | ✅ true | Qualifier Rule（`access` 前缀） |
| `issue_key` | `[key]` | ❌ false（值依赖） | Bare Key Rule（需检查值形态） |
| `auth_enabled` | `[auth]` | ❌ false | Boolean 值，保留配置 |

---

## 8. 高基数控制策略

### 8.1 CardinalityControlConfig 数据模型

```yaml
CardinalityControlConfig:
  enabled: boolean                          # 是否启用（默认 true）
  max_cardinality_per_metric: int           # 单指标最大基数（默认 10,000）
  allowed_label_keys: string[]              # 允许作为标签的 key 白名单
  forbidden_label_keys: string[]            # 禁止作为标签的 key 黑名单（优先级高于白名单）
  url_sanitizer_enabled: boolean            # URL Sanitizer 启用（默认 true）
  overflow_bucket: string                   # 溢出值兜底（默认 "__overflow__"）
  estimation_method: enum                   # EXACT / HYPERLOGLOG
```

### 8.2 禁止标签黑名单（预置）

以下维度**禁止**作为 Metric 标签：

| 黑名单字段 | 理由 | 预估基数 |
|-----------|------|----------|
| `trace_id` | UUID，唯一性高 | 无上限 |
| `span_id` | UUID，唯一性高 | 无上限 |
| `request_id` | UUID，唯一性高 | 无上限 |
| `session_id` | UUID，唯一性高 | 无上限 |
| `user_id` | 用户数量 | 10,000 - 1,000,000+ |
| `task_id` | 任务数量 | 100,000+ |
| `workflow_id` | 工作流实例数 | 100,000+ |
| `raw_url` | URL 路径变体 | 无上限 |
| `exception_message` | 错误消息文本 | 无上限 |
| `prompt` | Prompt 文本 | 无上限 |
| `completion` | Completion 文本 | 无上限 |

### 8.3 允许标签白名单（预置）

以下维度**允许**作为 Metric 标签：

| 白名单字段 | 基数 | 说明 |
|-----------|------|------|
| `organization_id` | 低（< 100） | 组织数量有限 |
| `project_id` | 中（100 - 1,000） | 每组织项目数有限 |
| `model` | 低（< 50） | 模型种类有限 |
| `provider` | 低（< 10） | 供应商数量有限 |
| `tool_name` | 中（50 - 500） | 工具种类有限 |
| `tool_kind` | 低（< 5） | builtin / mcp / custom |
| `worker_type` | 低（< 10） | planner / coder / tester 等 |
| `status` | 低（< 10） | success / failure / timeout 等 |
| `risk_level` | 低（< 5） | low / medium / high / critical |
| `token_type` | 低（< 5） | input / output / cache_read 等 |
| `error_category` | 中（10 - 50） | 错误分类枚举 |

### 8.4 高基数检测算法

```
输入：dimensions (string[]), cardinality_config
输出：valid_dimensions (string[]), warnings (string[])

步骤 1：黑名单过滤（最高优先级）
  candidate = dimensions - forbidden_label_keys
  removed = dimensions ∩ forbidden_label_keys

步骤 2：白名单检查
  candidate = candidate ∩ allowed_label_keys

步骤 3：基数估算
  for each dim in candidate:
    cardinality = estimate_dimension_cardinality(dim)
    if cardinality > max_cardinality_per_metric:
      warnings.append(dim)
      candidate.remove(dim)

步骤 4：溢出告警
  for each warning in warnings:
    emit ObsHighCardinalityAlert{
      dimension: warning,
      estimated_cardinality: cardinality,
      action: OVERFLOW_BUCKET
    }

返回：valid_dimensions, warnings
```

### 8.5 URL Sanitizer

```
输入：url (string)
输出：sanitized_url (string)

移除模式：
- UUID: [0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}
- Timestamp: \d{10,13}
- 数字 ID: /\d+/

示例：
  原始：GET /users/550e8400-e29b-41d4-a716-446655440000/orders/1234567890
  净化：GET /users/{uuid}/orders/{id}
```

---

## 9. 调试模式（临时 Full 模式）

### 9.1 触发条件

- 用户显式请求 + 组织管理员审批
- 有效期不超过 24 小时
- 限定特定 Task ID

### 9.2 执行流程

```
步骤 1：用户在 Task 详情页点击"启用调试模式"

步骤 2：系统创建 DebugModeRequest
  user_id: 请求人
  task_id: 目标任务
  reason: 调试原因
  requested_at: 时间戳

步骤 3：发送至组织管理员审批队列

步骤 4：管理员审批通过
  更新 Task.debug_mode_enabled = true
  设置 Task.debug_mode_expires_at = now + 24h

步骤 5：Agent Runtime 在采集端检查 Task.debug_mode_enabled
  如果为 true：跳过脱敏（保留原始内容）

步骤 6：生成 DebugModeAuditEvent
  user_id, task_id, reason, approved_by, duration, expires_at

步骤 7：24 小时后自动失效，或管理员可手动撤销
```

### 9.3 审计要求

- 调试模式启用/禁用必须记录到审计日志
- 调试模式下的 Trace 标记特殊标签 `debug_session=true`
- 调试数据留存期：7 天后自动删除

---

## 10. 异常与失败处理

| 异常场景 | 检测方法 | 动作 | 恢复策略 |
|----------|----------|------|----------|
| **脱敏规则执行失败** | try-catch + timeout (100ms) | FAIL_CLOSE：跳过该字段，记录 `rejected_fields` | 不阻塞 Agent 执行；记录失败事件 |
| **无法扫描的内容格式**（非 UTF-8） | encoding 检测 | FAIL_CLOSE：拒绝内容捕获，返回错误 | 发送 `unscannable_body` 错误码 |
| **递归深度超限** | 深度计数器 > 32 | 截断并记录 `recursion_overflow` | 不阻塞执行；记录溢出标记 |
| **脱敏规则配置无效** | Schema 验证 | 回退到默认规则；记录配置错误 | 通知管理员检查配置 |
| **HMAC 密钥不可用** | key lookup 失败 | FAIL_OPEN：跳过哈希，保留原值（带警告标记） | 立即告警 key_missing；人工介入 |
| **高基数超限** | 基数预计算 | 替换为 `__overflow__`；发出告警 | 持续监控；评估是否需要调整阈值 |
| **脱敏后内容仍含敏感模式** | 后置扫描（可选） | FAIL_CLOSE：拒绝该条记录 | 通知安全团队分析新模式 |
| **流式输出缓冲超限**（> 1MB） | 缓冲区大小检测 | 截断流；记录 `stream_truncated` | 发送警告；评估是否需要扩大缓冲区 |

---

## 11. 验收标准

### 11.1 功能性验收

| # | 验收项 | 验证方法 |
|---|--------|----------|
| AC-1 | 凭据值（API Key、Token、Password）不出现在任何遥测字段中 | 安全测试：搜索敏感字符串模式 |
| AC-2 | PII（Email、Phone、SSN、Credit Card）不出现在遥测后端 | 安全测试：正则匹配常见 PII 模式 |
| AC-3 | JSON 嵌套深度超 32 层时截断处理 | 单元测试：构造超深嵌套 JSON |
| AC-4 | 流式输出跨 chunk 边界脱敏正确 | 集成测试：模拟 streaming 场景 |
| AC-5 | 脱敏失败时按 fail_mode 执行（Close/Open） | 故障注入测试：模拟检测器异常 |
| AC-6 | 调试模式需管理员审批，记录审计日志 | 集成测试：模拟调试模式请求流程 |
| AC-7 | 高基数维度被替换为 `__overflow__` | 压力测试：构造高基数标签 |
| AC-8 | 脱敏规则按 priority 顺序执行 | 单元测试：验证执行顺序 |
| AC-9 | 组织级规则覆盖生效 | 集成测试：配置不同组织的规则 |
| AC-10 | 脱敏统计指标正确发射 | 单元测试：验证指标值 |
| AC-11 | 内容截断上限 32KB 生效 | 单元测试：构造 > 32KB 内容 |
| AC-12 | HMAC 哈希相同 scope+value 产生相同结果 | 单元测试：验证哈希一致性 |
| AC-13 | URL Sanitizer 移除高基数片段 | 单元测试：构造含 UUID 的 URL |
| AC-14 | 非 UTF-8 内容拒绝捕获（fail_close） | 故障注入测试：注入二进制数据 |
| AC-15 | 脱敏规则版本管理可用 | 集成测试：创建、更新、发布规则 |

### 11.2 合规性验收

| # | 验收项 | 验证方法 |
|---|--------|----------|
| CO-1 | 调试模式启用后 24 小时自动失效 | 时间推进测试 |
| CO-2 | 脱敏变更记录到审计日志（不可篡改） | 合规测试：尝试修改历史记录 |
| CO-3 | HMAC 密钥定期轮换（可配置） | 配置测试：验证密钥轮换逻辑 |
| CO-4 | 调试数据 7 天后自动删除 | 数据生命周期测试 |

---

## 12. 依赖与跨模块边界

### 12.1 前置依赖

| 需求编号 | 依赖内容 | 集成方式 |
|----------|----------|----------|
| `REQ-RT-001` | 核心实体（TaskId、TraceId、SpanId） | 脱敏上下文 |
| `REQ-RT-006` | Trace 传播和审计关联 | 审计事件关联 |
| `REQ-OBS-001` | 内容捕获策略（DISABLED/FEEDBACK_ONLY/FULL） | 脱敏模式判断 |
| `REQ-OBS-002` | Evidence.sensitivity_level | 敏感度分级脱敏 |
| `REQ-OBS-003` | 指标维度定义、高基数控制算法 | 维度白名单/黑名单 |
| `REQ-SEC-008` | 多租户隔离、数据驻留 | 组织级配置隔离 |

### 12.2 下游依赖

| 需求编号 | 本设计提供 | 集成方式 |
|----------|-----------|----------|
| `REQ-OBS-005` | 告警规则引用 `obs.redaction.failure.total` 等指标 | 告警条件 |
| `REQ-OBS-006` | 审计查询 API 返回脱敏状态 | 查询字段 |
| `REQ-OBS-007` | 留存完整性涉及脱敏后证据 | 证据哈希 |

---

## 13. 版本与变更记录

### 13.1 当前状态

`REQ-OBS-004` 当前版本为 `v0.1-designed`：本专项详细设计已完成，待与 Runtime Contract、安全、审计查询专项交叉评审后冻结。设计完成不代表已实现或运行指标已经验证。

### 13.2 冻结条件

1. 与 `REQ-RT-001/006` 完成实体、Trace 传播交叉评审
2. 与 `REQ-OBS-001/002/003` 对齐内容捕获、Evidence Schema、指标体系
3. 与 `REQ-SEC-008` 完成多租户隔离、数据驻留评审
4. 完成脱敏规则、高基数控制契约测试设计
5. 用代表性 Agent 运行验证脱敏覆盖率、高基数控制效果

### 13.3 变更记录

| 版本 | 日期 | 变更 |
|------|------|------|
| `v0.1-designed` | 2026-10-05 | 基于 OpenTelemetry、Cursor、LangSmith、DeepSeek、Azure Foundry、Grafana、AISIX 等 8 家标杆公开资料，完成四层敏感度分级、Key Name 词素分词脱敏、32 层递归上限、调试模式审批流、高基数黑名单/白名单、URL Sanitizer、15 项功能验收 + 4 项合规验收设计 |

---

**文档维护**：架构组  
**最后更新**：2026-10-05
