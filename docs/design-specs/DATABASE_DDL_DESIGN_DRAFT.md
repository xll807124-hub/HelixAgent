# 数据库 DDL 设计 - 实现设计阶段基线

> **设计版本**: v0.1-draft  
> **目标**: AI Agent 平台 PostgreSQL 核心表设计（Event Store / Projections / Checkpoint / RBAC / Audit）  
> **范围**: MVP 阶段必需的表结构  
> **状态**: 设计稿（伪代码形式），待 DBA 和架构团队评审后生成完整 SQL 脚本  
> **依赖**: REQ-RT-001/003/005/007、REQ-SEC-002/008、REQ-OBS-002/007、REQ-REL-004/006

---

## 核心表设计原则

1. **事件溯源为主线**：Event Store 是唯一真实源，所有 Projection 由事件计算得出
2. **不可变追踪**：Audit 和 Event Store 记录写入后不可修改（WORM 特性）
3. **严格分区**：按 `organization_id` / `tenant_id` 分区，禁止跨租户查询
4. **版本绑定**：Task/Workflow 的运行时版本与事件版本强关联
5. **无外键约束**（Event Store 层）：避免约束导致的性能问题；用应用层验证

---

## 表结构设计

### 1. 核心层 - Event Store（不可变）

#### 1.1 Events 表（事件存储）

```sql
CREATE TABLE IF NOT EXISTS events (
  -- 主键与分布
  event_id CHAR(26),                           -- UUIDv7，唯一主键
  organization_id VARCHAR(128),                -- 分区键
  task_id VARCHAR(128) NOT NULL,               -- 业务唯一键成分
  workflow_id VARCHAR(128),
  worker_id VARCHAR(128),
  action_id VARCHAR(128),
  attempt SMALLINT DEFAULT 1,

  -- 事件类型与版本
  event_type VARCHAR(64) NOT NULL,             -- 如 "TaskCreated", "ActionProposed"
  event_type_version VARCHAR(16),              -- 当前事件载荷版本，如 "v1.0"
  event_category VARCHAR(32),                  -- DOMAIN / LIFECYCLE / ACTION / CONTROL / OBSERVATION / AUDIT
  schema_version VARCHAR(16) DEFAULT 'runtime.event-envelope.v1',

  -- 追踪关联
  trace_id VARCHAR(32),
  span_id VARCHAR(32),
  parent_span_id VARCHAR(32),
  correlation_id VARCHAR(128),
  
  -- 版本与来源
  source_revision VARCHAR(128),                -- Git commit SHA / revision id
  base_revision VARCHAR(128),
  working_revision VARCHAR(128),
  policy_decision_id VARCHAR(128),
  idempotency_key VARCHAR(256),

  -- 行为者与生产者
  producer VARCHAR(32),                        -- USER / WORKER / TOOL / SYSTEM
  actor_type VARCHAR(32),                      -- user / agent / system
  actor_id VARCHAR(128),
  actor_email VARCHAR(256),
  
  -- 时间戳（事实 vs 写入）
  occurred_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,    -- 事实发生时间
  recorded_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,    -- 写入时间（系统时间）

  -- 载荷与脱敏
  payload_schema VARCHAR(256),                 -- 载荷描述符
  payload JSONB NOT NULL,                      -- 完整载荷（包含敏感字段）
  payload_redacted JSONB,                      -- 脱敏版载荷（供审计查询）
  redaction_rules VARCHAR(256),                -- 应用的脱敏规则版本

  -- 元数据
  source_system VARCHAR(64),                   -- MCP 连接器、Git 平台等
  severity VARCHAR(16) DEFAULT 'INFO',         -- 用于告警聚合
  tags JSONB DEFAULT '{}',                     -- 灵活标签

  PRIMARY KEY (event_id)
) PARTITION BY LIST (organization_id);

-- 创建首个默认分区
CREATE TABLE events_org_default PARTITION OF events
  FOR VALUES IN ('_system');

-- 索引（用于查询加速）
CREATE INDEX idx_events_task_id ON events (organization_id, task_id, recorded_at DESC);
CREATE INDEX idx_events_workflow_id ON events (organization_id, workflow_id, recorded_at DESC);
CREATE INDEX idx_events_idempotency ON events (organization_id, idempotency_key, recorded_at DESC);
CREATE INDEX idx_events_trace_id ON events (trace_id) WHERE trace_id IS NOT NULL;
CREATE INDEX idx_events_occurred_at ON events (organization_id, occurred_at DESC);
CREATE INDEX idx_events_type ON events (organization_id, event_type, recorded_at DESC);

-- Event Store 不允许 UPDATE / DELETE（仅 APPEND）
ALTER TABLE events ENABLE ROW LEVEL SECURITY;
CREATE POLICY events_insert_only ON events 
  FOR ALL USING (FALSE) WITH CHECK (TRUE);  -- 仅允许 INSERT
```

