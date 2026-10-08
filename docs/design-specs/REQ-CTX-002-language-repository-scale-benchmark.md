# REQ-CTX-002 语言、仓库规模和基准集详细设计

> 版本：v0.1-designed  
> 优先级：P1  
> 状态：详细设计已完成，待跨模块评审与冻结  
> 所属模块：上下文管理（CTX）  
> 前置依赖：REQ-CTX-001（索引实体和关系 Schema）、REQ-EVA-001（Golden Dataset）  
> 下游依赖：REQ-CTX-003~009

---

## 1. 目标与范围

### 1.1 需求目标

明确定义 MVP 阶段的语言支持范围、仓库规模分级标准、基准集构建规范，为下游模块提供统一的设计基线。

**核心价值**：
- 降低下游模块的设计歧义
- 提供可验证的评测基准
- 控制实现复杂度（不过度设计）
- 支持演进和扩展

### 1.2 设计边界

**包含**：
- 语言支持等级定义（TIER_1/TIER_2/UNSUPPORTED）
- 仓库规模分级标准（SMALL/MEDIUM/LARGE/XLARGE）
- 基准集构建规范和元数据结构
- 性能目标和验收标准
- 与 Runtime Contract 的集成

**不包含**：
- 具体的 AST 解析器实现（归属 REQ-CTX-003）
- 混合检索算法实现（归属 REQ-CTX-004）
- 权限过滤规则（归属 REQ-CTX-005）
- Context Selector 实现（归属 REQ-CTX-006）

---

## 2. 行业调研与可借鉴设计

### 2.1 GitHub Copilot

**语言支持策略**：
- 14 种核心语言：C, C++, C#, Go, Java, JavaScript, Kotlin, PHP, Python, Ruby, Rust, Scala, Swift, TypeScript
- 自动语义索引，秒级完成（大型仓库 < 60 秒）
- 支持非 GitHub 仓库（需策略启用）

**可借鉴点**：
1. 核心语言覆盖 Web、后端、移动开发主流场景
2. 秒级索引作为性能目标
3. 增量更新机制

