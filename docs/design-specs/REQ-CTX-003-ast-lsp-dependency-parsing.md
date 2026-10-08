# REQ-CTX-003 AST/LSP/依赖解析 详细设计

> 版本：v0.1-designed  
> 优先级：P1  
> 状态：详细设计已完成，待跨模块评审与冻结  
> 所属模块：上下文管理（CTX）  
> 前置依赖：REQ-CTX-001（索引实体和关系 Schema）、REQ-CTX-002（语言、仓库规模和基准集）  
> 下游依赖：REQ-CTX-004~009

---

## 1. 目标与范围

### 1.1 需求目标

建立统一的代码解析框架，支持多语言 AST 解析、符号提取、调用图构建和依赖分析。

**核心价值**：
- 为 REQ-CTX-004 混合检索提供结构化输入（符号、关系）
- 为 REQ-CTX-006 Context Selector 提供调用图数据
- 为 REQ-CTX-007 增量索引一致性提供 Merkle 树基础
- 支持工程级跨文件上下文感知

### 1.2 设计边界

**包含**：
- Tree-sitter 统一 AST 解析框架
- LSP 协同解析策略（TIER_1 语言）
- Merkle 树增量变更检测
- 符号提取和 qualified name 生成
- 调用图构建和循环依赖检测
- 依赖分析（直接依赖 + 一层传递依赖）

**不包含**：
- 混合检索算法实现（归属 REQ-CTX-004）
- 权限过滤规则（归属 REQ-CTX-005）
- Context Selector 实现（归属 REQ-CTX-006）
- 向量化流水线（归属 REQ-CTX-004）

---

## 2. 行业调研与可借鉴设计

### 2.1 Sourcegraph SCIP 协议

**设计原则**：
- Protobuf Schema + Human-readable string IDs
- 跨仓库符号解析
- 内容寻址存储（Content-Addressable）

**可借鉴点**：
1. 符号 qualified name 设计（跨仓库唯一性）
2. 增量索引的流式处理架构
3. 循环依赖不阻塞索引