**说明**：
- `event_id` 使用 UUIDv7 确保时间单调性和全局唯一
- `payload` 存 JSONB 以支持灵活的载荷结构变化
- `occurred_at` vs `recorded_at` 用于追踪延迟
- 分区策略按 `organization_id` 避免跨租户混淆
- 索引设计优先满足常见查询（task / workflow / idempotency 追踪）

---

### 2. 投影层 - Read Models（物化视图）

#### 2.1 Task 投影表

```sql
CREATE TABLE IF NOT EXISTS task_projections (
  organization_id VARCHAR(128),
  task_id VARCHAR(128),
  version BIGINT,                              -- 从第 N 个事件计算得出

  -- 核心属性
  title VARCHAR(512),
  description TEXT,
  issue_url VARCHAR(512),
  status VARCHAR(32),                          -- CREATED / AUTHORIZING / ... / COMPLETED
  status_at TIMESTAMP(6) WITH TIME ZONE,

  -- 实体关联
  workflow_id VARCHAR(128),
  primary_worker_id VARCHAR(128),
  created_by_user_id VARCHAR(128),
  organization VARCHAR(128),
  project VARCHAR(128),
  repository VARCHAR(128),

  -- 预算与约束
  estimated_cost_dollars NUMERIC(10, 2),
  actual_cost_dollars NUMERIC(10, 2),
  estimated_duration_seconds BIGINT,
  actual_duration_seconds BIGINT,
  max_iterations SMALLINT,
  current_iterations SMALLINT,

  -- 权限与决策
  policy_decision_id VARCHAR(128),
  required_approvals JSONB,                    -- [{approver_id, status}]
  approval_status VARCHAR(32),                 -- PENDING / APPROVED / REJECTED

  -- 源代码版本
  source_revision VARCHAR(128),                -- 当前基准 commit
  working_revision VARCHAR(128),               -- 当前工作分支

  -- 指标
  artifact_count SMALLINT DEFAULT 0,
  evidence_count SMALLINT DEFAULT 0,
  failure_count SMALLINT DEFAULT 0,
  last_event_id CHAR(26),

  -- 时间戳
  created_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
  updated_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,   -- 最后一个事件时间

  PRIMARY KEY (organization_id, task_id),
  FOREIGN KEY (organization_id, workflow_id) REFERENCES workflow_projections (organization_id, workflow_id)
);

CREATE INDEX idx_task_proj_status ON task_projections (organization_id, status, updated_at DESC);
CREATE INDEX idx_task_proj_user ON task_projections (organization_id, created_by_user_id, updated_at DESC);
```

**说明**：
- Projection 缓存的是最新状态，用于加速查询
- `version` 记录对应的事件版本，支持事件重放验证
- 通过触发器或定时 ETL 从 Event Store 重新计算

#### 2.2 Worker 投影表

```sql
CREATE TABLE IF NOT EXISTS worker_projections (
  organization_id VARCHAR(128),
  worker_id VARCHAR(128),
  task_id VARCHAR(128),
  workflow_id VARCHAR(128),
  version BIGINT,

  -- 核心属性
  worker_type VARCHAR(64),                     -- "react_loop", "coder", etc.
  status VARCHAR(32),                          -- CREATED / READY / RUNNING / COMPLETED
  status_at TIMESTAMP(6) WITH TIME ZONE,

  -- 执行上下文
  toolset_version VARCHAR(16),
  allowed_tools JSONB,                         -- ["git", "shell", "file", ...]
  policy_version VARCHAR(16),
  current_action_id VARCHAR(128),
  attempt_count SMALLINT,
  max_attempts SMALLINT,

  -- 约束
  remaining_budget_tokens BIGINT,
  remaining_budget_seconds BIGINT,
  remaining_budget_dollars NUMERIC(10, 2),

  -- 完成条件
  output_artifact_ids JSONB DEFAULT '[]',
  required_evidence_types JSONB,
  received_evidence_types JSONB DEFAULT '{}',

  -- 状态
  is_paused BOOLEAN DEFAULT FALSE,
  pause_reason VARCHAR(256),
  last_action_at TIMESTAMP(6) WITH TIME ZONE,
  estimated_completion_at TIMESTAMP(6) WITH TIME ZONE,

  created_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
  updated_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,

  PRIMARY KEY (organization_id, worker_id)
);

CREATE INDEX idx_worker_proj_status ON worker_projections (organization_id, status, updated_at DESC);
CREATE INDEX idx_worker_proj_task ON worker_projections (organization_id, task_id, status);
```

