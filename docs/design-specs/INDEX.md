# 设计功能点快速索引

> 本文档提供全部 60 项正式基线需求（60 项均已完成详细设计，待跨模块评审与冻结）的快速导航。统一状态、版本基线和需求编号以 [AI Agent 平台统一设计基线与未完成需求清单](./00-integrated-design-baseline.md) 为准。

## 📋 设计规范文档列表

### 核心基础层（P0 - 阻塞所有实现）

| 编号 | 文档名称 | 优先级 | 状态 | 关键阻塞 | 快速链接 |
|------|----------|--------|------|----------|----------|
| 01 | [运行时基础契约总览](./01-runtime-contracts.md) | P0 | 详细设计已完成，待跨模块冻结 | 所有后续模块 | [查看详情](./01-runtime-contracts.md) |
| RT-001 | [核心实体 Schema](./REQ-RT-001-core-runtime-entities.md) | P0 | 详细设计已完成，待跨模块冻结 | 所有后续模块 | [查看详情](./REQ-RT-001-core-runtime-entities.md) |
| RT-002 | [状态机与迁移约束](./REQ-RT-002-state-machines.md) | P0 | 详细设计已完成，待跨模块冻结 | 事件、投影、恢复和执行 | [查看详情](./REQ-RT-002-state-machines.md) |
| RT-003 | [Event Schema 与版本策略](./REQ-RT-003-event-schema-versioning.md) | P0 | 详细设计已完成，待跨模块冻结 | 状态投影、Checkpoint、审计和恢复 | [查看详情](./REQ-RT-003-event-schema-versioning.md) |
| RT-004 | [状态投影与一致性规则](./REQ-RT-004-state-projections.md) | P0 | 详细设计已完成，待跨模块冻结 | Checkpoint、查询、调度和恢复 | [查看详情](./REQ-RT-004-state-projections.md) |
| RT-005 | [Checkpoint Protocol](./REQ-RT-005-checkpoint-protocol.md) | P0 | 详细设计已完成，待跨模块冻结 | 恢复、失败处理和持久执行 | [查看详情](./REQ-RT-005-checkpoint-protocol.md) |
| RT-006 | [Trace 传播和审计关联](./REQ-RT-006-Trace-传播和审计关联.md) | P0 | 详细设计已完成，待跨模块冻结 | 运行链路追踪、审计关联和跨服务传播 | [查看详情](./REQ-RT-006-Trace-传播和审计关联.md) |
| RT-007 | [Idempotency Key 与副作用边界](./REQ-RT-007-idempotency-key.md) | P0 | 详细设计已完成，待跨模块冻结 | Action 去重、未知结果核查、并行操作保护 | [查看详情](./REQ-RT-007-idempotency-key.md) |
| SEC-004 | [沙箱隔离基线](./REQ-SEC-004-sandbox-isolation-baseline.md) | P0 | v0.2-designed，待跨模块评审与冻结 | 多后端路由、出口治理、执行隔离与验证 | [查看详情](./REQ-SEC-004-sandbox-isolation-baseline.md) |
| REL-004 | [Checkpoint 保存与保留策略](./REQ-REL-004-checkpoint-retention-policy.md) | P0 | v0.1-designed，待跨模块评审与冻结 | 保存时机决策矩阵、保留期计算、保护谓词、清理并发控制 | [查看详情](./REQ-REL-004-checkpoint-retention-policy.md) |
| 02 | [安全威胁模型与控制矩阵](./02-security-threat-model.md) | P0 | SEC-001~010 全部 10 项已完成详细设计，待跨模块冻结 | 可控上线、生产部署 | [查看详情](./02-security-threat-model.md) |
| 03 | [持久执行、失败恢复与重试](./03-failure-recovery-retry.md) | P0 | REL-001~009 全部 9 项已完成详细设计，待跨模块冻结 | 可靠执行、生产可用性 | [查看详情](./03-failure-recovery-retry.md) |
| 05 | [评估体系](./05-evaluation-system.md) | P0 | EVA-001~007 已完成详细设计（7/7），待跨模块冻结 | 质量保证、持续改进 | [查看详情](./05-evaluation-system.md) |

### 质量提升层（P1 - 阻塞质量优化）

