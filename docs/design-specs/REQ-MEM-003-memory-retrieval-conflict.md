# REQ-MEM-003 记忆检索与冲突详细设计

> 版本：v0.1-designed  
> 状态：详细设计已完成，待跨模块评审与冻结  
> 优先级：P1  
> 所属模块：记忆管理（MEM）  
> 设计日期：2026-10-05  
> 前置依赖：REQ-MEM-001 Memory Schema、REQ-CTX-006 Context Selector 与预算  
> 后续依赖：REQ-MEM-004 记忆生命周期

---

## 1. 需求基本信息

| 属性 | 内容 |
|---|---|
| 编号 | REQ-MEM-003 |
| 名称 | 记忆检索与冲突 |
| 优先级 | P1 |
| 所属模块 | 记忆管理（MEM） |
| 原始位置 | `docs/design-specs/PENDING-REQUIREMENTS.md`，第 150-153 行 |
| 原始描述 | 排序、冲突合并和覆盖规则 |
| 原定目标 | 记忆检索排序、冲突合并规则、覆盖策略 |
| 前置依赖 | MEM-001、CTX-006 |
| 设计状态 | v0.1-designed；不代表实现或验证完成 |

---

## 2. 目标、范围与边界

### 2.1 目标

建立统一、高效、冲突感知的记忆检索和冲突处理机制，确保：
1. 精确检索：支持按 ID 精确查找、语义检索、关键词检索、多维过滤
2. 多信号排序：融合语义相关度、关键词命中、时序新鲜度、置信度权重、作用域优先级
3. 冲突感知：检测主题冲突和结构冲突，根据冲突类型选择解决策略
4. 渐进披露：按 L1→L2→L3 三层加载，控制 Token 消耗
5. 可恢复压缩：只在保留重建路径时允许丢弃信息

### 2.2 范围

**本需求包含**：
- 记忆检索策略：语义检索、关键词检索、时序检索、精确查找
- 五维评分体系：语义相关度、关键词命中、时序新鲜度、置信度权重、作用域优先级
- 三层渐进披露：L1 摘要预览（200 字符）、L2 时序上下文（1000 字符）、L3 全量详情
- 冲突检测算法：主题相似度检测（Jaccard）、极性冲突检测、协调冲突检测
- 冲突解决策略：AUTO_REJECT、AUTO_REPLACE、MANUAL_ARBITRATION、KEEP_BOTH、MERGE
- 权限过滤与审计追踪

**本需求不包含**：
- 具体的存储后端选型（PostgreSQL / MongoDB / Redis）
- 向量检索的具体算法参数（embedding 模型选型归属实现设计）
- 记忆衰减的完整策略（归属 REQ-MEM-004）
- Context Selector 的具体实现（归属 REQ-CTX-006）
- 跨用户记忆推荐（Phase 3 扩展）

### 2.3 非目标

- MVP 不实现学习型权重调整（Phase 2）
- MVP 不实现 Cross-Encoder 重排（Phase 2 可选）
- MVP 不实现记忆作为向量图检索（可扩展）
- 不实现主动记忆预取（Phase 3）

---

## 3. 问题分析

当前 `PENDING-REQUIREMENTS.md` 中仅有"排序、冲突合并和覆盖规则"九字描述，存在以下系统性缺口：

### 3.1 检索策略缺失

| 缺口 | 具体问题 | 影响 |
|------|----------|------|
| 检索路径不明确 | 未定义检索入口、查询类型、支持的操作 | Agent 无法按场景选择检索策略 |
| 排序算法模糊 | 仅"排序"二字，未定义多信号评分、权重分配 | 检索结果排序随意，相关性无保证 |
| 过滤规则缺失 | 未定义作用域过滤、权限过滤、时序过滤 | 可能泄露 PRIVATE 记忆或返回过期记忆 |
| 渐进披露未定义 | 未定义快速索引层、详情层、全量层的分层加载 | Token 消耗不可控，延迟无保证 |

### 3.2 冲突处理语义模糊

