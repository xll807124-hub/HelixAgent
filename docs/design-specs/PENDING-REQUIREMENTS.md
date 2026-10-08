# AI Agent 平台未完成需求清单

> **文档用途**：列出所有尚未完成设计的需求，作为后续专项设计的任务清单  
> **状态基准日期**：2026-09-26  
> **说明**：`REQ-SEC-003`、`REQ-SEC-004`、`REQ-SEC-005`、`REQ-SEC-006`、`REQ-SEC-007`、`REQ-SEC-008`、`REQ-SEC-009`、`REQ-SEC-010` 已完成详细设计；均待跨模块评审与冻结，不代表已实现或验证。  
> **维护规则**：每完成一个正式基线 `REQ-*` 的详细设计后，从待设计表移至已完成详细设计表并更新统一设计基线；扩展候选需求单独维护，不计入本清单总数  
> **唯一真相来源**：[AI Agent 平台统一设计基线与未完成需求清单](./00-integrated-design-baseline.md)  
>  
> **统计口径**：沿用统一设计基线的正式总数 59 项。本次状态变更将 REQ-OBS-004 纳入已完成详细设计表；逐项状态以本清单的唯一需求编号及下方分模块表为准，分模块历史汇总存在口径差异，待全量盘点时统一校准。

---

## 📊 总体进度

| 分类 | 总数 | 已完成设计 | 待设计 | 完成率 |
|------|------|-----------|--------|--------|
| **运行时基础（RT）** | 8 | 8 | 0 | 100% |
| **安全（SEC）** | 10 | **10** | 0 | 100% |
| **可靠性（REL）** | 9 | **9** | 0 | 100% |
| **上下文（CTX）** | 9 | **9** | **0** | **100%** |
| **记忆（MEM）** | 4 | **4** | **0** | **100%** |
| **Harness（HAR）** | 6 | **6** | **0** | **100%** |
| **可观测（OBS）** | 7 | **7** | **0** | **100%** |
| **评估（EVA）** | 7 | **7** | **0** | **100%** |
| **总计（当前汇总口径）** | 60 | **60** | **0** | **100%** |

> **计数规则（全局说明）**：
> 1. 本表总数 60 统计**正式基线需求**（纯数字编号，如 `REQ-REL-008`）。算术校验：RT(8) + SEC(10) + REL(9) + CTX(9) + MEM(4) + HAR(6) + OBS(7) + EVA(7) = 60。
> 2. **带字母后缀的编号（如 `REQ-REL-008A`）为子需求，不单独计入总数**。子需求与其父需求共享同一正式基线名额，用于拆分单个需求内范围过大、职责不同的设计内容（例如 `REQ-REL-008A` 是 `REQ-REL-008` 的分类引擎子设计）。
> 3. **扩展候选需求（如 `REQ-MEM-005`、`REQ-MEM-006`）不计入 60 项总数**，详见下方「扩展候选需求」章节。
> 4. **`REQ-EVA-007`（生产反馈、数据集更新和版本回滚）已于 2026-10-05 从扩展候选升级为正式基线需求**（原归档于候选区，经对标 Anthropic 评估生产闭环实践与业界 bundle 回滚规范，确认其填补 EVA-001~006 发布前质量门与生产态持续反馈之间的结构性缺口，不属于锦上添花的扩展功能），EVA 模块由 6 项增至 7 项，总基线由 59 升至 60；详见 [`00-integrated-design-baseline.md`](./00-integrated-design-baseline.md) 第 5.5 节「EVA 模块闭环缺口说明」。

---

## ✅ 已完成详细设计（待跨模块冻结）