| 编号 | 文档名称 | 优先级 | 状态 | 关键阻塞 | 快速链接 |
|------|----------|--------|------|----------|----------|
| 04 | [上下文管理与代码索引](./04-context-and-code-indexing.md) | P1 | CTX-001~009 全部 9 项已完成详细设计，待跨模块冻结 | 代码理解、准确率提升 | [查看详情](./04-context-and-code-indexing.md) |
| CTX-001 | [索引实体和关系 Schema](./REQ-CTX-001-index-entities-schema.md) | P1 | 详细设计已完成，待跨模块冻结 | 索引实体定义 | [查看详情](./REQ-CTX-001-index-entities-schema.md) |
| CTX-002 | [语言、仓库规模和基准集](./REQ-CTX-002-language-repository-scale-benchmark.md) | P1 | 详细设计已完成，待跨模块冻结 | 语言支持范围 | [查看详情](./REQ-CTX-002-language-repository-scale-benchmark.md) |
| CTX-003 | [AST/LSP/依赖解析](./REQ-CTX-003-ast-lsp-dependency-parsing.md) | P1 | 详细设计已完成，待跨模块冻结 | 代码解析能力 | [查看详情](./REQ-CTX-003-ast-lsp-dependency-parsing.md) |
| CTX-004 | [混合检索与排序](./REQ-CTX-004-hybrid-retrieval-ranking.md) | P1 | 详细设计已完成，待跨模块冻结 | 检索质量和相关性 | [查看详情](./REQ-CTX-004-hybrid-retrieval-ranking.md) |
| CTX-005 | [检索权限与敏感路径](./REQ-CTX-005-retrieval-permissions-sensitive-paths.md) | P1 | 详细设计已完成，待跨模块冻结 | 检索安全和合规 | [查看详情](./REQ-CTX-005-retrieval-permissions-sensitive-paths.md) |
| CTX-006 | [Context Selector 与预算](./REQ-CTX-006-context-selector-budget.md) | P1 | 详细设计已完成，待跨模块冻结 | Token预算分配和上下文选择 | [查看详情](./REQ-CTX-006-context-selector-budget.md) |
| MEM-001 | [Memory Schema](./REQ-MEM-001-memory-schema.md) | P1 | 详细设计已完成，待跨模块冻结 | 记忆实体定义和类型系统 | [查看详情](./REQ-MEM-001-memory-schema.md) |
| MEM-002 | [记忆写入审批](./REQ-MEM-002-memory-write-approval.md) | P1 | 详细设计已完成，待跨模块冻结 | 记忆写入决策和审批流程 | [查看详情](./REQ-MEM-002-memory-write-approval.md) |
| MEM-003 | [记忆检索与冲突](./REQ-MEM-003-memory-retrieval-conflict.md) | P1 | 详细设计已完成，待跨模块冻结 | 混合检索、冲突检测和解决策略 | [查看详情](./REQ-MEM-003-memory-retrieval-conflict.md) |
| MEM-004 | [记忆生命周期](./REQ-MEM-004-memory-lifecycle.md) | P1 | 详细设计已完成，待跨模块冻结 | 记忆衰减、过期、删除和数据驻留 | [查看详情](./REQ-MEM-004-memory-lifecycle.md) |
| HAR-001 | [Harness 生命周期](./REQ-HAR-001-harness-lifecycle.md) | P0 | 详细设计已完成，待跨模块冻结 | Harness初始化、运行、暂停、恢复和关闭接口 | [查看详情](./REQ-HAR-001-harness-lifecycle.md) |
| HAR-002 | [Context Compaction](./REQ-HAR-002-context-compaction.md) | P0 | 详细设计已完成，待跨模块冻结 | 上下文压缩触发、快照和恢复语义 | [查看详情](./REQ-HAR-002-context-compaction.md) |
| HAR-003 | [Tool Adapter](./REQ-HAR-003-tool-adapter.md) | P0 | 详细设计已完成，待跨模块冻结 | 工具输入、输出、错误、风险和超时Schema | [查看详情](./REQ-HAR-003-tool-adapter.md) |
| HAR-004 | [Hook Registry](./REQ-HAR-004-hook-registry.md) | P0 | 详细设计已完成，待跨模块冻结 | Hook注册、签名、顺序、失败策略和兼容性 | [查看详情](./REQ-HAR-004-hook-registry.md) |
| HAR-005 | [LSP/MCP/Skill 统一路由](./REQ-HAR-005-unified-routing.md) | P0 | 详细设计已完成，待跨模块冻结 | 能力发现、权限裁剪和调用边界 | [查看详情](./REQ-HAR-005-unified-routing.md) |
| HAR-006 | [Harness 契约测试](./REQ-HAR-006-harness-contract-testing.md) | P0 | 详细设计已完成，待跨模块冻结 | 契约验证、轨迹回放、攻击回放、五层测试金字塔 | [查看详情](./REQ-HAR-006-harness-contract-testing.md) |

