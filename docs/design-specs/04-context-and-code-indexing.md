# 上下文管理与代码索引设计规范

> 优先级：P1 - 阻塞代码任务质量  
> 状态：部分完成（REQ-CTX-001/002/003 已完成详细设计）  
> 依赖：运行时基础契约  
> 阻塞：代码理解、准确率提升

**已完成专项设计**：
- ✅ [REQ-CTX-001 索引实体和关系 Schema](./REQ-CTX-001-index-entities-schema.md)（v0.1-designed）
- ✅ [REQ-CTX-002 语言、仓库规模和基准集](./REQ-CTX-002-language-repository-scale-benchmark.md)（v0.1-designed）
- ✅ [REQ-CTX-003 AST/LSP/依赖解析](./REQ-CTX-003-ast-lsp-dependency-parsing.md)（v0.1-designed）
- ✅ [REQ-CTX-004 混合检索与排序](./REQ-CTX-004-hybrid-retrieval-ranking.md)（v0.1-designed）
- ✅ [REQ-CTX-005 检索权限与敏感路径](./REQ-CTX-005-retrieval-permissions-sensitive-paths.md)（v1.0-designed）
- ✅ [REQ-CTX-006 Context Selector 与预算](./REQ-CTX-006-context-selector-budget.md)（v0.1-designed）
- ✅ [REQ-CTX-007 增量索引一致性](./REQ-CTX-007-incremental-index-consistency.md)（v0.1-designed）
- ✅ [REQ-CTX-008 上下文压缩与分层加载](./REQ-CTX-008-context-compression-tiered-loading.md)（v0.1-designed）

**待设计专项**：
- REQ-CTX-009 检索评测

## 一、设计目标

建立基于评测数据的上下文管理和代码索引基线，确保检索质量、成本和任务正确率的平衡。

### 核心问题

当前只推荐了组合基线，但具体实现尚未确定：

- 首批支持哪些编程语言？
- 目标仓库规模是多少？
- 索引包含哪些实体和关系？
- BM25、向量、图检索如何组合和排序？
- Context Selector 如何分配 Token 预算？
- 上下文如何压缩？
- 索引如何增量更新？
- 如何处理检索权限过滤？
- 如何评估检索质量？

如果这些问题不明确，系统可能出现：

- 检索不到关键代码
- 上下文 Token 超限
- 索引延迟过高
- 检索结果不相关
- 无法验证改进效果

## 二、设计范围

### 支持语言（MVP）

**第一批次**（必须支持）：
- Python
- TypeScript / JavaScript
- Go

**第二批次**（视评测结果）：
- Java
- Rust
- C/C++

**选择理由**：
1. 覆盖最常见的 Web、后端、基础设施场景
2. 有成熟的 AST 和 LSP 工具
3. 开源生态丰富，便于构建测试集

### 目标仓库规模

> **详细设计**：完整的规模定义和基准集请参考 [REQ-CTX-002 语言、仓库规模和基准集](./REQ-CTX-002-language-repository-scale-benchmark.md)

| 规模 | 文件数 | 代码行数 | 典型场景 | MVP 支持 |
|------|--------|----------|----------|----------|
| SMALL | < 100 | < 10K | 单体服务、工具库 | ✓ |
| MEDIUM | 100-1000 | 10K-100K | 微服务、应用 | ✓ |
| LARGE | 1000-10K | 100K-1M | 单体应用、框架 | 部分 |
| XLARGE | > 10K | > 1M | Monorepo、操作系统 | 后续 |

**性能目标**（详见 REQ-CTX-003）：
- SMALL 仓库：全量索引 < 5s，增量 < 0.5s/文件
- MEDIUM 仓库：全量索引 < 30s，增量 < 1s/文件
- LARGE 仓库：全量索引 < 120s，增量 < 2s/文件

## 三、索引数据模型

> **详细设计**：完整的 Schema 定义请参考 [REQ-CTX-001 索引实体和关系 Schema](./REQ-CTX-001-index-entities-schema.md)

### 核心实体摘要

**关键设计原则**（借鉴 Sourcegraph SCIP、GitHub Copilot、Cursor）：
1. 每个实体绑定 `repository_id` 和 `source_revision`（版本追溯）
2. 符号采用 qualified name 标识（跨仓库唯一性）
3. 关系包含属性（权重、调用次数等）
4. 索引元数据追踪新鲜度（`indexed_at`、`index_version`）

#### 1. 文件（FileNode）

