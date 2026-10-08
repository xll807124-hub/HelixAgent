# REQ-CTX-004: 混合检索与排序

> **需求编号**: REQ-CTX-004  
> **需求名称**: 混合检索与排序  
> **优先级**: P1  
> **所属模块**: 上下文管理（CTX）  
> **状态**: v0.1-designed  
> **设计日期**: 2026-10-03  
> **前置依赖**: REQ-CTX-001（索引实体和关系 Schema）、REQ-CTX-003（AST/LSP/依赖解析）

---

## 一、需求目标

### 1.1 功能目标

实现 BM25 关键词检索、向量语义检索、符号图结构检索的三路混合检索系统，提供高召回率、高精度排序的代码检索能力。

**核心交付**：
1. BM25F 多字段加权关键词检索
2. 向量语义检索（基于嵌入模型）
3. 符号图结构检索（基于调用关系和依赖关系）
4. RRF（Reciprocal Rank Fusion）融合策略
5. 可选的加权融合和 Cross-Encoder 重排

### 1.2 用户价值

| 价值维度 | 具体收益 |
|----------|----------|
| 任务成功率 | 多路召回覆盖不同查询意图，提升关键代码发现率 |
| 排序精度 | RRF 融合 + 可选重排确保相关结果排名靠前 |
| 查询体验 | 并行召回 + 异步重排保证低延迟（p95 < 500ms） |
| 可解释性 | 保留各路召回的原始分数和排名，便于调优 |

### 1.3 行业对标

本设计参考以下行业标杆：

| 产品 | 核心架构 | 关键技术 |
|------|----------|----------|
| **Sourcegraph** | 两阶段检索（BM25F 召回 + Cross-Encoder 重排） | BM25F 多字段加权、Transformer 重排 |
| **Cursor** | 向量 + 图中心性 + RRF 融合 | Merkle 树增量索引、图扩展 |
| **DeepSeek** | BM25 + 向量并行 + Cross-Encoder | 模块化服务、GPU 隔离 |
| **通义灵码** | 向量 + BM25 + 加权融合（0.7/0.3） | 本地 RAG、企业知识库 |
| **Qoder** | 六路并行召回 + RRF + 图扩展 | Agentic 检索编排、记忆图 |

---

## 二、设计范围

### 2.1 包含内容

1. ✅ BM25F 关键词检索（多字段加权）
2. ✅ 向量语义检索（基于嵌入模型）
3. ✅ 符号图结构检索（基于代码图）
4. ✅ RRF 融合策略（默认）
5. ✅ 加权融合策略（可配置）
6. ✅ Cross-Encoder 重排（可选）
7. ✅ 权限过滤
8. ✅ 敏感路径黑名单过滤
9. ✅ 链路追踪和指标监控

### 2.2 不包含内容（后续阶段）

1. ❌ Agentic 检索编排（Phase 3）
2. ❌ 学习型融合权重（Phase 3）
3. ❌ 多模态检索（文档 + 图表）（Phase 3）
4. ❌ 实时索引更新（依赖 REQ-CTX-007）

---

## 三、目标用户与使用场景

### 3.1 目标用户

| 用户类型 | 使用场景 |
|----------|----------|
| **AI Agent** | 执行任务时检索代码上下文 |
| **开发者** | 通过自然语言或代码片段搜索代码 |
| **平台运营** | 监控和调优检索质量 |

### 3.2 典型使用场景

| 场景 | 查询类型 | 推荐检索路径 |
|------|----------|-------------|
| 精确符号搜索 | "找到 `check_user_permission` 函数" | BM25 优先（精确匹配） |
| 语义理解搜索 | "处理用户认证的代码" | 向量检索优先 |
| 结构导航 | "哪些函数调用了这个方法" | 图检索优先 |
| 混合意图 | "修复登录权限检查的逻辑" | 三路并行 + RRF |
| 低延迟场景 | 实时补全 | 仅向量或仅 BM25 |

### 3.3 用户故事

**用户故事 1：Bug 修复场景**

```
作为 AI Agent
我需要在修复 bug 时找到所有相关的代码
以便理解问题上下文并实施修复

场景：用户报告"用户登出后权限缓存未清除"
流程：
1. Agent 发送查询："用户登出后权限缓存未清除"
2. 检索服务并行执行三路召回
3. RRF 融合结果，Top-20 候选
4. 权限过滤（移除未授权文件）
5. 返回排序后的代码块列表
6. Agent 基于上下文实施修复
```