**来源**：
- [Announcing SCIP](https://sourcegraph.com/blog/announcing-scip)（访问日期：2026-09-27）
- [SCIP Design](https://github.com/sourcegraph/scip/blob/main/docs/DESIGN.md)（访问日期：2026-09-27）

---

### 2.2 Cursor Merkle 树索引

**设计原则**：
- SHA-256 文件哈希 + Merkle 树变更检测
- Tree-sitter AST-based 语义分块
- SimHash 缓存优化

**可借鉴点**：
1. Merkle 树 O(log N) 变更检测
2. AST 深度优先遍历分块
3. 相邻兄弟节点合并策略

**来源**：
- [Cursor Secure Indexing](https://cursor.com/blog/secure-codebase-indexing)（访问日期：2026-09-27）
- [How Cursor Indexes Fast](https://read.engineerscodex.com/p/how-cursor-indexes-codebases-fast)（访问日期：2026-09-27）

---

### 2.3 Codebase-Memory Tree-sitter KG

**设计原则**：
- Tree-sitter 解析 66 种语言
- SQLite 本地存储知识图谱
- MCP 协议暴露 14 个结构化查询工具

**可借鉴点**：
1. 并行 Worker 池流水线
2. 文件监视 + 内容哈希增量重索引
3. 符号对齐分块策略

**来源**：
- [Codebase-Memory Paper](https://arxiv.org/html/2603.27277v1)（访问日期：2026-09-27）

---

### 2.4 通义灵码 GraphTransformer

**设计原则**：
- AST GraphTransformer 图编码
- 引用链追踪
- 增量 AST Diff 事件驱动

**可借鉴点**：
1. 工程级跨文件上下文感知
2. TF-IDF 动态识别高相关性片段
3. 增量 Diff 技术

**来源**：
- [通义灵码技术解析](https://developer.aliyun.com/article/1661439)（访问日期：2026-09-27）

---

### 2.5 LSP 企业级部署架构（2026 最佳实践）

**设计原则**：
- Kubernetes 容器化，每仓库独立 LSP Pod
- Redis 跨实例缓存层（共享常见符号/类型）
- 持久卷缓存 AST 和符号索引
- HPA 基于活跃请求队列深度扩缩容

**可借鉴点**：
1. 每仓库专用 LSP 实例（避免状态混乱）
2. Redis 缓存层优化冷启动
3. 文件描述符限制调整（fs.inotify.max_user_watches=524288）

**来源**：
- [Enterprise LSP Deployment](https://dredyson.com/how-to-integrate-python-code-quality-tools-into-your-enterprise-stack-for-maximum-scalability-a-complete-step-by-step-guide-for-it-architects-managing-thousands-of-developers/)（访问日期：2026-09-28）
- [Deploying MCP on K8s](https://mcp-codex.com/articles/deploying-remote-mcp-kubernetes)（访问日期：2026-09-28）

---

### 2.6 Qoder 混合检索架构

**设计原则**：
- 向量 + 图双通道互补
- 分支感知检索
- 秒级增量更新

**可借鉴点**：
1. 图遍历扩展候选结果
2. 依赖图深度控制策略

**来源**：
- [Qoder Hybrid Retrieval](https://dev.to/qoder/qoders-codebase-aware-code-retrieval-a-hybrid-approach-for-ai-coding-gpm)（访问日期：2026-09-27）

---

## 3. 核心设计决策（基于行业标杆分析）

### 3.1 LSP 部署模式：每仓库独立实例 + Redis 缓存层

**决策**：采用 **每仓库独立 LSP 实例 + Redis 跨实例缓存**

**理由**：
1. **2026 行业标准**：企业级部署已从"共享服务池"演进到"每仓库专用实例"
2. **会话亲和性**：LSP 状态（AST、符号表）与仓库版本强绑定
3. **故障隔离**：一个仓库的 LSP 崩溃不影响其他仓库
4. **性能优化**：Redis 缓存层共享常见库的类型信息，避免重复解析

**部署架构**：
```
Repository A → LSP Pod A ──┐
Repository B → LSP Pod B ──┼──→ Redis 缓存层（共享常见符号/类型）
Repository C → LSP Pod C ──┘
```

**资源配置**（参考行业实践）：
- 每 Pod：512Mi-2Gi 内存、250m-1000m CPU
- 持久卷：10-50GB（缓存 AST 和符号索引）
- 文件描述符限制：65536
- fs.inotify.max_user_watches：524288

---

### 3.2 依赖解析精度：直接依赖 + 一层传递依赖（MVP）

**决策**：**MVP 支持直接依赖 + 一层传递依赖，Phase 2 扩展到完整传递依赖图**

**理由**：
1. **工程级上下文感知需求**：通义灵码、Qoder 强调"跨文件上下文感知"，仅直接依赖不足以支持影响范围分析
2. **传递依赖深度控制**：完整传递依赖图在大型项目中可能包含数千节点，一层传递依赖已覆盖 90% 查询场景
3. **计算成本平衡**：一层传递依赖的解析成本可控（O(N)），完整传递依赖需要图遍历（O(N²)）

**依赖层级定义**：
```
层级 0（直接依赖）：
  - package.json 中显式声明的依赖
  - requirements.txt 中声明的包
  
层级 1（一层传递依赖）：
  - 直接依赖的直接依赖
  - 示例：A 依赖 B，B 依赖 C，则 C 是 A 的一层传递依赖

层级 2+（深度传递依赖）：
  - Phase 2 支持，MVP 阶段不解析
```

**示例**：
```
项目 MyApp
├── 直接依赖：express@4.18.0
│   └── 一层传递：body-parser@1.20.0
│       └── 深度传递：bytes@3.1.2 ← MVP 不解析
├── 直接依赖：lodash@4.17.21 ← 无传递依赖
```

---

### 3.3 循环依赖处理：静默检测 + 图遍历深度限制

**决策**：**检测并记录循环依赖，图遍历时设置深度限制，不主动告警**

**理由**：
1. **循环依赖合法性**：TypeScript、Python 等语言中循环导入是合法的设计模式
2. **行业标杆实践**：Sourcegraph SCIP、Codebase-Memory 均不阻塞索引
3. **误报问题**：主动告警会造成大量误报，降低用户信任度
4. **图遍历优化**：循环依赖检测的真正目的是优化图遍历算法（避免无限递归）

**处理策略**：
```
1. 使用 Tarjan 算法检测强连通分量（SCC）
2. 在依赖图中标记 SCC 节点
3. 图遍历时：
   - 设置最大深度限制（默认 5 层）
   - 访问过的节点不重复访问
   - SCC 内部视为一个逻辑单元
4. 仅在用户请求"依赖分析报告"时展示循环依赖
```

**存储结构**：
```typescript
interface DependencyNode {
  // ... 其他字段
  is_in_cycle: boolean;              // 是否在循环依赖中
  cycle_id?: string;                 // 所属循环依赖组 ID
  cycle_size?: number;               // 循环依赖组大小
}
```

---

## 4. 解析框架设计

### 4.1 统一解析器接口

```typescript
interface Parser {
  // 解析器标识
  parser_id: string;
  language: string;
  tier: LanguageTier;
  
  // 解析方法
  parse(source: string, file_path: string): ParseResult;
  parse_incremental(old_tree: Tree, edits: Edit[]): ParseResult;
  
  // 能力声明
  supports_lsp: boolean;
  supports_incremental: boolean;
  supports_types: boolean;
}

interface ParseResult {
  success: boolean;
  ast_root?: ASTNode;
  symbols: SymbolNode[];
  relations: RelationEdge[];
  errors: ParseError[];
  metadata: ParseMetadata;
}
```

### 4.2 解析器组合策略

**TIER_1 语言（Python/TypeScript/Go）**：
```
主路径：原生 AST + LSP 增强
├── Step 1: Tree-sitter 快速解析（提取结构）
├── Step 2: LSP 语义增强（类型信息）
└── Step 3: 合并结果

降级路径：
├── LSP 超时（5s）→ 回退到纯 AST
├── LSP 不可用 → 使用 Tree-sitter
└── Tree-sitter 失败 → 文本正则提取（最低降级）
```

**TIER_2 语言（Java/Rust/C++/C#）**：
```
主路径：Tree-sitter AST
├── Step 1: Tree-sitter 解析
└── Step 2: 符号和关系提取

降级路径：
└── Tree-sitter 失败 → 文本正则提取
```

### 4.3 Merkle 树增量变更检测

**算法**：
```
MerkleTreeChangeDetector:
  输入：当前文件哈希列表、上次 Merkle 树
  输出：变更文件列表（新增/修改/删除）
  
  步骤：
    1. 为每个文件计算 SHA-256 哈希（叶子节点）
    2. 递归向上计算父节点哈希
    3. 根哈希代表整个仓库指纹
    4. 对比新旧 Merkle 树：
       - 根哈希相同 → 无变更，退出
       - 根哈希不同 → 递归找出差异子树
    5. 差异子树下的叶子节点即为变更文件
  
  复杂度：
    - 全量构建：O(N)
    - 变更检测：O(log N)
```

**存储结构**：
```typescript
interface MerkleNode {
  hash: string;                      // SHA-256
  path?: string;                     // 文件路径（叶子节点）
  children?: MerkleNode[];           // 子节点
}

interface MerkleTree {
  root: MerkleNode;
  repository_id: string;
  source_revision: string;
  computed_at: Timestamp;
}
```

---

## 5. 符号提取与 Qualified Name 生成

### 5.1 符号 Qualified Name 生成算法

**算法目的**：生成跨文件唯一的符号标识

**算法步骤**：
```
SymbolQualifiedNameGenerator:
  输入：符号节点、命名空间上下文
  输出：qualified_name 字符串
  
  步骤：
    1. 确定符号的命名空间（package/module/class）
    2. 按层级拼接：namespace1::namespace2::...::name
    3. 对于函数，添加参数类型哈希以区分重载
  
  示例：
    - Python: module.submodule.ClassName.method_name
    - TypeScript: namespace.module.ClassName.methodName
    - Go: package/module.ClassName.MethodName
```

**唯一性保证**：
- 同一仓库内 qualified_name 唯一
- 不同仓库可复用相同 qualified_name（通过 repository_id 区分）

### 5.2 符号提取流程

```
Step 1: AST 遍历
  - 深度优先遍历 AST
  - 识别符号节点（function/class/interface/type/variable）

Step 2: 符号元数据提取
  - name: 短名称
  - qualified_name: 完全限定名
  - kind: 符号类型
  - signature: 函数签名或类型签名
  - docstring: 文档字符串
  - range: 源码范围
  - visibility: 可见性

Step 3: 符号表构建
  - 建立符号索引：qualified_name → SymbolNode
  - 建立位置索引：file_path:line → SymbolNode
```

---

## 6. 调用图构建

### 6.1 调用图构建算法

```
CallGraphBuilder:
  输入：AST 节点列表、符号表
  输出：调用图（有向图）
  
  步骤：
    1. 遍历 AST，识别函数调用节点
    2. 对每个调用节点，解析被调用符号
       - 使用符号表进行名称解析
       - 处理跨文件调用
    3. 创建 CALLS 边（调用者 → 被调用者）
    4. 记录调用次数（call_count）
    5. 处理间接调用（函数指针、回调）
    
  循环依赖检测：
    - 使用 Tarjan 算法找强连通分量
    - 标记 SCC 内的符号
    - 不阻塞索引，仅记录
```

### 6.2 循环依赖检测（Tarjan 算法）

```
TarjanSCC:
  输入：调用图
  输出：强连通分量列表
  
  步骤：
    1. 初始化：index = 0, stack = []
    2. 对每个未访问节点调用 strongconnect
    3. strongconnect(v):
       - 设置 v.index = v.lowlink = index++
       - stack.push(v)
       - 对 v 的每个后继 w：
         - 如果 w 未访问：
           strongconnect(w)
           v.lowlink = min(v.lowlink, w.lowlink)
         - 如果 w 在栈中：
           v.lowlink = min(v.lowlink, w.index)
       - 如果 v.lowlink == v.index：
         - 弹出栈到 v，形成一个 SCC
  
  时间复杂度：O(V + E)
```

### 6.3 图遍历深度限制

```
GraphTraversal:
  输入：起始符号、遍历方向（CALLS/CALLED_BY）、最大深度
  输出：相关符号列表
  
  策略：
    - 默认最大深度：5 层
    - 访问过的节点不重复访问（避免循环）
    - SCC 内部视为一个逻辑单元（深度计为 1）
    - 超过深度限制时返回部分结果 + 截断标记
```

---

## 7. 依赖分析

### 7.1 依赖解析策略

**MVP 阶段：直接依赖 + 一层传递依赖**

```
DependencyResolver:
  输入：仓库路径、包管理文件
  输出：DependencyNodes 列表
  
  Step 1: 解析包管理文件
    - Python: requirements.txt, pyproject.toml, Pipfile
    - TypeScript: package.json, package-lock.json
    - Go: go.mod, go.sum
    - Java: pom.xml, build.gradle
  
  Step 2: 提取直接依赖（层级 0）
    - 解析依赖声明
    - 提取包名、版本约束
    - 标记为 source="direct"
  
  Step 3: 提取一层传递依赖（层级 1）
    - 解析 lockfile 获取传递依赖
    - 对每个直接依赖 D：
      - 解析 D 的直接依赖列表
      - 标记为 source="transitive", depth=1
    - 去重（避免重复记录）
  
  Step 4: 构建依赖图
    - 节点：DependencyNode
    - 边：DEPENDS_ON 关系
    - 标记循环依赖（如存在）
```

**Phase 2 扩展：完整传递依赖图**

```
FullDependencyResolver:
  输入：仓库路径、包管理文件
  输出：完整依赖图
  
  步骤：
    - 递归解析所有依赖的依赖
    - 使用图遍历算法（BFS/DFS）
    - 检测循环依赖并处理
    - 构建完整依赖树
```

### 7.2 依赖版本绑定

```typescript
interface DependencyNode {
  // ... 其他字段
  version: string;                   // 实际使用的版本
  version_constraint?: string;       // 声明的版本约束（如 ^1.0.0）
  resolved_version: string;          // lockfile 中的精确版本
  source: DependencySource;          // direct / transitive
  depth: number;                     // 依赖深度（0=直接，1=一层传递）
}
```

---

## 8. LSP 协同解析（TIER_1 语言）

### 8.1 LSP 部署架构

**部署模式**：每仓库独立 LSP 实例 + Redis 缓存层

```
Repository A
  ↓
LSP Pod A
  ├── tsserver (TypeScript)
  ├── pyright (Python)
  ├── gopls (Go)
  ├── 持久卷缓存（10GB）
  └── Redis 连接（共享符号/类型）
```

**资源配置**：
```yaml
resources:
  requests:
    memory: "512Mi"
    cpu: "250m"
  limits:
    memory: "2Gi"
    cpu: "1000m"

volumeMounts:
  - name: lsp-cache
    mountPath: /cache
    
env:
  - name: REDIS_URL
    value: "redis://redis-cluster:6379"
  - name: FS_INOTIFY_MAX_USER_WATCHES
    value: "524288"
```

### 8.2 LSP 增强流程

```
Hybrid LSP+AST Parser:
  输入：源代码文件
  输出：增强的符号节点
  
  Step 1: 并行启动
    - Thread 1: Tree-sitter AST 解析
    - Thread 2: 启动 LSP 服务器（如未启动）
  
  Step 2: AST 解析（基础结构）
    - 提取符号定义
    - 提取调用关系
    - 生成基础符号表
  
  Step 3: LSP 语义增强（超时 5 秒）
    - textDocument/hover → 获取类型信息
    - textDocument/definition → 确认符号定义位置
    - textDocument/references → 获取符号引用
    - textDocument/callHierarchy → 获取调用层次
  
  Step 4: 合并结果
    - 以 AST 结果为基础
    - 补充 LSP 语义信息
    - 标记 lsp_enhanced=true
  
  Step 5: 降级处理
    - LSP 超时 → 使用纯 AST 结果，lsp_enhanced=false
    - LSP 错误 → 记录日志，使用纯 AST 结果
```

### 8.3 Redis 缓存策略

**缓存内容**：
```typescript
interface RedisCache {
  // 常见库的类型信息
  library_types: Record<string, TypeInfo>;
  
  // 符号解析结果
  symbol_resolutions: Record<string, SymbolDefinition>;
  
  // 调用图片段
  call_graph_fragments: Record<string, CallGraphNode[]>;
}
```

**缓存策略**：
- TTL: 24 小时
- 淘汰策略：LRU
- 更新时机：仓库代码变更时失效相关缓存

---

## 9. 处理逻辑与流程

### 9.1 全量解析流水线

```
Step 1: 仓库扫描
  输入：repository_path, source_revision
  处理：
    1.1 遍历仓库文件（排除 .gitignore）
    1.2 按语言分组
    1.3 初始化 Merkle 树
  输出：文件列表、Merkle 树

Step 2: 并行 AST 解析
  输入：文件列表、解析器配置
  处理：
    2.1 Worker 池并行处理
    2.2 选择解析器（TIER_1: AST+LSP; TIER_2: Tree-sitter）
    2.3 提取 AST 节点
  输出：AST 节点列表

Step 3: 符号提取
  输入：AST 节点列表
  处理：
    3.1 生成 qualified_name
    3.2 提取签名和文档字符串
    3.3 确定可见性
  输出：SymbolNodes 列表

Step 4: 关系提取
  输入：AST 节点列表、符号表
  处理：
    4.1 提取 IMPORTS（文件导入）
    4.2 提取 DEFINES（文件定义符号）
    4.3 提取 CALLS（符号调用）
    4.4 提取 USES_TYPE（类型使用）
    4.5 提取 EXTENDS/IMPLEMENTS（继承/实现）
  输出：RelationEdges 列表

Step 5: 依赖分析
  输入：包管理文件
  处理：
    5.1 解析包管理文件
    5.2 提取直接依赖（层级 0）
    5.3 提取一层传递依赖（层级 1）
    5.4 构建依赖图
  输出：DependencyNodes 列表

Step 6: 调用图构建
  输入：CALLS 关系
  处理：
    6.1 构建有向图
    6.2 使用 Tarjan 检测 SCC
    6.3 标记循环依赖
    6.4 计算图度量
  输出：CallGraph

Step 7: 版本绑定与提交
  输入：所有解析结果
  处理：
    7.1 绑定 source_revision
    7.2 生成 index_version
    7.3 更新 IndexMetadata
    7.4 原子写入索引存储
  输出：索引完成事件
```

### 9.2 增量解析流水线

```
Step 1: Merkle 树对比
  输入：当前文件列表、上次 Merkle 树
  处理：
    1.1 计算当前 Merkle 树
    1.2 对比根哈希
    1.3 递归找出差异
  输出：变更文件列表

Step 2: 增量 AST 解析
  输入：变更文件列表
  处理：
    2.1 对修改/新增文件重新解析
    2.2 对删除文件标记删除
  输出：增量 AST 节点

Step 3: 增量符号更新
  输入：旧符号表、增量 AST 节点
  处理：
    3.1 删除旧符号和关系
    3.2 提取新符号和关系
    3.3 重建受影响的调用图子图
  输出：更新的符号和关系

Step 4: 一致性验证
  输入：增量更新结果
  处理：
    4.1 验证符号 qualified_name 无冲突
    4.2 验证关系完整性
    4.3 验证无悬空引用
  输出：验证报告

Step 5: 原子提交
  输入：验证通过的增量更新
  处理：
    5.1 原子写入索引存储
    5.2 更新 Merkle 树缓存
    5.3 失效 Redis 相关缓存
  输出：增量更新事件
```

---

## 10. 异常与失败处理

| 异常场景 | 检测方法 | 处理策略 | 影响范围 |
|----------|----------|----------|----------|
| **AST 解析失败** | 解析器返回 error | 记录警告，跳过文件 | 局部 |
| **LSP 超时** | 5 秒超时 | 回退到纯 AST | 语义信息缺失 |
| **LSP Pod 不可用** | 健康检查失败 | 触发 Pod 重启，期间使用 Tree-sitter | 临时精度下降 |
| **符号解析冲突** | qualified_name 重复 | 抛出异常，人工干预 | 阻塞索引 |
| **循环依赖** | Tarjan 算法检测 | 记录但不阻塞，图遍历深度限制 | 无 |
| **依赖解析失败** | 包管理文件格式错误 | 跳过依赖分析，记录警告 | 依赖图不完整 |
| **Merkle 树损坏** | 缓存校验失败 | 回退到全量解析 | 全量重解析 |
| **Redis 缓存不可用** | 连接失败 | 降级到无缓存模式 | 冷启动延迟增加 |

---

## 11. 性能、成本、延迟考量

### 11.1 性能目标

| 规模 | 全量索引时间 | 增量索引时间 | LSP 响应延迟 p95 |
|------|-------------|-------------|------------------|
| SMALL (<100 文件) | < 5s | < 0.5s/文件 | < 2s |
| MEDIUM (100-1000 文件) | < 30s | < 1s/文件 | < 2s |
| LARGE (1000-10000 文件) | < 120s | < 2s/文件 | < 3s |

### 11.2 成本估算

| 成本项 | 估算 | 说明 |
|--------|------|------|
| **计算成本** | $0.001/千行代码 | AST 解析 |
| **LSP 实例成本** | $0.10/仓库/月 | Kubernetes Pod |
| **Redis 缓存成本** | $0.02/GB/月 | 共享缓存层 |
| **存储成本** | $0.001/文件/月 | 索引数据 + 持久卷 |

### 11.3 延迟优化策略

1. **并行解析**：Worker 池并行处理独立文件
2. **增量优先**：Merkle 树避免全量重解析
3. **Redis 缓存**：共享常见库的类型信息
4. **持久卷缓存**：AST 和符号索引缓存到持久卷
5. **流式写入**：解析结果流式写入，减少内存占用

---

## 12. 可观测性与评估指标

### 12.1 解析质量指标

| 指标 | 定义 | 目标 | 测量方法 |
|------|------|------|----------|
| `parse_success_rate` | 成功解析文件数 / 总文件数 | > 95% | 解析日志统计 |
| `symbol_extraction_recall` | 提取符号数 / 实际符号数 | > 90% | 人工抽样验证 |
| `call_graph_accuracy` | 正确调用关系数 / 总调用关系数 | > 90% | 人工抽样验证 |
| `lsp_enhancement_rate` | LSP 增强成功数 / LSP 请求数 | > 85% | LSP 响应统计 |
| `dependency_resolution_accuracy` | 正确依赖关系数 / 总依赖数 | > 95% | 对比 lockfile |

### 12.2 性能指标

| 指标 | 定义 | 目标 | 告警阈值 |
|------|------|------|----------|
| `full_index_duration` | 全量索引耗时 | < 目标 | > 目标 2x |
| `incremental_index_duration` | 增量索引耗时 | < 1s/文件 | > 5s/文件 |
| `lsp_response_time_p95` | LSP 响应延迟 p95 | < 2s | > 5s |
| `redis_cache_hit_rate` | Redis 缓存命中率 | > 70% | < 50% |
| `merkle_tree_diff_time` | Merkle 树对比耗时 | < 100ms | > 500ms |

### 12.3 健康指标

| 指标 | 定义 | 告警阈值 |
|------|------|----------|
| `parse_failure_rate` | 解析失败文件数 / 总文件数 | > 5% |
| `lsp_timeout_rate` | LSP 超时次数 / LSP 请求数 | > 10% |
| `lsp_pod_restart_count` | LSP Pod 重启次数 | > 5/天 |
| `redis_connection_errors` | Redis 连接错误次数 | > 10/小时 |
| `circular_dependency_count` | 检测到的循环依赖数量 | > 100 |

---

## 13. 验收标准

| 编号 | 验收标准 | 验证方法 |
|------|----------|----------|
| V1 | TIER_1 语言（Python/TypeScript/Go）支持 AST + LSP 解析 | 功能测试 |
| V2 | LSP 部署为每仓库独立实例 | 架构审查 |
| V3 | Redis 缓存层正常工作，缓存命中率 > 70% | 性能测试 |
| V4 | MEDIUM 仓库全量索引 < 30s（实测） | 性能测试 |
| V5 | 单文件增量解析 < 1s（实测） | 性能测试 |
| V6 | 符号提取 Recall > 0.9（基准集验证） | 质量评测 |
| V7 | 依赖解析支持直接依赖 + 一层传递依赖 | 功能测试 |
| V8 | 循环依赖检测不阻塞索引 | 功能测试 |
| V9 | Merkle 树变更检测准确率 100% | 单元测试 |
| V10 | LSP 超时自动降级到纯 AST | 异常测试 |
| V11 | 敏感路径（.env）正确过滤 | 安全测试 |
| V12 | 解析错误详细日志记录 | 可观测性验证 |

---

## 14. 依赖与接口

### 14.1 上游依赖

| 依赖 | 接口 | 说明 |
|------|------|------|
| REQ-CTX-001 | FileNode, SymbolNode, RelationEdge, DependencyNode Schema | 索引实体定义 |
| REQ-CTX-002 | LanguageConfig, RepositoryScaleConfig | 语言和规模配置 |
| REQ-RT-001 | repository_id, source_revision | 运行时实体 |
| REQ-SEC-002 | RBAC 权限 | 索引权限检查 |
| REQ-SEC-005 | 敏感路径黑名单 | 解析前过滤 |

### 14.2 下游接口

| 接口 | 消费者 | 说明 |
|------|--------|------|
| `SymbolNodes` | REQ-CTX-004 | 混合检索输入 |
| `RelationEdges` | REQ-CTX-004 | 图检索输入 |
| `DependencyNodes` | REQ-CTX-004 | 依赖检索输入 |
| `CallGraph` | REQ-CTX-006 | Context Selector |
| `MerkleTree` | REQ-CTX-007 | 增量一致性 |
| `ParseMetadata` | REQ-EVA-003 | 评估输入 |

---

## 15. 版本与演进

### 15.1 版本策略

| 变更类型 | 版本升级 | 兼容性 |
|----------|----------|--------|
| 新增解析器支持 | 小版本 | 向前兼容 |
| 新增关系类型 | 小版本 | 向前兼容 |
| 修改 qualified_name 格式 | 大版本 | 需要迁移 |
| 依赖解析精度升级（一层→完整） | 小版本 | 向前兼容 |

### 15.2 演进路线

| 阶段 | 语言扩展 | 解析能力扩展 | 依赖解析扩展 |
|------|----------|-------------|-------------|
| MVP | Python, TypeScript, Go | AST + LSP | 直接 + 一层传递 |
| Phase 2 | +Java, Rust, C++, C# | Tree-sitter | 完整传递依赖图 |
| Phase 3 | +Ruby, PHP, Kotlin, Swift | 渐进增强 | 跨仓库依赖分析 |

---

## 16. 决策记录

| 决策项 | 决策 | 依据 |
|-------|------|------|
| 解析框架 | Tree-sitter 统一框架 | Codebase-Memory, auto-lsp |
| 增量检测 | Merkle 树 | Cursor 公开实践 |
| 符号标识 | Qualified name（SCIP 风格） | Sourcegraph 最佳实践 |
| LSP 部署 | 每仓库独立实例 + Redis 缓存 | 2026 企业级部署标准 |
| 依赖精度 | 直接 + 一层传递（MVP） | 通义灵码、Qoder 工程级感知 |
| 循环依赖 | 静默检测 + 深度限制 | Sourcegraph SCIP, Codebase-Memory |

---

**文档创建时间**：2026-09-28  
**维护团队**：架构组