```typescript
interface FileNode {
  schema_version: string;        // "index.file.v1"
  file_id: string;               // UUIDv7
  repository_id: string;
  path: string;                  // 相对于仓库根目录
  language: string;
  size_bytes: number;
  lines_of_code: number;
  source_revision: string;       // Git commit SHA（不可变）
  file_hash: string;             // SHA-256 内容哈希
  indexed_at: Timestamp;
  index_version: string;
  embedding?: number[];
  embedding_model?: string;
  summary?: string;
  is_sensitive: boolean;         // 权限过滤支持
  metadata: SafeMetadata;
}
```

#### 2. 符号（SymbolNode）

```typescript
interface SymbolNode {
  schema_version: string;        // "index.symbol.v1"
  symbol_id: string;             // qualified symbol ID
  file_id: string;
  repository_id: string;
  name: string;                  // 短名称
  qualified_name: string;        // 完全限定名（如：com.example.UserService.login）
  kind: SymbolKind;              // function/class/interface/type/...
  signature?: string;            // 函数签名或类型签名
  docstring?: string;
  range: SourceRange;            // {start_line, start_column, end_line, end_column}
  visibility: Visibility;        // public/private/protected/internal
  owner?: string;                // 所属符号ID
  source_revision: string;
  embedding?: number[];
  embedding_model?: string;
  metadata: SafeMetadata;
}
```

#### 3. 依赖（DependencyNode）

```typescript
interface DependencyNode {
  schema_version: string;        // "index.dependency.v1"
  dependency_id: string;
  repository_id: string;
  package_name: string;
  version: string;
  version_constraint?: string;   // 版本约束（如：^1.0.0）
  source: DependencySource;      // direct/transitive
  ecosystem: Ecosystem;          // npm/pypi/go-mod/maven/cargo/...
  declared_in_file?: string;
  source_revision: string;
  metadata: SafeMetadata;
}
```

#### 4. 关系（RelationEdge）

```typescript
interface RelationEdge {
  schema_version: string;        // "index.relation.v1"
  relation_id: string;
  repository_id: string;
  relation_type: RelationType;   // 8 种类型（见下方）
  source_id: string;             // 源节点ID
  target_id: string;             // 目标节点ID
  weight?: number;               // 关系权重（图中心性排序）
  is_direct?: boolean;
  call_count?: number;           // 仅 CALLS 关系
  source_range?: SourceRange;
  source_revision: string;
  metadata: SafeMetadata;
}
```

### 关系类型枚举（RelationType）

| 关系类型 | 源→目标 | 说明 |
|----------|---------|------|
| **IMPORTS** | File → File | 文件导入关系 |
| **DEPENDS_ON** | Repository → Dependency | 依赖关系 |
| **DEFINES** | File → Symbol | 文件定义符号 |
| **CALLS** | Symbol → Symbol | 函数/方法调用 |
| **REFERENCES** | Symbol → Symbol | 符号引用（非调用） |
| **USES_TYPE** | Symbol → Symbol | 类型使用 |
| **EXTENDS** | Symbol → Symbol | 类继承 |
| **IMPLEMENTS** | Symbol → Symbol | 接口实现 |

### 索引元数据（IndexMetadata）

```typescript
interface IndexMetadata {
  schema_version: string;
  repository_id: string;
  source_revision: string;       // Git commit SHA
  index_version: string;         // 索引构建版本（如：idx-20260926-001）
  indexed_at: Timestamp;
  state: IndexState;             // PENDING/BUILDING/ACTIVE/STALE/...
  total_files: number;
  total_symbols: number;
  total_relations: number;
  language_distribution: Record<string, number>;
  build_duration_seconds: number;
  indexer_config: IndexerConfig;
}
```

### 增量索引机制

**Merkle 树变更检测**（借鉴 Cursor）：
```
Git Push → 计算新 Merkle 树
        → 与旧树对比获取变更文件
        → 重新解析变更文件 AST
        → 更新 Symbol 和 Relation
        → 更新向量索引
        → 更新 IndexMetadata
```

### 版本绑定与 Runtime Contract 集成

| Runtime 实体 | 索引实体 | 绑定字段 |
|--------------|----------|----------|
| Task.base_revision | IndexMetadata.source_revision | 版本一致性 |
| Worker.source_revision | RetrievalQuery.source_revision | 检索版本锁定 |
| Action | RetrievalResult | 检索结果可回放 |
| Artifact | RetrievedChunk | 产物绑定代码版本 |

### 图 Schema 示例

