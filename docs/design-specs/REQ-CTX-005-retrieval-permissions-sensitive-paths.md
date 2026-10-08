# REQ-CTX-005：检索权限与敏感路径过滤

**需求ID**: `REQ-CTX-005`  
**优先级**: P1（核心功能）  
**依赖**: `SEC-002`（权限与 RBAC），`SEC-008`（多租户隔离）  
**状态**: ✅ 已设计  
**版本**: v1.0  
**最后更新**: 2026-10-03

---

## 一、需求背景与目标

### 1.1 业务背景

在 AI Agent 平台的上下文检索场景中，用户通过向量检索、词法检索、图检索等多种方式查询代码片段、文档和符号。传统的"先检索、后过滤"（Post-filter）架构存在以下严重问题：

1. **授权泄露风险**：未授权内容可能先进入检索结果，后端或 UI 层过滤不及时导致敏感信息暴露
2. **Token 浪费**：检索大量无权限数据后再丢弃，浪费向量计算和 LLM Token 配额
3. **合规风险**：`.env`、私钥、密码文件等敏感路径若被误检索，违反 SOC2/ISO27001 合规要求
4. **多租户隔离不足**：不同组织、团队的数据可能在同一索引中混合，缺乏租户级隔离

### 1.2 核心目标

**REQ-CTX-005** 要求实现 **零信任预过滤检索**（Zero-Trust Pre-filter Retrieval）架构，确保：

- **Pre-filter 优先**：在向量/词法/图检索执行前，先进行权限校验和敏感路径过滤
- **三级敏感路径过滤**：Level 1（硬编码基线，不可绕过）、Level 2（组织级规则）、Level 3（项目级规则）
- **多租户数据隔离**：强制租户边界（`organization_id`、`team_id`）分区存储和检索
- **Fail-Secure 策略**：权限服务超时或失败时默认 DENY
- **全链路审计**：记录查询负载、过滤结果数、违规指标，支持 OpenTelemetry 追踪

---

## 二、竞品分析与行业实践

### 2.1 GitHub Copilot

- **路径过滤**: 通过 `.copilotignore` 文件和企业级策略排除敏感路径（如 `secrets/`、`.env`）
- **权限模型**: 基于 GitHub 仓库权限（Read/Write/Admin），Pre-filter 在检索前校验用户对仓库的访问权
- **审计**: GitHub Advanced Security 日志记录所有 Copilot 查询和响应，支持合规审计

### 2.2 Sourcegraph

- **Pre-filter 架构**: 在 Zoekt（代码搜索引擎）层面实现 Pre-filter，仅索引用户有权访问的仓库
- **RBAC**: 支持 OAuth/SAML SSO，集成 GitLab/GitHub/Bitbucket 权限模型
- **敏感路径**: 通过 `sg.config.yaml` 配置 `excludedPaths`（支持 Glob 和正则）排除 `.git/`、`node_modules/`、`secrets/`
- **多租户**: 企业版支持租户级索引分区（`site_id`）

### 2.3 Claude Code / Cursor

- **Context Filtering**: 在 Context Retrieval 前通过工作区配置（`.cursorrules` 或 `.clauignore`）排除敏感文件
- **权限粒度**: 基于用户工作区访问权限（本地文件系统或远程仓库权限）
- **审计**: 企业版支持审计日志（查询内容、检索结果、Token 消耗）

### 2.4 DeepSeek / Kimi Code / 通义灵码

- **路径黑名单**: 通过配置文件（如 `deepseek.ignore`）排除敏感路径，支持 Glob 通配符
- **权限集成**: 集成 GitLab/GitHub OAuth，基于仓库权限进行 Pre-filter
- **多租户**: 企业版支持组织级隔离，不同组织的向量索引物理分区

### 2.5 Dify + SpiceDB

- **Zero-Trust 模型**: Dify 使用 SpiceDB（Google Zanzibar 开源实现）实现 Relation-based Access Control
- **Pre-filter**: 在向量检索前通过 SpiceDB Check API 校验用户对文档/知识库的 `read` 关系
- **敏感路径**: 通过 Knowledge Base 配置的 `exclude_patterns` 排除敏感文件

### 2.6 行业最佳实践总结

