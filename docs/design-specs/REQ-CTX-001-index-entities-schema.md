# REQ-CTX-001 索引实体和关系 Schema 详细设计

> 版本：v0.1-designed  
> 优先级：P1  
> 状态：详细设计已完成，待跨模块评审与冻结  
> 所属模块：上下文管理（CTX）  
> 前置依赖：REQ-RT-001（核心运行时实体 Schema）  
> 下游依赖：REQ-CTX-002~009、REQ-HAR-003、REQ-EVA-003

---

## 1. 目标与范围

### 1.1 需求目标

定义代码索引的核心实体模型，建立索引 Schema 与 Runtime Contract 的版本绑定机制，支持多仓库、多语言、增量更新的索引场景。

**核心价值**：
- Agent 能理解代码结构和符号关系
- 检索结果可绑定到具体代码版本
- 支持跨文件依赖分析和影响范围评估
- 支持增量索引和版本追踪

### 1.2 设计边界

**包含**：
- File、Symbol、Dependency、Relation 核心实体 Schema
- 实体与 Runtime Contract 的版本绑定机制
- 关系类型枚举和属性定义
- 索引元数据和状态管理
- 与 REQ-RT-001 的接口约束

**不包含**：
- 具体语言的 AST 解析实现（归属 REQ-CTX-003）
- 混合检索算法实现（归属 REQ-CTX-004）
- 权限过滤规则（归属 REQ-CTX-005）
- Context Selector 预算分配（归属 REQ-CTX-006）
- 增量索引调度策略（归属 REQ-CTX-007）

---

## 2. 行业调研与可借鉴设计

### 2.1 Sourcegraph SCIP 协议

**设计原则**：
- Protocol Buffers Schema 定义
- Human-readable string IDs 替代 opaque numeric IDs
- 跨仓库符号解析

**核心结构**：
```protobuf
Document {
    document: path  // 相对于项目根目录
    occurrences: Occurrence[]  // 附加到源码范围的信息
    symbols: Symbol[]  // 文档中定义的符号
}

Occurrence {
    range: [start_line, start_col, end_line, end_col]
    symbol: string  // qualified symbol ID
    symbol_role: [Definition, Reference, ...]
}
```

**可借鉴点**：
1. 符号的 qualified name 设计
2. Occurrence 的语法信息与语义信息分离
3. 跨仓库符号标识包含包名和版本

