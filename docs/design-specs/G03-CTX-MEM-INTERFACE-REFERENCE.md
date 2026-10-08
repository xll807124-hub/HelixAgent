# G03 上下文与记忆 Schema — 下游消费接口参考

> 本文档从 `REQ-CTX-001` v0.1-designed 和 `REQ-MEM-001` v0.1-designed 提炼，供 Harness、Worker Runtime、CTX-002~009、MEM-002~004、OBS、EVA 等下游专项直接引用。
> 文档定位为"消费侧接口表"，不替代两份源设计；若冲突以源设计为准。
>
> 来源：
> - [REQ-CTX-001 索引实体和关系 Schema](REQ-CTX-001-index-entities-schema.md)（v0.1-designed）
> - [REQ-MEM-001 Memory Schema](REQ-MEM-001-memory-schema.md)（v0.1-designed）

---

## 一、共享标识与类型（CTX/MEM 共用，下游必须复用，禁止自建替代 ID）

| 类型 | 格式/约束 | 复用自 |
|---|---|---|
| `EntityId` | UUIDv7 | RT-001 §4.1 |
| `RepositoryId` | EntityId | RT-001 §4.1 |
| `TaskId` / `WorkflowId` / `WorkerId` / `ArtifactId` | 复用 G01 | RT-001 §4.1 |
| `SymbolId` | qualified name string（如 `com.example.UserService.login`），仓库内唯一 | CTX-001 §3.3 |
| `RevisionRef` | Git commit SHA（必须是具体 SHA，不能是 `latest`/`main`） | RT-001 §4.2 |
| `SourceRange` | `{start_line, start_column, end_line, end_column}`，行号从 1 开始 | CTX-001 §3.1 |
| `DataSensitivity` | `PUBLIC / INTERNAL / CONFIDENTIAL / RESTRICTED` | RT-001 §5.5 / SEC-001 §5.2 |
| `SafeMetadata` | 不含凭据、密钥、模型思维链的 JSON 对象 | RT-001 §4 |
| `ContentRef` | `{storage_provider, object_key, media_type, byte_size, content_hash, encryption_key_ref?}` | RT-001 §5.5 |

**硬性约束**：
- CTX/MEM 均不得将聚合/摘要/embedding 向量/缓存内容的敏感级别降至来源数据最高级别以下。
- 检索结果和记忆内容均不得包含未脱敏凭据。

---

## 二、CTX 索引实体速查（CTX-001 §3）

### 2.1 四大核心实体一览

| 实体 | 必填 ID | 关键字段 | 内容不可变字段 | 来源 |
|---|---|---|---|---|
| `FileNode` | `file_id` + `repository_id` | `path`（规范化相对路径）、`language`、`source_revision`、`file_hash`（SHA-256） | `source_revision` + `file_hash` | CTX-001 §3.2 |
| `SymbolNode` | `symbol_id`（qualified）+ `file_id` | `name`/`qualified_name`/`kind`（22 种）/`signature`/`docstring`/`visibility`/`range`/`owner` | `source_revision` | CTX-001 §3.3 |
| `DependencyNode` | `dependency_id` + `repository_id` | `package_name`/`version`/`ecosystem`（8 种）/`source`（direct/transitive） | `source_revision` | CTX-001 §3.4 |
| `RelationEdge` | `relation_id` + `repository_id` | `relation_type`（8 种）/`source_id`/`target_id`/`weight`（默认 1.0） | `source_revision` | CTX-001 §3.5 |

### 2.2 SymbolKind 枚举（22 种，下游代码解析/LSP 对接时必须映射）

```
FUNCTION / METHOD / CLASS / INTERFACE / TYPE / CONSTANT / VARIABLE /
ENUM / ENUM_MEMBER / STRUCT / MODULE / NAMESPACE
+ (来源：SCIP 协议补充)
```

### 2.3 RelationType 枚举（8 种，含文件级和符号级）

| 类型 | 源 → 目标 | 说明 |
|---|---|---|
| `IMPORTS` | File → File | 文件导入 |
| `DEPENDS_ON` | Repository → Dependency | 仓库依赖 |
| `DEFINES` | File → Symbol | 文件定义符号 |
| `CALLS` | Symbol → Symbol | 函数调用（含 `call_count`） |
| `REFERENCES` | Symbol → Symbol | 非调用引用 |
| `USES_TYPE` | Symbol → Symbol | 类型使用 |
| `EXTENDS` | Symbol → Symbol | 类继承 |
| `IMPLEMENTS` | Symbol → Symbol | 接口实现 |

**关系约束**（违反则拒绝）：
- IMPORTS: File → File
- DEPENDS_ON: Repository → Dependency
- DEFINES: File → Symbol
- CALLS/REFERENCES/USES_TYPE/EXTENDS/IMPLEMENTS: Symbol → Symbol

### 2.4 IndexState 枚举（7 种）