## 🎯 按功能领域分类

### 运行时与状态管理
- **[01-运行时基础契约](./01-runtime-contracts.md)**
  - 核心实体定义（Task、Action、Artifact、Evidence、Trace）
  - 状态机和状态迁移
  - 事件模型和版本策略
  - 检查点和恢复机制
  - Trace 传播、审计关联和 OpenTelemetry

### 安全与权限
- **[02-安全威胁模型与控制矩阵](./02-security-threat-model.md)**
  - `REQ-SEC-001` 威胁模型、`REQ-SEC-002` RBAC/资源授权、`REQ-SEC-003` Policy Gateway、`REQ-SEC-005` 凭据代理、`REQ-SEC-006` Prompt 注入防护、`REQ-SEC-007` MCP 连接器治理、`REQ-SEC-008` 多租户与数据治理、`REQ-SEC-009` Kill Switch 与事故响应已完成详细设计，均待跨模块评审与冻结
  - `REQ-SEC-010` 安全控制验证与红队测试计划已完成详细设计，待跨模块评审与冻结
  - 专项文档：[REQ-SEC-010 安全控制验证与红队测试计划](./REQ-SEC-010-security-control-validation-red-team.md)
  - 项目威胁场景目录、OWASP/ATLAS 映射和控制措施
  - 沙箱隔离技术选型（Docker/gVisor/Kata）
  - 凭据管理和代理方案
  - Kill Switch 和事故响应（六模式 + 三态 Fail-Closed + M5 分阶段恢复 + Break-Glass）

### 可靠性与恢复
- **[03-持久执行、失败恢复与重试](./03-failure-recovery-retry.md)**
  - 失败分类体系（4 大类、14 小类）
  - 重试策略和退避算法
  - **重试决策引擎（11 步流程、幂等闸门三分支与待决队列、双计数器、三值对账、三层熔断器和双层预算）**
  - **检查点保存与保留策略（记录类别基线、保护谓词五条件、软删除+48h宽限期、分片键控并发）**
  - **测试失败与工具异常分类（工具分波上线策略 W1/W2/W3、工具注册表 7 件必填事项、schema_hash 版本指纹、分类器职责分离、14 步分类流程、版本化配置契约）**：[REQ-REL-008-test-failure-tool-error-classification.md](./REQ-REL-008-test-failure-tool-error-classification.md)
  - 幂等性保证和补偿工作流

### 代码理解与检索
- **[04-上下文管理与代码索引](./04-context-and-code-indexing.md)**
  - 索引数据模型（文件、符号、依赖、关系）
  - 混合检索策略（BM25 + Vector + Graph）
  - **检索权限与敏感路径（零信任Pre-filter、三级敏感路径过滤、Fail-Secure策略、多租户数据隔离、RBAC权限校验、审计可观测性）**：[REQ-CTX-005-retrieval-permissions-sensitive-paths.md](./REQ-CTX-005-retrieval-permissions-sensitive-paths.md)
  - 增量索引和版本管理
  - 评估方法和指标

### 质量保证与评估
- **[05-评估体系](./05-evaluation-system.md)**
  - 5 层评估体系（工具/Worker/Workflow/端到端/安全对抗）
  - **Golden Dataset 构建（Oracle 入集闸门、五类血缘分开报告、污染控制安全事件管理、IRT 多维难度校准、对抗样本三层隔离）**：[REQ-EVA-001-golden-dataset.md](./REQ-EVA-001-golden-dataset.md)
  - **标注规范（六层标注Schema、Must-have/Nice-to-have分离、质量评估6维度、LLM-as-Judge校准、Krippendorff's alpha一致性、失败归因分类）**：[REQ-EVA-002-annotation-specification.md](./REQ-EVA-002-annotation-specification.md)
  - **自动评分器（独立grader架构、三层混合评分、per-criterion独立评分、五层评分体系、评分器校准、Security Judge独立设计）**：[REQ-EVA-003-automated-scorer.md](./REQ-EVA-003-automated-scorer.md)
  - **失败归因（反事实验证、三维正交分类体系、分层指标报告、约束保质期管理、置信度校准闭环）**：[REQ-EVA-004-failure-attribution.md](./REQ-EVA-004-failure-attribution.md)
  - **回归流水线（三层评估管道、轨迹感知子集选择、ATIF轨迹格式、统计显著性回归检测、CI/CD深度集成）**：[REQ-EVA-005-regression-pipeline.md](./REQ-EVA-005-regression-pipeline.md)