| 编号 | 需求名称 | 版本 | 完成日期 | 专项文档 |
|------|---------|------|----------|----------|
| `REQ-RT-001` | 核心实体 Schema | v0.2-designed | 2026-09-22 | [查看](./REQ-RT-001-core-runtime-entities.md) |
| `REQ-RT-002` | 状态机与迁移约束 | v0.1-designed | 2026-09-22 | [查看](./REQ-RT-002-state-machines.md) |
| `REQ-RT-003` | Event Schema 与版本策略 | v0.1-designed | 2026-09-22 | [查看](./REQ-RT-003-event-schema-versioning.md) |
| `REQ-RT-004` | 状态投影与一致性规则 | v0.1-designed | 2026-09-22 | [查看](./REQ-RT-004-state-projections.md) |
| `REQ-RT-005` | Checkpoint Protocol | v0.1-designed | 2026-09-22 | [查看](./REQ-RT-005-checkpoint-protocol.md) |
| `REQ-RT-006` | Trace 传播和审计关联 | v0.1-designed | 2026-09-23 | [查看](./REQ-RT-006-Trace-传播和审计关联.md) |
| `REQ-RT-007` | Idempotency Key 与副作用边界 | v0.1-designed | 2026-09-23 | [查看](./REQ-RT-007-idempotency-key.md) |
| `REQ-RT-008` | 事件查询、留存、脱敏和权限边界 | v0.1-designed | 2026-09-23 | [查看](./REQ-RT-008-event-query-retention-redaction-permission.md) |
| `REQ-REL-003` | 重试决策引擎 | v0.2-designed | 2026-09-24 | [查看](./REQ-REL-003-retry-decision-engine.md) |
| `REQ-REL-004` | Checkpoint 保存与保留策略 | v0.1-designed | 2026-09-24 | [查看](./REQ-REL-004-checkpoint-retention-policy.md) |
| `REQ-REL-005` | 恢复决策与失败处理 | v0.2-designed | 2026-09-24 | [查看](./REQ-REL-005-recovery-decision-failure-handling.md) |
| `REQ-SEC-001` | 威胁模型和风险评分 | v0.1-designed | 2026-09-23 | [查看](./REQ-SEC-001-threat-model-risk-scoring.md) |
| `REQ-SEC-002` | RBAC 与资源授权 | v0.1-designed | 2026-09-23 | [查看](./REQ-SEC-002-rbac-resource-authorization.md) |
| `REQ-SEC-003` | Policy Gateway | v0.1-designed | 2026-09-23 | [查看](./REQ-SEC-003-policy-gateway.md) |
| `REQ-SEC-005` | 凭据代理 | v0.1-designed | 2026-09-23 | [查看](./REQ-SEC-005-credential-proxy.md) |
| `REQ-SEC-006` | Prompt 注入与恶意仓库防护 | v0.1-designed | 2026-09-23 | [查看](./REQ-SEC-006-prompt-injection-malicious-repo-protection.md) |
| `REQ-SEC-004` | 沙箱隔离基线 | v0.2-designed | 2026-09-23 | [查看](./REQ-SEC-004-sandbox-isolation-baseline.md) |
| `REQ-SEC-007` | MCP 连接器治理 | v0.1-designed | 2026-09-23 | [查看](./REQ-SEC-007-mcp-connector-governance.md) |
| `REQ-SEC-008` | 多租户与数据治理 | v0.1-designed | 2026-09-23 | [查看](./REQ-SEC-008-multi-tenant-data-governance.md) |
| `REQ-SEC-009` | Kill Switch 与事故响应 | v0.1-designed | 2026-09-23 | [查看](./REQ-SEC-009-kill-switch-incident-response.md) |
| `REQ-SEC-010` | 安全控制验证与红队测试计划 | v0.1-designed | 2026-09-24 | [查看](./REQ-SEC-010-security-control-validation-red-team.md) |
| `REQ-REL-001` | Failure Taxonomy | v0.1-designed | 2026-09-23 | [查看](./REQ-REL-001-failure-taxonomy.md) |
| `REQ-REL-002` | RetryPolicy | v0.1-designed | 2026-09-23 | [查看](./REQ-REL-002-retry-policy.md) |
| `REQ-REL-006` | 写操作幂等封装 | v0.1-designed | 2026-09-25 | [查看](./REQ-REL-006-write-operation-idempotency.md) |
| `REQ-REL-007` | Compensation Workflow | v0.1-designed | 2026-09-25 | [查看](./REQ-REL-007-compensation-workflow.md) |
| `REQ-EVA-001` | Golden Dataset | v0.1-designed | 2026-09-25 | [查看](./REQ-EVA-001-golden-dataset.md) |
| `REQ-CTX-001` | 索引实体和关系 Schema | v0.1-designed | 2026-09-26 | [查看](./REQ-CTX-001-index-entities-schema.md) |
| `REQ-REL-008` | 测试失败与工具异常分类（工具治理） | v0.1-designed | 2026-09-26 | [查看](./REQ-REL-008-test-failure-tool-error-classification.md) |
| `REQ-REL-008A` | 测试失败与工具异常分类（分类引擎，008 子需求） | v0.1-designed | 2026-09-26 | [查看](./REQ-REL-008A-test-failure-tool-exception-classification.md) |
| `REQ-HAR-001` | Harness 生命周期 | v0.1-designed | 2026-09-26 | [查看](./REQ-HAR-001-harness-lifecycle.md) |
| `REQ-REL-009` | 故障注入和恢复验证场景 | v0.1-designed | 2026-09-26 | [查看](./REQ-REL-009-fault-injection-recovery-verification.md) |
| `REQ-CTX-002` | 语言、仓库规模和基准集 | v0.1-designed | 2026-09-26 | [查看](./REQ-CTX-002-language-repository-scale-benchmark.md) |
| `REQ-CTX-003` | AST/LSP/依赖解析 | v0.1-designed | 2026-09-28 | [查看](./REQ-CTX-003-ast-lsp-dependency-parsing.md) |
| `REQ-CTX-004` | 混合检索与排序 | v0.1-designed | 2026-10-03 | [查看](./REQ-CTX-004-hybrid-retrieval-ranking.md) |
| `REQ-CTX-005` | 检索权限与敏感路径 | v1.0-designed | 2026-10-03 | [查看](./REQ-CTX-005-retrieval-permissions-sensitive-paths.md) |
| `REQ-HAR-002` | Context Compaction | v0.1-designed | 2026-09-26 | [查看](./REQ-HAR-002-context-compaction.md) |
| `REQ-HAR-003` | Tool Adapter | v0.1-designed | 2026-09-30 | [查看](./REQ-HAR-003-tool-adapter.md) |
| `REQ-MEM-001` | Memory Schema | v0.1-designed | 2026-09-27 | [查看](./REQ-MEM-001-memory-schema.md) |
| `REQ-EVA-002` | 标注规范 | v0.1-designed | 2026-09-27 | [查看](./REQ-EVA-002-annotation-specification.md) |
| `REQ-EVA-003` | 自动评分器 | v0.1-designed | 2026-09-28 | [查看](./REQ-EVA-003-automated-scorer.md) |
| `REQ-EVA-004` | 失败归因 | v0.1-designed | 2026-09-29 | [查看](./REQ-EVA-004-failure-attribution.md) |
| `REQ-EVA-005` | 回归流水线 | v0.1-designed | 2026-09-30 | [查看](./REQ-EVA-005-regression-pipeline.md) |
| `REQ-EVA-006` | 发布门禁 | v0.1-designed | 2026-10-05 | [查看](./REQ-EVA-006-release-gate.md) |
| `REQ-EVA-007` | 生产反馈、数据集更新和版本回滚 | v1.0-designed | 2026-10-08 | [查看](./REQ-EVA-007-production-feedback-dataset-rollback.md) |
| `REQ-OBS-001` | OpenTelemetry 语义约定 | v0.1-designed | 2026-10-01 | [查看](./REQ-OBS-001-opentelemetry-semantic-conventions.md) |
| `REQ-OBS-002` | Trace/Event/Evidence Schema | v0.1-designed | 2026-10-04 | [查看](./REQ-OBS-002-trace-event-evidence-schema.md) |
| `REQ-HAR-004` | Hook Registry | v0.1-designed | 2026-10-02 | [查看](./REQ-HAR-004-hook-registry.md) |
| `REQ-CTX-006` | Context Selector 与预算 | v0.1-designed | 2026-10-03 | [查看](./REQ-CTX-006-context-selector-budget.md) |
| `REQ-CTX-007` | 增量索引一致性 | v0.1-designed | 2026-10-04 | [查看](./REQ-CTX-007-incremental-index-consistency.md) |
| `REQ-CTX-008` | 上下文压缩与分层加载 | v0.1-designed | 2026-10-04 | [查看](./REQ-CTX-008-context-compression-tiered-loading.md) |
| `REQ-CTX-009` | 检索评测 | v0.1-designed | 2026-10-04 | [查看](./REQ-CTX-009-retrieval-evaluation.md) |
| `REQ-MEM-002` | 记忆写入审批 | v0.1-designed | 2026-10-04 | [查看](./REQ-MEM-002-memory-write-approval.md) |
| `REQ-HAR-005` | LSP/MCP/Skill 统一路由 | v0.1-designed | 2026-10-05 | [查看](./REQ-HAR-005-unified-routing.md) |
| `REQ-MEM-004` | 记忆生命周期 | v0.1-designed | 2026-10-05 | [查看](./REQ-MEM-004-memory-lifecycle.md) |
| `REQ-OBS-004` | 脱敏和高基数控制 | v0.1-designed | 2026-10-05 | [查看](./REQ-OBS-004-redaction-cardinality-control.md) |
| `REQ-OBS-005` | 告警和 Kill Switch 联动 | v0.1-designed | 2026-10-05 | [查看](./REQ-OBS-005-alert-killswitch-linkage.md) |
| `REQ-OBS-006` | 审计查询 API | v0.1-designed | 2026-10-05 | [查看](./REQ-OBS-006-audit-query-api.md) |
| `REQ-OBS-007` | 审计留存和完整性 | v1.0-designed | 2026-10-05 | [查看](./REQ-OBS-007-audit-retention-integrity.md) |
| `REQ-HAR-006` | Harness 契约测试 | v0.1-designed | 2026-10-05 | [查看](./REQ-HAR-006-harness-contract-testing.md) |

