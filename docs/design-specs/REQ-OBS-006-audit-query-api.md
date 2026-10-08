# REQ-OBS-006 审计查询 API 详细设计

> 所属基线：`Observability Baseline v0.1`  
> 需求编号：`REQ-OBS-006`  
> 优先级：P0  
> 设计版本：`v0.1-designed`  
> 设计状态：详细设计已完成，待跨模块冻结  
> 前置依赖：`REQ-RT-006`、`REQ-SEC-008`、`REQ-OBS-002`  
> 关键决策：分层审计架构；多维过滤矩阵；游标分页；异步导出；90 天查询窗口；租户隔离

---

## 1. 需求定义

### 1.1 目标

为 AI Agent 平台提供标准化、可审计、高性能、多租户隔离的审计日志查询接口，支持安全审计、合规报告、故障排查和运营分析。确保审计日志的可追溯性、完整性和安全性。

### 1.2 用户价值

- **安全审计员**：可追溯所有关键操作（Task 创建、权限变更、工具执行、审批决策等），调查安全事件
- **合规人员**：生成符合法规要求的审计报告（ISO 27001、SOC 2、GDPR），满足审计需求
- **平台运营**：分析使用模式、检测异常行为、优化运营策略
- **SRE**：关联 Trace ID 进行故障排查，分析系统行为
- **AI 研究员**：分析 Agent 执行模式、评估工具使用效率

### 1.3 范围

**包含**：
- 审计日志查询 API（RESTful）
- 多维度过滤（EventType、时间范围、用户、组织、项目、仓库、Trace ID 等）
- 游标分页和排序
- 导出功能（CSV、JSON）
- 权限控制和租户隔离
- 分层存储查询（热/温/冷）
- 查询性能优化和成本控制

**不包含**：
- 审计日志写入机制（由 `REQ-RT-006` 和 `REQ-OBS-002` 定义）
- 审计日志留存和完整性机制（由 `REQ-OBS-007` 定义）
- 实时告警和监控（由 `REQ-OBS-005` 定义）
- SIEM 集成（放入 V2）

---

## 2. 共享契约与术语

本设计复用 `REQ-RT-006` 定义的审计关联规则、`REQ-SEC-008` 定义的租户隔离模型、`REQ-OBS-002` 定义的 Event Schema（44 种 EventType）。

### 2.1 核心术语

| 术语 | 定义 |
|------|------|
| **审计日志** | 对身份、授权、审批、执行结果及重要安全操作的结构化责任记录 |
| **EventType** | 审计事件类型枚举，覆盖 Agent 全生命周期（44 种） |
| **游标分页** | 使用 Opaque token 标记分页位置，防止深分页和游标篡改 |
| **分层存储** | 热存储（30 天）、温存储（180 天）、冷存储（7 年） |
| **租户隔离** | Organization 和 Team 两级隔离，防止跨租户数据泄露 |
| **导出** | 将审计日志导出为 CSV 或 JSON 格式，支持长期留存 |

---

## 3. 行业调研与可借鉴原则

### 3.1 OpenAI Audit Logs API