### 可观测性与审计
- **可观测性基线（OBS）**
  - **OpenTelemetry 语义约定（分层 Span 结构、标准属性集、采样策略、内容保护、传播边界）**：[REQ-OBS-001-opentelemetry-semantic-conventions.md](./REQ-OBS-001-opentelemetry-semantic-conventions.md)
  - **Trace/Event/Evidence Schema（44 EventType、敏感度分级、五层数据结构）**：[REQ-OBS-002-trace-event-evidence-schema.md](./REQ-OBS-002-trace-event-evidence-schema.md)
  - **指标字典（GenAI 专有指标、维度定义、高基数控制）**：[REQ-OBS-003-metrics-dictionary.md](./REQ-OBS-003-metrics-dictionary.md)
  - **脱敏和高基数控制（四层敏感度、Key Name 词素分词、32 层递归上限、调试模式审批流、URL Sanitizer、`__overflow__` 兜底）**：[REQ-OBS-004-redaction-cardinality-control.md](./REQ-OBS-004-redaction-cardinality-control.md)
  - **告警和 Kill Switch 联动（三维判定矩阵、告警规则引擎、M0-M5 模式映射、分层通知渠道）**：[REQ-OBS-005-alert-killswitch-linkage.md](./REQ-OBS-005-alert-killswitch-linkage.md)
  - **审计查询 API（四层 API 架构、统一查询过滤、权限隔离、完整性验证接口）**：[REQ-OBS-006-audit-query-api.md](./REQ-OBS-006-audit-query-api.md)
  - **审计留存和完整性（四层分层留存、防篡改哈希链、外部锚定、Merkle Tree、GDPR Tombstone、Legal Hold、PII 隔离、7年合规留存）**：[REQ-OBS-007-audit-retention-integrity.md](./REQ-OBS-007-audit-retention-integrity.md)

## 📊 设计进度统计

```text
主题规范数量: 5 个（01-运行时 / 02-安全 / 03-可靠性 / 04-上下文 / 05-评估）
已完成详细设计专项: 60/60 = 100%（均待跨模块评审与冻结）

按模块分布:
  - RT (运行时基础)：8/8 项完成
  - SEC (安全体系)：10/10 项完成
  - REL (可靠性)：9/9 项完成（含子需求 REQ-REL-008A，不单独计数）
  - CTX (上下文管理)：9/9 项完成
  - MEM (记忆管理)：4/4 项完成
  - HAR (Harness 工程)：6/6 项完成
  - OBS (可观测性)：7/7 项完成
  - EVA (评估体系)：7/7 项完成（REQ-EVA-007 于 2026-10-05 从扩展候选升级为正式基线，2026-10-08 完成详细设计）

优先级分布:
  - P0 主题规范: 4 个（01/02/03/05）
  - P1 主题规范: 1 个（04）
```

## 🚀 快速开始

### 新加入的架构师/工程师

**推荐阅读顺序**：
1. 先读 [README.md](./README.md) 了解整体规划
2. 阅读 [01-运行时基础契约](./01-runtime-contracts.md) 理解核心模型
3. 根据职责阅读相关领域文档：
   - 安全工程师 → [02-安全威胁模型](./02-security-threat-model.md)
   - 可靠性工程师 → [03-失败恢复与重试](./03-failure-recovery-retry.md)
   - 搜索工程师 → [04-上下文管理与代码索引](./04-context-and-code-indexing.md)
   - QA 工程师 → [05-评估体系](./05-evaluation-system.md)

### 准备启动设计工作

**阶段 0（设计冻结）已完成的文档**：
1. ✅ REQ-RT-001 ~ REQ-RT-008 运行时基础契约全部 8 项详细设计
2. ✅ REQ-SEC-001 ~ REQ-SEC-010 安全体系全部 10 项详细设计
3. ✅ REQ-REL-001 ~ REQ-REL-009 可靠性体系全部 9 项详细设计（含子需求 REQ-REL-008A）
4. ✅ REQ-CTX-001 ~ REQ-CTX-009 上下文管理全部 9 项详细设计
5. ✅ REQ-MEM-001 ~ REQ-MEM-004 记忆管理全部 4 项详细设计
6. ✅ REQ-HAR-001 ~ REQ-HAR-006 Harness 工程全部 6 项详细设计
7. ✅ REQ-OBS-001 ~ REQ-OBS-007 可观测性全部 7 项详细设计
8. ⏳ REQ-EVA-001 ~ REQ-EVA-006 评估体系已完成 6 项详细设计，REQ-EVA-007（生产反馈、数据集更新和版本回滚）待设计