#### 2.3 Action 投影表

```sql
CREATE TABLE IF NOT EXISTS action_projections (
  organization_id VARCHAR(128),
  action_id VARCHAR(128),
  task_id VARCHAR(128),
  worker_id VARCHAR(128),
  version BIGINT,

  -- 核心属性
  action_type VARCHAR(64),                     -- "ReadFile", "GitCommit", "ExecuteShell"
  status VARCHAR(32),                          -- PROPOSED / AUTHORIZED / EXECUTING / SUCCEEDED / FAILED
  status_at TIMESTAMP(6) WITH TIME ZONE,

  -- 请求与响应
  request_payload JSONB,
  response_payload JSONB,
  error_message TEXT,

  -- 追踪
  trace_id VARCHAR(32),
  span_id VARCHAR(32),
  idempotency_key VARCHAR(256),
  result_record_id VARCHAR(128),               -- 对应 Evidence 记录的 ID

  -- 性能与资源
  duration_milliseconds BIGINT,
  tokens_consumed BIGINT,
  cost_dollars NUMERIC(10, 2),

  -- 安全
  policy_decision_id VARCHAR(128),
  authorization_result VARCHAR(32),            -- ALLOW / DENY / REQUIRE_APPROVAL
  approval_status VARCHAR(32),

  created_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
  updated_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,

  PRIMARY KEY (organization_id, action_id)
);

CREATE INDEX idx_action_proj_worker ON action_projections (organization_id, worker_id, status);
CREATE INDEX idx_action_proj_idempotency ON action_projections (organization_id, idempotency_key);
```

---

### 3. 恢复层 - Checkpoint & Idempotency（REQ-RT-005, REQ-RT-007）

#### 3.1 Checkpoints 表

```sql
CREATE TABLE IF NOT EXISTS checkpoints (
  organization_id VARCHAR(128),
  checkpoint_id CHAR(26),                      -- UUIDv7
  task_id VARCHAR(128) NOT NULL,
  workflow_id VARCHAR(128),
  worker_id VARCHAR(128),
  
  -- 检查点位置
  last_completed_action_id VARCHAR(128),
  last_event_id CHAR(26),                      -- 检查点时刻的最后一个事件
  worker_state_snapshot JSONB,                 -- 压缩的 Worker 状态快照

  -- 凭据与环境
  credential_refs JSONB,                       -- [{service, credential_id, expires_at}]
  workspace_snapshot JSONB,                    -- 工作区文件列表 / VCS 状态

  -- 恢复时机
  trigger_reason VARCHAR(64),                  -- "crash" / "manual" / "timeout"
  created_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
  expires_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,    -- TTL，见 REL-004
  
  -- 元数据
  retention_class VARCHAR(32),                 -- "hot" / "warm" / "cold"
  recovery_attempt_count SMALLINT DEFAULT 0,
  
  PRIMARY KEY (organization_id, checkpoint_id),
  FOREIGN KEY (organization_id, task_id) REFERENCES task_projections (organization_id, task_id)
);

CREATE INDEX idx_checkpoint_task ON checkpoints (organization_id, task_id, created_at DESC);
CREATE INDEX idx_checkpoint_expires ON checkpoints (organization_id, expires_at);

-- Checkpoint 不可修改（仅读取用于恢复）
ALTER TABLE checkpoints ENABLE ROW LEVEL SECURITY;
```

**说明**：
- `last_event_id` 标记检查点时刻，重放时从此事件之后继续
- `credential_refs` 记录凭据 ID 和过期时间，不存长期密钥
- `expires_at` 由 REL-004 决策（根据操作类型和恢复策略）
- `retention_class` 用于分层存储策略（SSD / HDD / Archive）