| 维度 | 最佳实践 | 采纳产品 |
|------|----------|----------|
| **Pre-filter 架构** | 在检索引擎层（而非 UI 层）实施权限校验 | Sourcegraph, Dify |
| **敏感路径过滤** | 三级过滤（硬编码基线 + 组织规则 + 项目规则） | GitHub Copilot, Cursor |
| **多租户隔离** | 物理分区索引（`organization_id` 作为分片键） | Sourcegraph, DeepSeek |
| **Fail-Secure** | 权限服务超时默认拒绝访问 | SpiceDB, AWS IAM |
| **审计日志** | 记录查询负载、过滤结果数、拒绝原因 | GitHub Copilot, Dify |

---

## 三、架构设计

### 3.1 整体架构：Pre-filter Pipeline

```
用户查询请求
    ↓
┌─────────────────────────────────────────────────┐
│  1. 多租户隔离检查                               │
│     - 提取 organization_id, team_id           │
│     - 校验租户激活状态                          │
└─────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────┐
│  2. RBAC 权限校验（SEC-002）                    │
│     - 检查用户对仓库/路径的访问权限              │
│     - 匹配 allowed_repositories, allowed_paths │
│     - 应用 denied_paths（Deny > Ask > Allow）  │
└─────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────┐
│  3. 三级敏感路径过滤                            │
│     - Level 1: 硬编码基线（不可绕过）           │
│     - Level 2: 组织级规则                       │
│     - Level 3: 项目级规则                       │
│     - 匹配模式：Exact / Prefix / Glob / Regex   │
└─────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────┐
│  4. 构造分区检索查询                            │
│     - 向量/词法/图检索添加 WHERE 条件           │
│     - organization_id = ? AND team_id = ?      │
│     - file_path NOT IN (...)                   │
└─────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────┐
│  5. 执行检索                                    │
│     - Qdrant / Elasticsearch / Neo4j           │
│     - 仅返回授权且非敏感的结果                  │
└─────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────┐
│  6. 审计日志记录                                │
│     - 查询负载、过滤数、拒绝原因                │
│     - OpenTelemetry Trace 传播                 │
└─────────────────────────────────────────────────┘
    ↓
返回过滤后结果
```

### 3.2 Fail-Secure 策略

| 故障场景 | 行为 | 理由 |
|----------|------|------|
| 权限服务超时 | **DENY** | 无法验证授权时拒绝访问 |
| Redis 缓存失效 | **降级查询权限服务** | 确保权限校验不被绕过 |
| 敏感路径规则加载失败 | **仅应用 Level 1 基线** | 最小化敏感信息暴露风险 |
| 多租户 ID 缺失 | **DENY** | 无法确定租户边界 |

---

## 四、三级敏感路径过滤设计

### 4.1 Level 1：硬编码基线（不可绕过）

**目的**: 系统级强制规则，保护高风险敏感文件，**任何用户（包括组织管理员）均不可绕过**。

**过滤列表**（示例）：

```
# 密钥与凭证
.env*
*.pem
*.key
*.crt
*.p12
*.pfx
id_rsa*
id_ed25519*
.ssh/
.aws/credentials
.azure/credentials
.gcp/service-account.json

# 密码与 Token
*password*.txt
*secret*.txt
*token*.txt
.secrets/
secrets/

# 数据库备份
*.sql
*.db
*.sqlite
*.dump

# 配置敏感文件
kubeconfig
.kube/config
docker-compose.override.yml
```

**实现位置**: 
- 硬编码在 `retrieval-service/src/filters/baseline_sensitive_paths.rs`（Rust）或等效模块
- 配置文件：`config/sensitive_paths_baseline.yaml`（只读，系统级）

### 4.2 Level 2：组织级规则（管理员配置）

**目的**: 组织（Organization）管理员根据企业安全策略配置额外敏感路径。

**配置示例**：

```yaml
organization_id: org_abc123
sensitive_paths:
  - pattern: "internal/*"
    type: prefix
    reason: "内部专有代码库"
  - pattern: "财务报表/*.xlsx"
    type: glob
    reason: "财务敏感数据"
  - pattern: ".*\\.confidential$"
    type: regex
    reason: "标记为机密的文件"
```

**存储**: 
- PostgreSQL 表 `organization_sensitive_paths`
- Redis 缓存（Key: `org:{org_id}:sensitive_paths`, TTL: 300s）

### 4.3 Level 3：项目级规则（项目所有者配置）

**目的**: 项目（Repository/Project）所有者配置项目特定的敏感路径。

**配置方式**：
1. **代码仓库配置文件**: `.aiagentignore` 或 `.retrievalignore`
   ```
   # .aiagentignore
   /experimental/
   /prototypes/*.py
   /data/customer_*.csv
   ```