**下一步**：完成 `REQ-RT-001` 至 `REQ-RT-008` 的跨模块交叉评审，冻结 Runtime Contract v1；上下文管理（CTX）模块全部 9 项需求已完成详细设计（100%），待跨模块评审与冻结；记忆管理（MEM）模块全部 4 项需求已完成详细设计（100%），待跨模块评审与冻结；Harness 工程（HAR）模块全部 6 项需求已完成详细设计（100%），待跨模块评审与冻结；评估体系（EVA）模块全部 7 项需求已完成详细设计（100%），待跨模块评审与冻结；可观测性（OBS）模块全部 7 项需求已完成详细设计（100%），待跨模块评审与冻结；**总进度 60/60 = 100%，全部正式基线需求已完成详细设计（2026-10-08 完成最后一项 `REQ-EVA-007`），待跨模块评审与冻结。**

---

## ⏳ 未完成需求详细清单

### 1. 运行时基础（RT）- 全部设计完成

**运行时基础（RT）模块已全部完成详细设计，待跨模块评审与冻结。安全模块中的 `REQ-SEC-001` 至 `REQ-SEC-010` 已完成详细设计，详见上方已完成表；均未标记为冻结或已实现。**

---

### 2. 安全（SEC）- 全部 10 项已完成详细设计