```text
Repository
  |
  +-- IndexMetadata (source_revision, index_version, state)
  |
  +-- FileNode (path, language, source_revision, is_sensitive)
       |
       +-- SymbolNode (qualified_name, kind, signature, visibility)
            |
            +-- CALLS --> SymbolNode
            +-- REFERENCES --> SymbolNode
            +-- USES_TYPE --> SymbolNode
            +-- EXTENDS --> SymbolNode
            +-- IMPLEMENTS --> SymbolNode
```

## 四、索引构建流程

> **详细设计**：完整的解析流程、LSP 部署、依赖解析、循环依赖处理请参考 [REQ-CTX-003 AST/LSP/依赖解析](./REQ-CTX-003-ast-lsp-dependency-parsing.md)

### 核心设计决策（基于行业标杆）

**1. LSP 部署模式**：每仓库独立 LSP 实例 + Redis 缓存层
- 借鉴 2026 年企业级部署标准
- 避免共享服务池的状态混乱问题
- Redis 缓存层共享常见库的类型信息

**2. 依赖解析精度**：直接依赖 + 一层传递依赖（MVP）
- 支持工程级跨文件上下文感知
- Phase 2 扩展到完整传递依赖图

**3. 循环依赖处理**：静默检测 + 图遍历深度限制
- 使用 Tarjan 算法检测强连通分量
- 不主动告警（避免误报）
- 图遍历时设置深度限制（默认 5 层）

### 阶段 1：代码解析（AST + LSP 协同）

#### 工具选择

| 语言 | AST 工具 | LSP 工具 | 解析策略 |
|------|----------|----------|----------|
| Python (TIER_1) | tree-sitter | pyright | AST + LSP 增强 |
| TypeScript (TIER_1) | tree-sitter | tsserver | AST + LSP 增强 |
| Go (TIER_1) | tree-sitter | gopls | AST + LSP 增强 |
| Java (TIER_2) | tree-sitter | - | 纯 AST |
| Rust (TIER_2) | tree-sitter | - | 纯 AST |
| C++ (TIER_2) | tree-sitter | - | 纯 AST |

**TIER_1 解析流程**（Python/TypeScript/Go）：
```
并行启动：
├── Thread 1: Tree-sitter AST 解析（快速提取结构）
└── Thread 2: LSP 服务器语义增强（类型信息）

合并结果：
├── 以 AST 为基础
└── 补充 LSP 语义（超时 5s 自动降级到纯 AST）
```

**Merkle 树增量检测**（O(log N)）：
```
Git Push → 计算新 Merkle 树
        → 与旧树对比获取变更文件
        → 重新解析变更文件 AST
        → 更新 Symbol 和 Relation
        → 原子提交索引更新
```

### 阶段 2：依赖分析

**依赖解析层级**（MVP）：
```
层级 0（直接依赖）：
  - package.json 中显式声明的依赖
  - requirements.txt 中声明的包
  
层级 1（一层传递依赖）：
  - 直接依赖的直接依赖
  - 覆盖 90% 查询场景
```

**依赖解析流程**：
```text
1. 识别包管理文件
   - package.json + package-lock.json (npm)
   - pyproject.toml + poetry.lock (Python)
   - go.mod + go.sum (Go)
   ↓
2. 提取直接依赖（层级 0）
   ↓
3. 解析 lockfile 获取一层传递依赖（层级 1）
   ↓
4. 构建依赖图并检测循环依赖（Tarjan SCC）
```

### 阶段 3：调用图构建与循环依赖检测

**调用图构建**：
```
1. 遍历 AST，识别函数调用节点
2. 使用符号表进行名称解析
3. 创建 CALLS 边（调用者 → 被调用者）
4. 记录调用次数（call_count）
```

**循环依赖检测**（Tarjan 算法）：
```
检测强连通分量（SCC）
  ↓
标记循环依赖组（cycle_id）
  ↓
不阻塞索引，仅记录元数据
  ↓
图遍历时设置深度限制（避免无限递归）
```

```text
1. 启动 LSP 服务器
   ↓
2. 查询符号定义（textDocument/definition）
   ↓
3. 查询符号引用（textDocument/references）
   ↓
4. 查询类型信息（textDocument/hover）
   ↓
5. 补充调用关系到图中
```

### 阶段 4：向量化

```text
1. 为每个文件生成摘要
   - 文件路径
   - 主要符号列表
   - 文档字符串汇总
   ↓
2. 使用嵌入模型生成向量
   - 推荐：OpenAI text-embedding-3-small
   - 或：Cohere embed-english-v3.0
   - 或：开源模型（如 jina-embeddings-v2）
   ↓
3. 为每个符号生成向量
   - 符号签名
   - 文档字符串
   - 上下文（所属文件、类）
   ↓
4. 存储向量到向量数据库
```