| 缺口 | 具体问题 | 影响 |
|------|----------|------|
| "冲突"定义不清 | 哪些情况算冲突？主题相同？极性相反？ | Agent 无法判断是否触发冲突处理 |
| "合并"算法缺失 | 冲突时如何合并？保留两者？取其一？ | 合并结果不可预测 |
| "覆盖"策略歧义 | 覆盖是原子替换还是版本叠加？ | 覆盖决策可能导致信息丢失 |
| 可信度考量缺失 | 高低置信度记忆冲突时，是否应区别对待？ | 一刀切策略对高可信记忆不公平 |

### 3.3 与 MEM-001 的设计断链

| 断链点 | MEM-001 已有定义 | MEM-003 需要补足 |
|--------|------------------|------------------|
| memory_type | WORKING/TASK/PROJECT/ORGANIZATION | 不同类型检索权重如何？ |
| source | USER_EXPLICIT ~ SYSTEM_GENERATED | 来源是否影响排序？ |
| confidence | value + method + assessor | 置信度是否参与评分？ |
| lifecycle | ACTIVE/STALE/EXPIRED/DELETED/ARCHIVED | 非 ACTIVE 状态如何处理？ |

---

## 4. 标杆依据与公开事实/推断

研究访问日期：2026-10-04。公开产品做法仅作为设计参考。

### 4.1 Claude Code — LLM 路由扁平文件检索

**公开事实**：采用七层记忆架构，无向量搜索、无知识图谱、无衰减评分。检索完全由 LLM 驱动（Sonnet 侧查询）。构建 Manifest（文件名 + 描述约 30KB）→ Sonnet 选择 Top-5 → 异步预取 → 作为 Attachment 注入。

**设计推断**：LLM 路由适合小规模（<200 文件），零基础设施，但不可扩展。"过期优先召回哲学"值得借鉴。

**借鉴点**：渐进披露（Manifest → 侧查询 → 详情）、异步预取隐藏延迟、过期声明。