2. **数据库存储**: `project_sensitive_paths` 表

**优先级**: Level 3 规则不能覆盖 Level 1 和 Level 2。

### 4.4 匹配模式

| 模式类型 | 示例 | 匹配逻辑 |
|----------|------|----------|
| **Exact** | `.env` | `file_path == ".env"` |
| **Prefix** | `secrets/` | `file_path.startsWith("secrets/")` |
| **Glob** | `*.key` | Unix glob 通配符匹配 |
| **Regex** | `.*\\.pem$` | 正则表达式匹配 |

**性能优化**：
- Exact 和 Prefix 使用 HashSet 或 Trie 树（O(1) 或 O(m)，m 为路径长度）
- Glob 编译为正则表达式并缓存
- Regex 使用 `regex` crate 预编译并缓存（避免每次查询重新编译）

---

## 五、多租户隔离（集成 SEC-008）

### 5.1 分区策略

**物理分区**（推荐）：
- Qdrant Collection: `vectors_{organization_id}`
- Elasticsearch Index: `code_{organization_id}`
- Neo4j Database: `graph_{organization_id}`（Neo4j 4.0+ 支持多数据库）

**逻辑分区**（备选）：
- 在单一索引中添加 Payload Filter: `organization_id = ?`
- 适用于小规模部署或 Qdrant Cloud

### 5.2 检索查询改写

**原始查询**：
```json
{
  "query": "authentication logic",
  "top_k": 10
}
```

**改写后查询（Qdrant）**：
```json
{
  "collection": "vectors_org_abc123",
  "query_vector": [...],
  "filter": {
    "must": [
      {"key": "organization_id", "match": {"value": "org_abc123"}},
      {"key": "team_id", "match": {"value": "team_xyz"}},
      {"key": "file_path", "match": {"except": [
        ".env", "secrets/", "*.key"
      ]}}
    ]
  },
  "limit": 10
}
```

### 5.3 租户激活状态校验

在检索前检查：
```sql
SELECT status FROM organizations WHERE organization_id = ?
```
- `status = 'suspended'` → **DENY**（租户已暂停）
- `status = 'deleted'` → **DENY**（租户已删除）

---

## 六、RBAC 权限校验（集成 SEC-002）

### 6.1 权限模型

用户权限表 `user_permissions`：

| 字段 | 类型 | 说明 |
|------|------|------|
| `user_id` | UUID | 用户 ID |
| `organization_id` | UUID | 组织 ID |
| `allowed_repositories` | TEXT[] | 允许访问的仓库列表（`*` 表示全部） |
| `allowed_paths` | TEXT[] | 允许访问的路径模式（Glob） |
| `denied_paths` | TEXT[] | 拒绝访问的路径模式（优先级最高） |

### 6.2 权限校验逻辑

**Deny > Ask > Allow 优先级**：

```
1. 检查 denied_paths：
   IF file_path matches any pattern in denied_paths:
       RETURN DENY

2. 检查 allowed_repositories：
   IF repository NOT IN allowed_repositories:
       RETURN DENY

3. 检查 allowed_paths：
   IF file_path matches any pattern in allowed_paths:
       RETURN ALLOW
   ELSE:
       RETURN DENY (默认拒绝)
```

### 6.3 缓存策略

- **Redis Key**: `user:{user_id}:perms`
- **TTL**: 300 秒（5 分钟）
- **版本号**: `permissions_version` 字段，权限更新时递增版本号并清除缓存

---

## 七、审计与可观测性

### 7.1 审计日志字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `timestamp` | TIMESTAMP | 查询时间（ISO 8601） |
| `trace_id` | VARCHAR(64) | OpenTelemetry Trace ID |
| `user_id` | UUID | 用户 ID |
| `organization_id` | UUID | 组织 ID |
| `query_text` | TEXT | 用户查询内容（脱敏） |
| `query_type` | ENUM | `vector` / `lexical` / `graph` |
| `total_candidates` | INT | 检索前候选数 |
| `filtered_count` | INT | 被过滤的结果数 |
| `returned_count` | INT | 返回给用户的结果数 |
| `denied_reasons` | JSONB | 拒绝原因（`sensitive_path`, `no_permission`, `tenant_blocked`） |
| `latency_ms` | INT | 总耗时（毫秒） |

### 7.2 Metrics（Prometheus）

