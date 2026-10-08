# REQ-OBS-007: 审计留存和完整性 (Audit Retention & Integrity)

**版本**: v0.1-designed  
**状态**: 已设计 (Designed)  
**设计日期**: 2026-10-05  
**依赖需求**: REQ-OBS-002, REQ-SEC-008, REQ-SEC-009

---

## 1. 需求定义 (Requirements Definition)

### 1.1 核心需求
作为企业级 AI Agent 运营平台，系统必须确保所有审计事件（操作日志、决策轨迹、敏感数据访问记录）满足：
- **长期留存**: 支持 7 年合规留存周期（可配置）
- **防篡改保证**: 采用密码学方法确保事件一旦写入不可修改
- **法律保全**: 支持诉讼保全（Legal Hold）机制阻止自动清理
- **可验证删除**: GDPR/CCPA 删除请求需提供加密签名的删除证明

### 1.2 合规驱动因素
- **SOC 2 Type II**: 要求审计日志不可篡改且可追溯
- **GDPR Article 17**: 删除权需提供技术证明且不破坏审计完整性
- **ISO 27001**: 安全事件留存至少 12 个月
- **金融行业监管**: 部分场景要求 7-10 年留存（如 SEC Rule 17a-4）

---

## 2. 问题分析 (Problem Analysis)

### 2.1 当前痛点
1. **存储成本爆炸**: 全量热存储 7 年成本不可接受
2. **删除与留存冲突**: GDPR 删除权 vs. 监管留存义务
3. **篡改检测延迟**: 事后发现日志被修改但无法溯源时间点
4. **法律保全遗漏**: 诉讼发起后仍有数据被自动清理的风险

### 2.2 技术挑战
- **跨代查询性能**: 冷数据解冻查询需 < 5min（p95）
- **分布式时钟一致性**: 多节点哈希链构建需全局时序保证
- **向量数据删除**: Embedding 无法精确删除单条，需 collection 级清理
- **合规审计窗口**: 监管机构要求 24h 内提供完整性证明

---

## 3. 竞品分析 (Competitive Analysis)

### 3.1 行业标杆

| 产品/服务 | 留存策略 | 完整性保证 | 删除机制 | 法律保全 |
|---------|---------|-----------|---------|---------|
| **AWS CloudTrail** | 90d 免费 + S3 Object Lock | SHA-256 + 可选加密签名 | 按 Bucket 生命周期 | ❌ 需自建 |
| **Google Cloud Audit Logs** | Admin 400d, Data 30d | 内部 Merkle Tree (未公开) | Retention Policy + VPC-SC | ✅ Legal Hold API |
| **Microsoft Purview** | 可配置 1-10 年 | WORM + Event Hubs 存档 | Disposition Review | ✅ eDiscovery 集成 |
| **Datadog Audit Trail** | 保留 15 个月 | 加密存储，未提供哈希链 | 自动滚动删除 | ❌ |
| **OpenAI Enterprise** | 未公开（推测 30-90d） | 未公开 | 组织级数据删除（30d 延迟） | 未公开 |
| **Anthropic Claude** | 未公开 | 未公开 | GDPR 删除请求人工处理 | 未公开 |
| **Cursor Enterprise** | 未明确披露 | 未明确披露 | 工作区删除 + 30d 软删除 | 未公开 |

### 3.2 关键差异化设计
本平台采用 **三层分级 + 双重完整性（哈希链 + WORM）**：
- **Hot Tier (30d)**: PostgreSQL + Merkle Hash Chain，查询 p95 < 100ms
- **Warm Tier (180d)**: 归档表 + 压缩，查询 p95 < 500ms
- **Cold Tier (7y)**: S3 Object Lock Compliance Mode + Glacier Deep Archive

---

## 4. 架构设计 (Architecture Design)

### 4.1 三层存储分级 (Storage Tiering)