### 阶段 5：全文索引

```text
1. 为每个文件和符号建立全文索引
   ↓
2. 使用 BM25 算法
   ↓
3. 索引内容：
   - 文件路径
   - 符号名称
   - 文档字符串
   - 代码内容（可选）
   ↓
4. 存储到搜索引擎（Elasticsearch / Meilisearch）
```

## 五、检索策略

### 混合检索流程

> **完整设计**：混合检索与排序的完整技术方案请参考 [REQ-CTX-004 混合检索与排序](./REQ-CTX-004-hybrid-retrieval-ranking.md)

**基本架构**：

```text
用户查询（自然语言或代码片段）
  ↓
查询路由（exact_match / semantic / graph / hybrid）
  ↓
  +------------------+------------------+------------------+
  ↓                  ↓                  ↓                  ↓
BM25检索           Dense Vector      Graph遍历         权限过滤
(Tantivy)          (HNSW ANN)        (Call Graph)      (RBAC)
Top-K=100          Top-K=100         Top-K=100         Pre-fusion
  ↓                  ↓                  ↓                  ↓
  +------------------+------------------+------------------+
  ↓
Reciprocal Rank Fusion (RRF k=60)
score(d) = Σ wᵢ/(k + rankᵢ(d))
  ↓
[Optional] Cross-Encoder Reranker (Phase 2)
  ↓
Progressive Disclosure (L1→L2→L3)
  ↓
Context Selector（预算分配）
  ↓
最终上下文
```

**核心设计要点**（REQ-CTX-004）：

1. **三通道并行检索**：
   - **BM25F多字段评分**：`symbol_name`(×3.0), `filename`(×2.0), `docstring`(×1.5), `code`(×1.0)
   - **Dense Vector语义检索**：HNSW索引，cosine相似度，1536维嵌入
   - **Graph调用链遍历**：DFS深度3，Tarjan SCC防环，距离衰减0.8

2. **Reciprocal Rank Fusion（RRF）**：
   - 公式：$\text{score}(d) = \sum_{i=1}^{N} \frac{w_i}{k + rank_i(d)}$
   - 默认参数：$k=60$（大型仓库），$k=10\sim30$（小型仓库）
   - 权重配置：根据查询类型动态调整（exact_match: BM25=0.7/Graph=0.3; semantic: Vector=0.6/BM25=0.4; hybrid: 0.4/0.4/0.2）
   - 优势：无需分数归一化，鲁棒性强，可解释性高

3. **权限前置过滤**：
   - 在RRF融合前对每个通道结果执行RBAC检查
   - 批量权限检查 + 缓存（TTL=5分钟）
   - 零权限泄漏容忍度

4. **渐进式上下文暴露**：
   - **L1 Compact Summary**：文件路径 + 符号签名 + 一句话描述（~50 tokens）
   - **L2 Timeline Context**：符号定义 + 关键依赖 + 简化调用链（~200 tokens）
   - **L3 Full Code**：完整代码片段 + 注释 + 上下文行（~500-1000 tokens）
   - Token预算：20个结果 × L1 = 1000 tokens（初始），按需加载L2/L3

5. **性能与质量SLA**：
   - 端到端延迟：p50 < 200ms，p95 < 500ms
   - 质量指标：Recall@20 > 85%，Precision@5 > 75%，MRR > 0.70
   - 可观测性：来源标注、排序解释、Prometheus指标、审计日志

6. **行业对标**：
   - Cursor：语义+词法双通道，+12.5%准确率
   - GitHub Copilot：自研嵌入模型，37.6%召回提升
   - Anthropic：Contextual Retrieval减少49%失败率
   - Sourcegraph Zoekt：BM25F多字段评分
   - DeepSeek：BM25 + Qdrant + Cross-Encoder三阶段流水线

7. **演进路线**：
   - **Phase 1 - MVP（v0.1）**：BM25 + Vector + Graph + RRF + 权限过滤 + 渐进暴露
   - **Phase 2 - 质量增强（v1.0）**：Contextual Embeddings + Cross-Encoder重排 + 自适应权重调优
   - **Phase 3 - 规模化（v2.0）**：分布式检索 + 增量索引 + 多租户隔离 + 高级图算法

**实现参考**：

### 关键词检索（BM25）

**适用场景**：
- 查询包含明确的符号名、文件名
- 用户描述包含技术术语

**实现**：
```python
def keyword_search(query: str, top_k: int = 100) -> List[Result]:
    # 使用 BM25F 算法，多字段加权
    # 搜索字段权重：
    # - symbol_name: 3.0
    # - file_path: 2.0
    # - docstring: 1.5
    # - code: 1.0
    # 返回分数最高的 top_k 个结果
    pass
```