来源：[Claude Code Memory System Overview](https://github.com/luyao618/Claude-Code-Source-Study/blob/main/docs-en/31-memory-subsystem-overview.md)，访问日期：2026-10-04

### 4.2 Mem0 v3 — ADD-ONLY + 检索时解决

**公开事实**：v3 采用 ADD-ONLY 提取架构，矛盾事实同时存储，通过 `linked_memory_ids` 链接。检索使用多信号混合：语义向量 + BM25 关键词 + 实体匹配，`score = (semantic + bm25 + entity_boost) / max_possible`。检索时根据新鲜度和相关性决定显示哪条。

**设计推断**：历史记录有价值，冲突在检索层解决而非写入层。

**借鉴点**：ADD-ONLY 哲学、多信号混合检索、实体级权限隔离。

来源：[Mem0 Search API](https://mem0.mintlify.app/api-reference/memory/search-memories)，访问日期：2026-10-04

### 4.3 Zep/Graphiti — 时序知识图谱

**公开事实**：双时态模型，`valid_at`（事实成立时间）+ `invalid_at`（失效时间）+ `expired_at`（被废止时间）。检索三路并行：向量 + BM25 + 图遍历，无 LLM 重排。

**设计推断**：确定性失效优于概率衰减，时序有效性窗口支持审计。

**借鉴点**：双时态模型、确定性失效、三路并行检索。

来源：[Graphiti](https://www.getzep.com/platform/graphiti/)，访问日期：2026-10-04

### 4.4 LatticeMind — 冲突感知记忆基元

**公开事实**：首次将矛盾处理作为一等记忆更新操作。冲突分类：符号冲突（机械违反）、可信度冲突（一方应胜出）、协调冲突（资源碰撞）。符号检查器优先，仅必要时调用 LLM reconciler。

**设计推断**：不同类型冲突需要不同策略，一刀切无效。

**借鉴点**：三轨冲突分类、廉价符号检查先行、协调冲突保留双方。

来源：[LatticeMind](https://arxiv.org/html/2608.08236)，访问日期：2026-10-04

### 4.5 Kimi Mem — 渐进披露三层

**公开事实**：SQLite FTS5 + sqlite-vec，三层渐进披露：L1 索引（~50 tokens）→ L2 时间线（~200-500 tokens）→ L3 全量详情（~500-1000 tokens）。

**设计推断**：渐进披露有效控制 Token 消耗，避免一次性高开销。

**借鉴点**：L1→L2→L3 三层模型、会话生命周期 Hooks 驱动。

来源：[Kimi Mem](https://github.com/alanrezendeee/kimi-mem)，访问日期：2026-10-04

### 4.6 调研结论

本项目采用以下共同原则：
- 检索策略：语义 + BM25 + 时序三路并行（不依赖图数据库）
- 冲突处理：ADD-ONLY + 三轨冲突分类（符号/可信度/协调）
- 渐进披露：L1 摘要 → L2 时序上下文 → L3 全量
- 新鲜度：decay_rate 可配置的时序评分
- 权限：scope + RBAC 双重过滤

---

## 5. 核心设计

### 5.1 功能目标与价值

**功能目标**：
1. 精确检索：支持 memory_id 精确查找、语义检索、关键词检索
2. 多信号排序：五维评分体系（语义+关键词+时序+置信度+作用域）
3. 冲突感知：检测主题冲突和结构冲突
4. 渐进披露：L1→L2→L3 三层加载
5. 可恢复压缩：保留重建路径时允许丢弃信息

**用户价值**：
- 任务成功率：相关记忆被准确检索
- 信任度：冲突解决透明可追溯
- Token 效率：渐进加载避免一次性高消耗
- 审计合规：冲突历史保留，支持 GDPR

### 5.2 目标用户与使用场景

| 目标用户 | 使用场景 |
|----------|----------|
| AI Agent | Worker 执行任务时检索记忆；写入时触发冲突检测 |
| 终端用户 | 查询个人偏好记忆；查看冲突历史；手动解决冲突 |
| 组织管理员 | 审计组织级记忆使用；配置冲突解决策略 |
| 安全/合规团队 | 审查记忆检索日志；验证冲突解决决策 |

### 5.3 用户故事

**用户故事 1**：任务中按需检索记忆
```
作为 AI Agent，我需要在执行任务时检索相关记忆，
以便利用历史知识避免重复工作。

场景：用户要求添加"社交分享"功能
流程：
1. Agent 发送记忆查询：query="社交分享" + memory_type=TASK
2. 检索服务执行语义+关键词混合检索
3. 过滤 scope、lifecycle=ACTIVE
4. 五维评分排序，返回 Top-5 记忆
5. L1 层返回摘要预览
6. Agent 利用记忆中的项目约定和历史决策
```

**用户故事 2**：自动检测并解决冲突
```
作为 AI Agent，我在写入新记忆时发现与已有记忆主题冲突，
以便系统自动选择正确的记忆或标记需要人工介入。

场景：Agent 推断"用户偏好 React"，但已有记忆"用户偏好 Vue"
流程：
1. Agent 尝试写入新记忆（AGENT_INFERRED, confidence=0.55）
2. 冲突检测：检查同一 scope 下是否存在主题相似但极性相反的记忆
3. 极性冲突检测：识别出"React" vs "Vue"的框架偏好冲突
4. 置信度对比：新记忆 0.55 vs 已有记忆 0.75（USER_EXPLICIT）
5. 决策：自动拒绝新记忆，生成冲突记录
6. 审计：记录冲突检测结果和解决决策
```

---

## 6. 输入与输出定义

### 6.1 检索输入

```text
MemoryRetrievalQuery
- query: string (1..500)
- query_type: QueryType  # NATURAL_LANGUAGE / KEYWORD / STRUCTURED
- memory_type: MemoryType[]?
- scope: MemoryScope[]?
- source: MemorySource[]?
- min_confidence: float?  # 0.0~1.0
- max_age_days: integer?
- repository_id: EntityId?
- project_id: EntityId?
- include_stale: boolean = false
- include_expired: boolean = false
- user_id: EntityId
- top_k: integer = 10 (1..100)
- retrieval_depth: RetrievalDepth  # L1 / L2 / L3
- trace_id: TraceId

QueryType = NATURAL_LANGUAGE | KEYWORD | STRUCTURED
RetrievalDepth = L1 | L2 | L3
```

### 6.2 检索输出

```text
MemoryRetrievalResult
- query_id: string (UUIDv7)
- total_candidates: integer
- filtered_count: integer
- items: RetrievalItem[]
- conflicts: ConflictRecord[]?
- warnings: string[]
- trace_id: TraceId
- retrieval_latency_ms: integer

RetrievalItem
- memory_id: MemoryId
- memory_type: MemoryType
- scope: MemoryScope
- content_preview: string  # L1: 1..200, L2: 1..1000, L3: 全量
- relevance_score: float  # 0.0~1.0
- relevance_breakdown: RelevanceBreakdown
- conflict_status: ConflictStatus
- lifecycle_state: MemoryState
- created_at: Timestamp
- updated_at: Timestamp

RelevanceBreakdown
- semantic_score: float
- keyword_score: float
- freshness_score: float
- confidence_score: float
- scope_priority_score: float

ConflictStatus = NONE | POLARITY_RESOLVED | COORDINATION_PENDING | MANUAL_REQUIRED
```

### 6.3 冲突检测输入

```text
ConflictDetectionQuery
- new_memory: Memory
- candidate_memories: Memory[]
- detection_mode: DetectionMode  # AUTO / THOROUGH

DetectionMode = AUTO | THOROUGH
```

### 6.4 冲突检测输出

```text
ConflictDetectionResult
- has_conflicts: boolean
- conflict_type: ConflictType?
- conflicts: ConflictDetail[]?
- resolution: ConflictResolution?
- resolution_confidence: float

ConflictType = POLARITY_CONFLICT | COORDINATION_CONFLICT | STRUCTURAL_CONFLICT | NONE

ConflictDetail
- existing_memory_id: MemoryId
- new_memory_id: MemoryId?
- conflict_type: ConflictType
- polarity: Polarity?
- evidence: string[]
- assessment_method: AssessmentMethod

Polarity = PREFERENCE_A | PREFERENCE_B | OPPOSITE | UNRELATED

ConflictResolution
- strategy: ResolutionStrategy
- resolved_memory_ids: MemoryId[]
- rejected_memory_ids: MemoryId[]
- pending_memory_ids: MemoryId[]
- audit_record: ConflictAuditRecord

ResolutionStrategy = AUTO_REPLACE | AUTO_REJECT | MANUAL_ARBITRATION | KEEP_BOTH | MERGE
```

---

## 7. 处理逻辑与流程

### 7.1 记忆检索主流程（8 步）

```
步骤 1：查询解析与预处理
  输入：MemoryRetrievalQuery
  处理：解析 query_type，构建作用域过滤条件，检查检索深度
  输出：ParsedQuery

步骤 2：候选检索（三路并行）
  ① 向量语义检索：embedding ANN 查询 top-k
  ② 关键词全文检索：BM25 匹配
  ③ 时序检索：按 updated_at 倒序
  超时：单路 200ms，整体 500ms
  输出：CandidateList[vector, bm25, temporal]

步骤 3：过滤
  权限过滤、scope 过滤、lifecycle 过滤、confidence 过滤、去重
  输出：FilteredList

步骤 4：五维评分
  final_score = w1*semantic + w2*keyword + w3*freshness + w4*confidence + w5*scope_priority
  默认权重：w1=0.30, w2=0.15, w3=0.20, w4=0.20, w5=0.15
  输出：ScoredList

步骤 5：冲突检测（可选，仅在验证场景触发）
  按主题聚类 Top-10，检测冲突，注入 conflict_status
  输出：ScoredList + ConflictAnnotations

步骤 6：重排（可选）
  如果 top_k <= 20 且配置启用：Cross-Encoder 重排
  输出：RerankedList

步骤 7：渐进披露封装
  L1：content_preview = summary（无则前 200 字符）
  L2：content_preview = content_text[0..1000] + updated_at
  L3：content_preview = 完整 MemoryContent
  输出：ProgressiveResult

步骤 8：结果返回
  分页、生成 trace 事件、附加冲突记录（如有）
  输出：MemoryRetrievalResult
```

### 7.2 冲突检测与解决流程（6 步）

```
步骤 1：候选收集
  在同一 scope 下收集所有非 DELETED 状态的记忆
  输出：GroupedCandidates

步骤 2：主题相似度检测（符号检查）
  Jaccard 相似度 >= 0.6 → 标记为"同主题候选"
  输出：TopicSimilarCandidates

步骤 3：极性冲突检测（符号检查）
  分析极性关系：
  ① USER_EXPLICIT vs AGENT_INFERRED → 推断让位显式
  ② 同为 AGENT_* 且 confidence 相差 > 0.2 → 高置信度胜出
  ③ 极性指示词检测：["prefer X" vs "prefer Y"] → OPPOSITE
  输出：PolarityConflictCandidates

步骤 4：协调冲突检测（符号检查）
  检测资源碰撞、循环依赖
  输出：CoordinationConflictCandidates

步骤 5：解决策略路由
  分支 A（极性冲突）：
    置信度差 > 0.2 → AUTO_REJECT 或 AUTO_REPLACE
    置信度差 <= 0.2 → MANUAL_ARBITRATION
  分支 B（协调冲突）：
    KEEP_BOTH + 标记协调冲突待处理
  输出：ConflictResolution

步骤 6：冲突记录与通知
  生成 ConflictAuditRecord
  如果 MANUAL_ARBITRATION：发送通知给 owner
  所有冲突写入不可变审计日志
  输出：ConflictDetectionResult + AuditEvent
```

---

## 8. 算法设计思路

### 8.1 五维评分融合算法

**语义信号（semantic_score）**：
- 余弦相似度归一化：`score = (cos_sim + 1) / 2`，范围 [0, 1]

**关键词信号（keyword_score）**：
- BM25F，字段权重：summary=2.0, keywords=1.5, content_text=0.5
- 参数：k1=1.5, b=0.75

**时序新鲜度信号（freshness_score）**：
```
freshness_score = 1 / (1 + days_since_update * decay_rate)
decay_rate = 0.05/天（30 天后 freshness ≈ 0.4）
```

**置信度信号（confidence_score）**：
- 直接使用 `memory.confidence.value`

**作用域优先级信号（scope_priority_score）**：
```
base_score = {WORKING: 1.0, TASK: 0.8, PROJECT: 0.6, ORGANIZATION: 0.4}
overlap_bonus = 0.2 * (调用者当前 scope == 记忆 scope)
```

**融合公式**：
```
final_score = Σ wi * si，其中 Σ wi = 1.0
```

### 8.2 冲突检测算法

**主题相似度（符号检查）**：
```
keywords_A = extract_keywords(memory_A.summary + memory_A.keywords)
keywords_B = extract_keywords(memory_B.summary + memory_B.keywords)
jaccard = |keywords_A ∩ keywords_B| / |keywords_A ∪ keywords_B|
if jaccard >= 0.6 → same_topic
```

**极性判断（LLM 分析，THOROUGH 模式可选）**：
```
使用轻量模型（如 gpt-4o-mini）分析极性关系，p99 < 500ms
```

### 8.3 解决策略路由算法

```
1. 极性冲突检测
   if source_A == USER_EXPLICIT:
       return AUTO_REJECT(new_memory)
   if abs(confidence_A - confidence_B) > 0.2:
       winner = max(confidence_A, confidence_B)
       return AUTO_REPLACE(loser)
   return MANUAL_ARBITRATION

2. 协调冲突检测
   return KEEP_BOTH + COORDINATION_PENDING
```

---

## 9. 状态管理与数据流转

### 9.1 检索状态机

```
idle → parsing → candidate_retrieval → filtering → scoring
→ [可选] reranking → progressive_packaging → returning → idle

error → fallback → returning 或 idle + 告警
```

### 9.2 冲突状态机

```
no_conflict → checking → polarity_analysis → credibility_evaluation
→ auto_resolution 或 manual_required

coordination_check → coordination_pending
```

---

## 10. 异常与失败处理

| 异常场景 | 检测条件 | 处理策略 | 降级方案 |
|----------|----------|----------|----------|
| 向量检索超时 | > 200ms | 使用 BM25 + 时序结果 | 仅 BM25 + 时序 |
| BM25 超时 | > 200ms | 使用向量 + 时序结果 | 仅向量 + 时序 |
| 全链路超时 | > 500ms | 返回缓存结果（60s TTL） | 返回空 + 告警 |
| 权限服务不可用 | RBAC 调用失败 | fail-closed：拒绝全部结果 | 返回空 + 告警 |
| 冲突检测超时 | > 300ms | 降级为 AUTO 模式 | 符号检查即可 |
| LLM 极性分析失败 | LLM 返回错误 | 降级为符号检查结果 | 标记 MANUAL_REQUIRED |

---

## 11. 权限、安全与合规

### 11.1 权限模型

| 权限 | 主体 | 描述 |
|------|------|------|
| memory:retrieve | Owner、SHARED 成员、PUBLIC 读者 | 检索记忆 |
| memory:retrieve_stale | Owner、Admin | 查看 STALE 状态记忆 |
| memory:conflict_view | Owner、Admin | 查看冲突历史 |
| memory:conflict_resolve | Owner、Admin | 手动解决冲突 |

### 11.2 安全约束

- 检索结果必须经过 RBAC 授权过滤
- PRIVATE 记忆仅返回给 owner
- 检索请求必须携带 trace_id
- 禁止通过检索结果反推其他用户的 PRIVATE 记忆

### 11.3 合规要求

| 要求 | 实现方式 |
|------|----------|
| GDPR 数据可携带 | 支持按 user_id 导出所有记忆内容 |
| GDPR 数据删除 | 按 REQ-MEM-002 的撤销机制执行 |
| 冲突历史审计 | 所有冲突决策写入不可变审计日志 |

---

## 12. 性能、成本、延迟考量

### 12.1 延迟预算

| 阶段 | 预算 | 说明 |
|------|------|------|
| 查询解析 | 5ms | query_type 判断、过滤条件构建 |
| 向量检索 | 80ms | 含 ANN 查询网络往返 |
| BM25 检索 | 30ms | 含全文索引查询 |
| 时序检索 | 20ms | 按 updated_at 排序过滤 |
| 权限过滤 | 20ms | RBAC RPC 调用 |
| 五维评分计算 | 10ms | 内存计算 |
| 渐进披露封装 | 5ms | 按 retrieval_depth 选择内容 |
| **总计（不含冲突检测）** | **170ms** | SLO p95 ≤ 200ms |

### 12.2 成本考量

| 组件 | 单次查询成本 | 优化策略 |
|------|-------------|----------|
| 向量嵌入 | $0.00005/查询（批量） | 缓存查询 embedding，TTL 5min |
| Cross-Encoder 重排 | $0.0005/20 pairs | 仅对 Top-20 候选重排 |
| LLM 极性分析 | $0.001/次 | 仅 THOROUGH 模式 |

---

## 13. 可观测性与评估指标

### 13.1 核心指标

| 指标 | 定义 | SLO | 告警阈值 |
|------|------|-----|----------|
| memory_retrieval_latency_p95 | p95 检索延迟 | < 200ms | > 300ms |
| memory_retrieval_hit_rate | 检索命中率 | > 0.85 | < 0.70 |
| memory_conflict_auto_resolution_rate | 冲突自动解决率 | > 0.80 | < 0.60 |
| retrieval_ndcg@10 | NDCG Top-10 | > 0.75 | < 0.65 |
| retrieval_mrr | 平均倒数排名 | > 0.70 | < 0.60 |

### 13.2 Trace 关联

- `memory_retrieval` 事件关联：query_id、user_id、task_id、top_k、retrieval_latency_ms
- `memory_conflict_detected` 事件关联：conflict_id、memory_id、conflict_type、resolution_strategy
- `memory_conflict_resolved` 事件关联：conflict_id、resolver_id、resolution

---

## 14. 验收标准

| 编号 | 验收标准 | 验证方法 |
|------|----------|----------|
| AC01 | 支持按 memory_id 精确查找 | 单元测试 |
| AC02 | 支持自然语言语义检索 | 集成测试 + Golden Dataset 评测 |
| AC03 | 支持关键词 BM25 检索 | 单元测试 |
| AC04 | 支持五维评分融合排序 | 评分计算验证测试 |
| AC05 | 支持 L1/L2/L3 三层渐进披露 | 渐进加载测试 |
| AC06 | 检测主题相似冲突（Jaccard >= 0.6） | 冲突检测测试 |
| AC07 | 极性冲突中，高置信度记忆自动胜出 | 冲突解决测试 |
| AC08 | USER_EXPLICIT 与 AGENT_* 冲突触发人工仲裁 | 仲裁触发测试 |
| AC09 | 协调冲突保留双方记忆并标记待处理 | 协调冲突测试 |
| AC10 | PRIVATE 记忆仅返回给 owner | 权限隔离测试 |
| AC11 | 检索结果写入 Trace 事件 | 追踪测试 |
| AC12 | p95 检索延迟 < 200ms | 性能测试 |
| AC13 | NDCG@10 > 0.75 | Golden Dataset 评测 |
| AC14 | 冲突自动解决率 > 80% | 冲突统计测试 |
| AC15 | 与 REQ-CTX-006 正确集成 | 集成测试 |

---

## 15. 依赖与跨模块接口

### 15.1 前置依赖

| 依赖编号 | 依赖内容 | 接口要求 |
|----------|----------|----------|
| REQ-MEM-001 | Memory Schema | 复用 Memory、ConfidenceScore、MemoryLifecycle |
| REQ-CTX-006 | Context Selector 与预算 | 复用 L1/L2/L3 渐进暴露模型 |
| REQ-CTX-004 | 混合检索与排序 | 复用向量检索、BM25 算法思路 |
| REQ-SEC-002 | RBAC 授权 | 复用权限校验接口 |

### 15.2 下游依赖

| 下游 | 接口 | 描述 |
|------|------|------|
| 记忆存储 | search(query, filters, top_k) | 底层检索 |
| 向量索引 | vector_search(embedding, top_k) | 语义检索 |
| 全文索引 | bm25_search(query, top_k) | 关键词检索 |
| 审计系统 | log(RetrievalEvent/ConflictEvent) | 写入审计事件 |

---

## 16. MVP 范围与后续扩展

### 16.1 MVP 包含

- L1/L2/L3 三层渐进披露
- 语义 + BM25 + 时序三信号混合排序（固定权重）
- 五维评分体系（固定权重）
- 符号检查器冲突检测
- 三种解决策略（AUTO_REJECT / AUTO_REPLACE / MANUAL_ARBITRATION）
- 协调冲突 KEEP_BOTH 策略
- 权限过滤
- 降级策略

### 16.2 Phase 2 扩展候选

| 扩展方向 | 触发条件 | 优先级 |
|----------|----------|--------|
| Cross-Encoder 重排 | 检索质量 NDCG@10 < 0.75 | P1 |
| 学习型权重调整 | 积累足够检索反馈数据 | P2 |
| LLM 语义冲突分析 | 符号检查误报率 > 5% | P2 |

---

## 17. 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1-designed | 2026-10-05 | 基于 Claude Code、Mem0 v3、Graphiti、LatticeMind、Kimi Mem 等行业标杆完成详细设计；定义三路并行检索、五维评分体系、三轨冲突分类、渐进披露、验收标准；待跨模块评审与冻结 |
