# REQ-MEM-001 Memory Schema 详细设计

> 版本：v0.1-designed  
> 状态：详细设计已完成，待跨模块评审与冻结  
> 优先级：P1  
> 所属模块：记忆管理（MEM）  
> 设计日期：2026-09-27  
> 前置依赖：REQ-RT-001 核心实体 Schema、REQ-SEC-008 多租户与数据治理  
> 后续依赖：REQ-MEM-002 至 REQ-MEM-004

---

## 1. 需求基本信息

| 属性 | 内容 |
|---|---|
| 编号 | REQ-MEM-001 |
| 名称 | Memory Schema |
| 优先级 | P1 |
| 所属模块 | 记忆管理（MEM） |
| 原始位置 | `docs/design-specs/PENDING-REQUIREMENTS.md`，第130-133行 |
| 原始描述 | 记忆实体、来源、权限、版本和置信度 |
| 原定目标 | 记忆实体、来源、权限、版本和置信度 |
| 前置依赖 | RT-001、SEC-008 |
| 设计状态 | v0.1-designed；不代表实现或验证完成 |

---

## 2. 目标、范围与边界

### 2.1 目标

建立统一的记忆实体模型，为 AI Agent 平台提供跨会话、跨任务的持久化知识能力。模型应覆盖记忆类型、来源追溯、权限控制、置信度评估和生命周期管理，支持安全、可审计、可控的记忆操作。

### 2.2 范围

- 定义 Memory 核心实体 Schema，包含工作记忆、任务记忆、项目记忆和组织记忆四层
- 建立记忆与核心运行时实体（Task、Workflow、Worker、Artifact）的关联关系
- 定义记忆来源、置信度、权限、生命周期和溯源（Provenance）模型
- 明确记忆的创建、检索、更新、删除流程边界
- 定义 Schema 版本化和扩展规则

### 2.3 非目标

- 本需求不实现具体的存储后端选型和实现细节
- 不定义记忆写入审批的具体策略（归属 REQ-MEM-002）
- 不定义记忆检索的混合算法和冲突处理（归属 REQ-MEM-003）
- 不定义记忆衰减、过期和清理的完整策略（归属 REQ-MEM-004）
- 不实现向量检索的具体算法和参数调优
- MVP 不实现自动衰减算法，仅支持手动过期

---

## 3. 问题分析

当前 `PENDING-REQUIREMENTS.md` 中只提出"记忆实体、来源、权限、版本和置信度"的高层描述，存在以下缺口：

1. **记忆类型边界模糊**：未明确工作记忆、任务记忆、项目记忆和组织记忆的语义区分
2. **与运行时实体关联缺失**：无法回答"这条记忆是在哪个任务中产生的"
3. **来源追溯机制缺失**：无法评估记忆的可信度和责任主体
4. **置信度评估模型缺失**：无法区分高可信事实和低可信推断
5. **权限边界不清晰**：多租户环境下记忆隔离的实现路径未定义
6. **生命周期规则未定义**：记忆何时衰减、如何过期、如何清理未明确
7. **敏感信息处理规则缺失**：用户偏好可能包含密码提示等敏感内容

这些缺口影响：
- 用户无法跨会话复用偏好和知识，重复工作增加
- 记忆来源不可追溯，信任度降低
- 后续 MEM-002~004 的设计缺乏基础 Schema 支撑
- 多租户环境下记忆泄露风险

---

## 4. 标杆依据与公开事实/推断

研究访问日期：2026-09-26 至 2026-09-27。公开产品做法仅作为设计参考，不代表其控制对本项目无条件适用。

### 4.1 Claude Code：七层记忆架构

**公开事实**：Claude Code 采用七层记忆架构，包括 CLAUDE.md 指令文件、Auto Memory、后台提取记忆、会话记忆、Agent 记忆、相关记忆、Auto Dream。记忆严格分为四类：`user`（用户偏好）、`feedback`（行为纠正）、`project`（项目上下文）、`reference`（外部系统指针）。

**设计推断**：封闭的分类体系避免记忆类型混乱。"What NOT to Save" 原则同等重要：排除代码模式、Git 历史、可推断信息等，约束 AI 行为边界。

