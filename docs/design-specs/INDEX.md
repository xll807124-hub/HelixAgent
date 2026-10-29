# 设计功能点快速索引

> ✅ SEC-007 生命周期切片及依赖/扫描扩展于 2026-10-29 验收；2026-10-28 实测：全量 2100 通过 / 3 Docker 跳过，SAST/SCA/Secret 通过。其余缺口保持开放。
> 本文提供 60 项正式需求的导航。2026-10-28 用户确认：RT 八项保留 2026-10-07 冻结版本；Security 等未冻结项继续待评审；CTX-008 缺失章节已按用户确认r2重建，G-CTX待验收，未全项冻结。开发顺序以[执行手册正文](../../项目开发执行手册.md)为准；对齐评审已验收，当前为 SEC-007 生命周期发现/调用补缺的✅ 已完成状态（2026-10-29 用户验收）。

## 📋 正式需求完整索引（60 项）

设计状态与实现状态分列；历史成果日期和测试摘要见[评审记录](../review/roadmap-status-and-stage0-proposal-2026-10-28.md)。✅ 对齐评审于 2026-10-28 完成：60 项需求、341 链接通过，2001 测试通过 / 3 跳过。SEC 仍待评审；[当前子任务方案](../review/sec007-lifecycle-discovery-design-2026-10-28.md)已于 2026-10-28 确认；✅ 已于 2026-10-29 验收完成。

### RT 运行时

| 编号 | 功能 | 设计状态 | 实现/验收状态 |
|---|---|---|---|
| REQ-RT-001 | [核心运行时实体 Schema](./REQ-RT-001-core-runtime-entities.md) | v0.2-frozen；2026-10-07 | 进行中（已有实现，待完整验收） |
| REQ-RT-002 | [Task、Workflow、Worker、Action 状态机与迁移约束](./REQ-RT-002-state-machines.md) | v0.1-frozen；2026-10-07 | 进行中（已有实现，待完整验收） |
| REQ-RT-003 | [Event Schema 与版本策略](./REQ-RT-003-event-schema-versioning.md) | v0.1-frozen；2026-10-07 | 进行中（已有实现，待完整验收） |
| REQ-RT-004 | [状态投影与一致性规则](./REQ-RT-004-state-projections.md) | v0.1-frozen；2026-10-07 | 进行中（已有实现，待完整验收） |
| REQ-RT-005 | [Checkpoint Protocol](./REQ-RT-005-checkpoint-protocol.md) | v0.1-frozen；2026-10-07 | 进行中（已有实现，待完整验收） |
| REQ-RT-006 | [Trace 传播和审计关联](./REQ-RT-006-Trace-传播和审计关联.md) | v0.1-frozen；2026-10-07 | 进行中（已有实现，待完整验收） |
| REQ-RT-007 | [Idempotency Key 与副作用边界](./REQ-RT-007-idempotency-key.md) | v0.1-frozen；2026-10-07 | 进行中（已有实现，待完整验收） |
| REQ-RT-008 | [事件查询、留存、脱敏和权限边界](./REQ-RT-008-event-query-retention-redaction-permission.md) | v0.1-frozen；2026-10-07 | 进行中（已有实现，待完整验收） |

### SEC 安全