**来源**：
- [GitHub Changelog 2025-03-12](https://github.blog/changelog/2025-03-12-instant-semantic-code-search-indexing-now-generally-available-for-github-copilot/)（访问日期：2026-09-26）
- [索引文档](https://docs.github.com/copilot/concepts/indexing-repositories-for-copilot-chat)（访问日期：2026-09-26）

### 2.2 Cursor

**仓库规模策略**：
- Merkle 树增量同步，按需同步变更文件
- 向量 embedding 缓存，重复索引快速
- Simhash 加速新用户索引重用

**可借鉴点**：
1. Merkle 树零配置增量更新
2. 缓存策略优化重复索引
3. 内容证明防止越权访问

**来源**：
- [Cursor 安全索引文档](https://cursor.com/blog/secure-codebase-indexing)（访问日期：2026-09-26）
- [Engineer's Codex 分析](https://read.engineerscodex.com/p/how-cursor-indexes-codebases-fast)（访问日期：2026-09-26）

### 2.3 Sourcegraph

**语言与规模策略**：
- 8 种语言 GA 支持：Go, TypeScript/JavaScript, C/C++/CUDA, Java/Kotlin/Scala, Rust, Python, Ruby, C#/Visual Basic
- 调度策略参数化配置：批处理规模（100 仓库/批次）、延迟（24 小时/仓库）、并发（1 工作者）
- 多分支保留策略（HEAD vs 所有分支 vs 所有 commit）

**可借鉴点**：
1. SCIP 协议标准化（Human-readable 符号 ID）
2. 调度策略参数化配置
3. 保留策略与成本权衡

**来源**：
- [SCIP 协议文档](https://sourcegraph.com/docs/code-navigation/precise-code-navigation.md)（访问日期：2026-09-26）
- [环境变量文档](https://sourcegraph.com/docs/code-navigation/envvars)（访问日期：2026-09-26）

### 2.4 通义灵码（阿里）

**语言与规模策略**：
- 200+ 种语言整体支持
- 企业代码库：Java, C#, C/C++, Go, Python, JavaScript, TypeScript, Vue, React
- 最多索引 6000 个文件（硬限制）
- 单个代码包上限 100 MB

**可借鉴点**：
1. 6000 文件规模限制作为参考
2. 企业代码库分语言支持
3. 增量索引（首次全量，后续单文件触发）

**来源**：
- [代码库索引文档](https://help.aliyun.com/zh/lingma/index)（访问日期：2026-09-26）
- [企业代码补全最佳实践](https://help.aliyun.com/zh/lingma/enterprise-code-completion-enhancement-best-practice)（访问日期：2026-09-26）

### 2.5 Qoder

**仓库规模策略**：
- 10 万文件支持上限
- 1 万文件以下自动索引，以上需手动激活
- 混合架构：服务端向量数据库 + 客户端代码图
- Repo Wiki：10000 文件项目推荐

**可借鉴点**：
1. 10 万文件规模上限
2. 自动/手动索引切换阈值（1 万）
3. 向量 + 图混合架构

**来源**：
- [索引文档](https://docs.qoder.com/user-guide/indexing)（访问日期：2026-09-26）
- [混合检索技术文章](https://dev.to/qoder/qoders-codebase-aware-code-retrieval-a-hybrid-approach-for-ai-coding-gpm)（访问日期：2026-09-26）

### 2.6 DeepSeek-Coder

**语言支持策略**：
- V1: 87 种语言，16K 上下文
- V2: 338 种语言，128K 上下文
- 依赖感知打包：Python, Java, C#, C, C++ 使用修改的拓扑排序处理循环依赖

**可借鉴点**：
1. 338 种语言覆盖范围（参考目标）
2. 依赖图构建策略
3. 循环依赖处理

**来源**：
- [GitHub 仓库](https://github.com/deepseek-ai/DeepSeek-Coder)（访问日期：2026-09-26）
- [arxiv V2 论文](https://arxiv.org/html/2406.11931v1)（访问日期：2026-09-26）

### 2.7 SWE-bench

**基准集策略**：
- 2,294 个真实 GitHub Issue
- SWE-bench Verified: 500 个人工验证问题（人工确认可解决）
- 平均仓库规模：43.8 万行代码
- 评测设置：45 分钟运行时限、全仓库输入、无文件提示

**可借鉴点**：
1. 人工验证子集标准（筛选标准：15-60 分钟难度、恰好 2 文件修改）
2. 多难度级别分布
3. 真实任务来源

**来源**：
- [SWE-bench GitHub](https://github.com/swe-bench/SWE-bench)（访问日期：2026-09-26）
- [SWE-bench 论文](https://proceedings.iclr.cc/paper_files/paper/2024/file/edac78c3e300629acfe6cbe9ca88fb84-Paper-Conference.pdf)（访问日期：2026-09-26）

### 2.8 Infino code-context

**性能基准数据**：
- Django（3,597 文件）：索引 6.7 秒
- TypeScript 全仓库（51,826 文件）：索引 83 秒
- 增量索引：< 1 秒/文件
- Token 节省：聚合查询 -43%，理解查询 -29%，混合查询 -32%

**可借鉴点**：
1. 索引时间基准数据
2. 增量索引性能目标
3. 评测问题分类（聚合/理解/混合）

**来源**：
- [code-context benchmark](https://github.com/infino-ai/code-context/blob/main/docs/benchmark.md)（访问日期：2026-09-26）

---

## 3. 语言支持等级定义

### 3.1 语言支持分级标准

```typescript
enum LanguageTier {
  TIER_1 = "tier_1",         // 完全支持：AST + LSP + 向量化 + 全文 + 图关系
  TIER_2 = "tier_2",         // 部分支持：AST + 向量化 + 全文（无 LSP、无图关系）
  UNSUPPORTED = "unsupported" // 暂不支持：仅向量化 + 全文（无结构化分析）
}
```

### 3.2 TIER_1 语言（完全支持）

**MVP 阶段 TIER_1 语言**：
1. **Python**
2. **TypeScript**
3. **Go**

**选择依据**：

| 语言 | 开源生态 | AST 工具 | LSP 支持 | 评测数据 | 团队匹配 | 综合得分 |
|------|----------|----------|----------|----------|----------|----------|
| Python | ★★★★★ | ast, tree-sitter | pyright, jedi | ★★★★★ | ★★★★★ | 5/5 |
| TypeScript | ★★★★★ | TS compiler, tree-sitter | tsserver | ★★★★★ | ★★★★★ | 5/5 |
| Go | ★★★★★ | go/ast, tree-sitter | gopls | ★★★★★ | ★★★★☆ | 4.6/5 |

**TIER_1 语言配置**：

```typescript
const TIER_1_LANGUAGES: LanguageConfig[] = [
  {
    language: "Python",
    extensions: [".py", ".pyw", ".pyi"],
    tier: LanguageTier.TIER_1,
    ast_parser: "ast (stdlib) / tree-sitter-python",
    lsp_available: true,
    lsp_servers: ["pyright", "jedi"],
    embedding_model: "text-embedding-3-small",
    ecosystem: ["pip", "poetry", "conda"],
    dependency_files: ["requirements.txt", "pyproject.toml", "setup.py", "Pipfile"],
    min_test_cases: 20,
  },
  {
    language: "TypeScript",
    extensions: [".ts", ".tsx", ".d.ts"],
    tier: LanguageTier.TIER_1,
    ast_parser: "typescript compiler API / tree-sitter-typescript",
    lsp_available: true,
    lsp_servers: ["tsserver"],
    embedding_model: "text-embedding-3-small",
    ecosystem: ["npm", "yarn", "pnpm"],
    dependency_files: ["package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml"],
    min_test_cases: 20,
  },
  {
    language: "Go",
    extensions: [".go"],
    tier: LanguageTier.TIER_1,
    ast_parser: "go/ast / tree-sitter-go",
    lsp_available: true,
    lsp_servers: ["gopls"],
    embedding_model: "text-embedding-3-small",
    ecosystem: ["go modules"],
    dependency_files: ["go.mod", "go.sum"],
    min_test_cases: 20,
  },
];
```

### 3.3 TIER_2 语言（部分支持）

**Phase 2 扩展 TIER_2 语言**：
1. **Java**
2. **Rust**
3. **C++**
4. **C#**

**TIER_2 语言配置**：

```typescript
const TIER_2_LANGUAGES: LanguageConfig[] = [
  {
    language: "Java",
    extensions: [".java"],
    tier: LanguageTier.TIER_2,
    ast_parser: "tree-sitter-java",
    lsp_available: true,  // 可选支持
    lsp_servers: ["jdtls"],
    embedding_model: "text-embedding-3-small",
    ecosystem: ["maven", "gradle"],
    dependency_files: ["pom.xml", "build.gradle", "build.gradle.kts"],
    min_test_cases: 10,
  },
  {
    language: "Rust",
    extensions: [".rs"],
    tier: LanguageTier.TIER_2,
    ast_parser: "tree-sitter-rust",
    lsp_available: true,
    lsp_servers: ["rust-analyzer"],
    embedding_model: "text-embedding-3-small",
    ecosystem: ["cargo"],
    dependency_files: ["Cargo.toml", "Cargo.lock"],
    min_test_cases: 10,
  },
  {
    language: "C++",
    extensions: [".cpp", ".cc", ".cxx", ".hpp", ".h", ".hxx"],
    tier: LanguageTier.TIER_2,
    ast_parser: "tree-sitter-cpp",
    lsp_available: true,
    lsp_servers: ["clangd"],
    embedding_model: "text-embedding-3-small",
    ecosystem: ["cmake", "vcpkg", "conan"],
    dependency_files: ["CMakeLists.txt", "vcpkg.json", "conanfile.txt"],
    min_test_cases: 10,
  },
  {
    language: "C#",
    extensions: [".cs", ".csx"],
    tier: LanguageTier.TIER_2,
    ast_parser: "tree-sitter-c-sharp",
    lsp_available: true,
    lsp_servers: ["omnisharp"],
    embedding_model: "text-embedding-3-small",
    ecosystem: ["nuget", "dotnet"],
    dependency_files: [".csproj", "packages.config", "nuget.config"],
    min_test_cases: 10,
  },
];
```

### 3.4 UNSUPPORTED 语言（暂不支持）

**处理策略**：
- 仅向量化 + 全文索引（无结构化分析）
- 回退到通用文本检索
- 记录警告日志

---

## 4. 仓库规模分级标准

### 4.1 规模等级定义

```typescript
enum RepositoryScaleTier {
  SMALL = "small",       // < 100 文件
  MEDIUM = "medium",     // 100-1000 文件
  LARGE = "large",       // 1000-10000 文件
  XLARGE = "xlarge"      // > 10000 文件
}
```

### 4.2 规模分级配置

```typescript
const REPOSITORY_SCALE_CONFIGS: RepositoryScaleConfig[] = [
  {
    tier: RepositoryScaleTier.SMALL,
    file_count_range: [0, 99],
    loc_range: [0, 10000],
    index_time_target_seconds: 5,
    retrieval_latency_p95_ms: 200,
    incremental_index_time_target_seconds: 0.5,
    storage_estimate_mb: 10,
    recommended_strategy: "full_ast_lsp_vector",
  },
  {
    tier: RepositoryScaleTier.MEDIUM,
    file_count_range: [100, 999],
    loc_range: [10000, 100000],
    index_time_target_seconds: 30,
    retrieval_latency_p95_ms: 300,
    incremental_index_time_target_seconds: 1,
    storage_estimate_mb: 50,
    recommended_strategy: "full_ast_lsp_vector",
  },
  {
    tier: RepositoryScaleTier.LARGE,
    file_count_range: [1000, 9999],
    loc_range: [100000, 1000000],
    index_time_target_seconds: 120,
    retrieval_latency_p95_ms: 500,
    incremental_index_time_target_seconds: 2,
    storage_estimate_mb: 200,
    recommended_strategy: "ast_vector_selective_lsp",
  },
  {
    tier: RepositoryScaleTier.XLARGE,
    file_count_range: [10000, Infinity],
    loc_range: [1000000, Infinity],
    index_time_target_seconds: 300,
    retrieval_latency_p95_ms: 1000,
    incremental_index_time_target_seconds: 5,
    storage_estimate_mb: 500,
    recommended_strategy: "ast_vector_no_lsp",
    requires_manual_activation: true,
  },
];
```

### 4.3 规模判定算法

```typescript
function determineRepositoryScale(repository: Repository): RepositoryScaleConfig {
  const fileCount = countCodeFiles(repository);  // 排除 node_modules, .git 等
  const loc = countLinesOfCode(repository);
  
  for (const config of REPOSITORY_SCALE_CONFIGS) {
    if (fileCount >= config.file_count_range[0] && 
        fileCount <= config.file_count_range[1]) {
      return config;
    }
  }
  
  // 回退到 XLARGE
  return REPOSITORY_SCALE_CONFIGS.find(c => c.tier === RepositoryScaleTier.XLARGE)!;
}
```

---

## 5. 基准集构建规范

### 5.1 基准集定义

**MVP 基准集规模**：
- 每种 TIER_1 语言：至少 10 个基准仓库
- 总计至少 50 个真实任务（脱敏）
- 难度分布：简单 40%、中等 40%、困难 20%

**Phase 2 基准集扩展**：
- 每种 TIER_1 语言：20 个基准仓库
- 每种 TIER_2 语言：10 个基准仓库
- 总计至少 100 个真实任务

### 5.2 基准集元数据结构

```typescript
interface BenchmarkSetMetadata {
  // 基本信息
  name: string;
  version: string;
  description: string;
  
  // 语言和规模分布
  languages: string[];
  scale_tiers: RepositoryScaleTier[];
  
  // 统计信息
  total_repositories: number;
  total_tasks: number;
  
  // 仓库分布
  repository_distribution: {
    language: string;
    scale_tier: RepositoryScaleTier;
    count: number;
  }[];
  
  // 任务分布
  task_distribution: {
    language: string;
    difficulty: "easy" | "medium" | "hard";
    count: number;
  }[];
  
  // 难度分布
  difficulty_distribution: {
    easy: number;    // 40%
    medium: number;  // 40%
    hard: number;    // 20%
  };
  
  // 来源和合规
  source: "opensource" | "anonymized" | "synthetic";
  license: string;
  privacy_reviewed: boolean;
  
  // 版本和时间
  created_at: string;
  last_updated: string;
  schema_version: string;
}
```

### 5.3 基准仓库元数据

```typescript
interface BenchmarkRepository {
  // 标识
  repo_id: string;
  name: string;
  
  // 语言和规模
  primary_language: string;
  language_distribution: Record<string, number>;  // 百分比
  scale_tier: RepositoryScaleTier;
  file_count: number;
  loc: number;
  
  // 来源
  original_url?: string;  // 如果是开源仓库
  anonymized: boolean;
  
  // 特征
  has_tests: boolean;
  has_documentation: boolean;
  dependency_count: number;
  
  // Git 信息
  commit_sha: string;
  indexed_at: string;
}
```

### 5.4 基准任务元数据

```typescript
interface BenchmarkTask {
  // 标识
  task_id: string;
  repo_id: string;
  
  // 任务描述
  title: string;
  description: string;
  task_type: "bug_fix" | "feature_add" | "refactor" | "code_review";
  
  // 难度
  difficulty: "easy" | "medium" | "hard";
  estimated_time_minutes: number;
  
  // Ground Truth
  ground_truth: {
    required_files: string[];
    required_symbols: string[];
    relevance_scores: Record<string, number>;  // file_path -> score (0-1)
  };
  
  // 评测标准
  evaluation_criteria: {
    recall_at_5_target: number;
    recall_at_10_target: number;
    precision_at_5_target: number;
    mrr_target: number;
  };
  
  // 元数据
  created_at: string;
  created_by: string;  // 标注者ID
  reviewed: boolean;
}
```

### 5.5 基准集构建流程

```
Step 1: 仓库收集
  - 从开源平台筛选代表性仓库（GitHub, GitLab）
  - 或脱敏内部真实仓库
  - 覆盖 TIER_1 语言 × 规模等级

Step 2: 仓库预处理
  - 克隆仓库到固定 commit SHA
  - 排除敏感信息（.env, credentials）
  - 生成仓库元数据

Step 3: 任务标注
  - 从真实 Issue/PR 中提取任务描述
  - 或由工程师编写任务
  - 人工标注 required_files 和 required_symbols

Step 4: 质量评审
  - 交叉验证标注一致性
  - 检查难度分布
  - 确认隐私合规

Step 5: 版本发布
  - 生成基准集元数据
  - 打包仓库快照
  - 发布到评测平台
```

---

## 6. 性能目标与验收标准

### 6.1 索引性能目标

| 规模等级 | 索引时间目标 | 增量索引目标 | 依据 |
|----------|--------------|--------------|------|
| SMALL | < 5 秒 | < 0.5 秒/文件 | GitHub Copilot 秒级索引 |
| MEDIUM | < 30 秒 | < 1 秒/文件 | Infino Django benchmark (6.7s) |
| LARGE | < 120 秒 | < 2 秒/文件 | 推测（比例扩展） |
| XLARGE | < 300 秒 | < 5 秒/文件 | Infino TypeScript benchmark (83s) |

### 6.2 检索性能目标

| 规模等级 | 检索延迟 p95 | BM25 延迟 | 向量检索延迟 |
|----------|--------------|-----------|--------------|
| SMALL | < 200ms | < 50ms | < 100ms |
| MEDIUM | < 300ms | < 100ms | < 150ms |
| LARGE | < 500ms | < 150ms | < 200ms |
| XLARGE | < 1000ms | < 300ms | < 500ms |

### 6.3 检索质量目标

| 指标 | 目标 | 依据 |
|------|------|------|
| Recall@5 | > 0.8 | SWE-bench 基线 |
| Recall@10 | > 0.9 | 行业共识 |
| Precision@5 | > 0.6 | 行业共识 |
| MRR | > 0.7 | 行业共识 |

### 6.4 验收标准

| 编号 | 验收标准 | 验证方法 |
|------|----------|----------|
| V1 | 定义 TIER_1、TIER_2、UNSUPPORTED 三级语言等级 | 配置审查 |
| V2 | TIER_1 包含 Python、TypeScript、Go 三种语言 | 配置审查 |
| V3 | 定义 SMALL、MEDIUM、LARGE、XLARGE 四级规模 | 配置审查 |
| V4 | 每种 TIER_1 语言至少 10 个基准仓库 | 数据审查 |
| V5 | 基准集包含至少 50 个真实任务（脱敏） | 数据审查 |
| V6 | SMALL 仓库索引时间 < 5s（实测验证） | 性能测试 |
| V7 | MEDIUM 仓库索引时间 < 30s（实测验证） | 性能测试 |
| V8 | 语言配置和规模配置可通过 API 查询 | 接口测试 |
| V9 | 异常场景（未知语言、超大规模）有降级处理 | 异常测试 |
| V10 | Recall@10 > 0.9（基准集验证） | 质量评测 |

---

## 7. 与 Runtime Contract 的集成

### 7.1 版本绑定

| Runtime 实体 | 索引实体 | 绑定字段 |
|--------------|----------|----------|
| Task.base_revision | IndexMetadata.source_revision | 版本一致性 |
| Worker.source_revision | RetrievalQuery.source_revision | 检索版本锁定 |
| Action | RetrievalResult | 检索结果可回放 |
| Artifact | RetrievedChunk | 产物绑定代码版本 |

### 7.2 接口定义

```typescript
// 查询语言配置
GET /api/v1/languages?repository_id={id}
Response: {
  languages: LanguageConfig[];
  primary_language: string;
  tier_distribution: Record<LanguageTier, number>;
  unsupported_extensions: string[];
}

// 查询规模配置
GET /api/v1/scales?repository_id={id}
Response: {
  tier: RepositoryScaleTier;
  file_count: number;
  loc: number;
  config: RepositoryScaleConfig;
  estimated_index_time_seconds: number;
}

// 查询基准集
GET /api/v1/benchmarks?languages={}&scale_tiers={}&min_tasks={}
Response: {
  benchmark_sets: BenchmarkSetMetadata[];
  total_repositories: number;
  total_tasks: number;
  filtered_count: number;
}

// 查询基准仓库
GET /api/v1/benchmarks/{set_name}/repositories
Response: {
  repositories: BenchmarkRepository[];
  total: number;
  page: number;
  page_size: number;
}

// 查询基准任务
GET /api/v1/benchmarks/{set_name}/tasks?repo_id={}&difficulty={}
Response: {
  tasks: BenchmarkTask[];
  total: number;
  difficulty_distribution: Record<string, number>;
}
```

---

## 8. 异常与失败处理

### 8.1 异常场景

| 异常场景 | 处理策略 | 降级方案 |
|----------|----------|----------|
| **未知语言** | 回退到 UNSUPPORTED，记录警告 | 仅向量化 + 全文 |
| **超大规模仓库** | 降级到 LARGE，提示用户排除部分目录 | 手动配置排除规则 |
| **混合语言仓库** | 按主要语言选择配置，次要语言尽力支持 | 多语言配置组合 |
| **基准集缺失** | 使用通用基准集，标记数据不足 | 跨语言通用评测 |
| **索引超时** | 记录失败，告警，提供重试选项 | 分批索引 |
| **依赖解析失败** | 跳过依赖分析，仅索引符号 | 无依赖图模式 |

### 8.2 降级策略

```typescript
function getDegradedConfig(
  language: string,
  tier: LanguageTier,
  scaleTier: RepositoryScaleTier
): IndexingConfig {
  if (tier === LanguageTier.UNSUPPORTED) {
    return {
      enable_ast: false,
      enable_lsp: false,
      enable_vector: true,
      enable_fulltext: true,
      enable_graph: false,
    };
  }
  
  if (scaleTier === RepositoryScaleTier.XLARGE) {
    return {
      enable_ast: true,
      enable_lsp: false,  // 禁用 LSP（性能考虑）
      enable_vector: true,
      enable_fulltext: true,
      enable_graph: false,  // 禁用图关系（存储考虑）
    };
  }
  
  // 默认完整配置
  return {
    enable_ast: true,
    enable_lsp: true,
    enable_vector: true,
    enable_fulltext: true,
    enable_graph: true,
  };
}
```

---

## 9. 可观测性与评估指标

### 9.1 健康指标

| 指标 | 定义 | 告警阈值 |
|------|------|----------|
| `language_support_coverage` | TIER_1 语言覆盖的仓库比例 | < 80% |
| `scale_tier_accuracy` | 规模判定准确率（与人工判定对比） | < 95% |
| `benchmark_representativeness` | 基准集语言分布与生产分布偏差 | > 20% |
| `index_time_actual_vs_target` | 实际索引时间 / 目标索引时间 | > 1.5x |
| `unknown_language_rate` | 未知语言文件占比 | > 10% |
| `index_failure_rate` | 索引失败率 | > 5% |

### 9.2 评测指标

| 指标 | 定义 | 目标 |
|------|------|------|
| `retrieval_recall_at_5` | 前 5 结果召回率 | > 0.8 |
| `retrieval_recall_at_10` | 前 10 结果召回率 | > 0.9 |
| `retrieval_precision_at_5` | 前 5 结果准确率 | > 0.6 |
| `retrieval_mrr` | 平均倒数排名 | > 0.7 |
| `task_success_rate` | 任务成功率（使用检索上下文） | > 0.85 |

---

## 10. 版本与演进

### 10.1 演进路线

| 阶段 | 语言扩展 | 规模扩展 | 基准集扩展 |
|------|----------|----------|------------|
| **MVP** | Python, TypeScript, Go | SMALL, MEDIUM | 每语言 10 仓库，50 任务 |
| **Phase 2** | +Java, Rust, C++, C# | +LARGE | 每语言 20 仓库，100 任务 |
| **Phase 3** | +Ruby, PHP, Kotlin, Swift | +XLARGE | 持续扩充，多难度级别 |
| **Long-term** | 扩展到 50+ 语言 | 支持 Monorepo | 多领域基准集 |

### 10.2 版本策略

| 变更类型 | 版本升级 | 说明 |
|----------|----------|------|
| 新增 TIER_2 语言 | 小版本 | 向前兼容 |
| TIER_2 升级到 TIER_1 | 小版本 | 向前兼容 |
| 新增规模等级 | 大版本 | 需要迁移 |
| 修改规模阈值 | 大版本 | 需要评审 |
| 扩展基准集 | 小版本 | 向前兼容 |
| 修改基准集标注 | 大版本 | 需要重新评测 |

---

## 11. 依赖与接口

### 11.1 上游依赖

| 依赖 | 说明 |
|------|------|
| `REQ-CTX-001` | 索引实体 Schema（使用 FileNode.language, IndexMetadata.state） |
| `REQ-EVA-001` | Golden Dataset（基准集来源） |
| `REQ-RT-001` | 核心实体 Schema（使用 repository_id, source_revision） |

### 11.2 下游接口

| 接口 | 消费者 | 说明 |
|------|--------|------|
| `LanguageConfig` | REQ-CTX-003 | AST/LSP 解析器选择 |
| `RepositoryScaleConfig` | REQ-CTX-004 | 检索策略选择 |
| `BenchmarkSetMetadata` | REQ-CTX-009 | 评测用例选择 |
| `LanguageTier` | REQ-CTX-005 | 权限过滤配置 |
| `RepositoryScaleTier` | REQ-CTX-006 | Token 预算分配 |

---

## 12. 参考资料

以下为公开来源，访问日期均为 2026-09-26：

- GitHub Copilot 索引：[Repository Indexing](https://docs.github.com/copilot/concepts/indexing-repositories-for-copilot-chat)
- GitHub 语言支持：[Language Support](https://docs.github.com/en/get-started/learning-about-github/github-language-support)
- Cursor 安全索引：[Secure codebase indexing](https://cursor.com/blog/secure-codebase-indexing)
- Sourcegraph SCIP：[Precise Code Navigation](https://sourcegraph.com/docs/code-navigation/precise-code-navigation.md)
- 通义灵码：[代码库索引](https://help.aliyun.com/zh/lingma/index)
- Qoder 索引：[Indexing](https://docs.qoder.com/user-guide/indexing)
- DeepSeek-Coder：[GitHub Repository](https://github.com/deepseek-ai/DeepSeek-Coder)
- SWE-bench：[GitHub Repository](https://github.com/swe-bench/SWE-bench)
- Infino code-context：[Benchmark](https://github.com/infino-ai/code-context/blob/main/docs/benchmark.md)

---

## 13. 决策记录

| 决策项 | 决策 | 依据 |
|-------|------|------|
| TIER_1 语言 | Python, TypeScript, Go | GitHub Copilot 核心语言 + 团队技术栈 |
| 规模阈值 | 100/1000/10000 文件 | Qoder 1万阈值 + 通义灵码 6000文件 |
| 索引时间目标 | SMALL < 5s, MEDIUM < 30s | GitHub Copilot 秒级 + Infino benchmark |
| 基准集规模 | 每语言 10 仓库，50 任务 | SWE-bench Verified 500 问题参考 |
| 检索质量目标 | Recall@10 > 0.9 | 行业共识 |

---

**文档创建时间**：2026-09-26  
**维护团队**：架构组