#### 3.2 Idempotency 表（幂等键去重）

```sql
CREATE TABLE IF NOT EXISTS idempotency_records (
  organization_id VARCHAR(128),
  idempotency_key VARCHAR(256),
  
  -- 请求与结果
  request_hash VARCHAR(64),                    -- SHA256(request_body + request_params)
  first_request_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
  action_id VARCHAR(128) NOT NULL,             -- 第一次请求对应的 Action
  
  -- 结果缓存
  result_status VARCHAR(32),                   -- SUCCEEDED / FAILED / IN_PROGRESS / UNKNOWN
  result_payload JSONB,                        -- 缓存返回值
  result_recorded_at TIMESTAMP(6) WITH TIME ZONE,
  
  -- 重复请求检测
  duplicate_request_count SMALLINT DEFAULT 0,
  last_duplicate_at TIMESTAMP(6) WITH TIME ZONE,
  
  -- 锁和协调
  lock_acquired_at TIMESTAMP(6) WITH TIME ZONE,
  lock_held_by VARCHAR(128),                   -- Worker ID
  
  PRIMARY KEY (organization_id, idempotency_key)
);

CREATE INDEX idx_idempotency_action ON idempotency_records (action_id);
CREATE INDEX idx_idempotency_created ON idempotency_records (organization_id, first_request_at DESC);
```

**说明**：
- `request_hash` 用于检测参数变化（同键不同参数应拒绝）
- `lock_acquired_at` 用于并发控制（只允许一个并发请求获得锁）
- 见 REQ-RT-007 and REQ-REL-006 的幂等性约束

---

### 4. 权限层 - RBAC & Policies（REQ-SEC-002, REQ-SEC-003）

#### 4.1 RBAC 策略表

```sql
CREATE TABLE IF NOT EXISTS rbac_policies (
  organization_id VARCHAR(128),
  policy_id VARCHAR(128),
  
  -- 主体、资源、操作
  subject_type VARCHAR(32),                    -- "user" / "group" / "role"
  subject_id VARCHAR(128),
  resource_type VARCHAR(32),                   -- "task" / "project" / "repository"
  resource_id VARCHAR(128),
  action VARCHAR(64),                          -- "read" / "write" / "execute" / "approve"
  
  -- 权限决策
  effect VARCHAR(16),                          -- "allow" / "deny"
  conditions JSONB,                            -- 附加条件（时间范围、IP 范围等）
  
  -- 来源与版本
  policy_version VARCHAR(16),
  created_by VARCHAR(128),
  created_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
  expires_at TIMESTAMP(6) WITH TIME ZONE,      -- 临时权限的过期时间
  
  PRIMARY KEY (organization_id, policy_id)
);

CREATE INDEX idx_rbac_subject ON rbac_policies (organization_id, subject_type, subject_id);
CREATE INDEX idx_rbac_resource ON rbac_policies (organization_id, resource_type, resource_id);
```

#### 4.2 Policy Gateway 决策缓存表

```sql
CREATE TABLE IF NOT EXISTS policy_decisions (
  organization_id VARCHAR(128),
  policy_decision_id VARCHAR(128),
  
  -- 决策对象
  request_context JSONB NOT NULL,              -- {actor, action, resource, ...}
  request_hash VARCHAR(64),
  
  -- 决策结果
  decision VARCHAR(32),                        -- "ALLOW" / "DENY" / "REQUIRE_APPROVAL"
  decision_reason VARCHAR(256),
  decision_metadata JSONB,                     -- 追踪原因的细节
  
  -- 缓存与生命周期
  decided_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
  expires_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,       -- 缓存 TTL，见 REQ-SEC-003
  policy_version_applied VARCHAR(16),
  
  PRIMARY KEY (organization_id, policy_decision_id),
  FOREIGN KEY (organization_id) REFERENCES organizations (organization_id)
);

CREATE INDEX idx_policy_decisions_hash ON policy_decisions (organization_id, request_hash, expires_at DESC);
CREATE INDEX idx_policy_decisions_expires ON policy_decisions (expires_at) WHERE expires_at > NOW();
```

---

### 5. 审计层 - Audit Trail（REQ-OBS-007）

#### 5.1 审计日志表（WORM，不可篡改）