**用户故事 2：功能扩展场景**

```
作为 AI Agent
我需要在添加新功能时找到依赖的模块
以便理解现有架构并扩展实现

场景：添加"社交分享"功能到现有系统
流程：
1. Agent 发送查询："社交分享" + seed_symbols=["share", "SocialShare"]
2. 图检索扩展：找到 share 相关的调用链
3. 向量检索：找到语义相关的代码
4. BM25：精确匹配 "share" 相关文件
5. RRF 融合 + 依赖过滤
6. 返回结构化的依赖图和代码上下文
```

---

## 四、输入与输出定义

### 4.1 输入定义

```typescript
interface RetrievalQuery {
  // 查询内容
  query_text: string;                    // 自然语言查询或代码片段
  seed_symbols?: string[];               // 可选：种子符号列表（用于图检索）
  
  // 版本绑定
  repository_id: string;                 // 仓库 ID
  source_revision: string;               // Git commit SHA
  
  // 权限上下文
  user_id: string;
  organization_id: string;
  
  // 检索配置
  config: RetrievalConfig;
  
  // 分页
  pagination: Pagination;
}

interface RetrievalConfig {
  // 各路召回配置
  bm25: BM25Config;
  vector: VectorConfig;
  graph: GraphConfig;
  
  // 融合策略
  fusion_strategy: FusionStrategy;
  
  // Top-K 配置
  recall_top_k: number;                 // 召回阶段 Top-K（默认 50）
  final_top_k: number;                  // 最终返回 Top-K（默认 20）
}

interface BM25Config {
  enabled: boolean;                     // 是否启用（默认 true）
  fields: BM25FieldConfig[];           // 字段权重配置
  top_k: number;                       // 召回数量（默认 30）
}

interface BM25FieldConfig {
  field: 'symbol_name' | 'file_path' | 'docstring' | 'code_content';
  weight: number;                      // 权重（默认 1.0）
}

interface VectorConfig {
  enabled: boolean;                     // 是否启用（默认 true）
  embedding_model: string;              // 嵌入模型
  top_k: number;                        // 召回数量（默认 30）
  min_score?: number;                   // 最低相似度阈值
}

interface GraphConfig {
  enabled: boolean;                     // 是否启用（默认 true）
  max_depth: number;                    // 图遍历深度（默认 2）
  max_breadth: number;                  // 每层最大广度（默认 10）
  traverse_directions: ('caller' | 'callee')[];
}

interface FusionStrategy {
  type: 'RRF' | 'WEIGHTED' | 'CROSS_ENCODER';
  
  // RRF 配置
  rrf_k?: number;                      // RRF 平滑参数（默认 60）
  
  // 加权融合配置
  weights?: {
    bm25: number;
    vector: number;
    graph: number;
  };
  
  // Cross-Encoder 配置
  reranker_model?: string;
  reranker_top_k?: number;
}
```

### 4.2 输出定义

```typescript
interface RetrievalResult {
  // 查询信息
  query_id: string;
  query_text: string;
  timestamp: Timestamp;
  
  // 版本信息
  repository_id: string;
  source_revision: string;
  
  // 检索结果
  items: RetrievalItem[];
  total_candidates: number;
  
  // 融合信息
  fusion: FusionMetadata;
  
  // 性能指标
  metrics: RetrievalMetrics;
}

interface RetrievalItem {
  item_id: string;
  chunk_id: string;
  entity_type: 'file' | 'symbol' | 'dependency';
  content: CodeChunk;
  fusion_score: number;
  recall_info: {
    bm25_rank?: number;
    bm25_score?: number;
    vector_rank?: number;
    vector_score?: number;
    graph_rank?: number;
    graph_score?: number;
  };
  relevance_score?: number;
}
```

---

## 五、处理逻辑与流程

### 5.1 总体流程图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            检索请求流程                                  │
└─────────────────────────────────────────────────────────────────────────┘

  User/Agent Query
         │
         ▼
┌─────────────────┐
│ 查询预处理       │
│ - 意图检测       │
│ - 权重调整       │
└────────┬────────┘
         │
         ▼
┌─────────────────┬─────────────────┬─────────────────┐
│    BM25 召回    │    向量召回      │     图召回       │
│    (并行)       │    (并行)       │    (并行)       │
└────────┬────────┴────────┬────────┴────────┬────────┘
         │                  │                  │
         ▼                  ▼                  ▼