来源：
- [Claude Code Source Study: Memory Subsystem](https://github.com/luyao618/Claude-Code-Source-Study/blob/main/docs-en/31-memory-subsystem-overview.md)
- 访问日期：2026-09-26

### 4.2 Mem0：生产级可扩展记忆

**公开事实**：Mem0 提供简单 API（`add/search/update/delete`），采用 LLM 门控的事实提取管道，每次 `add` 调用时触发。可选图扩展（Mem0^g）将记忆存储为有向标记图。在 LLM-as-Judge 指标上比 OpenAI 高 26%，p95 延迟降低 91%，Token 成本节省超过 90%。

**设计推断**：简单 API 降低集成复杂度。提取-评估-管理三模块分离支持可扩展性。性能优化指标明确可量化。

来源：
- [Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory](https://arxiv.org/html/2504.19413v1)
- 访问日期：2026-09-26

### 4.3 Zep / Graphiti：时序知识图谱

**公开事实**：Zep 采用 Graphiti 引擎，支持双时态数据模型：维护事实及其有效期的历史关系。实体-关系-事件模型支持时间衰减的事实演化。混合检索（向量+BM25 融合），无 LLM 在读取路径。在 DMR 基准上 94.8% vs MemGPT 93.4%，LongMemEval 基准精度提升 18.5%，延迟降低 90%。

**设计推断**：时序有效性窗口解决记忆过期问题。双时态模型支持历史回溯和版本追踪。关系建模优于扁平向量存储。

来源：
- [Zep: A Temporal Knowledge Graph Architecture for Agent Memory](https://arxiv.org/abs/2501.13956)
- 访问日期：2026-09-26

### 4.4 MemGPT / Letta：分层记忆操作系统

**公开事实**：MemGPT 采用三层记忆层次：Core Memory（主上下文）、Recall Store（外部召回）、Archival Store（归档存储）。Agent 通过工具调用自管理层级提升。虚拟内存分页类比：类似 OS 的 RAM vs Disk。

**设计推断**：层级分离支持上下文窗口高效利用。Agent 自主管理提升灵活性。适合长期运行的自管理场景。

来源：
- [MemGPT: Towards LLMs as Operating Systems](https://arxiv.org/abs/2310.08560)
- 访问日期：2026-09-26

### 4.5 LangGraph：Checkpoint + Store 分离

**公开事实**：LangGraph 提供两层持久化：Checkpointer（短时、线程作用域记忆）和 Store（长时、跨线程记忆）。命名空间模型支持层级组织：`("user_id", "memories")`。PostgresStore 支持向量检索和 TTL 清理。

**设计推断**：短时/长时记忆清晰分离。命名空间支持多租户和多用户隔离。可扩展存储后端（Postgres、MongoDB、Redis）。

来源：
- [LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [LangGraph Stores](https://docs.langchain.com/oss/python/langgraph/stores)
- 访问日期：2026-09-26

### 4.6 Manus：文件系统作为记忆

**公开事实**：Manus 将虚拟机文件系统作为持久化外部记忆。完整工具输出保存到文件，压缩版本保留路径引用。Schema 化摘要仅当压缩不再满足时触发。Projects 功能支持跨任务共享指令、文件和技能。

**设计推断**：文件系统作为最终记忆载体，无限大小。压缩优先于摘要，保持可恢复性。Schema 化摘要支持结构化检索。

来源：
- [Context Engineering for AI Agents: Lessons from Building Manus](https://manus.im/en/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)
- 访问日期：2026-09-26

### 4.7 DeepSeek Harness：会话持久化

**公开事实**：DeepSeek Harness 提供 SessionPersistence 服务：定位/创建/追加、逻辑加载/检查、物理后缀读取。Append-only SessionEvent 日志作为事实来源。支持崩溃恢复：检查点+日志重放。

**设计推断**：Append-only 日志作为事实来源。检查点优化恢复效率。抽象持久化服务支持多后端。

来源：
- [DeepSeek Harness: Persistence Subsystem](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/persistence.md)
- 访问日期：2026-09-26

### 4.8 调研结论

本项目 `REQ-MEM-001` 采用以下共同原则：

- 记忆类型封闭分类，避免 Agent 任意创建记忆类型导致混乱
- 记忆来源和置信度分离，支持可信度评估
- 记忆与运行时实体（Task、Workflow、Worker）关联，支持追溯
- 权限模型支持多租户隔离（PRIVATE/SHARED/PUBLIC）
- 生命周期管理支持自动过期和清理
- 敏感信息扫描和脱敏，支持安全合规

---

## 5. 设计边界

### 5.1 本需求包含

- Memory 核心实体 Schema
- MemoryType、MemoryScope、MemorySource、ConfidenceScore、MemoryLifecycle、MemoryProvenance、MemoryAccessPolicy、MemoryContent
- 记忆与核心运行时实体的关联字段（task_id、workflow_id、worker_id）
- 记忆的创建、检索、更新、删除流程边界
- Schema 版本化和扩展规则
- 字段级敏感信息约束
- 不变量和 Schema 校验规则

### 5.2 本需求不包含

以下内容必须由其他需求设计，不能在本需求中提前定义成最终协议：

| 内容 | 归属需求 |
|---|---|
| 记忆写入审批的具体策略 | REQ-MEM-002 |
| 记忆检索的混合算法和冲突处理 | REQ-MEM-003 |
| 记忆衰减、过期和清理的完整策略 | REQ-MEM-004 |
| 向量检索的具体算法和参数 | REQ-MEM-003 |
| 存储后端选型和实现细节 | 实现设计 |
| Context Selector 与记忆的融合策略 | REQ-CTX-006 |

---

## 6. 核心实体 Schema

以下 Schema 使用接近 JSON Schema/TypeScript 的中立表示，仅用于冻结概念和字段语义，不代表最终语言或 ORM。

### 6.1 Memory（记忆实体）

#### 职责

Memory 表示 AI Agent 平台中跨会话、跨任务持久化的知识单元。每条记忆绑定作用域、来源、置信度、权限和生命周期，支持追溯和审计。

#### Schema

```text
Memory
- schema_version: string = "memory.entity.v1"
- memory_id: MemoryId (UUIDv7)
- memory_type: MemoryType
- scope: MemoryScope
- organization_id: EntityId?
- project_id: EntityId?
- repository_id: EntityId?
- task_id: TaskId?
- workflow_id: WorkflowId?
- worker_id: WorkerId?
- content: MemoryContent
- source: MemorySource
- provenance: MemoryProvenance[]
- confidence: ConfidenceScore
- sensitivity: DataSensitivity
- lifecycle: MemoryLifecycle
- access_policy: MemoryAccessPolicy
- created_at: Timestamp
- updated_at: Timestamp
- expires_at: Timestamp?
- version: integer >= 1
- metadata: SafeMetadata
- trace_id: TraceId
```

#### 枚举

```text
MemoryType = WORKING | TASK | PROJECT | ORGANIZATION

MemoryScope = PRIVATE | SHARED | PUBLIC

MemorySource = USER_EXPLICIT | USER_IMPLICIT | AGENT_EXTRACTED | 
               AGENT_INFERRED | SYSTEM_GENERATED
```

#### Memory 不变量

1. `memory_id` 必须唯一，不可复用。
2. `memory_type` 与 `scope` 共同决定记忆的可见范围：
   - `WORKING` 记忆：仅当前 Worker 可见，`scope` 必须为 `PRIVATE`
   - `TASK` 记忆：当前 Task 内所有 Worker 可见，`scope` 可为 `PRIVATE` 或 `SHARED`
   - `PROJECT` 记忆：当前 Project 内所有 Task 可见，`scope` 可为 `SHARED`
   - `ORGANIZATION` 记忆：当前 Organization 内所有 Project 可见，`scope` 可为 `SHARED` 或 `PUBLIC`
3. 记忆绑定的作用域字段必须一致：
   - `organization_id` 必填（除非记忆为系统级）
   - `PROJECT` 记忆必须绑定 `project_id` 和 `organization_id`
   - `TASK` 记忆必须绑定 `task_id`、`project_id` 和 `organization_id`
   - `WORKING` 记忆必须绑定 `worker_id`、`task_id`、`project_id` 和 `organization_id`
4. `content.content_text` 必填，长度 1..10000 字符。
5. `content.content_hash` 创建后不可变更。
6. `source` 必须为有效枚举值，不能为空。
7. `confidence.value` 必须在 0.0 ~ 1.0 范围内。
8. `provenance` 至少包含一条来源记录。
9. `sensitivity` 必须符合 `REQ-SEC-008` 的数据分类定义。
10. `lifecycle.state` 初始值必须为 `ACTIVE`。
11. `version` 初始值必须为 1，每次更新递增。
12. `expires_at` 可选，用于支持自动过期（REQ-MEM-004）。
13. `metadata` 只能存放允许的非敏感扩展字段，不得包含凭据、密钥或模型思维链。
14. `trace_id` 必须与关联的 Task/Workflow/Worker 的 `trace_id` 一致。

---

### 6.2 MemoryContent（记忆内容）

#### 职责

MemoryContent 表示记忆的实际内容，支持文本、Schema 化结构、摘要和可选向量 embedding。

#### Schema

```text
MemoryContent
- content_type: MemoryContentType
- content_text: string (1..10000)
- content_schema: string?
- content_hash: string
- content_ref: ContentRef?
- summary: string? (1..500)
- keywords: string[]?
- embedding: float[]?

MemoryContentType = PREFERENCE | FACT | PROCEDURE | CONTEXT | RULE | GUIDELINE
```

#### MemoryContent 不变量

1. `content_text` 必填，不得为空。
2. `content_hash` 必须为 `content_text` 的 SHA-256 哈希。
3. `content_ref` 用于引用外部存储的大型内容，小型内容应直接存储在 `content_text`。
4. `summary` 可选，用于快速浏览记忆内容，不能替代原始内容。
5. `keywords` 可选，用于全文检索优化。
6. `embedding` 可选，用于向量检索。MVP 不强制要求，后续 REQ-MEM-003 可按需实现。

---

### 6.3 ConfidenceScore（置信度评分）

#### 职责

ConfidenceScore 表示记忆的可信度，包含数值分数、评估方法和评估者。

#### Schema

```text
ConfidenceScore
- value: float (0.0 ~ 1.0)
- assessment_method: AssessmentMethod
- assessor: string
- assessed_at: Timestamp

AssessmentMethod = HUMAN_RATED | MODEL_SELF_ASSESS | EXTRACTION_CONFIDENCE | 
                   VERIFICATION_RESULT
```

#### ConfidenceScore 不变量

1. `value` 必须在 0.0 ~ 1.0 范围内。
2. `assessment_method` 必须为有效枚举值。
3. `assessor` 记录评估者身份（用户 ID、Worker ID 或系统标识）。
4. `assessed_at` 记录评估时间，不得晚于 `created_at`。

#### 置信度评估算法（MVP 简化版）

```text
基础分规则：
- USER_EXPLICIT: 0.95
- HUMAN_RATED: 0.90
- VERIFICATION_RESULT: 0.85
- AGENT_EXTRACTED: 0.70
- MODEL_SELF_ASSESS: 0.60
- AGENT_INFERRED: 0.50
- SYSTEM_GENERATED: 0.40

MVP 阶段不实现衰减因子，后续 REQ-MEM-004 可扩展：
- 来源实体置信度（如关联 Artifact 的置信度）
- 内容时效性（距离当前时间越长，衰减越大）
- 内容稳定性（同一主题更新频率越高，置信度越低）
```

---

### 6.4 MemoryLifecycle（记忆生命周期）

#### 职责

MemoryLifecycle 表示记忆的生命周期状态，包含最后访问时间、访问次数、衰减评分和删除信息。

#### Schema

```text
MemoryLifecycle
- state: MemoryState
- last_accessed_at: Timestamp?
- access_count: integer >= 0
- decay_score: float? (0.0 ~ 1.0)
- decay_reason: string?
- deleted_at: Timestamp?
- deleted_by: EntityId?

MemoryState = ACTIVE | STALE | EXPIRED | DELETED | ARCHIVED
```

#### MemoryLifecycle 不变量

1. `state` 初始值必须为 `ACTIVE`。
2. `last_accessed_at` 在首次访问后必填。
3. `access_count` 初始值为 0，每次检索命中后递增。
4. `decay_score` 可选，用于记忆衰减评分（MVP 不实现）。
5. `deleted_at` 和 `deleted_by` 在软删除时必填。
6. `DELETED` 状态的记忆不得返回给检索调用者，仅供审计查询。

#### 状态机

```text
ACTIVE
  ├──> [访问超时] ──> STALE（MVP 不实现）
  ├──> [expires_at 到达] ──> EXPIRED
  ├──> [用户/系统删除] ──> DELETED
  └──> [手动归档] ──> ARCHIVED

STALE
  ├──> [再次访问] ──> ACTIVE（MVP 不实现）
  ├──> [过期清理] ──> EXPIRED（MVP 不实现）
  └──> [删除] ──> DELETED

EXPIRED
  └──> [保留期结束] ──> [硬删除]（REQ-MEM-004）

DELETED
  └──> [保留期结束] ──> [硬删除]（REQ-MEM-004）

ARCHIVED
  └──> [手动恢复] ──> ACTIVE
```

---

### 6.5 MemoryProvenance（记忆溯源）

#### 职责

MemoryProvenance 表示记忆的来源链路，支持追溯记忆产生的 Task、Worker、Action 或外部服务。

#### Schema

```text
MemoryProvenance
- source_type: ProvenanceSourceType
- source_id: string
- source_revision: string?
- source_location: string?
- extracted_at: Timestamp
- extraction_method: string?

ProvenanceSourceType = TASK_TRANSCRIPT | WORKER_ACTION | ARTIFACT | 
                       EXTERNAL_SERVICE | USER_INPUT
```

#### MemoryProvenance 不变量

1. `source_type` 必须为有效枚举值。
2. `source_id` 必须能够反向查询到对应实体（Task、Worker、Action 或 Artifact）。
3. `source_revision` 绑定代码版本（如 Git commit SHA），用于追溯记忆产生时的代码状态。
4. `extracted_at` 记录提取时间，不得晚于 `created_at`。
5. 每条记忆至少包含一条 Provenance 记录。
6. Provenance 数组按时间倒序排列，最新的来源在前。

---

### 6.6 MemoryAccessPolicy（记忆访问策略）

#### 职责

MemoryAccessPolicy 定义记忆的权限控制，包含所有者、读/写/管理权限主体。

#### Schema

```text
MemoryAccessPolicy
- owner_id: EntityId
- read_principals: EntityId[]
- write_principals: EntityId[]
- admin_principals: EntityId[]
- inherit_from_scope: boolean = true
```

#### MemoryAccessPolicy 不变量

1. `owner_id` 必填，表示记忆的创建者或责任主体。
2. `read_principals` 包含所有可读取记忆的用户/组织/项目 ID。
3. `write_principals` 包含所有可修改记忆的用户/组织/项目 ID。
4. `admin_principals` 包含所有可删除记忆的用户/组织/项目 ID。
5. `inherit_from_scope` 为 `true` 时，权限从 `scope` 继承：
   - `PRIVATE`：仅 `owner_id` 可读写
   - `SHARED`：组织/项目成员可读，`owner_id` 可写
   - `PUBLIC`：跨租户可读，仅 `admin_principals` 可写
6. 权限校验必须调用 `REQ-SEC-002` 的 RBAC 授权服务。

---

## 7. 记忆操作流程

### 7.1 记忆写入流程

```text
1. 触发阶段
   - 用户显式输入偏好（USER_EXPLICIT）
   - Agent 从对话/任务中提取事实（AGENT_EXTRACTED）
   - Agent 推断新知识（AGENT_INFERRED）
   - 系统自动生成元数据（SYSTEM_GENERATED）

2. 验证阶段
   - 内容格式校验（长度、字符集、Schema）
   - 敏感信息扫描（密码、密钥、个人信息）
   - 重复检测（与现有记忆的内容相似度检查）
   - 权限校验（用户/Worker 是否有写入权限）

3. 关联阶段
   - 确定记忆范围（PRIVATE/SHARED/PUBLIC）
   - 绑定作用域（组织/项目/仓库/任务）
   - 关联来源实体（Task、Worker、Artifact）

4. 持久化阶段
   - 分配 memory_id（UUIDv7）
   - 设置初始版本（version = 1）
   - 计算内容哈希（SHA-256）
   - 计算置信度（根据来源类型）
   - 设置生命周期状态（ACTIVE）
   - 生成首次 Provenance 记录

5. 索引阶段（可选）
   - 生成 embedding 向量（MVP 可选）
   - 提取 keywords
   - 生成 summary
```

### 7.2 记忆检索流程

```text
1. 查询请求
   - 接收查询条件（memory_type、scope、content 文本、keywords 等）
   - 解析调用者上下文（user_id、task_id、worker_id）

2. 权限过滤
   - 验证调用者是否在 read_principals 中
   - 按 scope 过滤：PRIVATE 仅所有者可读，SHARED 租户内可读，PUBLIC 租户间可读

3. 检索执行
   - 精确匹配（memory_id、内容哈希）
   - 向量检索（embedding 相似度）（MVP 可选）
   - 全文检索（content_text、keywords）
   - 时序检索（created_at、updated_at 范围）

4. 结果排序
   - 按相关性评分（向量距离 + 关键词命中）
   - 按置信度加权
   - 按新鲜度衰减（decay_score）（MVP 不实现）
   - 按作用域优先级（当前任务 > 当前项目 > 当前组织）

5. 返回结果
   - 分页（limit、offset）
   - 敏感字段脱敏（根据调用者权限）
   - 返回 Memory 对象列表
```

### 7.3 记忆更新流程

```text
1. 更新触发
   - 用户显式修正
   - Agent 发现冲突或过时
   - 关联的 Task/Worker 完成，触发记忆固化检查

2. 版本管理
   - 创建新版本（version += 1）
   - 保留历史版本（按 REQ-MEM-004 的保留策略）
   - 记录 updated_by 和 updated_at

3. 冲突处理（详见 REQ-MEM-003）
   - 检测与现有记忆的冲突
   - 触发冲突合并流程
   - 记录冲突解决结果
```

### 7.4 记忆删除流程

```text
1. 删除触发
   - 用户请求删除
   - 记忆过期（expires_at 到达）
   - 记忆衰减到阈值（decay_score 达到清除线）（MVP 不实现）
   - 系统清理（存储成本优化、GDPR 响应）

2. 软删除
   - 设置 deleted_at 和 deleted_by
   - 修改 lifecycle.state = DELETED
   - 保留内容供审计追溯

3. 硬删除（按 REQ-MEM-004 策略执行）
   - 清除内容（可配置保留 provenance 记录）
   - 清除 embedding 和 keywords
   - 释放存储空间
```

---

## 8. 不变量总表

以下不变量是后续所有模块必须遵守的共享约束：

### 身份不变量

1. 每条记忆有唯一、稳定、不可复用的 `memory_id`。
2. 记忆必须绑定至少一个作用域（组织/项目/仓库/任务）。
3. 记忆类型（WORKING/TASK/PROJECT/ORGANIZATION）与作用域（PRIVATE/SHARED/PUBLIC）必须一致。

### 版本不变量

1. 记忆内容哈希（content_hash）创建后不可变更。
2. 记忆版本号（version）初始为 1，每次更新递增。
3. 历史版本保留规则由 REQ-MEM-004 定义。

### 边界不变量

1. 记忆内容不得包含凭据、密钥、个人敏感信息。
2. 记忆内容不得包含模型内部思维链。
3. 记忆不能自动改变安全策略（详见 SEC-001）。

### 可追踪不变量

1. 每条记忆至少包含一条 Provenance 记录。
2. Provenance 可追溯到 Task、Worker、Action 或 Artifact。
3. 记忆的 `trace_id` 必须与关联的运行时实体一致。

### 权限不变量

1. `PRIVATE` 记忆仅所有者可读写。
2. `SHARED` 记忆租户内可读，所有者可写。
3. `PUBLIC` 记忆跨租户可读，仅管理员可写。
4. 权限校验必须调用 REQ-SEC-002 的 RBAC 服务。

---

## 9. 验收标准

| 编号 | 验收标准 | 验证方法 |
|------|----------|----------|
| AC-01 | Memory Schema 包含 memory_id、memory_type、scope、content、source、confidence、lifecycle、access_policy 等核心字段 | Schema 校验测试 |
| AC-02 | 记忆与 Task/Workflow/Worker 建立关联，支持通过运行时实体 ID 追溯记忆 | 关联查询测试 |
| AC-03 | 支持四种记忆类型：WORKING、TASK、PROJECT、ORGANIZATION | 类型枚举校验 |
| AC-04 | 支持五种来源类型：USER_EXPLICIT、USER_IMPLICIT、AGENT_EXTRACTED、AGENT_INFERRED、SYSTEM_GENERATED | 来源枚举校验 |
| AC-05 | 置信度评分包含 value、assessment_method、assessor、assessed_at | 字段完整性测试 |
| AC-06 | 记忆生命周期支持 ACTIVE、STALE、EXPIRED、DELETED、ARCHIVED 状态 | 状态迁移测试 |
| AC-07 | 权限策略包含 owner、read_principals、write_principals、admin_principals | 权限校验测试 |
| AC-08 | Provenance 记录支持追溯记忆来源的 Task、Worker、Action | 溯源查询测试 |
| AC-09 | 敏感信息（密码、密钥）写入记忆时触发告警 | 安全扫描测试 |
| AC-10 | 记忆 Schema 版本化，支持向后兼容扩展 | 版本兼容性测试 |
| AC-11 | PRIVATE 记忆仅所有者可读写 | 权限隔离测试 |
| AC-12 | 记忆内容哈希在创建后不可变更 | 不可变性测试 |
| AC-13 | 删除记忆支持软删除，保留审计追踪 | 软删除测试 |
| AC-14 | 记忆与 REQ-RT-001 核心实体（Task、Workflow、Worker、Artifact）建立关联 | Schema 关联测试 |
| AC-15 | 记忆的 metadata 字段符合 SafeMetadata 定义，不保存凭据和思维链 | 敏感字段测试 |

---

## 10. 依赖与跨模块接口

### 10.1 前置依赖

- **REQ-RT-001**：复用 TaskId、WorkflowId、WorkerId、ArtifactId、EntityId、TraceId、ContentRef、DataSensitivity、SafeMetadata
- **REQ-SEC-002**：复用 RBAC 权限模型和 principal 概念
- **REQ-SEC-008**：复用多租户隔离和数据分类（DataSensitivity）

### 10.2 后续接口

- **REQ-MEM-002**：调用记忆写入审批流程，根据 confidence 和 source 决定是否需要审批
- **REQ-MEM-003**：调用记忆检索和冲突处理，复用 memory_type、scope、lifecycle
- **REQ-MEM-004**：消费记忆生命周期状态和过期策略，复用 lifecycle.state、decay_score
- **REQ-CTX-006**：Context Selector 可将记忆作为上下文来源
- **REQ-OBS-001/002**：记忆操作事件纳入观测体系，记录 memory_id、operation、user_id、latency

### 10.3 不包含的接口（后续需求设计）

- 具体的存储后端选型和实现（PostgreSQL / MongoDB / Redis）
- 向量检索的具体算法和参数（embedding 模型、相似度计算）
- 记忆压缩和摘要协议
- 记忆与其他上下文来源（代码索引、外部文档）的融合策略

---

## 11. 性能、成本与延迟

### 11.1 性能目标（推断，需基线测试）

| 操作 | 目标延迟 |
|------|----------|
| 记忆写入 | p99 < 200ms |
| 记忆检索（单条） | p99 < 50ms |
| 记忆检索（向量 top-k） | p99 < 100ms（MVP 可选） |
| 批量读取（100 条） | p99 < 500ms |

### 11.2 成本考量

- 向量 embedding 计算成本：使用低成本 embedding 模型（如 all-MiniLM-L6-v2）
- 存储成本：大型记忆内容引用外部存储（如 S3）
- 索引成本：增量索引，避免全量重建

### 11.3 延迟优化

- 异步写入，不阻塞主对话流
- 记忆预取：在任务开始时按上下文加载相关记忆
- 缓存热点记忆：高频访问记忆缓存到内存

---

## 12. 可观测性与评估指标

### 12.1 关键指标

| 指标 | 定义 | 目标 |
|------|------|------|
| memory_write_count | 写入记忆总数/日 | - |
| memory_retrieval_latency_p99 | 检索延迟 p99 | < 100ms |
| memory_confidence_distribution | 置信度分布 | 高置信度(>0.8) > 80% |
| memory_decay_rate | 衰减率 | -（MVP 不实现） |
| memory_conflict_rate | 冲突率 | < 5% |
| memory_hit_rate | 检索命中率 | > 70% |
| memory_permission_denied_rate | 权限拒绝率 | < 1% |

### 12.2 日志字段

- memory_id、memory_type、operation（write/read/update/delete）
- user_id、worker_id、task_id
- latency_ms、result（success/failure）
- error_code（如有）

### 12.3 Trace 关联

- memory_write 事件关联 task_id、workflow_id、worker_id、trace_id
- memory_retrieval 事件关联调用者上下文和 trace_id

---

## 13. 安全与合规

### 13.1 权限模型

- 继承 REQ-SEC-002 的 RBAC 模型
- 记忆级别的 read/write/admin 权限
- PRIVATE 记忆：仅 owner 可读写
- SHARED 记忆：组织/项目成员可读，owner 可写
- PUBLIC 记忆：跨租户可读，仅 admin 可写

### 13.2 安全约束

- 敏感信息自动扫描和脱敏
- 凭据、密钥、个人信息不得写入记忆内容
- 记忆不得包含模型内部思维链
- 记忆内容加密存储（详见 SEC-008）

### 13.3 合规要求

- **GDPR**：用户可导出和删除个人记忆
- **数据驻留**：记忆按组织配置存储区域
- **留存期**：按 REQ-MEM-004 的生命周期策略执行
- **审计**：所有记忆操作记录审计日志

---

## 14. 版本与演进

### 14.1 当前版本

`REQ-MEM-001` 当前版本为 `v0.1-designed`，本需求范围内的详细设计已完成；该版本可以作为后续专项设计的输入，但仍需与状态机、事件、投影、恢复、权限和观测模块完成交叉评审后，才能升级为 `v1.0-frozen`。

### 14.2 升级到 `v1.0-frozen` 的条件

必须完成：

1. Schema 评审
2. 与 `REQ-MEM-002`、`REQ-MEM-003`、`REQ-MEM-004` 的交叉一致性评审
3. 与安全（SEC-002、SEC-008）、上下文（CTX-006）和观测（OBS）模块的引用评审
4. Schema 契约测试和不变量测试设计
5. 敏感字段和数据分类规则评审
6. 明确存储后端选型和实现承载方式
7. 解决所有字段语义冲突后发布 `v1.0-frozen`

### 14.3 兼容规则

- 新增可选字段：小版本升级
- 新增枚举值：需要消费者兼容评审
- 修改字段含义、类型或必填性：主版本升级
- 拆分实体或改变父子关系：主版本升级
- 修改 `content_hash`、ID 或 Trace 语义：必须重新评审全部依赖模块

### 14.4 Schema 版本演化

| 变更类型 | 版本升级 | 兼容性 |
|----------|----------|--------|
| 新增可选字段 | 小版本 | 向后兼容 |
| 新增必填字段 | 主版本 | 不兼容 |
| 删除字段 | 主版本 | 不兼容 |
| 修改字段语义 | 主版本 | 不兼容 |
| 新增枚举值 | 小版本 | 向后兼容 |

---

## 15. MVP 范围与后续扩展

### 15.1 MVP 包含

- Memory 核心实体 Schema
- 四类记忆类型（WORKING/TASK/PROJECT/ORGANIZATION）
- 五类来源类型（USER_EXPLICIT/USER_IMPLICIT/AGENT_EXTRACTED/AGENT_INFERRED/SYSTEM_GENERATED）
- 置信度评估（简化规则：基础分，无衰减因子）
- 权限模型（PRIVATE/SHARED/PUBLIC + owner + principals）
- 生命周期状态（ACTIVE/EXPIRED/DELETED，不实现 STALE/ARCHIVED）
- Provenance 溯源记录
- 全文检索（content_text、keywords）
- 手动过期（expires_at）

### 15.2 MVP 不包含（后续扩展）

- 自动衰减评分算法（decay_score）
- 向量检索（embedding）
- 记忆冲突自动解决
- 记忆压缩和摘要
- 记忆分层淘汰策略（Core/Recall/Archival）
- 记忆与代码索引的融合检索

---

## 16. 设计决策收敛

本轮联网复核后，以下原待决事项已形成设计决策：

1. **记忆类型分类**：采用封闭的四类分类（WORKING/TASK/PROJECT/ORGANIZATION），借鉴 Claude Code 的四类封闭体系。
2. **来源类型分类**：采用五类来源枚举（USER_EXPLICIT/USER_IMPLICIT/AGENT_EXTRACTED/AGENT_INFERRED/SYSTEM_GENERATED），支持置信度评估。
3. **置信度评估模型**：采用数值+方法+评估者三元组，MVP 采用简单规则，后续可扩展衰减因子。
4. **权限模型**：采用 owner + read/write/admin principals，支持 PRIVATE/SHARED/PUBLIC 分级，借鉴 LangGraph 命名空间隔离。
5. **生命周期管理**：采用五状态（ACTIVE/STALE/EXPIRED/DELETED/ARCHIVED），MVP 仅实现 ACTIVE/EXPIRED/DELETED。
6. **Provenance 溯源**：每条记忆至少包含一条来源记录，支持追溯 Task、Worker、Action、Artifact。
7. **向量检索**：MVP 不强制要求 embedding，后续 REQ-MEM-003 按需实现。
8. **存储后端**：Schema 不绑定特定后端，支持 PostgreSQL、MongoDB、Redis 等多后端。

仍需跨模块确认、但不阻塞本需求设计完成的内容：

- 最终存储后端选型（PostgreSQL vs MongoDB vs Redis）
- 向量检索的具体算法和参数（embedding 模型、相似度阈值）
- 记忆与 Context Selector 的融合策略
- 记忆衰减算法的完整参数（时间窗口、访问频率阈值）

这些事项不再作为本需求的模糊占位字段，而由对应后续需求负责。

---

## 17. 设计完成范围与结论

### 17.1 已完成设计的功能

以下功能已在 `REQ-MEM-001 v0.1-designed` 中完成设计：

- [x] Memory 核心实体 Schema
- [x] MemoryType、MemoryScope、MemorySource 枚举
- [x] ConfidenceScore、MemoryLifecycle、MemoryProvenance、MemoryAccessPolicy、MemoryContent 子实体
- [x] 记忆与核心运行时实体（Task、Workflow、Worker、Artifact）的关联字段
- [x] 记忆的创建、检索、更新、删除流程边界
- [x] 置信度评估算法（MVP 简化版）
- [x] 权限模型（PRIVATE/SHARED/PUBLIC + owner + principals）
- [x] 生命周期状态机（ACTIVE/STALE/EXPIRED/DELETED/ARCHIVED）
- [x] Provenance 溯源记录
- [x] 不变量和 Schema 校验规则
- [x] 验收标准
- [x] 与后续需求的接口约束

### 17.2 与旗舰 Agent 设计理念的符合性

本方案与公开资料能够确认的厂商共性基本一致：

- 与 Claude Code 的四类封闭分类、"What NOT to Save" 原则一致
- 与 Mem0 的简单 API、提取-评估-管理三模块分离一致
- 与 Zep/Graphiti 的时序有效性窗口、双时态模型方向一致（MVP 不实现）
- 与 MemGPT 的分层记忆层次（Core/Recall/Archival）方向一致（MVP 不实现）
- 与 LangGraph 的 Checkpointer/Store 分离、命名空间隔离一致
- 与 Manus 的文件系统持久化、Schema 化摘要方向一致（MVP 不实现）
- 与 DeepSeek Harness 的 Append-only 日志、检查点恢复方向一致

### 17.3 是否为"最优解"

不能在缺少本项目真实任务、Schema 契约测试和跨模块评审的情况下宣称全局最优。

当前可以确认的是：

> 本设计是在公开证据和本项目安全、可审计、可控目标下的推荐基线，已经完成本需求范围内的设计收敛；后续优化应通过评测和版本变更进行，而不是重新各自定义记忆模型。

正式冻结条件由第 14 节规定，后续记忆写入、检索、生命周期设计必须在本基线上扩展，不得替换共享坐标。

---

## 18. 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| `v0.1-designed` | 2026-09-27 | 基于项目既有设计基线及大厂竞品研究（Claude Code、Mem0、Zep、MemGPT、LangGraph、Manus、DeepSeek）形成详细设计；定义 Memory 核心实体、置信度评估、权限模型、生命周期管理和 Provenance 溯源；明确 MVP 范围和后续扩展路径。 |