```
PENDING → BUILDING → VALIDATING → ACTIVE → STALE → ARCHIVED
                                              ↘ FAILED
```

索引在 `ACTIVE` 状态才可用于检索；`STALE` 表示代码已更新需重建。

---

## 三、CTX 检索接口速查（CTX-001 §5）

### 3.1 检索请求必须包含的字段

```
repository_id（必填）
source_revision?（默认最新）
query_text / query_symbol? / query_file?（三选一或组合）
retrieval_mode: HYBRID | SEMANTIC | LEXICAL | SYMBOL | GRAPH
filters?（语言/文件模式/符号类型/可见性/排除路径）
top_k: number（默认 10）
include_sources: boolean
```

### 3.2 检索结果中每条 chunk 必须包含的字段

```
chunk_id / file_id / file_path / range: SourceRange
content（代码片段）
score（融合后相关性分数）
sources: ["bm25", "vector", "graph"]（RRF 融合来源）
symbols?（块内符号）
estimated_tokens（估算 Token 数）
```

### 3.3 与 Runtime Contract 的版本绑定（CTX-001 §7.1，下游必须遵守）

| Runtime 实体 | 索引绑定字段 | 语义 |
|---|---|---|
| Task | `source_revision` ← `base_revision` | 任务启动时的代码基线 |
| Workflow | `source_revision` ← `base_revision` | 同上 |
| Worker | `source_revision` ← `Worker.source_revision` | Worker 处理时的代码版本 |
| Action | 检索结果 → `Action.source_revision` 一致 | 动作引用的代码必须与上下文版本一致 |
| Artifact | `Artifact.content_inline` 包含 `RetrievalResult.chunks` | 上下文作为产物持久化 |

---

## 四、MEM 记忆实体速查（MEM-001 §6）

### 4.1 Memory 核心结构

```
memory_id（UUIDv7）
memory_type: WORKING | TASK | PROJECT | ORGANIZATION
scope: PRIVATE | SHARED | PUBLIC
+ organization_id / project_id / repository_id / task_id / workflow_id / worker_id
content: MemoryContent
source: USER_EXPLICIT | USER_IMPLICIT | AGENT_EXTRACTED | AGENT_INFERRED | SYSTEM_GENERATED
provenance: MemoryProvenance[]（至少 1 条）
confidence: ConfidenceScore
sensitivity: DataSensitivity（L1-L4）
lifecycle: MemoryLifecycle
access_policy: MemoryAccessPolicy
+ created_at / updated_at / expires_at? / version / trace_id
```

### 4.2 记忆类型与作用域不变量（MEM-001 §6.1 不变量 2）

| memory_type | scope 允许值 | 可见范围 | 必须绑定的作用域字段 |
|---|---|---|---|
| `WORKING` | 仅 `PRIVATE` | 仅当前 Worker | `worker_id` + `task_id` + `project_id` + `organization_id` |
| `TASK` | `PRIVATE` / `SHARED` | Task 内所有 Worker | `task_id` + `project_id` + `organization_id` |
| `PROJECT` | `SHARED` | Project 内所有 Task | `project_id` + `organization_id` |
| `ORGANIZATION` | `SHARED` / `PUBLIC` | Organization 内所有 Project | `organization_id` |

### 4.3 置信度评估（MEM-001 §6.3，MVP 简化规则）

```
基础分（来源 → 分值）：
  USER_EXPLICIT        → 0.95
  HUMAN_RATED          → 0.90
  VERIFICATION_RESULT  → 0.85
  AGENT_EXTRACTED     → 0.70
  MODEL_SELF_ASSESS   → 0.60
  AGENT_INFERRED      → 0.50
  SYSTEM_GENERATED     → 0.40
```

MVP 不实现衰减因子（`decay_score` 可选但不激活）。`value` 必须在 0.0~1.0 范围内。

### 4.4 记忆生命周期状态机（MEM-001 §6.4）

```
ACTIVE
  ├──> [expires_at 到达] ──> EXPIRED
  ├──> [用户/系统删除] ──> DELETED（软删除，保留审计）
  └──> [手动归档] ──> ARCHIVED

DELETED ──> [保留期结束] ──> [硬删除]（MEM-004）
EXPIRED ──> [保留期结束] ──> [硬删除]（MEM-004）
ARCHIVED ──> [手动恢复] ──> ACTIVE
```

MVP 不实现 `STALE` 状态和自动衰减评分。

### 4.5 Provenance 溯源类型（MEM-001 §6.5）

```
TASK_TRANSCRIPT | WORKER_ACTION | ARTIFACT | EXTERNAL_SERVICE | USER_INPUT
```

每条记忆至少一条；数组按时间倒序排列（最新来源在前）。

---

## 五、CTX/MEM 共用安全约束（SEC-001 §5.2 L1-L4 下游必须遵守）