┌─────────────────┬─────────────────┬─────────────────┐
│  Top-30 排名    │  Top-30 排名    │  Top-30 排名    │
│  + 分数         │  + 分数         │  + 分数         │
└────────┬────────┴────────┬────────┴────────┬────────┘
         │                  │                  │
         └──────────────────┼──────────────────┘
                            ▼
                   ┌─────────────────┐
                   │   RRF 融合      │
                   │   Top-50       │
                   └────────┬────────┘
                            │
                            ▼
                   ┌─────────────────┐
                   │  权限过滤       │
                   │  黑名单过滤     │
                   └────────┬────────┘
                            │
                            ▼
                   ┌─────────────────┐
                   │ Cross-Encoder   │ ← 可选阶段
                   │   重排 Top-20   │
                   └────────┬────────┘
                            │
                            ▼
                   ┌─────────────────┐
                   │   检索结果       │
                   │   返回给用户    │
                   └─────────────────┘
```

### 5.2 阶段 1：查询预处理

```
1.1 解析查询文本
    - 提取自然语言部分
    - 提取代码片段（如果有）
    - 提取符号名称（正则匹配 camelCase、snake_case）

1.2 检测查询意图
    - 精确符号查询：包含完整函数名/类名
    - 语义描述查询：自然语言描述
    - 结构导航查询：包含 "调用"、"依赖"、"继承" 等关键词
    - 混合意图查询：其他

1.3 意图驱动的召回权重调整
    - 精确符号：BM25 权重提高
    - 语义描述：向量权重提高
    - 结构导航：图权重提高
```

### 5.3 阶段 2：并行多路召回

```
2.1 BM25 召回
    - 索引字段：symbol_name（权重 2.0）、file_path（权重 1.5）、
                docstring（权重 1.0）、code_content（权重 0.5）
    - 算法：BM25F（字段加权 BM25）
    - 参数：k1=1.5, b=0.75
    - Top-K：30（可配置）

2.2 向量召回
    - 嵌入模型：text-embedding-3-small 或同等性能模型
    - 索引：pgvector 或 Qdrant
    - 相似度度量：Cosine
    - Top-K：30（可配置）

2.3 图召回
    - 从 seed_symbols 开始（如果有）
    - 遍历 CALLS、USES_TYPE、EXTENDS、IMPLEMENTS 边
    - 深度限制：2（可配置）
    - 广度限制：每层 10 个节点（可配置）
    - 方向：双向（调用者和被调用者）

2.4 并行执行
    - 三路召回并行执行
    - 使用 Promise.all 或类似机制
    - 超时控制：单路超时 2s，整体超时 3s
```

### 5.4 阶段 3：结果融合

```
3.1 RRF 融合（默认策略）
    - 对每路召回结果按排名分配分数
    - RRF 公式：score(d) = Σ 1/(k + rank_i(d))
    - 参数 k=60（平滑参数）
    - 合并多路排名得分

3.2 加权融合（可选策略）
    - 公式：score(d) = w1*BM25(d) + w2*Vector(d) + w3*Graph(d)
    - 默认权重：w1=0.3, w2=0.5, w3=0.2
    - 可根据查询意图动态调整

3.3 Cross-Encoder 重排（可选阶段）
    - 候选集：RRF 融合后的 Top-20
    - 模型：BAAI/bge-reranker-v2-m3 或同等性能模型
    - 对每个 (query, chunk) 对进行联合编码
    - 输出一元分数，重新排序
```

### 5.5 阶段 4：权限过滤

```
4.1 权限检查
    - 验证用户对仓库的访问权限
    - 验证用户对文件路径的访问权限

4.2 敏感路径过滤
    - 移除包含敏感路径的结果
    - 黑名单：.env、.aws/、.ssh/、credentials/、*.key、*.pem

4.3 过滤后重排序
    - 如果过滤导致结果不足，补充召回
    - 记录过滤原因用于审计
```

### 5.6 阶段 5：后处理与返回

```
5.1 去重
    - 按 file_path + start_line 去重
    - 保留融合分数最高的结果

5.2 上下文组装
    - 添加相邻代码行（增强可读性）
    - 添加符号签名和文档字符串

5.3 结果封装
    - 包装为 RetrievalResult
    - 添加元数据和性能指标