**`REQ-SEC-001` 至 `REQ-SEC-010` 均已完成详细设计，详见上方已完成表；均未标记为冻结或已实现。**

---

### 3. 可靠性（REL）- 全部 9 项已完成详细设计

**`REQ-REL-001` 至 `REQ-REL-009` 均已完成详细设计，待跨模块评审与冻结；详见专项设计文档。**

---

### 3.1 可靠性（REL）- 已完成详细设计

全部 9 项可靠性需求已完成详细设计。

| 编号 | 需求 | 版本 | 完成日期 | 专项文档 |
|------|------|------|----------|----------|
| `REQ-REL-001` | Failure Taxonomy | v0.1-designed | 2026-09-23 | [查看](./REQ-REL-001-failure-taxonomy.md) |
| `REQ-REL-002` | RetryPolicy | v0.1-designed | 2026-09-23 | [查看](./REQ-REL-002-retry-policy.md) |
| `REQ-REL-003` | 重试决策引擎 | v0.2-designed | 2026-09-24 | [查看](./REQ-REL-003-retry-decision-engine.md) |
| `REQ-REL-004` | Checkpoint 保存与保留策略 | v0.1-designed | 2026-09-24 | [查看](./REQ-REL-004-checkpoint-retention-policy.md) |
| `REQ-REL-005` | 恢复决策与失败处理 | v0.2-designed | 2026-09-24 | [查看](./REQ-REL-005-recovery-decision-failure-handling.md) |
| `REQ-REL-006` | 写操作幂等封装 | v0.1-designed | 2026-09-25 | [查看](./REQ-REL-006-write-operation-idempotency.md) |
| `REQ-REL-007` | Compensation Workflow | v0.1-designed | 2026-09-25 | [查看](./REQ-REL-007-compensation-workflow.md) |
| `REQ-REL-008` | 测试失败与工具异常分类（工具治理） | v0.1-designed | 2026-09-26 | [查看](./REQ-REL-008-test-failure-tool-error-classification.md) |
| `REQ-REL-008A` | 测试失败与工具异常分类（分类引擎，008 子需求） | v0.1-designed | 2026-09-26 | [查看](./REQ-REL-008A-test-failure-tool-exception-classification.md) |
| `REQ-REL-009` | 故障注入和恢复验证场景 | v0.1-designed | 2026-09-26 | [查看](./REQ-REL-009-fault-injection-recovery-verification.md) |

---

### 4. 上下文管理（CTX）- 6 项已完成详细设计，3 项待设计