```sql
CREATE TABLE IF NOT EXISTS audit_logs (
  organization_id VARCHAR(128),
  audit_id CHAR(26),                           -- UUIDv7
  
  -- 操作信息
  action VARCHAR(128) NOT NULL,                -- "task_created" / "action_authorized" / "approval_granted"
  resource_type VARCHAR(64),                   -- "task" / "worker" / "policy"
  resource_id VARCHAR(128),
  
  -- 行为者
  actor_type VARCHAR(32),                      -- "user" / "system" / "kill_switch"
  actor_id VARCHAR(128),
  actor_email VARCHAR(256),
  
  -- 变更详情
  before_state JSONB,                          -- 修改前状态
  after_state JSONB,                           -- 修改后状态
  change_description TEXT,
  
  -- 追踪与关联
  trace_id VARCHAR(32),
  span_id VARCHAR(32),
  causation_chain JSONB,                       -- 因果链（引起这次操作的事件链）
  
  -- 完整性
  log_hash VARCHAR(64),                        -- SHA256(整行内容)，用于检测篡改
  previous_log_hash VARCHAR(64),               -- 前一条日志的哈希，形成链
  
  -- 时间戳
  occurred_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
  recorded_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,
  
  -- 留存分类
  retention_class VARCHAR(32),                 -- "hot" / "warm" / "cold"
  retention_expires_at TIMESTAMP(6) WITH TIME ZONE,     -- 何时应删除
  
  PRIMARY KEY (audit_id)
);

-- 按 organization 分区
CREATE TABLE audit_logs_org_default PARTITION OF audit_logs
  FOR VALUES IN ('_system');

-- 索引
CREATE INDEX idx_audit_logs_resource ON audit_logs (organization_id, resource_type, resource_id, recorded_at DESC);
CREATE INDEX idx_audit_logs_actor ON audit_logs (organization_id, actor_id, recorded_at DESC);
CREATE INDEX idx_audit_logs_action ON audit_logs (organization_id, action, recorded_at DESC);
CREATE INDEX idx_audit_logs_hash ON audit_logs (previous_log_hash);  -- 链完整性检查

-- 审计日志不可修改
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
```

**说明**：
- `log_hash` 和 `previous_log_hash` 形成 Merkle 链，检测历史篡改
- `retention_class` 支持热路径（SSD）/ 温路径（HDD） / 冷存储（Archive）
- 见 REQ-OBS-007 的审计完整性设计

#### 5.2 审计日志完整性验证表

```sql
CREATE TABLE IF NOT EXISTS audit_checksum_block (
  organization_id VARCHAR(128),
  block_id BIGINT,
  
  -- 块范围
  first_audit_id CHAR(26),
  last_audit_id CHAR(26),
  audit_count BIGINT,
  
  -- 完整性指标
  block_hash VARCHAR(64),                      -- 整块哈希值
  merkle_root VARCHAR(64),                     -- 该块内所有审计日志的 Merkle 根
  
  -- 元数据
  sealed_at TIMESTAMP(6) WITH TIME ZONE NOT NULL,      -- 块密封时间（超过 TTL 后密封）
  finalized BOOLEAN DEFAULT FALSE,
  
  PRIMARY KEY (organization_id, block_id)
);
```

---

### 6. 可观测性层 - Trace & Metrics（REQ-OBS-001~003）

#### 6.1 追踪链表（关联到 Event Store）

```sql
CREATE TABLE IF NOT EXISTS trace_spans (
  organization_id VARCHAR(128),
  trace_id VARCHAR(32),
  span_id VARCHAR(32),
  parent_span_id VARCHAR(32),
  
  -- Span 身份
  span_name VARCHAR(256),                      -- "task.execute" / "worker.run" / "action.propose"
  span_status VARCHAR(16),                     -- OK / ERROR
  
  -- 关联到事件
  event_ids CHAR(26) [],                       -- 该 Span 包含的事件 ID 列表
  
  -- 性能指标
  start_time TIMESTAMP(6) WITH TIME ZONE NOT NULL,
  end_time TIMESTAMP(6) WITH TIME ZONE,
  duration_milliseconds BIGINT,
  
  -- 采样与脱敏
  sampled BOOLEAN,                             -- 是否被采样
  redacted BOOLEAN DEFAULT FALSE,              -- 是否已脱敏
  
  PRIMARY KEY (trace_id, span_id)
);

CREATE INDEX idx_spans_trace ON trace_spans (trace_id, span_id);
```