```

---

## 六、算法设计分析

### 6.1 BM25F 算法

BM25F 是 BM25 的多字段扩展，适用于结构化文档检索。

**核心公式**：

```
BM25F(d) = Σ_t [ IDF(t) × (tf_F(t,d) × (k1+1)) / (tf_F(t,d) + k1 × (1-b + b × |d|/avgdl)) ]

其中：
- t: 词项
- IDF(t): 逆文档频率
- tf_F(t,d): 字段加权词频
- k1: 词频饱和参数（默认 1.5）
- b: 文档长度归一化参数（默认 0.75）
- |d|: 文档长度
- avgdl: 平均文档长度
```

**字段权重配置**：

| 字段 | 权重 | 理由 |
|------|------|------|
| symbol_name | 2.0 | 精确匹配最重要 |
| file_path | 1.5 | 路径包含语义信息 |
| docstring | 1.0 | 文档提供上下文 |
| code_content | 0.5 | 代码内容辅助匹配 |

**参考来源**：
- Sourcegraph BM25F 实现：https://sourcegraph.com/blog/keeping-it-boring-and-relevant-with-bm25f
- 访问日期：2026-09-30

### 6.2 向量检索算法

**嵌入策略**：
- 文件级嵌入：文件路径 + 主要符号 + 摘要
- 符号级嵌入：符号签名 + 文档 + 上下文
- 查询嵌入：使用相同模型

**相似度度量**：

```
cosine_similarity(a, b) = (a · b) / (||a|| × ||b||)
```

**HNSW 索引参数**：
- M（连接数）：16
- efConstruction：200
- efSearch：100

**参考来源**：
- Cursor 向量索引实现：https://cursor.com/blog/secure-codebase-indexing
- 访问日期：2026-09-30

### 6.3 图检索算法

**图遍历策略**：

```
Input: seed_symbols, max_depth, max_breadth
Output: related_symbols with scores

1. Initialize queue with seed_symbols
2. Initialize visited set
3. Initialize scores map

4. While queue not empty:
   a. Pop node (symbol)
   b. If depth > max_depth: continue
   c. For each edge in outgoing_edges(node):
      - If target not visited or score improved:
        - Calculate edge weight (CALLS=1.0, USES_TYPE=0.8, EXTENDS=0.6)
        - Calculate node score = parent_score × edge_weight
        - Add to queue with depth+1
        - Update scores[target]

5. Return sorted(scores, by=score, reverse=True)
```

**参考来源**：
- Qoder 图检索实现：https://www.alibabacloud.com/blog/codebase-aware-code-retrieval-a-hybrid-approach-for-ai-coding_603326
- 访问日期：2026-09-30

### 6.4 RRF 融合算法

```
Input: result_lists[BM25, Vector, Graph], k=60
Output: fused_scores

1. Initialize fused_scores map

2. For each result_list in result_lists:
   a. For rank, item in enumerate(result_list):
      - rrf_score = 1 / (k + rank)
      - fused_scores[item] += rrf_score