```
┌─────────────────────────────────────────────────────────────────┐
│                         Event Ingestion                          │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ EventBus → Validation → Integrity Hash → Append to Chain │  │
│  └──────────────────────────────────────────────────────────┘  │
└───────────────────┬─────────────────────────────────────────────┘
                    │
        ┌───────────┼───────────┐
        │           │           │
        ▼           ▼           ▼
   ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
   │   HOT TIER      │  │   WARM TIER     │  │   COLD TIER     │
   │   (0-30 days)   │  │  (31-180 days)  │  │  (181d - 7y)    │
   ├─────────────────┤  ├─────────────────┤  ├─────────────────┤
   │ • PostgreSQL    │  │ • Archive Table │  │ • S3 Glacier    │
   │ • Full Index    │  │ • Compressed    │  │ • Object Lock   │
   │ • Hash Chain    │  │ • Partial Index │  │ • Compliance    │
   │ • p95 < 100ms   │  │ • p95 < 500ms   │  │ • p95 < 5min    │
   └─────────────────┘  └─────────────────┘  └─────────────────┘
          │                     │                     │
          └─────────────────────┴─────────────────────┘
                                │
                    ┌───────────▼───────────┐
                    │   Legal Hold Override  │
                    │   (Freeze Lifecycle)   │
                    └────────────────────────┘
```

### 4.2 核心组件

#### 4.2.1 Integrity Chain Manager
- **职责**: 为每个事件计算 `integrity_hash = SHA-256(event_payload + previous_hash)`
- **初始化**: 每个组织/租户独立链起点 `genesis_hash = SHA-256(org_id + created_at)`
- **批量验证**: 每 1000 条事件构建 Merkle Tree，根哈希存入 `integrity_checkpoints` 表

#### 4.2.2 Lifecycle Manager
- **职责**: 执行自动分层转移和清理策略
- **触发机制**: 
  - Cron 任务每日 02:00 UTC 扫描到期数据
  - 检查 `legal_hold=false` 且超过 TTL 的记录
  - 调用 StorageOrchestrator 执行迁移/删除

#### 4.2.3 Deletion Proof Generator
- **职责**: 生成符合 GDPR 的删除证明
- **流程**: 
  1. 查询待删除记录的 `event_id`, `integrity_hash`, `timestamp`
  2. 执行硬删除（Structured）+ Collection Drop（Vector）
  3. 生成签名证明：`proof = RSA-Sign(event_ids + deletion_timestamp + operator_id)`
  4. 存入 `deletion_receipts` 表（不可删除）

---

## 5. 数据模型 (Data Models)

### 5.1 核心表结构

#### audit_events (Hot Tier - PostgreSQL)
```sql
CREATE TABLE audit_events (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    team_id UUID,
    trace_id UUID NOT NULL,
    
    -- Event Core
    event_type VARCHAR(64) NOT NULL, -- 引用 REQ-OBS-002 的 44 种类型
    event_category VARCHAR(32) NOT NULL, -- workflow|auth|data|system|security
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actor_type VARCHAR(32) NOT NULL, -- user|agent|system|api
    actor_id UUID,
    
    -- Payload
    event_payload JSONB NOT NULL,
    evidence JSONB, -- 引用 REQ-OBS-002 Evidence 模型
    sensitivity_level VARCHAR(16) NOT NULL, -- public|internal|confidential|restricted
    
    -- Integrity
    integrity_hash VARCHAR(64) NOT NULL, -- SHA-256 hex
    previous_hash VARCHAR(64), -- NULL for genesis event
    chain_position BIGINT NOT NULL, -- Monotonic sequence per org
    
    -- Lifecycle
    tier VARCHAR(16) NOT NULL DEFAULT 'hot', -- hot|warm|cold
    legal_hold BOOLEAN NOT NULL DEFAULT false,
    retention_until TIMESTAMPTZ, -- NULL = 永久保留
    
    -- Metadata
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    migrated_at TIMESTAMPTZ,
    
    CONSTRAINT fk_org FOREIGN KEY (organization_id) REFERENCES organizations(id),
    INDEX idx_org_timestamp (organization_id, timestamp DESC),
    INDEX idx_trace (trace_id),
    INDEX idx_event_type (event_type, timestamp DESC),
    INDEX idx_legal_hold (legal_hold, retention_until) WHERE legal_hold = true
);
```

#### audit_events_warm (Warm Tier - Archive Table)
```sql
CREATE TABLE audit_events_warm (
    -- Same schema as audit_events
    -- Compressed with pg_compress or partitioned by month
) PARTITION BY RANGE (timestamp);
```