| 规则 | CTX 下游 | MEM 下游 |
|---|---|---|
| 聚合/摘要/embedding 不得低于来源最高级别 | CTX-002~009 向量化摘要 | MEM-002~004 embedding 摘要 |
| 检索结果/记忆不得包含未脱敏 L4 内容 | CTX-004~005 结果过滤 | MEM-001~002 写入扫描 |
| 凭据/密钥不得进入索引/记忆 | CTX-001 §8 权限过滤 | MEM-001 §13.2 安全约束 |
| 访问控制强制关联 organization_id | CTX-005 零信任预过滤 | MEM-001 access_policy |

---

## 六、对下游各专项的具体接口契约

| 下游专项 | 必须复用的 CTX/MEM 坐标 | 禁止事项 |
|---|---|---|
| **HAR-003** 工具适配器 | `SymbolNode.kind`（调用关系 `CALLS` + `call_count`）、`FileNode.path` | 不能把文件路径作为唯一权限依据 |
| **HAR-001** Harness 生命周期 | `RetrievalResult` 作为 Worker 上下文 Artifact 传入、`memory_id` 关联 `task_id` | Harness 不得绕过上下文版本绑定 |
| **CTX-002** 语言解析 | `SymbolKind`（22 种）、`SourceRange` | 不能发明新的符号类型枚举值 |
| **CTX-003** AST/LSP | `FileNode.language`（Tree-sitter 支持的 3 种 MVP） | 只能处理 Schema 定义的语言 |
| **CTX-004** 混合检索 | `RetrievalQuery`/`RetrievalResult`（5 种检索模式 + RRF 融合） | 检索结果必须绑定 `source_revision` |
| **CTX-005** 权限过滤 | `FileNode.sensitivity_level`（L1-L4）、SEC-001 §5.2 定级规则 | 过滤结果不能降级敏感内容 |
| **CTX-006** Context Selector | `RetrievalResult.estimated_tokens`、记忆作为上下文来源 | 不得超出预算分配而不触发压缩 |
| **CTX-007** 增量索引 | `MerkleTree` 变更检测接口（CTX-001 §6.1）、`IndexState` 状态机 | 不得对 `ARCHIVED`/`FAILED` 索引执行增量更新 |
| **MEM-002** 记忆写入审批 | `Memory.source`（5 种）、`ConfidenceScore`（MVP 基础分） | 不能跳过 USER_IMPLICIT/AGENT_INFERRED 的审批 |
| **MEM-003** 记忆检索与冲突 | `Memory.memory_type`（4 种）/`scope`（3 种）、`MemoryLifecycle.state`（5 种） | 不能对 `DELETED`/`EXPIRED` 记忆返回结果 |
| **MEM-004** 记忆生命周期 | `Memory.expires_at`、`MemoryLifecycle.decay_score`（MVP 不激活） | 不能在无审计记录的情况下执行硬删除 |
| **G01** RT 核心 | CTX/MEM 的 `trace_id`、`source_revision`、`task_id`/`workflow_id`/`worker_id` 关联 | 不能用不同 ID 体系替代 RT-001 坐标 |
| **G05** 遥测采集 | `IndexMetadata.state`（OBS 索引健康指标）、`memory_id`（OBS 日志字段） | 指标不能含未脱敏敏感内容 |
| **G06** 评估数据集 | `RetrievalResult.chunks`（CTX 上下文质量）、`Memory.confidence`（MEM 置信度分布） | 不能只凭模型自报判断检索/记忆质量 |
| **G21** 遥测质量审计 | CTX 检索质量指标（precision/recall@10）、MEM 命中率/冲突率 | 审计不能含原始代码或凭据内容 |

---

## 七、CTX/MEM 各专项开放项对照（下游设计时的占位符）

| 开放项 | CTX 占位 | MEM 占位 | 归属专项 |
|---|---|---|---|
| 向量检索算法 | `embedding` 字段存在但算法未冻结 | `embedding` 字段存在但算法未冻结 | CTX-004 / MEM-003 |
| 混合检索 RRF 参数 | top_k、权重系数未定义 | — | CTX-004 |
| Tree-sitter 语言覆盖 | MVP 仅 Python/TS/Go；其他语言需专项设计 | — | CTX-003 |
| 记忆冲突解决算法 | — | 冲突检测阈值、合并策略未定义 | MEM-003 |
| 自动衰减算法 | — | `decay_score` 激活后的完整参数未定义 | MEM-004 |
| 记忆与 Context Selector 的融合策略 | — | 记忆作为上下文来源的优先级未定义 | CTX-006 |
| 存储后端选型 | PostgreSQL / 向量数据库未冻结 | PostgreSQL / MongoDB / Redis 未冻结 | 实现设计 |

---

## 八、变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 本次生成 | 首次从 CTX-001/MEM-001 提炼下游消费接口参考，不改变任何源设计内容 |