3. Return sorted(fused_scores, by=score, reverse=True)
```

**参数说明**：
- k=60：平滑参数，降低顶级结果的优势，提升融合鲁棒性

**参考来源**：
- RRF 算法原理：https://www.vectorian.be/articles/2026-03-05/all-i-wanted-was-a-simple-code-search/
- 访问日期：2026-09-30

### 6.5 Cross-Encoder 重排算法

**模型输入**：

```
[CLS] query_text [SEP] code_chunk [SEP]
```

**评分**：

```
score = sigmoid(linear(query_chunk_embedding))
```

**重排流程**：

```
1. 获取 Top-20 候选（RRF 融合后）
2. 批量编码 (query, chunk) 对
3. 获取重排分数
4. 按分数降序排列
5. 返回 Top-K 结果
```

**参考来源**：
- DeepSeek Cross-Encoder 重排：https://markaicode.com/architecture/hybrid-retrieval-architecture-with-deepseek/
- 访问日期：2026-09-30

---

## 七、异常与失败处理

### 7.1 异常分类与处理策略

| 异常类型 | 检测条件 | 处理策略 | 降级方案 |
|----------|----------|----------|----------|
| BM25 超时 | > 2s | 返回部分结果 | 仅使用向量+图 |
| 向量检索超时 | > 2s | 返回部分结果 | 仅使用 BM25+图 |
| 图检索超时 | > 2s | 返回部分结果 | 仅使用 BM25+向量 |
| 全链路超时 | > 3s | 返回缓存结果或空 | 返回空 + 告警 |
| 权限过滤失败 | 权限服务不可用 | fail-closed | 拒绝全部结果 |
| 图数据库不可用 | 连接失败 | 使用缓存或降级 | 仅使用 BM25+向量 |
| 向量索引不可用 | 连接失败 | 使用缓存或降级 | 仅使用 BM25+图 |
| 融合失败 | 候选列表为空 | 返回空结果 | - |
| Cross-Encoder 失败 | 模型调用失败 | 跳过重排 | 使用 RRF 结果 |

### 7.2 错误码定义

| 错误码 | 含义 | HTTP 状态码 |
|--------|------|-------------|
| RET-001 | 查询解析失败 | 400 |
| RET-002 | 仓库不存在 | 404 |
| RET-003 | 仓库无索引 | 404 |
| RET-004 | 版本不存在 | 404 |
| RET-005 | 权限不足 | 403 |
| RET-006 | 检索超时 | 504 |
| RET-007 | 内部错误 | 500 |

---

## 八、权限、安全与合规

### 8.1 权限模型

- **仓库级权限**：用户必须对仓库有读取权限
- **路径级权限**：用户必须对文件路径有读取权限
- **符号级权限**：继承文件权限

### 8.2 安全控制

| 控制点 | 措施 |
|--------|------|
| 输入验证 | 查询文本长度限制（≤ 1000 字符） |
| 注入防护 | 查询文本转义，防止 Prompt 注入 |
| 审计日志 | 所有检索请求记录审计日志 |
| 敏感数据 | 黑名单路径不索引、不返回 |
| 速率限制 | 每用户/每仓库 QPS 限制 |

### 8.3 敏感路径黑名单

| 路径模式 | 说明 |
|---------|------|
| `.env` | 环境变量配置 |
| `.env.*` | 环境变量变体 |
| `secrets/` | 密钥目录 |
| `credentials/` | 凭据目录 |
| `*.key` | 私钥文件 |
| `*.pem` | 证书文件 |
| `.aws/` | AWS 配置 |
| `.ssh/` | SSH 密钥 |

### 8.4 合规要求

| 要求 | 实现 |
|------|------|
| 数据驻留 | 索引数据存储在用户所在区域 |
| 留存策略 | 查询日志 30 天热存储 + 180 天冷存储 |
| 删除响应 | Git SHA 回退时，相关索引立即失效 |

---

## 九、性能、成本、延迟考量

### 9.1 延迟预算

| 阶段 | 预算 | 说明 |
|------|------|------|
| 查询预处理 | 5ms | 意图检测、权重调整 |
| BM25 召回 | 50ms | 含网络往返 |
| 向量召回 | 100ms | 含 ANN 查询 |
| 图召回 | 50ms | 含图遍历 |
| RRF 融合 | 5ms | 内存计算 |
| 权限过滤 | 20ms | RPC 调用 |
| Cross-Encoder | 150ms | GPU 推理（可选） |
| **总计** | **430ms** | 含缓冲，SLO p95 ≤ 500ms |

### 9.2 成本估算

| 组件 | 单次查询成本 | 优化策略 |
|------|-------------|----------|
| 向量嵌入 | $0.0001/1K tokens | 批量处理、缓存查询嵌入 |
| Cross-Encoder | $0.001/20 pairs | 仅对 Top-20 候选重排 |
| 向量存储 | $0.25/1M vectors/month | 按仓库分区、冷热分离 |
| 图存储 | $0.10/100K nodes/month | 定期清理过期数据 |

### 9.3 扩展性设计

| 规模 | 仓库规模 | 索引策略 | QPS 能力 |
|------|----------|----------|----------|
| SMALL | < 100 文件 | 全量索引，内存缓存 | 100 QPS |
| MEDIUM | 100-1000 文件 | 全量索引，Redis 缓存 | 50 QPS |
| LARGE | 1000-10000 文件 | 分片索引，L1 缓存 | 20 QPS |

---

## 十、可观测性与评估指标

### 10.1 核心指标

| 指标 | 定义 | SLO | 告警阈值 |
|------|------|-----|----------|
| retrieval_latency_p50 | p50 检索延迟 | < 200ms | > 300ms |
| retrieval_latency_p95 | p95 检索延迟 | < 500ms | > 800ms |
| retrieval_latency_p99 | p99 检索延迟 | < 1000ms | > 1500ms |
| retrieval_qps | 检索吞吐量 | > 50 QPS | < 20 QPS |
| recall_rate@10 | Recall@10 | > 0.9 | < 0.8 |
| mrr | MRR | > 0.7 | < 0.6 |
| fusion_coverage | 多路召回覆盖率 | > 0.95 | < 0.9 |
| error_rate | 错误率 | < 0.01 | > 0.05 |

### 10.2 链路追踪

每个检索请求生成唯一 `trace_id`，追踪：
- 各路召回耗时
- 融合计算耗时
- 权限过滤耗时
- 重排耗时（如果有）

### 10.3 质量评估

| 评估类型 | 频率 | 方法 |
|----------|------|------|
| 离线评测 | 每周 | Golden Dataset + 人工标注 |
| 在线 A/B | 持续 | 分流实验 + 转化率对比 |
| 用户反馈 | 实时 | 结果相关性反馈 |
| 回归测试 | 每次发布 | 固定测试集回归 |

---

## 十一、验收标准

### 11.1 功能验收

| 编号 | 验收标准 | 验证方法 |
|------|----------|----------|
| CTX-004-F001 | 支持 BM25 关键词检索 | 单测 + 集成测试 |
| CTX-004-F002 | 支持向量语义检索 | 单测 + 集成测试 |
| CTX-004-F003 | 支持图结构检索 | 单测 + 集成测试 |
| CTX-004-F004 | 支持 RRF 融合 | 单测验证融合分数 |
| CTX-004-F005 | 支持加权融合（可配置） | 配置变更测试 |
| CTX-004-F006 | 支持 Cross-Encoder 重排 | 集成测试 + 质量评估 |
| CTX-004-F007 | 支持版本绑定检索 | 跨版本检索测试 |
| CTX-004-F008 | 权限过滤正确执行 | 安全测试 |
| CTX-004-F009 | 敏感路径黑名单生效 | 安全测试 |

### 11.2 性能验收

| 编号 | 验收标准 | 验证方法 |
|------|----------|----------|
| CTX-004-P001 | p95 延迟 < 500ms | 性能测试，1000 次请求 |
| CTX-004-P002 | p99 延迟 < 1000ms | 性能测试 |
| CTX-004-P003 | 支持 50 QPS | 压力测试 |
| CTX-004-P004 | 增量索引不影响检索 | 并发测试 |

### 11.3 质量验收

| 编号 | 验收标准 | 验证方法 |
|------|----------|----------|
| CTX-004-Q001 | Recall@10 > 0.9 | Golden Dataset 评测 |
| CTX-004-Q002 | MRR > 0.7 | Golden Dataset 评测 |
| CTX-004-Q003 | 融合覆盖率 > 0.95 | 日志分析 |

---

## 十二、依赖与接口

### 12.1 前置依赖

| 依赖编号 | 依赖内容 | 接口要求 |
|----------|----------|----------|
| REQ-CTX-001 | 索引实体和关系 Schema | IndexMetadata、SymbolNode、RelationEdge |
| REQ-CTX-003 | AST/LSP/依赖解析 | 符号名称、调用关系、依赖关系 |
| REQ-RT-006 | Trace 传播 | trace_id 生成和传播 |
| REQ-SEC-002 | RBAC 授权 | 权限检查接口 |
| REQ-SEC-008 | 多租户数据治理 | 租户隔离验证 |

### 12.2 外部接口

| 接口类型 | 说明 | 协议 |
|----------|------|------|
| 向量数据库 | 存储和检索向量嵌入 | HTTP/gRPC |
| 全文搜索引擎 | BM25 索引和检索 | HTTP |
| 图数据库 | 存储和遍历代码图 | HTTP/gRPC |
| 权限服务 | 权限检查 | HTTP/gRPC |
| 配置中心 | 融合参数管理 | HTTP |

### 12.3 内部接口

```typescript
// 检索服务接口
interface RetrievalService {
  // 主检索入口
  retrieve(query: RetrievalQuery): Promise<RetrievalResult>;
  