---

## 视图与聚合

### Event Store 查询视图

```sql
-- 按事件类型聚合
CREATE VIEW event_summary_by_type AS
SELECT 
  organization_id,
  event_type,
  DATE_TRUNC('hour', recorded_at) AS hour,
  COUNT(*) AS count,
  AVG(EXTRACT(EPOCH FROM (recorded_at - occurred_at))) AS avg_latency_seconds
FROM events
GROUP BY organization_id, event_type, DATE_TRUNC('hour', recorded_at);

-- Task 完整事件链
CREATE VIEW task_event_chain AS
SELECT 
  events.organization_id,
  events.task_id,
  events.event_id,
  events.event_type,
  events.recorded_at,
  events.actor_id,
  events.payload
FROM events
WHERE event_category IN ('DOMAIN', 'LIFECYCLE', 'ACTION')
ORDER BY events.task_id, events.recorded_at;
```

---

## 多租户隔离策略

所有表必须包含 `organization_id` 作为分区键或外键，确保：

1. **行级安全（RLS）**：触发器检查 `organization_id` 一致性
2. **分区隔离**：每个组织的表分区独立存储
3. **查询强制**：所有查询必须在 WHERE 子句中包含 `organization_id = :{org_id}`
4. **跨租户禁止**：禁止 JOIN 跨越不同 organization_id 的行

```sql
-- 多租户隔离策略示例
ALTER TABLE events ENABLE ROW LEVEL SECURITY;
CREATE POLICY events_org_isolation ON events 
  USING (organization_id = current_setting('app.current_org_id')::VARCHAR);
```

---

## 索引策略与维护

### 关键路径索引

| 表 | 索引 | 用途 |
|----|------|------|
| events | (org_id, task_id, recorded_at DESC) | Task 事件链查询 |
| events | (org_id, idempotency_key) | 幂等性去重 |
| events | (trace_id) | 分布式追踪 |
| task_projections | (org_id, status) | 按状态过滤 |
| worker_projections | (org_id, task_id, status) | Task 内的 Worker 查询 |
| audit_logs | (org_id, resource_type, recorded_at DESC) | 审计日志查询 |
| rbac_policies | (org_id, subject_id) | 权限检查（可缓存） |

### 定期维护

- **VACUUM / ANALYZE**：每小时执行一次（Event Store 增长快）
- **分区管理**：按时间 / 组织自动滚动分区
- **索引监控**：跟踪索引膨胀率，去除低效索引

---

## 迁移与演进策略（REQ-RT-003 Expand/Contract）

### Schema 演进规则

1. **新增可选字段**：直接 ALTER TABLE ADD COLUMN（向后兼容）
2. **修改字段类型 / 语义**：小版本升级（保留旧列 + 新列并行）
3. **删除字段**：弃用期 3 个月 → 标记废弃 → 删除

示例：

```sql
-- Phase 1: Add new column（向前兼容，旧消费者忽略）
ALTER TABLE events ADD COLUMN payload_v2 JSONB;

-- Phase 2: 双写逻辑（应用层同时写 payload 和 payload_v2）
-- （见应用层代码）

-- Phase 3: 消费者升级完毕，切换读（消费者改为读 payload_v2）
-- （见应用层代码）

-- Phase 4: 删除旧列（不会导致旧消费者读不到数据）
ALTER TABLE events DROP COLUMN payload;
```

---

## 验收标准

- [ ] 所有表支持按 organization_id 分区隔离
- [ ] Event Store 不允许 UPDATE / DELETE
- [ ] Audit 日志形成 Merkle 链（不可篡改）
- [ ] Projection 表有对应的物化视图刷新逻辑
- [ ] 关键索引性能基线测试通过（见 REL-004、OBS-003）
- [ ] 多租户隔离策略通过渗透测试（REQ-SEC-010）

---

## 下一步

1. **SQL 脚本生成**：由 DBA 基于本设计生成完整 SQL（含分区、权限、触发器）
2. **迁移脚本**：准备从候选数据模型到此设计的演进脚本
3. **性能基准测试**：Event Store 写入吞吐（目标：≥ 10k events/sec），查询延迟（p95 < 200ms）
4. **多租户测试**：验证租户隔离和跨租户查询拒绝

---

**设计者**: 架构组  
**最后更新**: 2026-10-12