**权重**（BM25F多字段评分）：
- 符号名称匹配：3.0x
- 文件路径匹配：2.0x
- 文档字符串匹配：1.5x
- 代码内容匹配：1.0x

### 向量检索（Embedding）

**适用场景**：
- 查询是语义描述（如"处理用户认证的代码"）
- 查询是代码片段或伪代码

**实现**：
```python
def vector_search(query: str, top_k: int = 100) -> List[Result]:
    # 1. 将查询向量化
    query_embedding = embed(query)
    
    # 2. 在向量数据库中搜索（HNSW ANN）
    results = vector_db.search(
        query_embedding,
        top_k=top_k,
        metric="cosine"  # 或 "dot_product"
    )
    
    return results
```

**向量数据库选型**：
- Qdrant（推荐，支持权限标签过滤）
- Pinecone（托管）
- Weaviate（自托管）
- pgvector（PostgreSQL 扩展）

### 图遍历（Symbol Graph）

**适用场景**：
- 需要理解调用链
- 需要找到某个函数的所有调用者
- 需要理解类的继承关系

**实现**：
```python
def graph_search(seed_symbols: List[str], depth: int = 2) -> List[Result]:
    # 1. 从种子符号开始
    # 2. 遍历 CALLS, USES_TYPE, EXTENDS 关系
    # 3. 返回相关符号和文件
    pass
```

**遍历策略**：
- 深度：1-2 层（避免过度扩展）
- 方向：双向（调用者和被调用者）
- 边权重：根据关系类型

### 重排序（Reranking）

合并三种检索结果后，使用更精确的模型重新排序：

**选项 1：基于规则**
```python
def rerank_by_rules(results: List[Result], query: str) -> List[Result]:
    for r in results:
        score = r.base_score
        
        # 文件名包含关键词
        if query_keyword in r.file_path:
            score *= 1.5
        
        # 符号名精确匹配
        if r.symbol_name == query_keyword:
            score *= 2.0
        
        # 最近修改的文件
        if r.last_modified > threshold:
            score *= 1.2
        
        # 高可见性（public）
        if r.visibility == "public":
            score *= 1.1
        
        r.reranked_score = score
    
    return sorted(results, key=lambda r: r.reranked_score, reverse=True)
```

**选项 2：使用 Rerank 模型**
- Cohere Rerank API
- 自训练 Cross-Encoder
- 基于 LLM 的相关性判断

### Context Selector（预算分配）

根据 Token 预算，智能选择包含哪些代码：

```python
def select_context(
    ranked_results: List[Result],
    budget: int = 8000  # Token 预算
) -> Context:
    context = Context()
    remaining_budget = budget
    
    # 优先级规则
    priorities = [
        ("exact_match", 0.4),      # 精确匹配文件/符号
        ("high_relevance", 0.3),   # 高相关度
        ("dependencies", 0.2),     # 依赖和调用关系
        ("documentation", 0.1)     # 文档和注释
    ]
    
    for priority_type, budget_ratio in priorities:
        allocated = remaining_budget * budget_ratio
        items = filter_by_priority(ranked_results, priority_type)
        
        for item in items:
            cost = estimate_tokens(item)
            if cost <= allocated:
                context.add(item)
                allocated -= cost
    
    return context
```

**策略**：
1. 完整包含高相关度文件（< 200 行）
2. 只包含相关符号（对于大文件）
3. 包含文件路径和符号签名（即使无法包含完整代码）
4. 包含调用链（如果预算允许）
5. 包含文档字符串和注释

## 六、权限过滤

> **完整设计**：检索权限与敏感路径过滤的详细方案请参考 [REQ-CTX-005 检索权限与敏感路径](./REQ-CTX-005-retrieval-permissions-sensitive-paths.md)

### 过滤时机

**关键原则**：**零信任预过滤检索**（Zero-Trust Pre-filter Retrieval）—— 权限过滤必须在检索阶段执行，而不是在结果展示阶段。

```text
用户查询
  ↓
1. 多租户隔离检查（organization_id, team_id）
  ↓
2. RBAC 权限校验（SEC-002）
  ↓
3. 三级敏感路径过滤（Level 1/2/3）
  ↓
4. 构造分区检索查询（Pre-filter）
  ↓
5. 执行检索（仅返回授权且非敏感的结果）
  ↓
6. 审计日志记录
```

### 核心设计（REQ-CTX-005）