**`REQ-CTX-001` 索引实体和关系 Schema 已完成详细设计（v0.1-designed），`REQ-CTX-002` 语言、仓库规模和基准集已完成详细设计（v0.1-designed），`REQ-CTX-003` AST/LSP/依赖解析已完成详细设计（v0.1-designed），`REQ-CTX-004` 混合检索与排序已完成详细设计（v0.1-designed），`REQ-CTX-005` 检索权限与敏感路径已完成详细设计（v1.0-designed），`REQ-CTX-006` Context Selector 与预算已完成详细设计（v0.1-designed），`REQ-CTX-007` 增量索引一致性已完成详细设计（v0.1-designed），待跨模块评审与冻结；详见专项设计文档。**

| 编号 | 需求 | 优先级 | 前置依赖 | 关键交付物 | 状态 |
|------|------|--------|----------|-----------|------|
| `REQ-CTX-001` | 索引实体和关系 Schema | P1 | RT-001 | ✅ [已完成详细设计](./REQ-CTX-001-index-entities-schema.md) | v0.1-designed |
| `REQ-CTX-002` | 语言、仓库规模和基准集 | P1 | CTX-001、EVA-001 | ✅ [已完成详细设计](./REQ-CTX-002-language-repository-scale-benchmark.md) | v0.1-designed |
| `REQ-CTX-003` | AST/LSP/依赖解析 | P1 | CTX-001、CTX-002 | ✅ [已完成详细设计](./REQ-CTX-003-ast-lsp-dependency-parsing.md) | v0.1-designed |
| `REQ-CTX-004` | 混合检索与排序 | P1 | CTX-001、CTX-003 | ✅ [已完成详细设计](./REQ-CTX-004-hybrid-retrieval-ranking.md) | v0.1-designed |
| `REQ-CTX-005` | 检索权限与敏感路径 | P1 | SEC-002、SEC-008 | ✅ [已完成详细设计](./REQ-CTX-005-retrieval-permissions-sensitive-paths.md) | v1.0-designed |
| `REQ-CTX-006` | Context Selector 与预算 | P1 | CTX-004、RT-007 | ✅ [已完成详细设计](./REQ-CTX-006-context-selector-budget.md) | v0.1-designed |
| `REQ-CTX-007` | 增量索引一致性 | P1 | CTX-001、RT-001 | ✅ [已完成详细设计](./REQ-CTX-007-incremental-index-consistency.md) | v0.1-designed |
| `REQ-CTX-008` | 上下文压缩与分层加载 | P1 | CTX-006、HAR-002 | ✅ [已完成详细设计](./REQ-CTX-008-context-compression-tiered-loading.md) | v0.1-designed |
| `REQ-CTX-009` | 检索评测 | P1 | CTX-002、EVA-001 | ✅ [已完成详细设计](./REQ-CTX-009-retrieval-evaluation.md) | v0.1-designed |

---

### 5. 记忆管理（MEM）- 全部 4 项已完成详细设计

**`REQ-MEM-001` Memory Schema 已完成详细设计（v0.1-designed），`REQ-MEM-002` 记忆写入审批已完成详细设计（v0.1-designed），`REQ-MEM-003` 记忆检索与冲突已完成详细设计（v0.1-designed），`REQ-MEM-004` 记忆生命周期已完成详细设计（v0.1-designed），待跨模块评审与冻结；详见专项设计文档。**

| 编号 | 需求 | 优先级 | 前置依赖 | 关键交付物 | 状态 |
|------|------|--------|----------|-----------|------|
| `REQ-MEM-001` | Memory Schema | P1 | RT-001、SEC-008 | ✅ [已完成详细设计](./REQ-MEM-001-memory-schema.md) | v0.1-designed |
| `REQ-MEM-002` | 记忆写入审批 | P1 | MEM-001、SEC-003 | ✅ [已完成详细设计](./REQ-MEM-002-memory-write-approval.md) | v0.1-designed |
| `REQ-MEM-003` | 记忆检索与冲突 | P1 | MEM-001、CTX-006 | ✅ [已完成详细设计](./REQ-MEM-003-memory-retrieval-conflict.md) | v0.1-designed |
| `REQ-MEM-004` | 记忆生命周期 | P1 | MEM-001、SEC-008 | ✅ [已完成详细设计](./REQ-MEM-004-memory-lifecycle.md) | v0.1-designed |

---

### 6. Harness 工程（HAR）- 全部 6 项已完成详细设计

**`REQ-HAR-001` Harness生命周期已完成详细设计（v0.1-designed），`REQ-HAR-002` Context Compaction已完成详细设计（v0.1-designed），`REQ-HAR-003` Tool Adapter已完成详细设计（v0.1-designed），`REQ-HAR-004` Hook Registry已完成详细设计（v0.1-designed），`REQ-HAR-005` LSP/MCP/Skill统一路由已完成详细设计（v0.1-designed），`REQ-HAR-006` Harness契约测试已完成详细设计（v0.1-designed），待跨模块评审与冻结；详见专项设计文档。**