#### audit_events_cold_metadata (Cold Tier Metadata)
```sql
CREATE TABLE audit_events_cold_metadata (
    batch_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL,
    s3_object_key TEXT NOT NULL, -- s3://bucket/org_id/year/month/batch_id.parquet
    event_count INTEGER NOT NULL,
    start_timestamp TIMESTAMPTZ NOT NULL,
    end_timestamp TIMESTAMPTZ NOT NULL,
    merkle_root_hash VARCHAR(64) NOT NULL,
    glacier_archive_id TEXT, -- Glacier Deep Archive ID
    object_lock_until TIMESTAMPTZ NOT NULL, -- S3 Object Lock retention date
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

#### integrity_checkpoints (Merkle Tree Roots)
```sql
CREATE TABLE integrity_checkpoints (
    checkpoint_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL,
    chain_position_start BIGINT NOT NULL,
    chain_position_end BIGINT NOT NULL,
    merkle_root_hash VARCHAR(64) NOT NULL,
    event_count INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    INDEX idx_org_chain (organization_id, chain_position_end DESC)
);
```

#### deletion_receipts (Immutable Deletion Proofs)
```sql
CREATE TABLE deletion_receipts (
    receipt_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL,
    request_type VARCHAR(32) NOT NULL, -- gdpr_erasure|ccpa_deletion|retention_expiry
    deleted_event_ids UUID[] NOT NULL,
    deleted_count INTEGER NOT NULL,
    deletion_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    operator_id UUID NOT NULL,
    approver_id UUID, -- Four-eyes principle
    signature TEXT NOT NULL, -- RSA-2048 signature
    verification_url TEXT, -- External audit portal link
    
    -- Immutable: No DELETE/UPDATE allowed
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 5.2 哈希链设计 (Hash Chain Design)

#### 5.2.1 哈希计算逻辑
```python
def compute_integrity_hash(event: AuditEvent, previous_hash: str | None) -> str:
    """
    计算审计事件的完整性哈希
    
    Args:
        event: 审计事件对象
        previous_hash: 链中前一个事件的哈希值（创世事件为 None）
    
    Returns:
        64 字符 SHA-256 十六进制哈希
    """
    # 规范化 payload 为确定性 JSON（排序键）
    canonical_payload = json.dumps(
        event.event_payload, 
        sort_keys=True, 
        ensure_ascii=False
    )
    
    # 构建哈希输入
    hash_input = f"{event.event_id}|{event.organization_id}|{event.timestamp.isoformat()}|{event.event_type}|{canonical_payload}|{previous_hash or 'GENESIS'}"
    
    # SHA-256 计算
    return hashlib.sha256(hash_input.encode('utf-8')).hexdigest()
```

#### 5.2.2 Merkle Tree 批量验证
```python
def build_merkle_checkpoint(events: list[AuditEvent]) -> str:
    """
    每 1000 条事件构建 Merkle Tree 根哈希
    """
    leaf_hashes = [event.integrity_hash for event in events]
    
    while len(leaf_hashes) > 1:
        next_level = []
        for i in range(0, len(leaf_hashes), 2):
            left = leaf_hashes[i]
            right = leaf_hashes[i + 1] if i + 1 < len(leaf_hashes) else left
            parent = hashlib.sha256(f"{left}{right}".encode()).hexdigest()
            next_level.append(parent)
        leaf_hashes = next_level
    
    return leaf_hashes[0]  # Merkle Root
```

---

## 6. 法律保全机制 (Legal Hold)

### 6.1 状态机

```
   ┌─────────────┐
   │   NORMAL    │ (legal_hold=false, retention_until set)
   └──────┬──────┘
          │
          │ Legal Hold Initiated
          ▼
   ┌─────────────┐
   │ LEGAL_HOLD  │ (legal_hold=true, lifecycle frozen)
   └──────┬──────┘
          │
          │ Legal Hold Released
          ▼
   ┌─────────────┐
   │   NORMAL    │ (resume lifecycle)
   └─────────────┘
```

### 6.2 API 设计

#### POST /api/v1/audit/legal-hold
```json
{
  "organization_id": "uuid",
  "case_id": "LEGAL-2026-001",
  "scope": {
    "event_types": ["agent.action.invoke", "data.pii.access"],
    "trace_ids": ["uuid1", "uuid2"],
    "time_range": {
      "start": "2026-01-01T00:00:00Z",
      "end": "2026-06-30T23:59:59Z"
    }
  },
  "initiated_by": "legal-team@company.com",
  "reason": "Litigation Case #12345"
}
```

**响应**:
```json
{
  "hold_id": "uuid",
  "affected_event_count": 15234,
  "status": "active",
  "created_at": "2026-10-05T13:00:00Z"
}
```

### 6.3 与 GDPR 删除的冲突处理

**场景**: 用户提交 GDPR 删除请求，但部分数据处于 Legal Hold

**处理流程**:
1. 系统标记删除请求为 `pending_legal_clearance`
2. 生成技术响应文档：
   - 可删除数据：立即执行 + 生成删除证明
   - Legal Hold 数据：说明法律义务阻止删除，引用 GDPR Recital 50
3. Legal Hold 解除后自动重试删除

---

## 7. 可验证删除 (Verifiable Deletion)

### 7.1 删除流程

```
User Request
     │
     ▼
┌─────────────────────┐
│ Deletion Controller │
│ • Validate scope    │
│ • Four-eyes check   │
│ • 24h cooling-off   │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ Execution Engine    │
│ • Structured: DELETE│
│ • Vector: DROP      │
│ • S3: Tombstone     │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ Proof Generator     │
│ • Sign deletion set │
│ • Store receipt     │
│ • Notify requester  │
└─────────────────────┘
```

### 7.2 删除证明生成

#### 证明数据结构
```json
{
  "receipt_id": "uuid",
  "organization_id": "uuid",
  "request_type": "gdpr_erasure",
  "deletion_summary": {
    "structured_events": 1523,
    "vector_embeddings": 342,
    "s3_objects": 12
  },
  "deleted_event_ids": ["uuid1", "uuid2", "..."],
  "deletion_timestamp": "2026-10-05T14:30:00Z",
  "operator_id": "uuid",
  "approver_id": "uuid",
  "signature": "BASE64_RSA_SIGNATURE",
  "verification_instructions": "Use public key at https://platform.example.com/audit/pubkey.pem"
}
```

#### 签名验证伪代码
```python
def verify_deletion_proof(receipt: DeletionReceipt, public_key: RSAPublicKey) -> bool:
    """
    验证删除证明的真实性
    """
    # 重建签名输入
    message = f"{receipt.receipt_id}|{receipt.organization_id}|{receipt.deletion_timestamp}|{','.join(receipt.deleted_event_ids)}"
    
    # RSA 验证
    try:
        public_key.verify(
            base64.b64decode(receipt.signature),
            message.encode('utf-8'),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256()
        )
        return True
    except InvalidSignature:
        return False
```

### 7.3 向量数据删除策略

**问题**: Qdrant/Milvus 无法精确删除单个 embedding

**解决方案**:
1. **Collection 级隔离**: 每个组织独立 collection（已在 REQ-SEC-008 定义）
2. **软删除 + 重建**: 
   - 标记待删除向量的元数据 `deleted=true`
   - 查询时过滤 `deleted=true` 记录
   - 每周后台任务重建 collection（排除已删除向量）
3. **删除证明**: 记录 collection 重建前后的向量计数差异

---

## 8. 性能与成本优化

### 8.1 查询优化

#### Hot Tier (PostgreSQL)
- **索引策略**: 
  - 复合索引 `(organization_id, timestamp DESC)` 覆盖 99% 时序查询
  - 部分索引 `WHERE legal_hold = true` 减少索引开销
- **分区**: 按月分区，自动删除超龄分区（需 legal_hold=false）

#### Warm Tier
- **压缩**: 使用 Parquet 列式存储，压缩比 5:1
- **缓存**: 频繁查询的归档数据预加载到 Redis（TTL 1h）

#### Cold Tier
- **解冻优化**: 
  - Glacier Flexible Retrieval: 5-12h（标准查询）
  - Glacier Expedited: 1-5min（紧急调查，额外成本）
- **元数据索引**: `audit_events_cold_metadata` 表支持不解冻检索范围

### 8.2 成本估算

假设 1M events/day, 每条 2KB:

| Tier | 存储期 | 月数据量 | 存储成本/月 | 查询成本/月 | 总成本/月 |
|------|--------|---------|------------|-----------|----------|
| Hot  | 30d    | 60GB    | $1.38 (RDS) | $0       | $1.38    |
| Warm | 150d   | 300GB   | $3.00 (RDS Archive) | $0.50 | $3.50    |
| Cold | 6.5y   | 14TB    | $14.00 (Glacier) | $2.00 | $16.00   |
| **Total** | **7y** | **14.36TB** | **$18.38** | **$2.50** | **$20.88** |

**对比全量热存储**: $3,220/月（14.36TB × $0.23/GB RDS）  
**节省**: 99.4%

---

## 9. 安全设计

### 9.1 加密

#### 传输加密
- 所有审计事件通过 TLS 1.3 写入
- gRPC EventBus 强制 mTLS

#### 静态加密
- **Hot/Warm Tier**: PostgreSQL TDE（Transparent Data Encryption）
- **Cold Tier**: S3 SSE-KMS with CMEK
- **哈希链**: 哈希值本身不加密（公开可验证）

#### 密钥分层（引用 REQ-SEC-008）
```
CMEK (Customer Master Key, AWS KMS)
  ↓
DEK (Data Encryption Key, per-tenant)
  ↓
Event Payload Encryption
```

### 9.2 访问控制

#### RBAC 策略
| 角色 | 权限 |
|------|------|
| **Security Auditor** | 读所有审计事件（脱敏后），验证哈希链 |
| **Compliance Officer** | 读+发起 Legal Hold + 查看删除证明 |
| **DPO (Data Protection Officer)** | 批准删除请求，生成删除证明 |
| **Platform Admin** | 配置留存策略，无权读取事件内容 |
| **End User** | 仅读自己的操作日志（通过 Privacy Portal） |

#### API 鉴权
- 审计查询 API 需 `audit:read` scope
- Legal Hold API 需 `audit:legal_hold` scope + MFA
- 删除 API 需 `audit:delete` scope + 双人审批

---

## 10. 异常处理

### 10.1 哈希链中断

**场景**: 数据库故障导致事件写入失败，链断裂

**检测**:
```sql
SELECT 
    event_id, 
    chain_position, 
    integrity_hash, 
    previous_hash
FROM audit_events
WHERE organization_id = :org_id
  AND chain_position NOT IN (
      SELECT chain_position - 1 
      FROM audit_events 
      WHERE organization_id = :org_id
  );
```

**修复**:
1. 标记断点事件为 `chain_status='broken'`
2. 从断点重新计算后续所有哈希
3. 生成 `integrity_incident` 报告
4. 通知 Security Team

### 10.2 Legal Hold 冲突

**场景**: Lifecycle Manager 尝试删除 Legal Hold 数据

**保护机制**:
```sql
-- 数据库约束
ALTER TABLE audit_events 
ADD CONSTRAINT check_legal_hold_deletion 
CHECK (legal_hold = false OR retention_until IS NULL);

-- 应用层二次校验
if event.legal_hold and operation == 'DELETE':
    raise IntegrityError("Cannot delete event under legal hold")
```

### 10.3 S3 Object Lock 失败

**场景**: 写入 Cold Tier 时 Object Lock 设置失败

**处理**:
1. 事件保留在 Warm Tier，标记 `migration_status='failed'`
2. 每小时重试 3 次
3. 3 次后告警运维团队
4. 手动介入前数据不清理

---

## 11. 监控与告警

### 11.1 关键指标

| 指标 | 阈值 | 告警级别 |
|------|------|---------|
| 哈希链验证失败率 | > 0.01% | P0 (Critical) |
| Hot Tier 查询 p95 | > 100ms | P2 (Warning) |
| Cold Tier 解冻失败率 | > 1% | P1 (High) |
| Legal Hold 覆盖事件数 | > 100k/org | P3 (Info) |
| 删除请求处理延迟 | > 48h | P2 (Warning) |
| 存储成本增长率 | > 20% MoM | P2 (Warning) |

### 11.2 仪表盘

#### Grafana Dashboard: "Audit Integrity"
```
┌────────────────────────────────────────────────────────────┐
│ Hash Chain Health                                           │
│ ✅ Integrity: 99.9999%   ⚠️ Broken Chains: 0   🔄 Validated: 1.2M/day │
├────────────────────────────────────────────────────────────┤
│ Storage Distribution                                        │
│ Hot: 15%  Warm: 25%  Cold: 60%                             │
├────────────────────────────────────────────────────────────┤
│ Legal Holds Active                                          │
│ 🔒 3 cases | 127K events frozen                            │
└────────────────────────────────────────────────────────────┘
```

---

## 12. 实施路线图

### Phase 1: 核心哈希链 (2 weeks)
- [ ] 实现 `IntegrityChainManager`
- [ ] PostgreSQL 表结构迁移
- [ ] 单元测试覆盖率 > 90%

### Phase 2: 三层存储 (3 weeks)
- [ ] Warm Tier 归档逻辑
- [ ] S3 + Object Lock 集成
- [ ] Lifecycle Manager 定时任务

### Phase 3: Legal Hold (1 week)
- [ ] Legal Hold API 开发
- [ ] 状态机实现
- [ ] GDPR 冲突处理逻辑

### Phase 4: 删除证明 (2 weeks)
- [ ] RSA 签名生成/验证
- [ ] 删除工作流（双人审批 + 24h 冷却）
- [ ] 向量数据软删除机制

### Phase 5: 监控告警 (1 week)
- [ ] Prometheus metrics 导出
- [ ] Grafana 仪表盘
- [ ] PagerDuty 集成

---

## 13. 验收标准

### 13.1 功能验收
- [ ] 写入 100 万条事件，哈希链完整性 100% 验证通过
- [ ] Hot → Warm 迁移后，查询结果与原始数据一致
- [ ] Warm → Cold 迁移使用 S3 Object Lock Compliance Mode
- [ ] Legal Hold 启用后，Lifecycle Manager 无法删除相关事件
- [ ] GDPR 删除请求生成带 RSA 签名的删除证明
- [ ] 删除证明可用公钥独立验证

### 13.2 性能验收
- [ ] Hot Tier 查询 p95 < 100ms (1M events)
- [ ] Warm Tier 查询 p95 < 500ms (5M events)
- [ ] Cold Tier 解冻 p95 < 5min (Expedited Retrieval)
- [ ] 哈希链验证 10K events < 2s

### 13.3 安全验收
- [ ] 篡改单条事件后，验证算法检测到哈希不匹配
- [ ] 删除中间事件导致链断裂，触发 P0 告警
- [ ] Legal Hold API 需 MFA + `audit:legal_hold` scope
- [ ] 删除操作需双人审批（operator + approver）

### 13.4 合规验收
- [ ] SOC 2 审计师确认哈希链不可篡改
- [ ] GDPR 法律顾问确认删除证明符合 Article 17
- [ ] 模拟 7 年留存周期（通过时间旅行测试）

---

## 14. 风险与缓解

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|---------|
| 哈希链性能瓶颈 | High | Medium | 批量 Merkle Tree 验证，异步哈希计算 |
| S3 Object Lock 成本高 | Medium | High | 仅 Cold Tier 启用，其他层用 PostgreSQL WORM |
| Legal Hold 滥用导致存储爆炸 | High | Low | 限制单 org 最多 5 个活跃 Legal Hold |
| GDPR 删除与监管留存冲突 | High | Medium | 法律意见书支持，记录合规例外 |
| 向量数据无法精确删除 | Medium | High | Collection 重建 + 软删除标记 |

---

## 15. 依赖关系

### 15.1 上游依赖
- **REQ-OBS-002**: 审计事件 Schema, 44 种 EventType, Evidence 模型
- **REQ-SEC-008**: 租户隔离边界, 30d/180d/7y 留存基线, DEK/KEK 加密

### 15.2 下游影响
- **REQ-SEC-009**: Kill Switch 触发条件新增"哈希链验证失败"
- **REQ-OBS-006**: 实时告警依赖审计事件的 `legal_hold` 字段
- **REQ-DATA-003**: 数据血缘追踪引用审计事件的 `trace_id`

---

## 16. 开放问题

1. **多区域复制**: 是否需要跨区域复制审计日志？（影响成本 +150%）
2. **量子安全**: SHA-256 未来是否需迁移到 SHA-3 或后量子哈希？
3. **链上存证**: 是否需要将 Merkle Root 锚定到区块链（如 Ethereum）？
4. **AI 模型审计**: LLM 推理日志是否需要更细粒度的完整性保证（如 per-token hash）？

---

## 17. 参考资料

1. AWS CloudTrail Log File Integrity: https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-log-file-validation-intro.html
2. Google Cloud Audit Logs: https://cloud.google.com/logging/docs/audit
3. SEC Rule 17a-4: WORM Requirements for Financial Records
4. GDPR Article 17 (Right to Erasure): https://gdpr-info.eu/art-17-gdpr/
5. SOC 2 Trust Service Criteria: Logging & Monitoring (CC7.2)
6. Merkle Tree Verification in Git: https://git-scm.com/book/en/v2/Git-Internals-Git-Objects

---

## 18. 版本历史

| 版本 | 日期 | 作者 | 变更说明 |
|------|------|------|---------|
| v0.1 | 2026-10-05 | AI Agent Requirements Analyst | 初始设计完成 |

---

**文档状态**: ✅ 已设计，待评审  
**下一步行动**: 提交技术评审 → 安全评审 → 实施排期