**1. 三级敏感路径过滤**：
- **Level 1（硬编码基线，不可绕过）**：`.env*`, `*.pem`, `*.key`, `.ssh/`, `secrets/`, `*.sql` 等
- **Level 2（组织级规则）**：管理员配置的企业安全策略
- **Level 3（项目级规则）**：项目所有者通过 `.aiagentignore` 配置

**2. Fail-Secure 策略**：
- 权限服务超时 → **DENY**
- Redis 缓存失效 → **降级查询权限服务**
- 敏感路径规则加载失败 → **仅应用 Level 1 基线**
- 多租户 ID 缺失 → **DENY**

**3. 多租户数据隔离**（集成 SEC-008）：
- **物理分区**（推荐）：`vectors_{organization_id}`, `code_{organization_id}`, `graph_{organization_id}`
- **逻辑分区**（备选）：单一索引 + Payload Filter `organization_id = ?`

**4. RBAC 权限校验**（集成 SEC-002）：
- **Deny > Ask > Allow** 优先级
- `allowed_repositories`, `allowed_paths`, `denied_paths`
- 支持 Exact / Prefix / Glob / Regex 匹配模式

**5. 审计与可观测性**：
- 审计日志字段：`trace_id`, `query_text`, `total_candidates`, `filtered_count`, `denied_reasons`, `latency_ms`
- Prometheus Metrics：`retrieval_queries_total`, `retrieval_sensitive_path_filtered_total`, `retrieval_permission_denied_total`
- OpenTelemetry Trace：跨服务追踪权限校验链路

**6. 性能优化**：
- Redis 缓存：用户权限（TTL=300s）、组织敏感路径（TTL=300s）、项目敏感路径（TTL=600s）
- Trie 树 + Bloom Filter：快速路径匹配（P99 延迟 < 50ms）
- 批量权限校验：减少数据库往返

### 实现参考

**Pre-filter 查询改写示例（Qdrant）**：

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

### 合规性

- **SOC2 Type II**：CC6.1（访问控制）、CC7.2（审计日志）
- **ISO27001**：A.9.4.1（访问策略）、A.12.4.1（审计保留 90 天）
- **GDPR**：审计日志脱敏，用户删除时级联删除关联记录

## 七、增量索引

### 触发时机

- Git push 后
- 手动触发重新索引
- 定期全量索引（每周）

### 增量更新流程

```text
1. 接收 Git webhook
   ↓
2. 获取变更的文件列表
   - git diff HEAD~1 HEAD --name-only
   ↓
3. 分类文件变更
   - 新增文件
   - 修改文件
   - 删除文件
   ↓
4. 重新解析变更文件
   ↓
5. 更新图结构
   - 删除旧符号和关系
   - 添加新符号和关系
   ↓
6. 更新向量索引
   - 删除旧向量
   - 添加新向量
   ↓
7. 更新全文索引
   ↓
8. 记录索引版本
   - index_version: git_sha
   - indexed_at: timestamp
```

### 一致性保证

**问题**：索引更新时，任务可能正在使用旧索引。

**方案**：
1. 索引版本绑定到 Git SHA
2. 任务创建时记录 `source_revision`
3. 检索时使用对应版本的索引
4. 保留最近 N 个版本的索引（如最近 10 个 commit）

### 索引失败处理

- 记录失败原因和文件
- 告警开发者
- 回退到上一个成功的索引版本
- 下次 push 时重试

## 八、上下文压缩

### 压缩时机

- 对话历史过长（> 10 轮）
- 上下文超过预算（> 8K tokens）
- 用户主动请求压缩

### 压缩策略

#### 策略 1：摘要压缩

```python
def compress_context(full_context: Context) -> Context:
    # 保留最近 3 轮完整对话
    recent = full_context[-3:]
    
    # 压缩更早的对话为摘要
    earlier = full_context[:-3]
    summary = llm.summarize(earlier, max_tokens=500)
    
    return Context([summary] + recent)
```

#### 策略 2：符号级压缩

对于大文件，只保留：
- 文件路径
- 符号签名（函数名、参数、返回类型）
- 文档字符串
- 关键逻辑（如主循环、条件分支）

移除：
- 注释（如果非关键）
- 日志语句
- 错误处理（如果非关键）
- 空行和格式

#### 策略 3：分层加载

```text
第一层（必须包含）：
  - 任务描述
  - 相关文件路径
  - 符号签名
  
第二层（预算允许时）：
  - 符号完整实现
  - 调用关系
  
第三层（预算充足时）：
  - 相关测试
  - 文档
  - 示例
```

## 九、评估方法