| 编号 | 功能 | 设计状态 | 实现/验收状态 |
|---|---|---|---|
| REQ-SEC-001 | [威胁模型和风险评分](./REQ-SEC-001-threat-model-risk-scoring.md) | 设计文件已有；待评审冻结 | 进行中（已有实现，待完整验收） |
| REQ-SEC-002 | [RBAC 与资源授权](./REQ-SEC-002-rbac-resource-authorization.md) | 设计文件已有；待评审冻结 | 进行中（已有实现，待完整验收） |
| REQ-SEC-003 | [Policy Gateway 策略决策、审批、拒绝与审计](./REQ-SEC-003-policy-gateway.md) | 设计文件已有；待评审冻结 | 进行中（已有实现，待完整验收） |
| REQ-SEC-004 | [沙箱隔离基线](./REQ-SEC-004-sandbox-isolation-baseline.md) | 设计文件已有；待评审冻结 | 进行中（已有实现，待完整验收） |
| REQ-SEC-005 | [凭据代理](./REQ-SEC-005-credential-proxy.md) | 设计文件已有；待评审冻结 | 进行中（已有实现，待完整验收） |
| REQ-SEC-006 | [Prompt注入与恶意仓库防护](./REQ-SEC-006-prompt-injection-malicious-repo-protection.md) | 设计文件已有；待评审冻结 | ✅ 历史已完成（2026-10-23 确认） |
| REQ-SEC-007 | [MCP 连接器治理](./REQ-SEC-007-mcp-connector-governance.md) | 设计文件已有；待评审冻结 | 进行中（已有实现，待完整验收） |
| REQ-SEC-008 | [多租户与数据治理](./REQ-SEC-008-multi-tenant-data-governance.md) | 设计文件已有；待评审冻结 | 进行中（已有实现，待完整验收） |
| REQ-SEC-009 | [Kill Switch 与事故响应](./REQ-SEC-009-kill-switch-incident-response.md) | 设计文件已有；待评审冻结 | 进行中（已有实现，待完整验收） |
| REQ-SEC-010 | [安全控制验证与红队测试计划](./REQ-SEC-010-security-control-validation-red-team.md) | 设计文件已有；待评审冻结 | 进行中（已有实现，待完整验收） |

### REL 可靠性

| 编号 | 功能 | 设计状态 | 实现/验收状态 |
|---|---|---|---|
| REQ-REL-001 | [Failure Taxonomy](./REQ-REL-001-failure-taxonomy.md) | 设计文件已有；待评审冻结 | 待开发（可有共用基础） |
| REQ-REL-002 | [RetryPolicy](./REQ-REL-002-retry-policy.md) | 设计文件已有；待评审冻结 | 待开发（可有共用基础） |
| REQ-REL-003 | [重试决策引擎](./REQ-REL-003-retry-decision-engine.md) | 设计文件已有；待评审冻结 | 待开发（可有共用基础） |
| REQ-REL-004 | [Checkpoint 保存与保留策略](./REQ-REL-004-checkpoint-retention-policy.md) | 设计文件已有；待评审冻结 | 进行中（已有实现，待完整验收） |
| REQ-REL-005 | [恢复决策与失败处理](./REQ-REL-005-recovery-decision-failure-handling.md) | 设计文件已有；待评审冻结 | 进行中（已有实现，待完整验收） |
| REQ-REL-006 | [写操作幂等封装](./REQ-REL-006-write-operation-idempotency.md) | 设计文件已有；待评审冻结 | 进行中（已有实现，待完整验收） |
| REQ-REL-007 | [Compensation Workflow](./REQ-REL-007-compensation-workflow.md) | 设计文件已有；待评审冻结 | 待开发（可有共用基础） |
| REQ-REL-008 | [测试失败与工具异常分类（工具治理与上线策略）](./REQ-REL-008-test-failure-tool-error-classification.md) | 设计文件已有；待评审冻结 | 进行中（已有实现，待完整验收） |
| REQ-REL-009 | [故障注入和恢复验证场景](./REQ-REL-009-fault-injection-recovery-verification.md) | 设计文件已有；待评审冻结 | 进行中（已有实现，待完整验收） |

### CTX 上下文

| 编号 | 功能 | 设计状态 | 实现/验收状态 |
|---|---|---|---|
| REQ-CTX-001 | [索引实体和关系 Schema](./REQ-CTX-001-index-entities-schema.md) | 设计文件已有；待评审冻结 | 待开发（可有共用基础） |
| REQ-CTX-002 | [语言、仓库规模和基准集](./REQ-CTX-002-language-repository-scale-benchmark.md) | 设计文件已有；待评审冻结 | 待开发（可有共用基础） |
| REQ-CTX-003 | [AST/LSP/依赖解析](./REQ-CTX-003-ast-lsp-dependency-parsing.md) | 设计文件已有；待评审冻结 | 待开发（可有共用基础） |
| REQ-CTX-004 | [混合检索与排序](./REQ-CTX-004-hybrid-retrieval-ranking.md) | 设计文件已有；待评审冻结 | 待开发（可有共用基础） |
| REQ-CTX-005 | [检索权限与敏感路径过滤](./REQ-CTX-005-retrieval-permissions-sensitive-paths.md) | 设计文件已有；待评审冻结 | 待开发（可有共用基础） |
| REQ-CTX-006 | [Context Selector 与预算](./REQ-CTX-006-context-selector-budget.md) | 设计文件已有；待评审冻结 | 待开发（可有共用基础） |
| REQ-CTX-007 | [增量索引一致性](./REQ-CTX-007-incremental-index-consistency.md) | 设计文件已有；待评审冻结 | 待开发（可有共用基础） |
| REQ-CTX-008 | [上下文压缩与分层加载](./REQ-CTX-008-context-compression-tiered-loading.md) | 原文开头不完整；未冻结 | 待开发（可有共用基础） |
| REQ-CTX-009 | [检索评测](./REQ-CTX-009-retrieval-evaluation.md) | 设计文件已有；待评审冻结 | 待开发（可有共用基础） |