| 编号 | 需求 | 优先级 | 前置依赖 | 关键交付物 | 状态 |
|------|------|--------|----------|-----------|------|
| `REQ-HAR-001` | Harness 生命周期 | P0 | RT-001、SEC-003 | ✅ [已完成详细设计](./REQ-HAR-001-harness-lifecycle.md) | ✅ v0.1-designed |
| `REQ-HAR-002` | Context Compaction | P0 | CTX-008、REL-004 | ✅ [已完成详细设计](./REQ-HAR-002-context-compaction.md) | ✅ v0.1-designed |
| `REQ-HAR-003` | Tool Adapter | P0 | RT-001、SEC-003 | ✅ [已完成详细设计](./REQ-HAR-003-tool-adapter.md) | ✅ v0.1-designed |
| `REQ-HAR-004` | Hook Registry | P0 | HAR-001、SEC-001 | ✅ [已完成详细设计](./REQ-HAR-004-hook-registry.md) | ✅ v0.1-designed |
| `REQ-HAR-005` | LSP/MCP/Skill 统一路由 | P0 | HAR-003、SEC-007 | ✅ [已完成详细设计](./REQ-HAR-005-unified-routing.md) | ✅ v0.1-designed |
| `REQ-HAR-006` | Harness 契约测试 | P0 | HAR-001 至 HAR-005、EVA-003 | ✅ [已完成详细设计](./REQ-HAR-006-harness-contract-testing.md) | ✅ v0.1-designed |

---

### 7. 可观测性（OBS）- 全部 7 项已完成详细设计

**`REQ-OBS-001` OpenTelemetry 语义约定已完成详细设计（v0.1-designed），`REQ-OBS-002` Trace/Event/Evidence Schema 已完成详细设计（v0.1-designed），`REQ-OBS-003` 指标字典已完成详细设计（v0.1-designed），`REQ-OBS-004` 脱敏和高基数控制已完成详细设计（v0.1-designed），`REQ-OBS-005` 告警和 Kill Switch 联动已完成详细设计（v0.1-designed），`REQ-OBS-006` 审计查询 API 已完成详细设计（v0.1-designed），`REQ-OBS-007` 审计留存和完整性已完成详细设计（v1.0-designed），待跨模块评审与冻结；详见专项设计文档。**

| 编号 | 需求 | 优先级 | 前置依赖 | 关键交付物 | 状态 |
|------|------|--------|----------|-----------|------|
| `REQ-OBS-001` | OpenTelemetry 语义约定 | P0 | RT-006 | ✅ [已完成详细设计](./REQ-OBS-001-opentelemetry-semantic-conventions.md) | v0.1-designed |
| `REQ-OBS-002` | Trace/Event/Evidence Schema | P0 | RT-003、RT-006 | ✅ [已完成详细设计](./REQ-OBS-002-trace-event-evidence-schema.md) | v0.1-designed |
| `REQ-OBS-003` | 指标字典 | P0 | RT-001、EVA-005 | ✅ [已完成详细设计](./REQ-OBS-003-metrics-dictionary.md) | v0.1-designed |
| `REQ-OBS-004` | 脱敏和高基数控制 | P0 | SEC-008、OBS-003 | ✅ [已完成详细设计](./REQ-OBS-004-redaction-cardinality-control.md) | v0.1-designed |
| `REQ-OBS-005` | 告警和 Kill Switch 联动 | P0 | SEC-009、OBS-003 | ✅ [已完成详细设计](./REQ-OBS-005-alert-killswitch-linkage.md) | v0.1-designed |
| `REQ-OBS-006` | 审计查询 API | P0 | RT-006、SEC-008 | ✅ [已完成详细设计](./REQ-OBS-006-audit-query-api.md) | v0.1-designed |
| `REQ-OBS-007` | 审计留存和完整性 | P0 | SEC-008、RT-003 | ✅ [已完成详细设计](./REQ-OBS-007-audit-retention-integrity.md) | v1.0-designed |

---

### 8. 评估体系（EVA）- 7/7 项已完成详细设计

**`REQ-EVA-001` Golden Dataset 已完成详细设计（v0.1-designed），`REQ-EVA-002` 标注规范已完成详细设计（v0.1-designed），`REQ-EVA-003` 自动评分器已完成详细设计（v0.1-designed），`REQ-EVA-004` 失败归因已完成详细设计（v0.1-designed），`REQ-EVA-005` 回归流水线已完成详细设计（v0.1-designed），`REQ-EVA-006` 发布门禁已完成详细设计（v0.1-designed），待跨模块评审与冻结；`REQ-EVA-007`（生产反馈、数据集更新和版本回滚）已于 2026-10-05 升级为正式基线需求，待详细设计；详见专项设计文档。**