  // BM25 召回
  bm25Recall(query: BM25Query): Promise<BM25Result[]>;
  
  // 向量召回
  vectorRecall(query: VectorQuery): Promise<VectorResult[]>;
  
  // 图召回
  graphRecall(query: GraphQuery): Promise<GraphResult[]>;
  
  // 融合
  fuse(results: RecallResult[], config: FusionConfig): Promise<FusionResult[]>;
  
  // 重排
  rerank(candidates: FusionResult[], query: string): Promise<RerankedResult[]>;
}
```

---

## 十三、版本与演进计划

### 13.1 MVP 版本（Phase 1）

MVP 实现基础三路召回 + RRF 融合：
- ✅ BM25F 关键词检索
- ✅ 向量语义检索
- ✅ 图结构检索（基础版）
- ✅ RRF 融合
- ✅ 基础权限过滤

### 13.2 Phase 2 扩展

- Cross-Encoder 重排
- 意图驱动的动态权重
- 图扩展优化（循环检测、深度学习排序）
- 增量索引支持

### 13.3 Phase 3 优化

- Agentic 检索编排（参考 Qoder）
- 学习型融合权重
- 多模态检索（文档 + 图表）
- 实时索引更新

---

## 十四、对其它需求的影响

### 14.1 被依赖的待办

| 待办编号 | 待办名称 | 影响说明 |
|----------|----------|----------|
| REQ-CTX-005 | 检索权限与敏感路径 | CTX-004 已设计权限过滤，可直接复用接口 |
| REQ-CTX-006 | Context Selector 与预算 | CTX-004 的融合结果作为 CTX-006 的输入 |
| REQ-CTX-009 | 检索评测 | CTX-004 的指标体系支撑评测需求 |

### 14.2 潜在风险与缓解措施

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| 图检索延迟过高 | 中 | 高 | 增加超时控制，降级策略 |
| Cross-Encoder 成本高 | 中 | 中 | 仅对 Top-20 候选重排，批量处理 |
| 多路召回结果冲突 | 低 | 中 | RRF 融合平滑冲突，人工调参 |
| 索引新鲜度问题 | 中 | 中 | 依赖 REQ-CTX-007 增量索引 |

---

## 十五、参考资料

### 15.1 行业标杆文档

1. **Sourcegraph BM25F**  
   - URL: https://sourcegraph.com/blog/keeping-it-boring-and-relevant-with-bm25f  
   - 访问日期：2026-09-30  
   - 关键内容：BM25F 多字段加权、两阶段检索架构

2. **Cursor 安全索引**  
   - URL: https://cursor.com/blog/secure-codebase-indexing  
   - 访问日期：2026-09-30  
   - 关键内容：Merkle 树增量索引、图中心性排序

3. **DeepSeek 混合检索架构**  
   - URL: https://markaicode.com/architecture/hybrid-retrieval-architecture-with-deepseek/  
   - 访问日期：2026-09-30  
   - 关键内容：BM25 + 向量并行、Cross-Encoder 重排

4. **通义灵码架构设计**  
   - URL: https://developer.aliyun.com/article/1537722  
   - 访问日期：2026-09-30  
   - 关键内容：本地 RAG、向量 + BM25 融合

5. **Qoder Codebase-Aware 检索**  
   - URL: https://www.alibabacloud.com/blog/codebase-aware-code-retrieval-a-hybrid-approach-for-ai-coding_603326  
   - 访问日期：2026-09-30  
   - 关键内容：六路并行召回、Agentic 编排

### 15.2 学术论文

1. **Reciprocal Rank Fusion (RRF)**  
   - 论文：Cormack, G. V., Clarke, C. L., & Buettcher, S. (2009). Reciprocal rank fusion outperforms condorcet and individual rank learning methods.  
   - 说明：RRF 算法原理和应用

2. **BM25 算法**  
   - 论文：Robertson, S., & Zaragoza, H. (2009). The probabilistic relevance framework: BM25 and beyond.  
   - 说明：BM25 及其变体

### 15.3 技术工具文档

1. **pgvector**：PostgreSQL 向量扩展
2. **Qdrant**：向量数据库
3. **Meilisearch**：全文搜索引擎
4. **Neo4j**：图数据库
5. **BAAI/bge-reranker-v2-m3**：Cross-Encoder 重排模型

---

## 十六、变更记录

| 版本 | 日期 | 变更内容 | 作者 |
|------|------|----------|------|
| v0.1-designed | 2026-10-03 | 初始设计完成 | 架构团队 |

---

**文档结束**