**来源**：[OpenAI Audit Logs API](https://developers.openai.com/api/reference/resources/organization/subresources/audit_logs/)  
**访问日期**：2026-10-05

**关键发现**：
- `GET /organization/audit_logs` 支持 `event_types[]` 过滤（140+ 种事件类型）
- 游标分页（`after` 参数）
- 审计日志与 API 请求内容分离，仅记录管理/配置事件
- 只记录组织级管理操作，不记录 API 请求内容

**借鉴点**：事件类型枚举驱动；游标分页避免深分页；审计与遥测分离。

**证据等级**：A（官方文档）

---

### 3.2 Anthropic Claude Compliance Activity Feed

**来源**：[Anthropic Compliance API](https://docs.anthropic.com/en/api/compliance)  
**访问日期**：2026-10-05

**关键发现**：
- `GET /v1/compliance/activities` 支持多维度过滤
- 参数：`activity_types[]`、`actor_ids[]`、`organization_ids[]`、`created_at.gte/lte`、`exclude_activity_types[]`
- 游标分页（`after_id`）
- 保留 6 年
- 返回格式：OCSF v1.7 API Activity Schema (Class UID 6003)

**借鉴点**：OCSF 标准格式便于 SIEM 集成；包含/排除双向过滤；组织级多租户查询；长期保留（6 年）。

**证据等级**：A（官方文档）

---

### 3.3 Microsoft Purview / Security Copilot

**来源**：[Microsoft Graph Audit Log API](https://learn.microsoft.com/en-us/graph/api/security-auditcoreroot-post-auditlogqueries)  
**访问日期**：2026-10-05

**关键发现**：
- 异步查询模式：`POST /security/auditLog/queries`（创建查询）→ `GET /security/auditLog/queries/{id}`（获取结果）
- 查询参数：`filterStartDateTime`、`filterEndDateTime`、`serviceFilter`、`operationFilters`、`userPrincipalNameFilters`、`ipAddressFilters`、`objectIdFilters`、`keywordFilter`
- 支持状态轮询：`status` = notStarted / running / succeeded / failed / cancelled
- 集成到 Microsoft 365 生态

**借鉴点**：异步查询模式适合大数据量；多维过滤矩阵；状态轮询机制。

**证据等级**：A（官方文档）

---

### 3.4 Cursor Enterprise Audit Logs

**来源**：[Cursor Compliance and Monitoring](https://prod.cursor.com/docs/enterprise/compliance-and-monitoring)  
**访问日期**：2026-10-05

**关键发现**：
- `GET /teams/audit-logs`（Team API Key）和 `GET /organizations/audit-logs`（Organization API Key）
- 查询参数：`startTime`、`endTime`、`eventTypes`、`users`、`page`、`pageSize`
- 查询窗口最大 30 天，每页最大 500 条
- 审计日志与 OpenTelemetry 遥测分离
- 事件类型：login、team_settings、api_key_*、role_* 等

**借鉴点**：团队级与组织级分层查询；简洁的分页参数设计；查询窗口限制。

**证据等级**：A（官方文档）

---

### 3.5 LangSmith / LangChain

**来源**：[LangSmith Query Traces API](https://docs.langchain.com/langsmith/smith-api/runs/query-traces)  
**访问日期**：2026-10-05

**关键发现**：
- 追踪查询：`POST /api/v2/traces/query`
- 参数：`project_id`、`min_start_time`、`page_size`、`selects[]`、`trace_filter`、`tree_filter`、`cursor`
- 支持字段投影（`selects`）
- 支持结构化过滤语言：`eq()`、`neq()`、`gt()`、`gte()`、`lt()`、`lte()`、`has()`、`search()`、`in()`
- 审计日志：`GET /api/v1/audit-logs`，返回 OCSF 格式

**借鉴点**：结构化过滤查询语言；字段投影减少响应大小；OCSF 标准格式。

**证据等级**：A（官方文档）

---

### 3.6 Dify Agent Observability

**来源**：[Dify Agent Logs API](https://github.com/langgenius/dify/blob/main/api/controllers/console/agent/roster.py)  
**访问日期**：2026-10-05

**关键发现**：
- `GET /agent/{agent_id}/logs`
- 查询参数：`page`、`limit`、`keyword`、`statuses[]`、`sources[]`、`sort_by`、`sort_order`、`start`、`end`
- 关键词搜索：query、answer、conversation name
- 状态过滤：success、failed、paused
- 来源过滤：`webapp:<app_id>` 或 `workflow:<app_id>:<workflow_id>:<node_id>`

**借鉴点**：来源维度的多层级过滤；关键词全文搜索；灵活的状态组合过滤。

**证据等级**：A（开源代码）

---

### 3.7 设计结论

采用分层审计架构，将合规审计日志（不可采样丢失）与可采样遥测数据分离。API 设计遵循以下原则：
1. **事件类型枚举驱动**：复用 REQ-OBS-002 定义的 44 种 EventType
2. **多维过滤矩阵**：支持 11+ 维度过滤（组织、项目、用户、EventType、时间范围等）
3. **游标分页 + HMAC 防篡改**：避免深分页性能问题和游标伪造
4. **异步导出**：支持大数据量导出而不阻塞 API
5. **租户隔离**：强制组织级/团队级隔离，防止跨租户数据泄露
6. **分层存储**：热/温/冷三层存储，不同 SLA
7. **防篡改**：哈希链 + HMAC 签名，满足合规要求

---

## 4. API 设计

### 4.1 查询审计日志 API

#### 4.1.1 请求

```
GET /api/v1/audit-logs
```

**查询参数**：

| 参数名 | 类型 | 必需 | 默认值 | 说明 |
|--------|------|------|--------|------|
| `organization_id` | string | 否 | JWT 提取 | 组织 ID，Organization Admin 可不指定 |
| `team_id` | string | 否 | - | 团队 ID，Organization Admin 可指定 |
| `project_id` | string | 否 | - | 项目 ID |
| `repository_id` | string | 否 | - | 仓库 ID |
| `user_id` | string | 否 | - | 操作者 ID |
| `task_id` | string | 否 | - | 任务 ID |
| `trace_id` | string | 否 | - | Trace ID |
| `event_types[]` | string[] | 否 | 全部 | EventType 枚举数组（44 种） |
| `exclude_event_types[]` | string[] | 否 | - | 排除的 EventType |
| `event_categories[]` | enum[] | 否 | 全部 | 事件分类（LIFECYCLE/WORKFLOW/WORKER/ACTION/TOOL/MODEL/PLAN/ERROR/SECURITY/HUMAN/EVIDENCE） |
| `severities[]` | enum[] | 否 | - | 严重级别（INFO/WARNING/ERROR/CRITICAL） |
| `source_services[]` | string[] | 否 | - | 事件来源服务 |
| `start_time` | datetime (ISO 8601 UTC) | 是 | - | 查询开始时间（包含） |
| `end_time` | datetime (ISO 8601 UTC) | 是 | - | 查询结束时间（包含） |
| `keyword` | string | 否 | - | 关键词搜索（脱敏后） |
| `sort_by` | enum | 否 | timestamp | 排序字段（timestamp/event_type/severity） |
| `sort_order` | enum | 否 | desc | 排序方向（asc/desc） |
| `cursor` | string | 否 | - | 游标分页 |
| `page_size` | int | 否 | 50 | 每页大小（最大 500） |
| `include_payload` | boolean | 否 | false | 是否包含 payload（需要额外权限） |

**示例请求**：

```http
GET /api/v1/audit-logs?organization_id=org_123&event_types[]=SECURITY_POLICY_DENIED&event_types[]=TASK_FAILED&start_time=2026-10-01T00:00:00Z&end_time=2026-10-05T23:59:59Z&page_size=100&sort_order=desc
Authorization: Bearer <jwt_token>
```

#### 4.1.2 响应

**成功响应（200 OK）**：

```json
{
  "data": [
    {
      "event_id": "evt_abc123",
      "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
      "span_id": "00f067aa0ba902b7",
      "event_type": "SECURITY_POLICY_DENIED",
      "event_name": "security.policy.denied",
      "event_category": "SECURITY",
      "timestamp": "2026-10-05T14:23:45.123Z",
      "organization_id": "org_123",
      "team_id": "team_456",
      "project_id": "proj_789",
      "user_id": "user_001",
      "task_id": "task_abc",
      "action_id": "action_xyz",
      "severity": "CRITICAL",
      "source_service": "policy-gateway",
      "source_component": "rbac-enforcer",
      "payload": {
        "policy_name": "high_risk_tool_restriction",
        "action_type": "TOOL_EXECUTE",
        "resource": "bash_command",
        "reason": "high_risk_tool_not_allowed"
      }
    }
  ],
  "pagination": {
    "cursor": "eyJsYXN0X3ZhbHVlIjoiMjAyNi0xMC0wNVQxNDoyMzo0NS4xMjNaIiwibGFzdF9pZCI6ImV2dF9hYmMxMjMiLCJzb3J0X2J5IjoidGltZXN0YW1wIiwic29ydF9vcmRlciI6ImRlc2MiLCJmaWx0ZXJzX2hhc2giOiJhYmNkMTIzNCJ9",
    "has_more": true,
    "total": 1523
  },
  "meta": {
    "query_id": "qry_def456",
    "executed_at": "2026-10-05T14:30:00.000Z",
    "elapsed_ms": 87,
    "storage_tier": "hot"
  }
}
```

**错误响应**：

| 错误码 | 错误消息 | 说明 |
|--------|---------|------|
| 400 | "查询窗口最大 90 天" | 时间范围超限 |
| 400 | "无效的分页游标，请重新查询" | 游标无效 |
| 403 | "需要 Organization Admin 或 Team Admin 权限" | 权限不足 |
| 413 | "查询结果超过 10,000 条限制，请缩小范围" | 数据量过大 |
| 504 | "查询超时，请尝试缩小范围或使用分页" | 查询超时 |

---

### 4.2 导出审计日志 API

#### 4.2.1 创建导出任务

```
POST /api/v1/audit-logs/exports
```

**请求体**：

```json
{
  "query": {
    "organization_id": "org_123",
    "team_id": "team_456",
    "event_types": ["SECURITY_POLICY_DENIED", "TASK_FAILED"],
    "start_time": "2026-10-01T00:00:00Z",
    "end_time": "2026-10-05T23:59:59Z"
  },
  "format": "csv",
  "compression": "gzip",
  "max_records": 100000,
  "email_notification": true
}
```

**响应（202 Accepted）**：

```json
{
  "export_id": "exp_ghi789",
  "status": "pending",
  "estimated_records": 1523,
  "estimated_completion_time": "2026-10-05T14:35:00.000Z",
  "created_at": "2026-10-05T14:30:00.000Z"
}
```

#### 4.2.2 查询导出状态

```
GET /api/v1/audit-logs/exports/{export_id}
```

**响应（200 OK）**：

```json
{
  "export_id": "exp_ghi789",
  "status": "completed",
  "download_url": "https://storage.example.com/exports/exp_ghi789.csv.gz?signature=...",
  "expires_at": "2026-10-06T14:30:00.000Z",
  "record_count": 1523,
  "file_size_bytes": 245678,
  "created_at": "2026-10-05T14:30:00.000Z",
  "completed_at": "2026-10-05T14:32:15.000Z"
}
```

---

## 5. 查询处理流程

### 5.1 查询流程

```
1. 请求接收
   ├─ 验证 JWT Token，提取 organization_id、user_id、roles
   ├─ 权限校验：user 必须是 Organization Admin 或 Team Admin
   ├─ 参数校验：时间范围、page_size、分页游标
   └─ 防注入：SQL 参数化、关键词脱敏

2. 租户隔离
   ├─ Organization Admin：可查询 organization_id 范围内的所有数据
   ├─ Team Admin：仅可查询 team_id 范围内的数据
   └─ 跨租户查询：返回空结果，不报错

3. 存储路由
   ├─ 热存储（< 30 天）：PostgreSQL，p95 < 100ms
   ├─ 温存储（30-180 天）：归档表，p95 < 500ms
   └─ 冷存储（> 180 天）：S3/Blob，异步查询

4. 查询执行
   ├─ 时间范围优先过滤（利用分区键）
   ├─ 按 event_type、severity、source_service 等维度过滤
   ├─ 租户隔离校验（team_id/organization_id）
   ├─ 关键词搜索（脱敏后，支持 ILIKE）
   └─ 排序（默认按 timestamp DESC）

5. 响应构建
   ├─ 字段投影（减少传输量）
   ├─ Payload 脱敏（按 REQ-OBS-004）
   ├─ 游标生成（Opaque token）
   └─ 元信息记录（query_id、elapsed_ms、storage_tier）

6. 结果返回
   └─ HTTP 200 + JSON 响应
```

### 5.2 导出流程

```
1. 导出请求接收
   ├─ 验证权限（Organization Admin）
   ├─ 参数校验（格式、大小限制）
   └─ 生成 export_id

2. 任务创建
   ├─ 估算记录数（不执行全量扫描）
   └─ 超过阈值时返回 413 Payload Too Large

3. 异步执行
   ├─ 分批查询（每批 10,000 条）
   ├─ 写入临时存储（S3/Blob）
   └─ 支持压缩（gzip）

4. 通知
   ├─ 完成后发送邮件（含下载链接）
   └─ 下载链接有效期：24 小时

5. 清理
   ├─ 7 天后自动删除临时文件
   └─ 记录导出审计日志
```

---

## 6. 游标分页算法

### 6.1 游标生成

```python
def generate_cursor(last_record, sort_by, sort_order, filters):
    """生成游标 token"""
    context = {
        "last_value": last_record[sort_by],  # 最后一条记录的排序字段值
        "last_id": last_record["event_id"],  # 最后一条记录的 ID
        "sort_by": sort_by,
        "sort_order": sort_order,
        "filters_hash": hashlib.md5(json.dumps(filters, sort_keys=True).encode()).hexdigest()
    }
    
    # 序列化为 JSON
    json_str = json.dumps(context)
    
    # HMAC 签名
    signature = hmac.new(SECRET_KEY, json_str.encode(), hashlib.sha256).hexdigest()
    
    # Base64 编码
    cursor = base64.urlsafe_b64encode(f"{json_str}|{signature}".encode()).decode()
    
    return cursor
```

### 6.2 游标验证

```python
def parse_cursor(cursor, current_filters):
    """解析并验证游标"""
    try:
        # Base64 解码
        decoded = base64.urlsafe_b64decode(cursor.encode()).decode()
        json_str, signature = decoded.rsplit('|', 1)
        
        # 验证 HMAC 签名
        expected_signature = hmac.new(SECRET_KEY, json_str.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected_signature):
            raise ValueError("Invalid cursor signature")
        
        # 解析 JSON
        context = json.loads(json_str)
        
        # 验证 filters_hash
        current_hash = hashlib.md5(json.dumps(current_filters, sort_keys=True).encode()).hexdigest()
        if context["filters_hash"] != current_hash:
            raise ValueError("Cursor filters mismatch")
        
        return context
    except Exception as e:
        raise ValueError(f"Invalid cursor: {e}")
```

---

## 7. 权限与安全控制

### 7.1 权限模型

| 角色 | 审计查询权限 | 审计导出权限 | Payload 访问权限 |
|------|-------------|-------------|----------------|
| **Organization Admin** | ✅ 全部 | ✅ 全部 | ✅ 全部 |
| **Team Admin** | ✅ 本团队 | ✅ 本团队 | ❌ 需额外审批 |
| **Security Auditor** | ✅ 只读 | ✅ 只读 | ✅ 全部 |
| **Platform Admin** | ✅ 全部 | ✅ 全部 | ✅ 全部 |
| **普通用户** | ❌ | ❌ | ❌ |

### 7.2 安全控制

1. **租户隔离**：所有查询强制包含 organization_id/team_id，跨租户查询返回空结果
2. **防注入**：SQL 参数化查询、关键词脱敏、正则表达式转义
3. **审计覆盖**：查询操作本身也要记录审计日志（包含 query_id、user_id、时间戳）
4. **速率限制**：每组织/每分钟最多 60 次查询请求，超出返回 429 Too Many Requests
5. **访问日志**：记录所有查询的 user_id、query_id、执行时间、返回记录数

### 7.3 防篡改机制

1. **哈希链**：每条审计记录包含前一条记录的哈希值，形成不可篡改链
2. **HMAC 签名**：游标使用 HMAC-SHA256 签名，防止客户端篡改
3. **Merkle Tree**：定期生成审计日志的 Merkle Tree 根哈希，用于完整性验证
4. **不可抵赖**：所有事件包含签名的 actor_id

---

## 8. 性能与成本优化

### 8.1 性能目标

| 指标 | 目标 | 条件 |
|------|------|------|
| 热存储查询延迟 | p95 < 100ms | 时间范围 ≤ 7 天，page_size ≤ 100 |
| 热存储查询延迟 | p95 < 500ms | 时间范围 ≤ 30 天，page_size ≤ 100 |
| 温存储查询延迟 | p95 < 2s | 时间范围 ≤ 180 天 |
| 冷存储查询延迟 | p95 < 60s | 异步模式 |
| 并发查询能力 | ≥ 100 QPS/组织 | - |
| 导出吞吐量 | ≥ 10,000 条/秒 | 异步导出 |

### 8.2 索引策略

**PostgreSQL 索引（热存储）**：

```sql
-- 主键索引
CREATE INDEX idx_events_pkey ON events(event_id);

-- 时间分区键索引
CREATE INDEX idx_events_timestamp ON events(timestamp DESC);

-- 租户隔离索引
CREATE INDEX idx_events_org_team_time ON events(organization_id, team_id, timestamp DESC);

-- EventType 过滤索引
CREATE INDEX idx_events_type_time ON events(event_type, timestamp DESC);

-- Trace 关联索引
CREATE INDEX idx_events_trace ON events(trace_id, timestamp DESC) WHERE trace_id IS NOT NULL;

-- 用户操作索引
CREATE INDEX idx_events_user_time ON events(user_id, timestamp DESC) WHERE user_id IS NOT NULL;

-- 复合索引（覆盖常见查询模式）
CREATE INDEX idx_events_org_type_sev_time ON events(organization_id, event_type, severity, timestamp DESC);
```

**分区策略**：

```sql
-- 按月分区（热存储）
CREATE TABLE events_2026_10 PARTITION OF events
  FOR VALUES FROM ('2026-10-01') TO ('2026-11-01');

-- 按季度分区（温存储）
CREATE TABLE events_archive_2026_q4 PARTITION OF events_archive
  FOR VALUES FROM ('2026-10-01') TO ('2027-01-01');
```

### 8.3 成本控制

| 资源 | 限制 | 说明 |
|------|------|------|
| 单次查询返回记录数 | ≤ 10,000 | 超出需分页 |
| 查询窗口 | ≤ 90 天 | 超出返回 400 |
| 单次导出记录数 | ≤ 100,000 | 超出需审批 |
| 导出文件大小 | ≤ 1 GB（压缩后） | 超出需分批 |
| 导出链接有效期 | 24 小时 | 自动过期 |
| 速率限制 | 60 请求/分钟/组织 | 超出返回 429 |

---

## 9. 异常与失败处理

### 9.1 错误场景与处理

| 场景 | 错误码 | 错误消息 | 处理策略 |
|------|--------|---------|---------|
| 时间范围超限 | 400 | "查询窗口最大 90 天" | 提示用户缩小范围 |
| 权限不足 | 403 | "需要 Organization Admin 或 Team Admin 权限" | 提示联系管理员 |
| 查询超时 | 504 | "查询超时，请尝试缩小范围或使用分页" | 建议缩小时间范围 |
| 冷存储查询超时 | 504 | "冷存储查询超时，查询时间 > 180 天的数据需要更长时间" | 建议缩小范围或等待 |
| 导出数据量过大 | 413 | "导出数据量超过 100,000 条限制，请缩小范围" | 提示分批导出 |
| 导出任务失败 | 500 | "导出任务失败，请重试" | 提供重试按钮 |
| 游标无效 | 400 | "无效的分页游标，请重新查询" | 提示刷新查询 |
| 速率限制 | 429 | "请求过于频繁，请稍后再试" | 提示等待 60 秒 |

### 9.2 降级策略

**冷存储查询降级**：

```
输入：查询请求（start_time > 180 天前）
输出：异步查询或拒绝

1. 估算查询复杂度：
   - 记录数 < 10,000：直接查询
   - 记录数 >= 10,000：异步查询

2. 异步查询模式：
   - 返回 query_id + status = "pending"
   - 客户端轮询或 WebSocket 通知

3. 超时处理：
   - 冷存储查询超时：60 秒
   - 超时后返回 504 Gateway Timeout
```

---

## 10. 可观测性与评估指标

### 10.1 API 层指标

| 指标名 | 定义 | 目标 | 告警阈值 |
|--------|------|------|---------|
| `audit.api.query.total` | 查询请求总数 | - | - |
| `audit.api.query.latency.p95` | 查询延迟 p95 | < 500ms | > 1s |
| `audit.api.query.error.rate` | 查询错误率 | < 0.1% | > 1% |
| `audit.api.export.total` | 导出请求总数 | - | - |
| `audit.api.export.duration` | 导出耗时分布 | p95 < 5min | > 30min |
| `audit.api.export.record_count` | 导出记录数分布 | - | > 100,000 |
| `audit.api.rate_limit.exceeded` | 速率限制超限次数 | < 10/day | > 100/day |

### 10.2 存储层指标

| 指标名 | 定义 | 目标 | 告警阈值 |
|--------|------|------|---------|
| `audit.storage.hot.query.latency` | 热存储查询延迟 | < 100ms | > 500ms |
| `audit.storage.warm.query.latency` | 温存储查询延迟 | < 2s | > 5s |
| `audit.storage.cold.query.latency` | 冷存储查询延迟 | < 60s | > 120s |
| `audit.storage.records.count` | 存储记录总数 | - | - |
| `audit.storage.size.bytes` | 存储大小 | - | 增长异常 |

### 10.3 业务层指标

| 指标名 | 定义 | 目标 | 告警阈值 |
|--------|------|------|---------|
| `audit.query.by_user.rate` | 每用户查询频率 | - | > 100/min |
| `audit.export.by_org.rate` | 每组织导出频率 | - | > 10/day |
| `audit.access.denied.rate` | 访问拒绝率 | < 0.1% | > 1% |
| `audit.cross_tenant.attempt` | 跨租户访问尝试次数 | 0 | > 0 |

---

## 11. 验收标准

| # | 验收项 | 验证方法 |
|---|--------|---------|
| 1 | Organization Admin 可查询本组织所有审计日志 | 集成测试：使用 Org Admin JWT 查询 |
| 2 | Team Admin 仅可查询本团队审计日志 | 集成测试：使用 Team Admin JWT 查询，跨团队返回空 |
| 3 | 普通用户无法访问审计查询 API | 集成测试：使用普通用户 JWT，返回 403 |
| 4 | 支持按 EventType 过滤 | 单元测试：查询 security.policy.denied |
| 5 | 支持按时间范围过滤 | 集成测试：查询 2026-10-01 ~ 2026-10-05 |
| 6 | 支持游标分页 | 集成测试：遍历所有页面 |
| 7 | 支持关键词搜索 | 集成测试：搜索脱敏后的关键词 |
| 8 | 热存储查询延迟 < 100ms (p95) | 性能测试：时间范围 ≤ 7 天 |
| 9 | 导出支持 CSV 和 JSON 格式 | 集成测试：触发导出并验证格式 |
| 10 | 导出链接 24 小时后过期 | 集成测试：验证过期时间 |
| 11 | 租户隔离：Team A 无法查询 Team B 数据 | 安全测试：跨租户查询 |
| 12 | 查询操作本身记录审计日志 | 集成测试：查询后验证审计日志 |
| 13 | 冷存储查询支持异步模式 | 集成测试：查询 > 180 天数据 |
| 14 | 查询窗口最大 90 天 | 集成测试：查询 91 天返回 400 |
| 15 | Payload 访问需要额外权限 | 集成测试：默认不包含 payload |
| 16 | 速率限制生效 | 集成测试：每分钟发送 61 次请求，返回 429 |
| 17 | 游标防篡改生效 | 安全测试：篡改游标返回 400 |
| 18 | Trace ID 关联查询 | 集成测试：通过 trace_id 查询关联事件 |

---

## 12. 依赖与跨模块边界

### 12.1 前置依赖

| 需求 | 依赖内容 | 边界 |
|------|---------|------|
| `REQ-RT-006` | Trace 传播和审计关联 | 审计事件与 Trace 关联规则 |
| `REQ-SEC-008` | 多租户与数据治理 | 租户隔离模型、organization_id/team_id |
| `REQ-OBS-002` | Trace/Event/Evidence Schema | Event 模型定义、44 种 EventType |
| `REQ-OBS-004` | 脱敏和高基数控制 | Payload 脱敏规则 |

### 12.2 下游依赖

| 需求 | 本设计提供的内容 | 边界 |
|------|---------------|------|
| `REQ-OBS-007` | 审计留存和完整性 | 查询 API 需适配留存策略 |
| `REQ-EVA-005` | 回归流水线 | 提供审计日志查询接口用于评估 |

---

## 13. 实现指导

### 13.1 推荐技术栈

**后端**：
- Python: Flask / FastAPI + SQLAlchemy
- Node.js: Express + TypeORM
- Go: Gin + GORM

**数据库**：
- PostgreSQL 15+ (热/温存储)
- S3 / Azure Blob (冷存储)

**缓存**：
- Redis (速率限制、游标缓存)

**异步任务**：
- Celery / RQ (导出任务)

### 13.2 实现检查清单

- [ ] 实现查询 API 端点 `GET /api/v1/audit-logs`
- [ ] 实现多维过滤逻辑（11+ 维度）
- [ ] 实现游标分页算法（生成 + 验证）
- [ ] 实现租户隔离校验
- [ ] 实现权限控制（Organization/Team Admin）
- [ ] 实现速率限制（Redis）
- [ ] 实现导出 API 端点 `POST /api/v1/audit-logs/exports`
- [ ] 实现异步导出任务（Celery）
- [ ] 实现冷存储查询降级策略
- [ ] 配置 PostgreSQL 索引和分区
- [ ] 编写单元测试和集成测试
- [ ] 编写 API 文档（OpenAPI/Swagger）

---

## 14. 版本与变更记录

### 14.1 当前状态

`REQ-OBS-006` 当前版本为 `v0.1-designed`：本专项详细设计已完成，待与 Runtime Contract、安全、审计留存专项交叉评审后冻结。设计完成不代表已实现或运行指标已经验证。

### 14.2 冻结条件

1. 与 `REQ-RT-006` 完成 Trace 传播、审计关联交叉评审
2. 与 `REQ-SEC-008` 完成租户隔离、区域钉扎交叉评审
3. 与 `REQ-OBS-002` 对齐 Event Schema、EventType 枚举
4. 与 `REQ-OBS-004/007` 确认脱敏、留存接口边界
5. 完成查询 API、导出 API、游标分页、租户隔离契约测试设计
6. 用代表性 Agent 运行验证查询性能、租户隔离和审计覆盖率

### 14.3 变更记录

| 版本 | 日期 | 变更 |
|------|------|------|
| `v0.1-designed` | 2026-10-05 | 基于 OpenAI、Anthropic Claude、Microsoft Purview、Cursor、LangSmith、Dify 公开资料，完成审计查询 API 设计；采样率、查询窗口、导出限制按用户确认收敛 |

---

**文档维护**：架构组  
**最后更新**：2026-10-05