| 编号 | 需求 | 优先级 | 前置依赖 | 关键交付物 | 状态 |
|------|------|--------|----------|-----------|------|
| `REQ-EVA-001` | Golden Dataset | P0 | RT-001、REL-001 | ✅ [已完成详细设计](./REQ-EVA-001-golden-dataset.md) | v0.1-designed |
| `REQ-EVA-002` | 标注规范 | P0 | EVA-001 | ✅ [已完成详细设计](./REQ-EVA-002-annotation-specification.md) | v0.1-designed |
| `REQ-EVA-003` | 自动评分器 | P0 | EVA-001、EVA-002 | ✅ [已完成详细设计](./REQ-EVA-003-automated-scorer.md) | v0.1-designed |
| `REQ-EVA-004` | 失败归因 | P0 | RT-003、REL-001、EVA-003 | ✅ [已完成详细设计](./REQ-EVA-004-failure-attribution.md) | v0.1-designed |
| `REQ-EVA-005` | 回归流水线 | P0 | EVA-003、EVA-004 | ✅ [已完成详细设计](./REQ-EVA-005-regression-pipeline.md) | v0.1-designed |
| `REQ-EVA-006` | 发布门禁 | P0 | EVA-005、SEC-001、SEC-009 | ✅ [已完成详细设计](./REQ-EVA-006-release-gate.md) | v0.1-designed |
| `REQ-EVA-007` | 生产反馈、数据集更新和版本回滚 | P1 | EVA-001、EVA-004、EVA-006 | ✅ [已完成详细设计](./REQ-EVA-007-production-feedback-dataset-rollback.md) | v0.1-designed |

---

## 📋 推荐设计顺序

基于依赖关系和阻塞优先级，推荐以下顺序。`REQ-RT-006` 已完成详细设计并移入上方已完成表；该设计优先于原推荐顺序中的后续待办。

### 第一批（阻塞所有模块）
1. ✅ `REQ-RT-008` 事件查询、留存、脱敏和权限边界（已完成详细设计）
2. ✅ `REQ-SEC-001` 威胁模型和风险评分（已完成详细设计，待跨模块评审与冻结）
3. ✅ `REQ-SEC-002` RBAC 与资源授权（v0.1-designed，待跨模块评审与冻结）
4. ✅ `REQ-REL-001` Failure Taxonomy（已完成详细设计，待跨模块评审与冻结）

### 第二批（核心安全与可靠性）
6. ✅ `REQ-SEC-003` Policy Gateway（已完成详细设计，待跨模块评审与冻结）
7. ✅ `REQ-SEC-004` 沙箱隔离基线（v0.2-designed，待跨模块评审与冻结）
8. `REQ-REL-002` RetryPolicy
9. ✅ `REQ-REL-003` 重试决策引擎（已完成详细设计）
10. `REQ-EVA-001` Golden Dataset

### 第三批（恢复与补偿）
11. `REQ-REL-004` Checkpoint 保存与保留策略
12. ✅ `REQ-REL-005` 恢复决策与失败处理（已完成详细设计）
13. ✅ `REQ-REL-006` 写操作幂等封装（已完成详细设计）
14. `REQ-REL-007` Compensation Workflow
15. `REQ-SEC-005` 凭据代理

### 第四批（上下文与评估基础）
16. ✅ `REQ-CTX-001` 索引实体和关系 Schema（已完成详细设计）
17. `REQ-CTX-002` 语言、仓库规模和基准集
18. ✅ `REQ-EVA-002` 标注规范（已完成详细设计）
19. `REQ-EVA-003` 自动评分器
20. `REQ-HAR-001` Harness 生命周期

### 第五批（剩余需求）
21-60. ✅ 全部完成（2026-10-08，REQ-EVA-007 为最后完成项）

---

## 🎯 关键里程碑

**重要更新**（2026-10-08）：全部 60 项正式基线需求已完成详细设计（100%），推荐设计顺序已完成，下一步进入跨模块评审与冻结阶段。

### 里程碑 1：Runtime Contract v1 冻结（下一步）
- **前置条件**：`REQ-RT-001` 至 `REQ-RT-008` 全部完成跨模块评审
- **交付标准**：Schema 文档、状态机图、事件 Schema、Checkpoint 协议、Trace 规范、幂等规则
- **预计工期**：4-6 周