### 评测数据集

#### Golden Dataset v1

**内容**：
- 100 个真实编码任务（脱敏）
- 涵盖小、中、大型仓库
- 涵盖 Python、TypeScript、Go
- 人工标注"必需文件"和"相关符号"

**格式**：
```json
{
  "task_id": "task_001",
  "repository": "example/repo",
  "language": "python",
  "query": "修复用户登录时的权限检查逻辑",
  "ground_truth": {
    "required_files": [
      "src/auth/login.py",
      "src/auth/permissions.py"
    ],
    "required_symbols": [
      "check_user_permission",
      "validate_login"
    ]
  },
  "relevance_scores": {
    "src/auth/login.py": 1.0,
    "src/auth/permissions.py": 0.9,
    "tests/test_auth.py": 0.7
  }
}
```

### 评估指标

#### 1. 检索质量

**Recall@K**：检索到的前 K 个结果中，包含多少必需文件/符号。

```python
def recall_at_k(retrieved: List[str], ground_truth: List[str], k: int) -> float:
    top_k = retrieved[:k]
    hits = len(set(top_k) & set(ground_truth))
    return hits / len(ground_truth)
```

**目标**：
- Recall@5 > 0.8
- Recall@10 > 0.9

**Precision@K**：检索到的前 K 个结果中，有多少是相关的。

```python
def precision_at_k(retrieved: List[str], ground_truth: List[str], k: int) -> float:
    top_k = retrieved[:k]
    hits = len(set(top_k) & set(ground_truth))
    return hits / k
```

**目标**：
- Precision@5 > 0.6

**MRR（Mean Reciprocal Rank）**：第一个相关结果的排名倒数的平均值。

```python
def mrr(retrieved: List[str], ground_truth: List[str]) -> float:
    for i, item in enumerate(retrieved):
        if item in ground_truth:
            return 1 / (i + 1)
    return 0
```

**目标**：
- MRR > 0.7

#### 2. 上下文成本

**Token 使用率**：实际使用 Token / 预算 Token

**目标**：
- 80% - 95%（既不浪费，也不溢出）

**相关度加权 Token**：只计算相关代码的 Token

```python
def weighted_tokens(context: Context, relevance_scores: Dict[str, float]) -> float:
    total = 0
    for item in context:
        tokens = estimate_tokens(item)
        relevance = relevance_scores.get(item.id, 0)
        total += tokens * relevance
    return total
```

**目标**：相关度加权 Token 占比 > 0.7

#### 3. 端到端任务正确率

**Task Success Rate**：使用检索上下文后，任务是否成功完成。

**评估方式**：
1. 使用检索上下文A运行任务
2. 使用完美上下文（包含所有必需文件）运行任务
3. 对比成功率

**目标**：
- 检索上下文任务成功率 / 完美上下文任务成功率 > 0.9

#### 4. 检索延迟

**p50, p95, p99 延迟**

**目标**：
- p50 < 200ms
- p95 < 500ms
- p99 < 1s

### 对照实验

**基线方案**：
- Baseline 1: 只使用 BM25
- Baseline 2: 只使用向量检索
- Baseline 3: 随机选择文件

**推荐方案**：
- Hybrid 1: BM25 + Vector（等权重）
- Hybrid 2: BM25 + Vector（调优权重）
- Hybrid 3: BM25 + Vector + Graph（推荐基线）

### A/B 测试

在真实任务中对比不同检索策略：

```text
用户群 A（50%）：使用基线检索
用户群 B（50%）：使用优化检索

观察指标：
- 任务完成率
- 任务耗时
- Token 消耗
- 用户满意度
```

## 十、技术栈推荐

### 索引构建

| 组件 | 推荐方案 | 备选方案 |
|------|----------|----------|
| AST 解析 | tree-sitter | 语言原生工具 |
| LSP 客户端 | pygls, vscode-languageclient | 手动实现 |
| 依赖解析 | syft, cyclonedx | 手动解析 manifest |
| 任务队列 | Celery, BullMQ | AWS SQS |

### 存储

| 组件 | 推荐方案 | 备选方案 |
|------|----------|----------|
| 图数据库 | Neo4j | PostgreSQL + pgGraphQL |
| 向量数据库 | pgvector, Weaviate | Pinecone, Milvus |
| 全文搜索 | Meilisearch | Elasticsearch, Typesense |
| 对象存储 | S3, MinIO | 本地文件系统 |

### 嵌入模型