```
# 检索查询总数
retrieval_queries_total{organization_id, query_type, status}

# 被敏感路径过滤的数量
retrieval_sensitive_path_filtered_total{organization_id, level}

# 权限拒绝数量
retrieval_permission_denied_total{organization_id, reason}

# Pre-filter 耗时（P50/P95/P99）
retrieval_prefilter_duration_seconds{organization_id, stage}
```

### 7.3 OpenTelemetry Trace

**Span 结构**：
```
Span: retrieval_query
  ├─ Span: multi_tenant_check
  ├─ Span: rbac_permission_check
  ├─ Span: sensitive_path_filter
  │   ├─ Span: level1_baseline
  │   ├─ Span: level2_org_rules
  │   └─ Span: level3_project_rules
  ├─ Span: qdrant_vector_search
  └─ Span: audit_log_write
```

---

## 八、API 设计

### 8.1 检索 API（Pre-filter 集成）

**Endpoint**: `POST /api/v1/retrieval/search`

**Request Body**:
```json
{
  "query": "authentication logic",
  "retrieval_type": "hybrid",
  "top_k": 10,
  "filters": {
    "repositories": ["repo1", "repo2"],
    "file_extensions": [".py", ".rs"]
  }
}
```

**Response**:
```json
{
  "results": [
    {
      "chunk_id": "chunk_abc123",
      "file_path": "src/auth/login.py",
      "content": "def authenticate_user(username, password):\n    ...",
      "score": 0.92,
      "metadata": {
        "repository": "repo1",
        "commit_sha": "a1b2c3d"
      }
    }
  ],
  "total_candidates": 156,
  "filtered_count": 48,
  "returned_count": 10,
  "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736"
}
```

### 8.2 敏感路径管理 API

**Endpoint**: `PUT /api/v1/organizations/{org_id}/sensitive-paths`

**Request Body**:
```json
{
  "paths": [
    {
      "pattern": "internal/*",
      "type": "prefix",
      "reason": "内部代码库"
    },
    {
      "pattern": "*.key",
      "type": "glob",
      "reason": "密钥文件"
    }
  ]
}
```

**权限要求**: 组织管理员（`role = 'org_admin'`）

---

## 九、性能优化

### 9.1 缓存策略

| 缓存项 | Key | TTL | 失效触发 |
|--------|-----|-----|----------|
| 用户权限 | `user:{user_id}:perms` | 300s | 权限更新时 |
| 组织敏感路径 | `org:{org_id}:sensitive_paths` | 300s | 规则更新时 |
| 项目敏感路径 | `proj:{proj_id}:sensitive_paths` | 600s | 规则更新时 |
| 租户激活状态 | `org:{org_id}:status` | 600s | 状态变更时 |

### 9.2 批量权限校验

当单次查询涉及多个仓库或路径时，批量查询权限：

```sql
SELECT repository_id, has_permission
FROM user_repository_permissions
WHERE user_id = ? AND repository_id IN (?, ?, ...)
```

### 9.3 敏感路径匹配优化

- **Trie 树**: 用于 Prefix 匹配（Level 1 和 Level 2）
- **Bloom Filter**: 快速排除不在敏感路径列表中的文件（误报率 < 0.01%）
- **Regex 预编译**: 启动时编译 Level 1 正则表达式并缓存

---

## 十、安全考虑

### 10.1 旁路攻击防护

**场景**: 攻击者通过 API 直接访问向量库，绕过 Pre-filter。

**防护措施**:
1. 向量库（Qdrant/Elasticsearch）部署在内网，仅允许 Retrieval Service 访问
2. Retrieval Service 使用专用数据库账户，限制权限（只读 + 特定 Collection/Index）
3. API 网关强制 JWT 校验，无 Token 请求无法到达 Retrieval Service

### 10.2 时序攻击（Timing Attack）

**场景**: 攻击者通过响应时间差异推测敏感路径是否存在。

**防护措施**:
- Pre-filter 阶段统一返回固定时间（通过 `sleep` 补齐延迟）
- 或对所有查询添加随机噪声延迟（50-100ms）

### 10.3 日志脱敏

审计日志中的 `query_text` 和 `denied_reasons` 可能包含敏感信息，需脱敏处理：

```python
def sanitize_query(query: str) -> str:
    # 移除潜在的密钥、Token 等
    query = re.sub(r'(token|key|password|secret)=[^\s&]+', r'\1=***', query)
    return query[:500]  # 截断过长查询
```

---

## 十一、测试策略

### 11.1 单元测试