**下一步行动** → 60/60 项正式基线需求已完成详细设计（100%），建议启动跨模块评审与冻结流程（参考 [00-integrated-design-baseline.md](./00-integrated-design-baseline.md) 维护规则及第 5.5 节 EVA 模块闭环缺口说明）

## 🔍 快速查找

### 按关键词查找

| 关键词 | 相关文档 |
|--------|----------|
| 状态机、事件、检查点 | [01-运行时基础契约](./01-runtime-contracts.md) |
| Prompt 注入、沙箱、凭据 | [02-安全威胁模型](./02-security-threat-model.md) |
| 重试、恢复、幂等性 | [03-失败恢复与重试](./03-failure-recovery-retry.md) |
| 代码索引、检索、向量 | [04-上下文管理与代码索引](./04-context-and-code-indexing.md) |
| 测试、评分、门禁 | [05-评估体系](./05-evaluation-system.md) |

### 按交付物查找

| 交付物 | 相关文档章节 |
|--------|-------------|
| Event Schema | [01-运行时契约 § 二.事件模型](./01-runtime-contracts.md#二、设计范围) |
| Checkpoint 格式 | [03-失败恢复 § 四.检查点](./03-failure-recovery-retry.md#四、检查点（checkpoint）) |
| 控制矩阵 | [02-安全威胁 § 三.控制矩阵](./02-security-threat-model.md#三、控制矩阵) |
| 索引 Schema | [04-上下文管理 § 三.索引数据模型](./04-context-and-code-indexing.md#三、索引数据模型) |
| Golden Dataset | [05-评估体系 § 三.Golden Dataset 构建](./05-evaluation-system.md#三、golden-dataset-构建) |

## 📈 设计依赖关系

```text
01-运行时基础契约 (所有模块的基础)
    ├── 02-安全威胁模型
    ├── 03-失败恢复与重试
    ├── 04-上下文管理与代码索引
    └── 05-评估体系
```

**关键依赖规则**：
- 必须先完成 01 才能开始其他设计
- 02、03、04、05 可以并行设计（有少量交叉依赖）
- 所有设计必须通过阶段 0 门禁才能进入实现

## ⚠️ 重要原则

### 设计不变量

所有设计必须遵守以下不变量（来自原始审计）：

**权限不变量**：
- 权限判断先于上下文加载
- 未授权资源不能被读取、检索或间接注入
- Worker 不能绕过 Policy Gateway

**执行不变量**：
- 模型不能直接执行 Action
- Action 必须绑定 user、task、trace
- 写操作不能盲目重试

**状态不变量**：
- 任务状态以事件为准
- 重试必须具备幂等键
- 进程重启后必须可恢复

**协作不变量**：
- Worker 通过 Artifact 协作
- 不共享完整对话历史
- 不允许无限递归创建 Worker

**交付不变量**：
- 模型返回成功 ≠ 任务完成
- 必须有测试、扫描或审查证据
- 所有变更可追溯、可回放、可撤销

### MVP 范围约束

**第一阶段必须包含**：
- 单组织、单仓库
- Bug 修复和小型功能
- GitHub Issue 到 PR
- Docker 沙箱隔离
- RBAC 和 Policy Gateway
- 基础工具集（文件、Git、测试）

**第一阶段不包含**：
- 长期组织记忆
- 多仓库和 Monorepo
- 复杂 DAG Workflow
- gVisor/Kata（可选）
- 自动学习和优化

## 📞 联系方式

| 领域 | 责任人 | 联系方式 |
|------|--------|----------|
| 整体架构 | 架构团队 | [待填写] |
| 运行时设计 | 后端 Lead | [待填写] |
| 安全设计 | 安全架构师 | [待填写] |
| 可靠性设计 | SRE Lead | [待填写] |
| 检索设计 | 搜索 Lead | [待填写] |
| 评估设计 | QA Lead | [待填写] |

---

**文档创建时间**：2026-09-22  
**最后更新时间**：2026-10-08（REQ-EVA-007 生产反馈、数据集更新和版本回滚已完成详细设计，EVA模块 7/7，总进度 60/60 = 100%，均待跨模块评审与冻结）  
**维护团队**：架构组