### MEM 记忆

| 编号 | 功能 | 设计状态 | 实现/验收状态 |
|---|---|---|---|
| REQ-MEM-001 | [Memory Schema](./REQ-MEM-001-memory-schema.md) | 设计文件已有；待评审冻结 | 待开发（可有共用基础） |
| REQ-MEM-002 | [记忆写入审批](./REQ-MEM-002-memory-write-approval.md) | 设计文件已有；待评审冻结 | 待开发（可有共用基础） |
| REQ-MEM-003 | [记忆检索与冲突](./REQ-MEM-003-memory-retrieval-conflict.md) | 设计文件已有；待评审冻结 | 待开发（可有共用基础） |
| REQ-MEM-004 | [记忆生命周期](./REQ-MEM-004-memory-lifecycle.md) | 设计文件已有；待评审冻结 | 待开发（可有共用基础） |

### HAR Harness

| 编号 | 功能 | 设计状态 | 实现/验收状态 |
|---|---|---|---|
| REQ-HAR-001 | [Harness 生命周期管理](./REQ-HAR-001-harness-lifecycle.md) | 设计文件已有；待评审冻结 | 进行中（已有实现，待完整验收） |
| REQ-HAR-002 | [Context Compaction（上下文压缩）](./REQ-HAR-002-context-compaction.md) | 设计文件已有；待评审冻结 | 待开发（可有共用基础） |
| REQ-HAR-003 | [Tool Adapter（工具适配器）](./REQ-HAR-003-tool-adapter.md) | 设计文件已有；待评审冻结 | 进行中（已有实现，待完整验收） |
| REQ-HAR-004 | [Hook Registry - Hook注册表、签名、顺序、失败策略和兼容性](./REQ-HAR-004-hook-registry.md) | 设计文件已有；待评审冻结 | 待开发（可有共用基础） |
| REQ-HAR-005 | [LSP/MCP/Skill 统一路由](./REQ-HAR-005-unified-routing.md) | 设计文件已有；待评审冻结 | 进行中（已有实现，待完整验收） |
| REQ-HAR-006 | [Harness 契约测试](./REQ-HAR-006-harness-contract-testing.md) | 设计文件已有；待评审冻结 | 进行中（已有实现，待完整验收） |

### OBS 可观测性

| 编号 | 功能 | 设计状态 | 实现/验收状态 |
|---|---|---|---|
| REQ-OBS-001 | [OpenTelemetry 语义约定](./REQ-OBS-001-opentelemetry-semantic-conventions.md) | 设计文件已有；待评审冻结 | 进行中（已有实现，待完整验收） |
| REQ-OBS-002 | [Trace/Event/Evidence Schema](./REQ-OBS-002-trace-event-evidence-schema.md) | 设计文件已有；待评审冻结 | 进行中（已有实现，待完整验收） |
| REQ-OBS-003 | [指标字典](./REQ-OBS-003-metrics-dictionary.md) | 设计文件已有；待评审冻结 | 待开发（可有共用基础） |
| REQ-OBS-004 | [脱敏和高基数控制](./REQ-OBS-004-redaction-cardinality-control.md) | 设计文件已有；待评审冻结 | 进行中（已有实现，待完整验收） |
| REQ-OBS-005 | [告警和 Kill Switch 联动](./REQ-OBS-005-alert-killswitch-linkage.md) | 设计文件已有；待评审冻结 | 待开发（可有共用基础） |
| REQ-OBS-006 | [审计查询 API](./REQ-OBS-006-audit-query-api.md) | 设计文件已有；待评审冻结 | 进行中（已有实现，待完整验收） |
| REQ-OBS-007 | [审计留存和完整性 (Audit Retention & Integrity)](./REQ-OBS-007-audit-retention-integrity.md) | 设计文件已有；待评审冻结 | 进行中（已有实现，待完整验收） |