**测试用例**：
1. `test_level1_baseline_blocks_dotenv`: 验证 `.env` 被 Level 1 过滤
2. `test_level2_org_rule_blocks_internal_path`: 验证组织规则生效
3. `test_level3_project_rule_blocks_prototype`: 验证项目规则生效
4. `test_deny_overrides_allow`: 验证 Deny > Allow 优先级
5. `test_permission_service_timeout_denies_access`: 验证 Fail-Secure
6. `test_multi_tenant_isolation`: 验证不同租户数据隔离

### 11.2 集成测试

**场景**：
- 模拟用户 A（有权访问 `repo1`）和用户 B（无权访问 `repo1`）分别查询同一关键词，验证结果差异
- 模拟组织管理员更新敏感路径规则，验证缓存失效和规则生效

### 11.3 性能测试

**目标**：
- Pre-filter 平均耗时 < 10ms（P99 < 50ms）
- 支持 1000 QPS（单实例）

**工具**: Locust、k6

---

## 十二、部署架构

### 12.1 服务拓扑

```
┌─────────────┐
│  API Gateway │
│  (Kong/APISIX)│
└──────┬───────┘
       │
       ↓
┌──────────────────┐
│ Retrieval Service │
│  (Rust/Go)        │
└──────┬───────────┘
       │
       ├──→ Redis (权限缓存、敏感路径缓存)
       ├──→ PostgreSQL (权限数据、审计日志)
       ├──→ Qdrant (向量检索)
       ├──→ Elasticsearch (词法检索)
       └──→ Neo4j (图检索)
```

### 12.2 高可用部署

- **Retrieval Service**: 至少 3 个实例，通过 Kubernetes HPA 自动扩缩容
- **Redis**: Redis Sentinel 或 Redis Cluster（3 主 3 从）
- **PostgreSQL**: 主从复制 + PgBouncer 连接池
- **Qdrant**: 分片 + 副本（每个分片 2 副本）

---

## 十三、监控告警

### 13.1 关键指标

| 指标 | 阈值 | 告警级别 |
|------|------|----------|
| Pre-filter 失败率 | > 1% | **Critical** |
| 权限服务响应时间 | P99 > 100ms | **Warning** |
| 敏感路径过滤数突增 | 环比增长 > 50% | **Info** |
| Redis 缓存命中率 | < 90% | **Warning** |
| 审计日志写入失败 | > 0.1% | **Critical** |

### 13.2 告警渠道

- **PagerDuty**: Critical 级别（24/7 On-call）
- **Slack**: Warning 和 Info 级别
- **Grafana Dashboard**: 实时监控

---

## 十四、合规性

### 14.1 SOC2 Type II

- **CC6.1**: Pre-filter 确保用户仅访问授权资源
- **CC7.2**: 审计日志记录所有访问请求和拒绝原因

### 14.2 ISO27001

- **A.9.4.1**: 访问控制策略（Deny > Ask > Allow）
- **A.12.4.1**: 审计日志保留 90 天，支持合规审计

### 14.3 GDPR

- 审计日志中的 `query_text` 脱敏，避免记录用户个人数据
- 用户删除账户时，级联删除审计日志中的关联记录

---

## 十五、迁移计划

### 15.1 Phase 1：基础设施准备（Week 1-2）

- 部署 Redis Cluster（权限缓存）
- 创建 PostgreSQL 表（`organization_sensitive_paths`, `project_sensitive_paths`, `retrieval_audit_logs`）
- 配置 Level 1 基线敏感路径列表

### 15.2 Phase 2：Pre-filter 实现（Week 3-4）

- 实现 Retrieval Service 的 Pre-filter 模块（Rust）
- 集成 RBAC 权限校验（调用 Auth Service API）
- 实现三级敏感路径过滤逻辑

### 15.3 Phase 3：集成与测试（Week 5-6）

- 改造 Qdrant、Elasticsearch、Neo4j 检索接口，添加 Pre-filter 查询条件
- 单元测试、集成测试、性能测试
- 灰度发布（5% → 50% → 100% 流量）

### 15.4 Phase 4：监控与优化（Week 7-8）

- 部署 Grafana Dashboard 和告警规则
- 性能调优（缓存命中率、Pre-filter 耗时）
- 编写运维手册和故障处理流程

---

## 十六、风险与缓解