### 里程碑 2：安全威胁模型冻结
- **前置条件**：`REQ-SEC-001` 至 `REQ-SEC-010` 全部完成
- **交付标准**：威胁模型文档、控制矩阵、沙箱选型报告、凭据方案、Kill Switch 设计
- **预计工期**：4-6 周（与里程碑 1 并行）

### 里程碑 3：失败恢复与重试冻结
- **前置条件**：`REQ-REL-001` 至 `REQ-REL-009` 全部完成
- **交付标准**：失败分类文档、RetryPolicy Schema、恢复协议、补偿工作流、故障注入测试套件（≥20 场景）
- **预计工期**：3-4 周（依赖里程碑 1）
- **当前状态**：✅ 全部 9 项已完成详细设计，待跨模块评审与冻结

### 里程碑 4：Golden Dataset 与评估基线（已完成设计）
- **前置条件**：`REQ-EVA-001` 至 `REQ-EVA-007` 全部完成
- **交付标准**：Golden Dataset v1.0（≥100 个真实任务、≥70 个安全对抗样本）、标注规范、自动评分器、发布门禁、生产反馈闭环
- **预计工期**：4-6 周（部分与里程碑 1-3 并行）
- **当前状态**：✅ 全部 7 项需求已完成详细设计（2026-10-08 完成 REQ-EVA-007）

---

## 🔮 扩展候选需求（不计入 60 项正式基线）

以下需求为扩展候选，暂不纳入正式基线，待后续阶段视优先级启动设计：

| 编号 | 需求名称 | 优先级 | 状态 | 说明 |
|------|---------|--------|------|------|
| `REQ-MEM-005` | 跨项目权限继承和租户隔离 | P2 | 待设计 | 记忆模块扩展：支持跨项目记忆共享的权限继承模型，多租户记忆物理隔离与逻辑隔离策略 |
| `REQ-MEM-006` | 错误记忆清理和效果评测 | P2 | 待设计 | 记忆模块扩展：自动识别低质量或误导性记忆并清理，评测记忆对 Agent 决策质量的影响 |

> **说明**：扩展候选需求不影响 MVP 交付，不占用核心设计资源；待 60 项正式基线冻结并进入实现阶段后，按实际需要选择性启动设计。
> 
> **`REQ-EVA-007` 已于 2026-10-05 移出候选区，升级为正式基线需求**（升级原因见上方计数规则说明第 4 条及 [`00-integrated-design-baseline.md`](./00-integrated-design-baseline.md) 第 5.5 节）。

---

## ⚠️ 阻塞关系警告

以下需求相互阻塞或循环依赖，需特别注意设计顺序：

| 阻塞关系 | 解决方案 |
|---------|---------|
| `REQ-CTX-005` 依赖 `REQ-SEC-002`，但 `SEC-002` 可能需要上下文授权模型 | 先冻结 RBAC 基础模型，上下文授权作为扩展 |
| `REQ-HAR-002` 依赖 `REQ-REL-004`，`REL-004` 依赖 `RT-005` | `RT-005` 已完成，`REL-004` 优先 |
| `REQ-OBS-001` 依赖 `REQ-RT-006` | `RT-006` 已定义 Trace 传播与审计关联；`OBS-001` 后续定义语义属性并细化观测采样映射 |
| `REQ-EVA-001` 需要真实任务，但真实任务依赖 Runtime 实现 | 使用历史任务或手工模拟任务构建初始数据集 |

---

## 📝 维护指南

### 当完成一个需求的详细设计后

1. 将该需求从本文档对应分类中**删除**
2. 在「已完成详细设计」表格中**添加**该需求
3. 更新 `00-integrated-design-baseline.md` 中的对应状态与汇总统计
4. 更新 `INDEX.md`、`README.md` 和总体方案中的进度统计及依赖引用
5. 提交 Git commit，标题格式：`docs(design): complete REQ-XX-NNN detailed design`

### 当冻结一个需求（跨模块评审通过）后

1. 将需求版本从 `vX.Y-designed` 升级为 `vX.Y-frozen`
2. 在统一设计基线中标记为「已冻结，可实现」
3. 更新所有依赖该需求的文档中的状态引用

---

**文档创建时间**：2026-09-23  
**最后更新时间**：2026-10-08（REQ-EVA-007 生产反馈、数据集更新和版本回滚已完成详细设计；EVA 模块进度更新为 7/7 = 100%；**总进度 60/60 = 100%，全部正式基线需求已完成详细设计**）  
**维护团队**：架构组