| 模型 | 维度 | 延迟 | 成本 | 推荐场景 |
|------|------|------|------|----------|
| OpenAI text-embedding-3-small | 1536 | 快 | 中 | 生产 |
| OpenAI text-embedding-3-large | 3072 | 中 | 高 | 高质量场景 |
| Cohere embed-english-v3.0 | 1024 | 快 | 中 | 备选 |
| jina-embeddings-v2-base-code | 768 | 快 | 免费 | 自托管 |

## 十一、交付物清单

### Phase 1: 数据模型与工具选型

- [ ] 索引数据模型定义
- [ ] 图 Schema
- [ ] AST 和 LSP 工具选型
- [ ] 技术栈确定

### Phase 2: 索引构建实现

- [ ] 代码解析器
- [ ] 依赖分析器
- [ ] 图构建器
- [ ] 向量化流水线
- [ ] 全文索引流水线
- [ ] 增量索引实现

### Phase 3: 检索实现

- [ ] BM25 检索
- [ ] 向量检索
- [ ] 图遍历检索
- [ ] 混合检索策略
- [ ] 重排序实现
- [ ] Context Selector

### Phase 4: 权限与安全

- [ ] 权限过滤实现
- [ ] 敏感路径黑名单
- [ ] 租户隔离验证

### Phase 5: 评估与优化

- [ ] Golden Dataset v1
- [ ] 评估指标计算
- [ ] 基线对比实验
- [ ] A/B 测试框架
- [ ] 性能基准测试

### Phase 6: 上下文压缩

- [ ] 压缩策略实现
- [ ] 分层加载实现
- [ ] 压缩质量评估

## 十二、验收标准

### 功能验收

- [ ] 支持 Python、TypeScript、Go 代码索引
- [ ] 小型仓库索引时间 < 5s
- [ ] 中型仓库索引时间 < 30s
- [ ] 检索延迟 p95 < 500ms
- [ ] 增量索引正常工作
- [ ] 权限过滤正确执行
- [ ] 未授权文件不出现在检索结果

### 质量验收

- [ ] Recall@10 > 0.9
- [ ] Precision@5 > 0.6
- [ ] MRR > 0.7
- [ ] Token 使用率 80%-95%
- [ ] 检索上下文任务成功率 / 完美上下文 > 0.9

### 性能验收

- [ ] 索引并发：支持 10 个仓库同时索引
- [ ] 检索并发：支持 100 QPS
- [ ] 向量搜索延迟 p95 < 200ms
- [ ] 全文搜索延迟 p95 < 100ms

### 可维护性验收

- [ ] 索引版本可追溯
- [ ] 索引失败有详细日志
- [ ] 支持重新索引
- [ ] 支持索引回滚
- [ ] 有监控指标和告警

## 十三、开放问题与候选方案

### 问题 1：CMV（Code Mapping Vector）是否采纳？

**CMV 声称**：
- 更适合代码理解
- 捕获语义和结构信息

**待验证**：
- 在本项目的真实任务上是否优于 OpenAI embedding？
- 训练和部署成本？
- 维护成本？

**决策**：
- 暂不采纳作为默认方案
- 可作为实验对比项
- 如果评测显著优于 OpenAI，再考虑切换

### 问题 2：CodeNexus/GitNexus 是否采纳？

**CodeNexus/GitNexus 声称**：
- 基于语义的代码导航
- 更好的代码关系理解

**待验证**：
- 是否有公开实现？
- 索引构建成本？
- 检索性能？

**决策**：
- 暂不采纳作为默认方案
- 如果有公开实现，可作为对比项
- 优先使用成熟的图数据库 + 混合检索

### 问题 3：Merkle 树是否用于索引一致性？

**用途**：
- 快速检测索引和代码不一致
- 支持分布式索引

**待评估**：
- 是否真的需要分布式索引？
- 简单的版本号（Git SHA）是否足够？

**决策**：
- MVP 不采用
- 使用 Git SHA 作为版本标识
- 如果后续需要分布式索引，再引入

## 十四、参考资料

- GitHub Semantic Code Search
- Sourcegraph Code Intelligence
- OpenAI Embeddings Best Practices
- BM25 Algorithm
- HNSW (Hierarchical Navigable Small World)
- Language Server Protocol Specification
- tree-sitter Documentation

## 十五、下一步行动

1. 确定首批支持的语言和仓库规模
2. 选择技术栈和工具
3. 设计和实现索引数据模型
4. 构建 Golden Dataset v1
5. 实现 BM25 + 向量混合检索
6. 执行基线对比实验
7. 根据评测结果调优权重和策略
8. 实现图遍历检索
9. 验证权限过滤
10. 执行 A/B 测试
11. 冻结推荐基线并发布