### 16.1 风险矩阵

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| 权限服务故障导致所有查询被拒绝 | **High** | Medium | 实现降级策略（缓存兜底） + 99.9% SLA |
| Pre-filter 性能瓶颈 | Medium | Low | 缓存优化 + 异步权限校验 |
| 敏感路径规则配置错误导致误伤 | Medium | Medium | 提供规则测试工具 + Dry-run 模式 |
| 审计日志存储成本过高 | Low | High | 日志归档（90 天后转存 S3）+ 采样（非敏感查询 10% 采样） |

### 16.2 回滚方案

如果 Pre-filter 导致严重故障：
1. 通过 Feature Flag 关闭 Pre-filter（降级为 Post-filter）
2. 保留审计日志，事后分析敏感信息暴露风险
3. 修复后重新灰度上线

---

## 十七、后续优化方向

1. **机器学习敏感路径识别**: 使用 NLP 模型自动识别代码中的敏感信息（如硬编码密钥）
2. **动态权限更新**: 支持实时权限变更（通过 WebSocket 推送到 Retrieval Service）
3. **联邦检索**: 支持跨组织的安全检索（基于 Federated Learning）
4. **区块链审计**: 将审计日志哈希存储到区块链，确保不可篡改

---

## 附录 A：配置文件示例

### A.1 `sensitive_paths_baseline.yaml`（Level 1）

```yaml
version: "1.0"
baseline_sensitive_paths:
  - pattern: ".env*"
    type: glob
    reason: "环境变量文件"
  - pattern: "*.pem"
    type: glob
    reason: "SSL/TLS 私钥"
  - pattern: ".ssh/"
    type: prefix
    reason: "SSH 密钥目录"
  - pattern: ".*password.*\\.txt$"
    type: regex
    reason: "密码文本文件"
```

### A.2 `.aiagentignore`（Level 3）

```
# .aiagentignore (项目级)

# 实验性代码
/experimental/
/prototypes/

# 客户数据
/data/customer_*.csv

# 第三方依赖
/node_modules/
/vendor/
```

---

## 附录 B：Rust 代码示例

### B.1 Pre-filter 核心逻辑

```rust
use regex::Regex;
use std::collections::HashSet;

pub struct SensitivePathFilter {
    level1_baseline: HashSet<String>,
    level2_org_rules: Vec<PathRule>,
    level3_proj_rules: Vec<PathRule>,
}

pub struct PathRule {
    pattern: String,
    rule_type: RuleType,
}

pub enum RuleType {
    Exact,
    Prefix,
    Glob,
    Regex(Regex),
}

impl SensitivePathFilter {
    pub fn is_sensitive(&self, file_path: &str) -> bool {
        // Level 1: Baseline (不可绕过)
        if self.level1_baseline.contains(file_path) {
            return true;
        }

        // Level 2: Organization rules
        for rule in &self.level2_org_rules {
            if self.matches_rule(file_path, rule) {
                return true;
            }
        }

        // Level 3: Project rules
        for rule in &self.level3_proj_rules {
            if self.matches_rule(file_path, rule) {
                return true;
            }
        }

        false
    }

    fn matches_rule(&self, file_path: &str, rule: &PathRule) -> bool {
        match &rule.rule_type {
            RuleType::Exact => file_path == rule.pattern,
            RuleType::Prefix => file_path.starts_with(&rule.pattern),
            RuleType::Glob => {
                // 使用 glob 库匹配
                glob::Pattern::new(&rule.pattern)
                    .unwrap()
                    .matches(file_path)
            }
            RuleType::Regex(re) => re.is_match(file_path),
        }
    }
}
```

---

## 总结

**REQ-CTX-005** 通过 **零信任预过滤检索架构**，从根本上解决了传统 Post-filter 的安全隐患和性能浪费问题。核心设计包括：

1. **Pre-filter Pipeline**: 在检索前完成多租户隔离、RBAC 校验、三级敏感路径过滤
2. **三级敏感路径**: Level 1（硬编码基线）+ Level 2（组织规则）+ Level 3（项目规则）
3. **Fail-Secure**: 权限服务故障时默认 DENY
4. **全链路审计**: OpenTelemetry Trace + Prometheus Metrics + 审计日志
5. **高性能缓存**: Redis 缓存权限和敏感路径规则，P99 延迟 < 50ms

该设计参考了 GitHub Copilot、Sourcegraph、Claude Code、Dify + SpiceDB 等业界最佳实践，满足 SOC2、ISO27001、GDPR 合规要求，为 AI Agent 平台的安全检索奠定坚实基础。