**来源**：
- [SCIP: a better code indexing format](https://sourcegraph.com/blog/announcing-scip)（访问日期：2026-09-26）
- [Sourcegraph indexers](https://sourcegraph.com/docs/docs/code-navigation/writing-an-indexer.md)（访问日期：2026-09-26）

### 2.2 GitHub Copilot Semantic Search

**设计原则**：
- 自动云端索引 GitHub 仓库
- 增量更新机制
- 新嵌入模型：检索质量提升 37.6%，吞吐量 2x，索引大小减少 8x

**训练策略**：
- 对比学习 + InfoNCE loss
- Matryoshka Representation Learning
- Hard Negatives 挖掘

**可借鉴点**：
1. 增量索引 + 版本绑定机制
2. 嵌入模型针对代码的对比学习训练范式
3. 语义分块策略（200-400 行逻辑块）

**来源**：
- [GitHub Copilot indexing](https://docs.github.com/en/copilot/concepts/context/repository-indexing)（访问日期：2026-09-26）
- [GitHub Blog: New embedding model](https://github.blog/news-insights/product-news/copilot-new-embedding-model-vs-code/)（访问日期：2026-09-26）

### 2.3 Cursor Codebase Indexing

**设计原则**：
- Merkle 树检测文件变更
- 混淆路径元数据保护隐私
- RRF 混合融合：+12.5% 准确率（语义），+23.5%（组合）

**增量索引**：
```
文件变更 → Merkle 树检测
        → 只重嵌入变更块
        → 更新向量数据库
```

**可借鉴点**：
1. Merkle 树零配置增量更新
2. RRF 混合融合生产级范式
3. 混淆路径隐私保护设计

**来源**：
- [Cursor secure indexing](https://cursor.com/blog/secure-codebase-indexing)（访问日期：2026-09-26）

### 2.4 Qoder Hybrid Architecture

**设计原则**：
- 服务器端向量数据库
- 客户端代码图（调用、继承）
- Repo Wiki 预索引

**可借鉴点**：
1. 向量 + 图双通道互补
2. 预索引结构化文档
3. 分支感知检索

**来源**：
- [Qoder indexing](https://docs.qoder.com/user-guide/indexing)（访问日期：2026-09-26）

### 2.5 codebase-index (MCP Tool)

**设计原则**：
- Tree-sitter AST 解析
- 符号边界分块（而非行窗口）
- SQLite 本地存储

**可借鉴点**：
1. 符号对齐分块策略
2. MCP 工具标准化接口
3. Token 预算输出设计

**来源**：
- [codebase-index GitHub](https://github.com/denfry/codebase-index)（访问日期：2026-09-26）

---

## 3. 核心实体 Schema

### 3.1 统一类型与共享坐标

```typescript
// 标识类型
type EntityId = string;         // UUIDv7
type RepositoryId = EntityId;
type SymbolId = string;         // qualified symbol ID
type RevisionRef = string;      // Git commit SHA

// 版本坐标
interface VersionCoordinate {
    schema_version: string;     // 例如 "index.v1"
    source_revision: RevisionRef;
    indexed_at: Timestamp;
    index_version: string;      // 索引构建版本标识
}

// 位置信息
interface SourceRange {
    start_line: number;
    start_column: number;
    end_line: number;
    end_column: number;
}
```

### 3.2 File（文件节点）

```typescript
interface FileNode {
    // 身份标识
    schema_version: string;             // "index.file.v1"
    file_id: EntityId;
    repository_id: RepositoryId;
    
    // 文件信息
    path: string;                       // 相对于仓库根目录的路径
    language: string;                   // 编程语言
    size_bytes: number;
    lines_of_code: number;
    
    // 版本绑定
    source_revision: RevisionRef;       // 文件所属的 Git commit SHA
    file_hash: string;                  // 文件内容哈希 (SHA-256)
    
    // 索引元数据
    indexed_at: Timestamp;
    index_version: string;
    
    // 向量化（可选）
    embedding?: number[];               // 文件摘要向量
    embedding_model?: string;           // 嵌入模型标识
    
    // 摘要
    summary?: string;                   // 文件摘要（200 字符以内）
    
    // 扩展元数据
    metadata: SafeMetadata;
}
```

**不变量**：
1. `path` 必须是相对于仓库根目录的规范化路径
2. `source_revision` 创建后不可变
3. `file_hash` 必须与文件内容一致
4. `embedding` 如果存在，必须记录 `embedding_model`

### 3.3 Symbol（符号节点）

```typescript
interface SymbolNode {
    // 身份标识
    schema_version: string;             // "index.symbol.v1"
    symbol_id: SymbolId;                // qualified symbol ID
    file_id: EntityId;
    repository_id: RepositoryId;
    
    // 符号信息
    name: string;                       // 短名称
    qualified_name: string;             // 完全限定名（例如：com.example.UserService.login）
    kind: SymbolKind;                   // 符号类型
    
    // 签名与文档
    signature?: string;                 // 函数签名或类型签名
    docstring?: string;                 // 文档字符串
    
    // 位置
    range: SourceRange;                 // 源码范围
    
    // 可见性与作用域
    visibility: Visibility;             // public / private / protected / internal
    owner?: SymbolId;                   // 所属符号（例如方法的所属类）
    
    // 版本绑定
    source_revision: RevisionRef;
    
    // 向量化（可选）
    embedding?: number[];               // 符号向量
    embedding_model?: string;
    
    // 扩展元数据
    metadata: SafeMetadata;
}

enum SymbolKind {
    FUNCTION = "function",
    METHOD = "method",
    CLASS = "class",
    INTERFACE = "interface",
    TYPE = "type",
    CONSTANT = "constant",
    VARIABLE = "variable",
    ENUM = "enum",
    ENUM_MEMBER = "enum_member",
    STRUCT = "struct",
    MODULE = "module",
    NAMESPACE = "namespace",
}

enum Visibility {
    PUBLIC = "public",
    PRIVATE = "private",
    PROTECTED = "protected",
    INTERNAL = "internal",
    PACKAGE = "package",
}
```

**不变量**：
1. `qualified_name` 必须在仓库内唯一
2. `symbol_id` 推荐格式：`<package>.<name>`（参考 SCIP）
3. `owner` 如果存在，必须指向已存在的 Symbol
4. `range` 必须在文件边界内

### 3.4 Dependency（依赖节点）

```typescript
interface DependencyNode {
    // 身份标识
    schema_version: string;             // "index.dependency.v1"
    dependency_id: EntityId;
    repository_id: RepositoryId;
    
    // 依赖信息
    package_name: string;               // 包名
    version: string;                    // 版本号
    version_constraint?: string;        // 版本约束（例如：^1.0.0）
    
    // 来源
    source: DependencySource;           // direct / transitive
    ecosystem: Ecosystem;               // npm / pypi / go-mod / maven / cargo
    
    // 声明位置
    declared_in_file?: EntityId;        // 声明该依赖的文件
    
    // 版本绑定
    source_revision: RevisionRef;
    
    // 扩展元数据
    metadata: SafeMetadata;
}

enum DependencySource {
    DIRECT = "direct",
    TRANSITIVE = "transitive",
}

enum Ecosystem {
    NPM = "npm",
    PYPI = "pypi",
    GO_MOD = "go-mod",
    MAVEN = "maven",
    CARGO = "cargo",
    GEM = "gem",
    NUGET = "nuget",
}
```

### 3.5 Relation（关系边）

```typescript
interface RelationEdge {
    // 身份标识
    schema_version: string;             // "index.relation.v1"
    relation_id: EntityId;
    repository_id: RepositoryId;
    
    // 关系信息
    relation_type: RelationType;
    source_id: EntityId;                // 源节点 ID（File 或 Symbol）
    target_id: EntityId;                // 目标节点 ID
    
    // 关系属性
    weight?: number;                    // 关系权重（用于图排序）
    is_direct?: boolean;                // 是否是直接关系
    call_count?: number;                // 调用次数（仅 CALLS 关系）
    
    // 位置（可选）
    source_range?: SourceRange;         // 关系发生的位置
    
    // 版本绑定
    source_revision: RevisionRef;
    
    // 扩展元数据
    metadata: SafeMetadata;
}

enum RelationType {
    // 文件级关系
    IMPORTS = "imports",                // FileA imports FileB
    DEPENDS_ON = "depends_on",          // Repository depends on Dependency
    
    // 符号级关系
    DEFINES = "defines",                // FileA defines SymbolB
    CALLS = "calls",                    // SymbolA calls SymbolB
    REFERENCES = "references",          // SymbolA references SymbolB（非调用引用）
    USES_TYPE = "uses_type",            // SymbolA uses TypeB
    EXTENDS = "extends",                // ClassA extends ClassB
    IMPLEMENTS = "implements",          // ClassA implements InterfaceB
}
```

**不变量**：
1. `source_id` 和 `target_id` 必须指向已存在的实体
2. 不同关系类型的 source/target 类型约束：
   - IMPORTS: File → File
   - DEPENDS_ON: Repository → Dependency
   - DEFINES: File → Symbol
   - CALLS: Symbol → Symbol
   - REFERENCES: Symbol → Symbol
   - USES_TYPE: Symbol → Symbol
   - EXTENDS: Symbol → Symbol
   - IMPLEMENTS: Symbol → Symbol
3. `weight` 默认为 1.0
4. 同一关系不应重复（相同 source, target, relation_type）

### 3.6 IndexMetadata（索引元数据）

```typescript
interface IndexMetadata {
    // 身份标识
    schema_version: string;             // "index.metadata.v1"
    repository_id: RepositoryId;
    
    // 版本信息
    source_revision: RevisionRef;
    index_version: string;              // 索引构建版本（例如：idx-20260926-001）
    indexed_at: Timestamp;
    
    // 索引状态
    state: IndexState;
    state_since: Timestamp;
    
    // 统计信息
    total_files: number;
    total_symbols: number;
    total_relations: number;
    total_dependencies: number;
    
    // 语言分布
    language_distribution: Record<string, number>;  // { "Python": 45, "TypeScript": 23, ... }
    
    // 索引耗时
    build_duration_seconds: number;
    
    // 索引配置
    indexer_config: IndexerConfig;
    
    // 扩展元数据
    metadata: SafeMetadata;
}

enum IndexState {
    PENDING = "pending",                // 索引任务已创建，等待处理
    BUILDING = "building",              // 正在构建索引
    VALIDATING = "validating",          // 正在验证索引完整性
    ACTIVE = "active",                  // 索引已激活，可用于检索
    STALE = "stale",                    // 索引已过期（代码已更新）
    ARCHIVED = "archived",              // 索引已归档（保留用于回放）
    FAILED = "failed",                  // 索引构建失败
}

interface IndexerConfig {
    // 解析器配置
    parsers: string[];                  // 使用的解析器列表
    
    // 向量化配置
    embedding_model?: string;           // 嵌入模型
    embedding_dimensions?: number;      // 向量维度
    
    // 排除配置
    excluded_paths: string[];           // 排除的路径模式
    excluded_extensions: string[];      // 排除的文件扩展名
    
    // 分块配置
    chunk_strategy: string;             // "syntactic" / "symbol-aligned" / "fixed-size"
    max_chunk_size: number;             // 最大块大小（字符数）
}
```

---

## 4. 索引构建流程

```
Step 1: 代码解析
  输入：仓库文件列表
  处理：
    1.1 遍历仓库文件，过滤代码文件（根据扩展名和 .gitignore）
    1.2 对每个代码文件调用对应语言的 AST 解析器
    1.3 提取 AST 节点：文件头、导入、符号定义、符号引用

Step 2: 符号提取
  输入：解析后的 AST
  处理：
    2.1 对每个符号节点提取：
        - 符号名（name）
        - 限定名（qualified_name）
        - 符号类型（kind）
        - 签名（signature）
        - 文档字符串（docstring）
        - 可见性（visibility）
        - 位置（range）
    2.2 为每个符号生成唯一 ID

Step 3: 关系提取
  输入：符号列表 + AST
  处理：
    3.1 提取导入关系（IMPORTS）
    3.2 提取调用关系（CALLS）
    3.3 提取类型使用关系（USES_TYPE）
    3.4 提取定义关系（DEFINES）
    3.5 提取继承/实现关系（EXTENDS/IMPLEMENTS）
    3.6 提取引用关系（REFERENCES）

Step 4: 向量化（可选）
  输入：文件 + 符号
  处理：
    4.1 为每个文件生成摘要向量
    4.2 为每个符号生成向量
    4.3 存储向量到向量数据库

Step 5: 版本绑定
  输入：实体列表
  处理：
    5.1 绑定 source_revision
    5.2 记录 indexed_at
    5.3 生成 index_version
    5.4 发布索引完成事件
```

---

## 5. 检索接口定义

### 5.1 检索请求

```typescript
interface RetrievalQuery {
    // 身份标识
    repository_id: RepositoryId;
    source_revision?: RevisionRef;      // 可选，默认最新
    
    // 查询内容
    query_text: string;                 // 自然语言查询
    query_symbol?: string;              // 可选，符号名
    query_file?: string;                // 可选，文件路径
    
    // 检索模式
    retrieval_mode: RetrievalMode;
    
    // 过滤条件
    filters?: RetrievalFilters;
    
    // 返回配置
    top_k: number;                      // 返回结果数（默认 10）
    include_sources: boolean;           // 是否包含来源信息
}

enum RetrievalMode {
    HYBRID = "hybrid",                  // 混合检索（BM25 + Vector + Graph）
    SEMANTIC = "semantic",              // 仅语义检索
    LEXICAL = "lexical",                // 仅词法检索
    SYMBOL = "symbol",                  // 仅符号检索
    GRAPH = "graph",                    // 仅图遍历
}

interface RetrievalFilters {
    languages?: string[];               // 语言过滤
    file_patterns?: string[];           // 文件路径模式
    symbol_kinds?: SymbolKind[];        // 符号类型过滤
    visibility?: Visibility[];          // 可见性过滤
    excluded_paths?: string[];          // 排除路径
}
```

### 5.2 检索结果

```typescript
interface RetrievalResult {
    // 检索结果
    chunks: RetrievedChunk[];
    total_hits: number;
    
    // 查询元数据
    query_embedding?: number[];         // 查询向量
    index_version: string;              // 检索使用的索引版本
    retrieval_latency_ms: number;
    
    // 来源分布
    source_distribution?: Record<string, number>;  // { "bm25": 4, "vector": 3, "graph": 3 }
}

interface RetrievedChunk {
    // 块标识
    chunk_id: string;
    file_id: EntityId;
    file_path: string;
    
    // 位置
    range: SourceRange;
    
    // 内容
    content: string;                    // 代码片段
    
    // 相关性
    score: number;                      // 融合后的相关性分数
    sources: string[];                  // 来源：["bm25", "vector", "graph"]
    
    // 上下文
    symbols?: SymbolNode[];             // 块内包含的符号
    related_symbols?: SymbolNode[];     // 相关符号
    
    // Token 预算
    estimated_tokens: number;           // 估算 Token 数
}
```

---

## 6. 增量索引机制

### 6.1 Merkle 树变更检测

```typescript
interface MerkleNode {
    hash: string;                       // 本节点哈希
    path?: string;                      // 文件路径（叶子节点）
    children?: MerkleNode[];            // 子节点
}

interface MerkleTree {
    root: MerkleNode;
    repository_id: RepositoryId;
    source_revision: RevisionRef;
    computed_at: Timestamp;
}

/**
 * 检测变更文件
 */
function detectChanges(oldTree: MerkleTree, newTree: MerkleTree): string[] {
    const changes: string[] = [];
    
    function traverse(oldNode: MerkleNode, newNode: MerkleNode) {
        if (oldNode.hash === newNode.hash) {
            return;  // 无变更
        }
        
        if (!oldNode.children) {
            // 叶子节点，文件有变更
            changes.push(oldNode.path!);
        } else {
            // 递归检查子节点
            for (let i = 0; i < oldNode.children.length; i++) {
                traverse(oldNode.children[i], newNode.children?.[i] || emptyNode());
            }
        }
    }
    
    traverse(oldTree.root, newTree.root);
    return changes;
}
```

### 6.2 增量更新流程

```
Git Push/Webhook 触发
    ↓
Step 1: 计算新 Merkle 树
    ↓
Step 2: 与旧树对比，获取变更文件列表
    ↓
Step 3: 对变更文件重新解析 AST
    ↓
Step 4: 更新 Symbol 和 Relation 索引
    - 删除旧符号和关系
    - 添加新符号和关系
    ↓
Step 5: 更新向量索引（如启用）
    - 删除旧向量
    - 添加新向量
    ↓
Step 6: 更新 IndexMetadata
    - 更新 source_revision
    - 更新 indexed_at
    - 更新统计信息
    ↓
Step 7: 发布索引更新事件
```

---

## 7. 与 Runtime Contract 的集成

### 7.1 版本绑定

| Runtime 实体 | 索引实体 | 绑定字段 |
|--------------|----------|----------|
| Task | IndexMetadata | `source_revision` = Task.`base_revision` |
| Workflow | IndexMetadata | `source_revision` = Workflow.`base_revision` |
| Worker | RetrievalQuery | `source_revision` = Worker.`source_revision` |
| Action | RetrievalResult | 检索结果绑定到 Action.`source_revision` |
| Artifact | RetrievedChunk | Artifact 包含检索结果 |

### 7.2 检索上下文传递

```typescript
// Worker 执行检索
const query: RetrievalQuery = {
    repository_id: worker.repository_id,
    source_revision: worker.source_revision,  // 绑定 Worker 的代码版本
    query_text: "用户登录权限检查",
    retrieval_mode: RetrievalMode.HYBRID,
    top_k: 10,
};

const result: RetrievalResult = await retrievalService.query(query);

// 结果封装为 Artifact
const artifact: Artifact = {
    artifact_id: generateId(),
    task_id: worker.task_id,
    workflow_id: worker.workflow_id,
    producer_worker_id: worker.worker_id,
    type: ArtifactType.CONTEXT_RETRIEVAL,
    source_revision: worker.source_revision,  // 版本一致性
    content_inline: {
        chunks: result.chunks,
        index_version: result.index_version,
    },
    trace_id: worker.trace_id,
};
```

---

## 8. 权限与安全

### 8.1 权限过滤 Schema 支持

```typescript
interface FileNode {
    // ... 其他字段
    
    // 权限元数据
    is_sensitive: boolean;              // 是否包含敏感内容
    sensitivity_level?: SensitivityLevel;
    access_scope?: string;              // 访问范围标识（与 SEC-002 对齐）
}

enum SensitivityLevel {
    PUBLIC = "public",
    INTERNAL = "internal",
    CONFIDENTIAL = "confidential",
    RESTRICTED = "restricted",
}
```

### 8.2 检索权限过滤

```
检索请求 + 用户权限
    ↓
Step 1: 查询索引（不带权限过滤）
    ↓
Step 2: 对每个结果检查权限
    - 检查用户是否有 repository 访问权限
    - 检查文件是否在用户授权路径内
    - 检查文件敏感级别是否在用户权限内
    ↓
Step 3: 移除未授权结果
    ↓
返回过滤后结果
```

---

## 9. 性能与成本

### 9.1 性能目标

| 指标 | 目标 | 说明 |
|------|------|------|
| **小型仓库索引时间** | < 5s | < 100 文件，< 10K 行 |
| **中型仓库索引时间** | < 30s | 100-1000 文件，10K-100K 行 |
| **检索延迟 p95** | < 500ms | 混合检索 + 权限过滤 |
| **向量检索延迟 p95** | < 200ms | 单独向量检索 |
| **增量索引时间** | < 1s/文件 | Merkle 树检测 + 单文件重索引 |

### 9.2 成本估算

| 成本项 | 估算 | 说明 |
|--------|------|------|
| **存储成本** | < $0.01/文件/月 | 包含向量 + 关系 |
| **计算成本** | < $0.001/检索 | 混合检索 |
| **索引构建成本** | < $0.10/千行代码 | 初次索引 |

---

## 10. 可观测性

### 10.1 索引健康指标

| 指标 | 定义 | 告警阈值 |
|------|------|----------|
| `index_build_success_rate` | 索引构建成功率 | < 99% |
| `index_freshness_seconds` | 索引新鲜度（距最新 commit 的时间） | > 300s |
| `index_build_duration_seconds` | 索引构建耗时 | > 目标 2x |
| `index_size_mb` | 索引大小 | > 配额 80% |

### 10.2 检索质量指标

| 指标 | 定义 | 目标 |
|------|------|------|
| `retrieval_latency_p95` | 检索延迟 p95 | < 500ms |
| `retrieval_hit_rate` | 检索命中率 | > 90% |
| `retrieval_precision_at_10` | 前 10 结果准确率 | > 0.6 |
| `retrieval_recall_at_10` | 前 10 结果召回率 | > 0.9 |

---

## 11. 验收标准

| 编号 | 验收标准 | 验证方法 |
|------|----------|----------|
| V1 | Schema 包含 File、Symbol、Dependency、Relation 核心实体 | Schema 审查 |
| V2 | 每个实体绑定 `repository_id` 和 `source_revision` | Schema 审查 |
| V3 | Symbol 包含 name、qualified_name、kind、signature、visibility | Schema 审查 |
| V4 | Relation 支持 8 种类型：IMPORTS、CALLS、DEFINES、USES_TYPE、EXTENDS、IMPLEMENTS、REFERENCES、DEPENDS_ON | Schema 审查 |
| V5 | 每个实体包含 `schema_version` 字段 | Schema 审查 |
| V6 | 索引元数据包含 `indexed_at` 和 `index_version` | Schema 审查 |
| V7 | 实体可与 Runtime Contract 的 Task/Workflow/Worker 关联 | Schema 审查 |
| V8 | 支持增量索引的 Merkle 树变更检测接口 | 接口审查 |
| V9 | 检索输入/输出与 Schema 定义一致 | 接口测试 |
| V10 | Schema 文档完整，包含不变量和约束 | 文档审查 |

---

## 12. 依赖与接口

### 12.1 上游依赖

| 依赖 | 说明 |
|------|------|
| `REQ-RT-001` | 核心实体 Schema（Task/Workflow/Worker/Action/Artifact） |
| `REQ-RT-003` | Event Schema（索引构建事件） |
| `REQ-SEC-002` | RBAC（权限过滤基础） |
| `REQ-SEC-008` | 多租户隔离（租户索引分区） |

### 12.2 下游接口

| 接口 | 消费者 | 说明 |
|------|--------|------|
| `FileNode, SymbolNode, RelationEdge` | CTX-002~009 | 索引数据访问 |
| `RetrievalQuery` | Harness/CTX-004 | 检索请求 |
| `RetrievalResult` | Worker Runtime | 上下文组装 |
| `IndexMetadata` | OBS 模块 | 可观测性指标 |

---

## 13. 版本与演进

### 13.1 Schema 版本策略

| 变更类型 | 版本升级 | 说明 |
|----------|----------|------|
| 新增可选字段 | 小版本 | 向前兼容 |
| 新增必填字段 | 大版本 | 需要迁移 |
| 删除字段 | 大版本 | 保留废弃标识 |
| 修改字段语义 | 大版本 | 需要评审 |

### 13.2 向后兼容规则

- 新版本必须能读取旧版本索引
- 旧版本消费者可忽略新增字段
- 索引升级后旧版本检索仍可用

---

## 14. 参考资料

以下为公开来源，访问日期均为 2026-09-26：

- Sourcegraph SCIP 协议：[Announcing SCIP](https://sourcegraph.com/blog/announcing-scip)
- Sourcegraph 架构：[Architecture](https://sourcegraph.com/docs/admin/architecture)
- GitHub Copilot 索引：[Repository Indexing](https://docs.github.com/en/copilot/concepts/context/repository-indexing)
- GitHub 嵌入模型：[New embedding model](https://github.blog/news-insights/product-news/copilot-new-embedding-model-vs-code/)
- Cursor 索引：[Secure codebase indexing](https://cursor.com/blog/secure-codebase-indexing)
- Qoder 混合检索：[Hybrid code retrieval](https://dev.to/qoder/qoders-codebase-aware-code-retrieval-a-hybrid-approach-for-ai-coding-gpm)
- codebase-index：[GitHub Repository](https://github.com/denfry/codebase-index)

---

## 15. 决策记录

| 决策项 | 决策 | 依据 |
|-------|------|------|
| 符号标识设计 | 采用 qualified name（参考 SCIP） | Sourcegraph 最佳实践 |
| 增量检测算法 | Merkle 树 | Cursor 公开实践 |
| 关系类型 | 8 种（新增 REFERENCES） | Sourcegraph/codebase-index |
| 版本绑定 | 每个实体绑定 source_revision | Runtime Contract 规范 |
| 权限元数据 | Schema 包含 sensitivity_level | SEC-002 对齐 |

---

**文档创建时间**：2026-09-26  
**维护团队**：架构组