### EVA 评估

| 编号 | 功能 | 设计状态 | 实现/验收状态 |
|---|---|---|---|
| REQ-EVA-001 | [Golden Dataset](./REQ-EVA-001-golden-dataset.md) | 设计文件已有；待评审冻结 | 待开发（可有共用基础） |
| REQ-EVA-002 | [标注规范](./REQ-EVA-002-annotation-specification.md) | 设计文件已有；待评审冻结 | 待开发（可有共用基础） |
| REQ-EVA-003 | [自动评分器](./REQ-EVA-003-automated-scorer.md) | 设计文件已有；待评审冻结 | 待开发（可有共用基础） |
| REQ-EVA-004 | [失败归因](./REQ-EVA-004-failure-attribution.md) | 设计文件已有；待评审冻结 | 待开发（可有共用基础） |
| REQ-EVA-005 | [回归流水线](./REQ-EVA-005-regression-pipeline.md) | 设计文件已有；待评审冻结 | 进行中（已有实现，待完整验收） |
| REQ-EVA-006 | [发布门禁](./REQ-EVA-006-release-gate.md) | 设计文件已有；待评审冻结 | 进行中（已有实现，待完整验收） |
| REQ-EVA-007 | [生产反馈、数据集更新和版本回滚](./REQ-EVA-007-production-feedback-dataset-rollback.md) | 设计文件已有；待评审冻结 | 待开发（可有共用基础） |

### 主题总览与额外设计

主题总览：[运行时](./01-runtime-contracts.md)、[安全](./02-security-threat-model.md)、[可靠性](./03-failure-recovery-retry.md)、[上下文](./04-context-and-code-indexing.md)、[评估](./05-evaluation-system.md)。旧总览状态以本次已确认口径为准。

[REL-008A](./REQ-REL-008A-test-failure-tool-exception-classification.md) 为子设计，[WKR-001](./REQ-WKR-001-coder-worker-architecture.md) 为额外 Worker 设计，均不重复计入正式 60 项。

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
正式需求文件: 60 项；冻结 8 项；未冻结 52 项（含 1 项 CTX-008 原文完整性缺口）

按模块分布:
  - RT (运行时基础)：8 项已冻结（2026-10-07）
  - SEC (安全体系)：10/10 项完成
  - REL (可靠性)：9/9 项完成（含子需求 REQ-REL-008A，不单独计数）
  - CTX (上下文管理)：9 项文件已有，CTX-008 开头缺失
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

### 准备启动设计或开发工作

1. 阅读执行手册正文，核对唯一当前任务；当前是阶段 0 / 步骤 2 的 SEC-007 生命周期发现/调用补缺，✅ 已完成（2026-10-29 用户验收）。
2. RT 八项已冻结，代码实现仍需逐项验收；Security 等设计不能因已有局部代码而自动冻结。
3. EVA-007 已于 2026-10-08 完成详细设计，继续跟踪与 EVA-006 的接口评审；不再列“待设计”。
4. CTX-008 从 5.2 节附近开始，已检索 Git 历史但未找到完整开头；保留待恢复/重新设计条目。
5. 对当前任务完成需求分析、对标、设计确认、实现和验证；交付确认后再选下一任务。

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
**最后更新时间**：2026-10-28（正文顺序、RT 冻结、60 项索引及 CTX-008 缺口对齐）
**维护团队**：架构组


## G-CTX 2026-10-29 引用同步记录

用户已确认 `gctx-review-20261029-r2`，见 [契约与交付记录](../development/contracts/context.md) §9～15。CTX-001/004/006/007/008 与 HAR-002 为 v0.2-designed，CTX-005 为 v1.1-designed；规则加载失败为 DENY；CTX-008 缺失章节为批准重建，并非历史原稿恢复。以上仅为限定文档基线，不代表整项 REQ 冻结、生产实现或 G-CTX 用户验收。原历史统计和未涉及模块状态不由本记录更新。

变更：G-CTX 引用修订 r1；日期 2026-10-29；仅同步上述版本、完整性和安全语义，不改变正式需求总数。
