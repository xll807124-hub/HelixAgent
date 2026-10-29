# 正文路线图复核与阶段 0 评审交付记录

> ✅ SEC-007 生命周期切片及依赖/扫描扩展于 2026-10-29 验收；2026-10-28 实测：全量 2100 通过 / 3 Docker 跳过，SAST/SCA/Secret 通过。其余缺口保持开放。
> 日期：2026-10-28（Asia/Shanghai）
>
> 状态：**✅ 对齐评审已完成，2026-10-28**。用户先回复“确认以上三点”批准评审方案，交付后再次回复“继续”，据此记录评审文档验收。测试摘要：60 项需求、341 链接通过，2001 测试通过 / 3 跳过。Security 冻结及软件安全门禁不在本次验收范围。
>
> 本记录对应阶段 0 的第一个子任务——设计—代码对齐评审及状态基线整理。下一项为 SEC-007 生命周期发现/调用补缺，[✅ 已完成（2026-10-29 用户验收）](./sec007-lifecycle-discovery-design-2026-10-28.md)。
>
> 测试数据来源：历史修复报告与本轮重新运行的全量回归/覆盖率/实际 SCA 扫描分别记录。本轮结果见第 7 节和[结构化报告](../test-reports/stage0-alignment-2026-10-28.json)。

## 1. 已确认依据与文档用途

用户已明确：“项目开发步骤”指《项目开发执行手册》；执行顺序按手册**正文路线图**重新核定。顶部历史 Task 编号保留追溯用途，不再用其决定下一任务。用户要求每次只做一个任务，方案确认后实现，交付确认后才标记完成。

| 文档类型 | 主要入口 | 用途与证据边界 |
|---|---|---|
| 执行手册 | [项目开发执行手册](../../项目开发执行手册.md) | 决定路线图顺序、DoR/DoD；与迭代规则冲突时按用户要求以手册为准，并提交冲突确认 |
| 迭代规则 | [规则文档/AGENTS.md](../../规则文档/AGENTS.md) | 开发、测试和变更纪律；本轮按用户明确要求引用，适配区有旧版本信息 |
| 需求分析 | [需求分析报告](../需求分析报告.md)、[需求设计方案](../../需求设计方案.md) | 明确问题、产品边界和功能范围；历史状态段落不能替代最新实现证据 |
| 总基线与索引 | [总基线](../design-specs/00-integrated-design-baseline.md)、[INDEX](../design-specs/INDEX.md) | 需求目录、依赖、版本和冻结汇总；目前与部分 REQ 页状态不一致 |
| 专项需求契约 | [design-specs](../design-specs/) 下 REQ 文档 | 单项字段、流程、边界与验收标准；designed 与 frozen 分别记录 |
| API/实现说明 | [API 说明](../api/README.md)、[历史实现报告](../implementation/) | 接口、运行方式和历史交付范围；不能单独证明真实环境验收 |
| 评审/冻结草稿 | [旧接口对齐清单](../design-specs/INTERFACE_ALIGNMENT_CHECKLIST.md)、[Runtime 草案](../design-specs/runtime-contract-v1.0-draft.md)、[Security 草案](../design-specs/security-baseline-v1.0-draft.md) | 拟议决策；旧接口清单已自带勘误，明确不得直接作为评审依据 |
| 测试证据 | [最新修复报告](../test-reports/remaining-issues-2026-10-28.json) | 已执行检查、结果及跳过原因；测试通过不自动等于整项 REQ 完成 |
| 根目录日报/完成总结 | 例如 [STAGE0 历史总结](../../STAGE0_COMPLETION_SUMMARY_2026-10-11.md) | 历史过程记录；该总结明确撤回过未经证实的完成率，不能采信旧百分比 |

MVP 需求是单组织、单仓库、GitHub 优先的 Issue → PR 闭环，要求可审批、可恢复、可审计，并包含 Web 任务控制台。本轮评审解决“无法可靠判断下一开发任务”的问题；开发范围沿用这些需求。

## 2. 当前任务状态表

以下为核查后的状态；未完成阶段中已有的代码和测试成果继续保留。未找到证据表示目前不能确认完成，不代表断言整个仓库绝无相关实现。

| 正文顺序 | 任务 | 核查状态 | 主要依据/待办 |
|---|---|---|---|
| 0 / 步骤 1 | 设计—代码对齐评审 | **✅ 已完成，2026-10-28** | 60 项需求、341 链接通过；2001 测试通过 / 3 跳过；评审文档验收 |
| 0 / 步骤 2～3 | 优先补缺及冻结决议 | **进行中；SEC-007 子任务✅ 已完成（2026-10-29 用户验收）** | 生命周期发现/调用补缺优先；Security 条件冻结尚缺一致决议 |
| 1.1 | Walking Skeleton | 进行中（历史已交付内存骨架） | 事件写读、投影、Action/Evidence 已有；正文列出的 PostgreSQL 存储仍有缺口 |
| 1.2 | 核心运行时 | 进行中（历史组件已交付） | 八项 Runtime 有实现与单测；持久化恢复和全契约对齐需核验 |
| 1.3 | 基础安全 | 进行中 | RBAC/网关/凭据/Docker 已有；白名单、逃逸检测、真实环境验收不完整 |
| 1.4 | 基础工具集 | 进行中 | File/Git/Shell/pytest 已有；jest/go test 适配器未找到 |
| 1.5 | 简单 Worker | 进行中（本地链路已实现） | 本地真实 Git/工具 E2E 使用 MockModelClient；真实模型与远端 PR 闭环需证据 |
| 2.1 | 安全强化 | 进行中 | 含 SAST/SCA/Secret、Prompt 防护和 MCP；部分组件已交付，MCP 未闭环 |
| 2.2 | 可观测性 | 进行中 | Trace/Span 有基础；审计完整性、指标/仪表盘、告警仍有缺口 |
| 2.3 | Kill Switch | 进行中 | 已有简化三态/闸门；完整模式、降级状态、传播与恢复演练待补 |
| 2.4 | 多租户隔离 | 进行中（局部基础） | 范围校验已有；数据分区、池分组与资源配额待补 |
| 2.5 | 回归测试与发布门禁 | 进行中（局部基础） | pytest/Nox、SCA workflow 已有；Golden Dataset 和完整发布门禁待补 |
| 3.1 | 索引构建 | 待开发 | AST/LSP/依赖解析及基准未找到 |
| 3.2 | 混合检索 | 待开发 | 三通道、RRF、检索权限预过滤未形成 |
| 3.3 | Context Selector | 待开发 | 预算、分层加载与压缩实现未找到 |
| 3.4 | 检索评估与调优 | 待开发 | 评测集、A/B 结果和冻结基线未找到 |
| 4.1 | Workflow DAG | 待开发（已有实体/状态基础） | Workflow 模型不等于依赖调度与多 Worker 协作 |
| 4.2 | 专家 Worker | 待开发 | 当前仅 Coder/ReAct；五个专家 Worker 未找到 |
| 4.3 | 记忆系统 | 待开发 | 四项 MEM 设计已有，实现未找到 |
| 4.4 | Harness SDK | 进行中（共用工具基础） | 生命周期/工具部分基础已有，Hook/统一路由/完整契约测试待补 |
| 5 | 高级优化 | 待开发 | 长期组织记忆、多模型路由、WarmPool、IDE/CLI、SSO/SCIM |

需求分析中的 **Web 任务控制台** 尚无 React 代码骨架；正文没有单列前端任务编号。该项保留为“待开发/路线图归属待确认”，不能因正文未编号而从需求清单中删除；本轮不另开前端任务。

### 历史已完成成果与验证日期

此表限定历史交付范围；未据此重新验收整个阶段。

| 已完成成果 | 日期 | 测试/核查摘要 | 边界 |
|---|---|---|---|
| ✅ SAST/Secret、SCA 扫描适配器历史交付 | 2026-10-12 / 2026-10-13 | 手册记载 SCA 当时 29 测试通过；2026-10-28 最新全量回归通过 | 适配器通过不代表当前仓库真实扫描已全部达门禁 |
| ✅ Prompt 注入防护 Task 2.3 历史交付并确认 | 2026-10-13 交付；2026-10-23 用户确认 | 最新 JUnit 对应单测分组 114 通过 | 保留用户历史确认；专项设计页“未实现”待同步 |
| ✅ 遗留问题修复与本地检查入口交付 | 2026-10-28 | 全量 2001 通过、0 失败、3 跳过；Ruff 0；mypy 196 源文件 0 错误；行覆盖率 85.55% | Docker 3 项跳过及 MCP 生产缺口仍开放 |
| ✅ RT-008 查询链路、参数/范围校验与递归脱敏修复交付 | 2026-10-28 | 已纳入上述全量回归；修复点见报告 | 不将局部修复外推为所有留存/持久化验收完成 |

没有可靠日期和证据的项目保留“待核验”，不编造完成日期。Runtime 源文档记录的 **2026-10-07 冻结日期**另列为设计状态事实，不当作代码完成日期。

### 顶部旧编号与正文编号的对应关系

| 顶部历史编号 | 内容 | 正文归属 |
|---|---|---|
| Task 2.1 | SAST/Secret | 2.1 安全强化 |
| Task 2.2 | SCA | 2.1 安全强化 |
| Task 2.3 | Prompt 防护 | 2.1 安全强化 |
| Task 2.4 | MCP 治理 | 2.1 安全强化；同时被阶段 0 列为优先缺口 |
| Task 2.5～2.8 | 顶部仅列“待开始” | 不凭编号猜测，后续按正文具体任务定位 |

正文 **2.4 始终表示多租户隔离**。阶段 0 还列出 RT-008、SEC-007 等补缺项；本轮首个子任务交付确认后，仍须按阶段 0 剩余清单核定下一项，不能直接跳到 1.1 或 2.1。

## 3. 六十项正式需求盘点

已定位 **60 个唯一正式 REQ ID**，分布为 RT 8、SEC 10、REL 9、CTX 9、MEM 4、HAR 6、OBS 7、EVA 7。REL-008A 是子设计，WKR-001 是额外 Worker 设计；完成总结和 EVA-006/007 协同评审不重复计数。

设计状态：RT-001～008 页首均标注 2026-10-07 已冻结；其余主体文件普遍为 designed/待评审。CTX-008 正文开头不完整，因此此轮只能确认“60 项均有文件”，不能未经恢复核查继续宣称“60 项设计全部完整”。

以下是定位级盘点，不替代每份需求全部验收条件的逐条审计。正文没有给每个 REL/OBS/EVA 子项分配独立开发编号，其归属在阶段 0 对齐时明确，不自行另排优先级。

### 运行时（8 项）

| 需求 | 功能 | 实现状态（核查） | 证据与缺口 |
|---|---|---|---|
| [REQ-RT-001](../design-specs/REQ-RT-001-core-runtime-entities.md) | 核心运行时实体 Schema | 进行中（已有实现，待完整验收） | 已有实体模型及单测；须逐项核对引用完整性和不变量。 |
| [REQ-RT-002](../design-specs/REQ-RT-002-state-machines.md) | Task、Workflow、Worker、Action 状态机与迁移约束 | 进行中（已有实现，待完整验收） | 已有分层状态机、迁移校验和单测；须核对父子状态与暂停/恢复约束。 |
| [REQ-RT-003](../design-specs/REQ-RT-003-event-schema-versioning.md) | Event Schema 与版本策略 | 进行中（已有实现，待完整验收） | 已有事件契约与内存存储；离线构造接受非法 ID（A02）；PostgreSQL 实现未找到，持久性未验收。 |
| [REQ-RT-004](../design-specs/REQ-RT-004-state-projections.md) | 状态投影与一致性规则 | 进行中（已有实现，待完整验收） | 已有四类投影与重放；存储为内存实现，持久化一致性待补。 |
| [REQ-RT-005](../design-specs/REQ-RT-005-checkpoint-protocol.md) | Checkpoint Protocol | 进行中（已有实现，待完整验收） | 已有检查点构建、校验、恢复；Runtime 默认存储为内存，持久化恢复待验收。 |
| [REQ-RT-006](../design-specs/REQ-RT-006-Trace-传播和审计关联.md) | Trace 传播和审计关联 | 进行中（已有实现，待完整验收） | 已有 Trace 传播、采样、审计关联；完整生产采集链路待验收。 |
| [REQ-RT-007](../design-specs/REQ-RT-007-idempotency-key.md) | Idempotency Key 与副作用边界 | 进行中（已有实现，待完整验收） | 已有幂等键、存储接口、对账与升级；内存存储不能证明跨进程去重。 |
| [REQ-RT-008](../design-specs/REQ-RT-008-event-query-retention-redaction-permission.md) | 事件查询、留存、脱敏和权限边界 | 进行中（已有实现，待完整验收） | 查询、权限、递归脱敏已修复并回归；完整留存执行与持久化查询仍需验收。 |

代码/验证入口：[运行时相关目录](../../src/runtime/)。目录和符号检索只用于定位实现，不替代逐项验收。

### 安全（10 项）

| 需求 | 功能 | 实现状态（拟核定） | 证据与缺口 |
|---|---|---|---|
| [REQ-SEC-001](../design-specs/REQ-SEC-001-threat-model-risk-scoring.md) | 威胁模型和风险评分 | 进行中（已有实现，待完整验收） | 风险枚举/局部评分已出现在实体、网关和检测器中；统一威胁模型落地待核验。 |
| [REQ-SEC-002](../design-specs/REQ-SEC-002-rbac-resource-authorization.md) | RBAC 与资源授权 | 进行中（已有实现，待完整验收） | 已有 RBAC、资源授权及单测；持久授权、全链路接入和租户边界待核验。 |
| [REQ-SEC-003](../design-specs/REQ-SEC-003-policy-gateway.md) | Policy Gateway 策略决策、审批、拒绝与审计 | 进行中（已有实现，待完整验收） | 已有简化/v2 网关与 OPA 适配；决策 ID、审批枚举映射、风险差异 TTL 及生产装配仍有缺口（A04～A06）。 |
| [REQ-SEC-004](../design-specs/REQ-SEC-004-sandbox-isolation-baseline.md) | 沙箱隔离基线 | 进行中（已有实现，待完整验收） | Docker SDK 契约已修复；出口白名单和逃逸检测明确未实现，3 个真实 Docker 用例未验收。 |
| [REQ-SEC-005](../design-specs/REQ-SEC-005-credential-proxy.md) | 凭据代理 | 进行中（已有实现，待完整验收） | 已有 GitHub HTTP 契约测试；CDP 仍示例铸造，审批证明与请求 TTL 上限存在缺口（A08～A10）；真实服务/撤销未验收。 |
| [REQ-SEC-006](../design-specs/REQ-SEC-006-prompt-injection-malicious-repo-protection.md) | Prompt注入与恶意仓库防护 | ✅ 历史已完成（2026-10-23 确认） | 历史 Task 2.3 已于 2026-10-23 获用户确认；最近单测分组 114 通过。设计页的“未实现”已过时；全红队指标不能由单测数量推出。 |
| [REQ-SEC-007](../design-specs/REQ-SEC-007-mcp-connector-governance.md) | MCP 连接器治理 | 进行中（已有实现，待完整验收） | 已有 MCP 注册、策略、传输、签名和凭据适配；生产授权装配、Schema 复审、撤销失效等仍待补。 |
| [REQ-SEC-008](../design-specs/REQ-SEC-008-multi-tenant-data-governance.md) | 多租户与数据治理 | 进行中（已有实现，待完整验收） | 查询中已有租户/项目范围校验，沙箱有租户契约；数据分区、计算池与配额未形成完整闭环。 |
| [REQ-SEC-009](../design-specs/REQ-SEC-009-kill-switch-incident-response.md) | Kill Switch 与事故响应 | 进行中（已有实现，待完整验收） | 仅简化 IDLE/TRIGGERED/RECOVERING 与四类作用域；M0～M5、NORMAL/DEGRADED/LOCKED、传播演练及 Break-Glass 待实现/验收（A07）。 |
| [REQ-SEC-010](../design-specs/REQ-SEC-010-security-control-validation-red-team.md) | 安全控制验证与红队测试计划 | 进行中（已有实现，待完整验收） | 已有安全回归及扫描器测试；专项红队场景库、真实隔离攻击与发布阻断证据待补。 |

代码/验证入口：[安全相关目录](../../src/security/)。目录和符号检索只用于定位实现，不替代逐项验收。

### 可靠性（9 项）

| 需求 | 功能 | 实现状态（拟核定） | 证据与缺口 |
|---|---|---|---|
| [REQ-REL-001](../design-specs/REQ-REL-001-failure-taxonomy.md) | Failure Taxonomy | 待开发（可有共用基础） | 已有分散异常类型；未找到独立、完整的 Failure Taxonomy 实现。 |
| [REQ-REL-002](../design-specs/REQ-REL-002-retry-policy.md) | RetryPolicy | 待开发（可有共用基础） | 已有局部重试/退避（如幂等对账）；未找到统一 RetryPolicy 完整实现。 |
| [REQ-REL-003](../design-specs/REQ-REL-003-retry-decision-engine.md) | 重试决策引擎 | 待开发（可有共用基础） | 幂等对账有重试基础；三分支决策引擎和待决队列未见完整实现。 |
| [REQ-REL-004](../design-specs/REQ-REL-004-checkpoint-retention-policy.md) | Checkpoint 保存与保留策略 | 进行中（已有实现，待完整验收） | 可复用 Runtime 检查点；保留、清理与持久化策略未见独立完整实现。 |
| [REQ-REL-005](../design-specs/REQ-REL-005-recovery-decision-failure-handling.md) | 恢复决策与失败处理 | 进行中（已有实现，待完整验收） | 已有 Runtime 恢复和 Worker checkpoint；九态恢复决策、Effect Log 等待补。 |
| [REQ-REL-006](../design-specs/REQ-REL-006-write-operation-idempotency.md) | 写操作幂等封装 | 进行中（已有实现，待完整验收） | 可复用 RT-007 和工具执行器；外部写操作全链路持久幂等未验收。 |
| [REQ-REL-007](../design-specs/REQ-REL-007-compensation-workflow.md) | Compensation Workflow | 待开发（可有共用基础） | 未找到补偿工作流执行器；设计已存在。 |
| [REQ-REL-008](../design-specs/REQ-REL-008-test-failure-tool-error-classification.md) | 测试失败与工具异常分类（工具治理与上线策略） | 进行中（已有实现，待完整验收） | 已有工具错误模型和 pytest 结果解析；统一分类治理、上线策略待补。 |
| [REQ-REL-009](../design-specs/REQ-REL-009-fault-injection-recovery-verification.md) | 故障注入和恢复验证场景 | 进行中（已有实现，待完整验收） | 已有故障/异常单测；设计规定的故障注入场景库和恢复演练待补。 |

代码/验证入口：[可靠性相关目录](../../src/runtime/)。目录和符号检索只用于定位实现，不替代逐项验收。

### 上下文（9 项）

| 需求 | 功能 | 实现状态（拟核定） | 证据与缺口 |
|---|---|---|---|
| [REQ-CTX-001](../design-specs/REQ-CTX-001-index-entities-schema.md) | 索引实体和关系 Schema | 待开发（可有共用基础） | 未找到代码索引实体实现。 |
| [REQ-CTX-002](../design-specs/REQ-CTX-002-language-repository-scale-benchmark.md) | 语言、仓库规模和基准集 | 待开发（可有共用基础） | 未找到语言/仓库规模基准集及运行结果。 |
| [REQ-CTX-003](../design-specs/REQ-CTX-003-ast-lsp-dependency-parsing.md) | AST/LSP/依赖解析 | 待开发（可有共用基础） | 未找到 AST/LSP/依赖解析实现。 |
| [REQ-CTX-004](../design-specs/REQ-CTX-004-hybrid-retrieval-ranking.md) | 混合检索与排序 | 待开发（可有共用基础） | 未找到 BM25F/向量/图检索及 RRF 实现。 |
| [REQ-CTX-005](../design-specs/REQ-CTX-005-retrieval-permissions-sensitive-paths.md) | 检索权限与敏感路径过滤 | 待开发（可有共用基础） | 已有文件路径授权基础；检索前权限过滤与敏感路径检索控制尚未实现。 |
| [REQ-CTX-006](../design-specs/REQ-CTX-006-context-selector-budget.md) | Context Selector 与预算 | 待开发（可有共用基础） | 未找到 Context Selector 与预算分配实现。 |
| [REQ-CTX-007](../design-specs/REQ-CTX-007-incremental-index-consistency.md) | 增量索引一致性 | 待开发（可有共用基础） | 未找到增量索引一致性实现。 |
| [REQ-CTX-008](../design-specs/REQ-CTX-008-context-compression-tiered-loading.md) | 上下文压缩与分层加载 | 待开发（可有共用基础） | 未找到对应实现；设计正文从残余代码块及 5.2 节起始，缺少标题/前置章节，完整性待恢复核对。 |
| [REQ-CTX-009](../design-specs/REQ-CTX-009-retrieval-evaluation.md) | 检索评测 | 待开发（可有共用基础） | 未找到检索评测集、A/B 基线与性能结果。 |

代码/验证入口：[上下文相关目录](../../src/)。目录和符号检索只用于定位实现，不替代逐项验收。

### 记忆（4 项）

| 需求 | 功能 | 实现状态（拟核定） | 证据与缺口 |
|---|---|---|---|
| [REQ-MEM-001](../design-specs/REQ-MEM-001-memory-schema.md) | Memory Schema | 待开发（可有共用基础） | 未找到三类记忆 Schema 的生产模块；Worker checkpoint 不等于记忆系统。 |
| [REQ-MEM-002](../design-specs/REQ-MEM-002-memory-write-approval.md) | 记忆写入审批 | 待开发（可有共用基础） | 未找到记忆写入审批实现。 |
| [REQ-MEM-003](../design-specs/REQ-MEM-003-memory-retrieval-conflict.md) | 记忆检索与冲突 | 待开发（可有共用基础） | 未找到记忆检索与冲突处理实现。 |
| [REQ-MEM-004](../design-specs/REQ-MEM-004-memory-lifecycle.md) | 记忆生命周期 | 待开发（可有共用基础） | 未找到记忆衰减、清理及生命周期实现。 |

代码/验证入口：[记忆相关目录](../../src/)。目录和符号检索只用于定位实现，不替代逐项验收。

### Harness（6 项）

| 需求 | 功能 | 实现状态（拟核定） | 证据与缺口 |
|---|---|---|---|
| [REQ-HAR-001](../design-specs/REQ-HAR-001-harness-lifecycle.md) | Harness 生命周期管理 | 进行中（已有实现，待完整验收） | 已有 Runtime Worker 生命周期基础；独立 Harness 生命周期契约未完整落地。 |
| [REQ-HAR-002](../design-specs/REQ-HAR-002-context-compaction.md) | Context Compaction（上下文压缩） | 待开发（可有共用基础） | 未找到 Harness 上下文压缩模块。 |
| [REQ-HAR-003](../design-specs/REQ-HAR-003-tool-adapter.md) | Tool Adapter（工具适配器） | 进行中（已有实现，待完整验收） | 已有 ToolRegistry、ActionExecutor 和工具基类；完整 Harness Tool Adapter 契约待补。 |
| [REQ-HAR-004](../design-specs/REQ-HAR-004-hook-registry.md) | Hook Registry - Hook注册表、签名、顺序、失败策略和兼容性 | 待开发（可有共用基础） | 未找到 Hook Registry 实现。 |
| [REQ-HAR-005](../design-specs/REQ-HAR-005-unified-routing.md) | LSP/MCP/Skill 统一路由 | 进行中（已有实现，待完整验收） | 已有 MCP 局部执行能力；LSP/MCP/Skill 统一路由未形成。 |
| [REQ-HAR-006](../design-specs/REQ-HAR-006-harness-contract-testing.md) | Harness 契约测试 | 进行中（已有实现，待完整验收） | 已有局部 HTTP/SDK 契约测试；完整 Harness 契约套件未建立。 |

代码/验证入口：[Harness相关目录](../../src/tools/)。目录和符号检索只用于定位实现，不替代逐项验收。

### 可观测性（7 项）

| 需求 | 功能 | 实现状态（拟核定） | 证据与缺口 |
|---|---|---|---|
| [REQ-OBS-001](../design-specs/REQ-OBS-001-opentelemetry-semantic-conventions.md) | OpenTelemetry 语义约定 | 进行中（已有实现，待完整验收） | 已有 src/observability 和 Runtime Trace；语义规范、采集导出及生产链路待核验。 |
| [REQ-OBS-002](../design-specs/REQ-OBS-002-trace-event-evidence-schema.md) | Trace/Event/Evidence Schema | 进行中（已有实现，待完整验收） | 已有 Event、Evidence、Trace 基础模型；完整 OBS 关联约束待核验。 |
| [REQ-OBS-003](../design-specs/REQ-OBS-003-metrics-dictionary.md) | 指标字典 | 待开发（可有共用基础） | 未找到完整指标字典落地、Prometheus/Grafana 配置与验收结果。 |
| [REQ-OBS-004](../design-specs/REQ-OBS-004-redaction-cardinality-control.md) | 脱敏和高基数控制 | 进行中（已有实现，待完整验收） | 已有 Runtime 查询递归脱敏；遥测全链路脱敏及高基数治理待补。 |
| [REQ-OBS-005](../design-specs/REQ-OBS-005-alert-killswitch-linkage.md) | 告警和 Kill Switch 联动 | 待开发（可有共用基础） | 已有 Kill Switch 基础；告警判定、通知渠道与自动联动闭环待补。 |
| [REQ-OBS-006](../design-specs/REQ-OBS-006-audit-query-api.md) | 审计查询 API | 进行中（已有实现，待完整验收） | RT-008 已有事件查询服务；不能据此认定独立 OBS 审计查询 API 完成。 |
| [REQ-OBS-007](../design-specs/REQ-OBS-007-audit-retention-integrity.md) | 审计留存和完整性 (Audit Retention & Integrity) | 进行中（已有实现，待完整验收） | 已有留存策略和局部审计记录；WORM、外部锚定与完整性验证链路未验收。 |

代码/验证入口：[可观测性相关目录](../../src/observability/)。目录和符号检索只用于定位实现，不替代逐项验收。

### 评估（7 项）

| 需求 | 功能 | 实现状态（拟核定） | 证据与缺口 |
|---|---|---|---|
| [REQ-EVA-001](../design-specs/REQ-EVA-001-golden-dataset.md) | Golden Dataset | 待开发（可有共用基础） | 未找到可执行的 Golden Dataset 入集/版本流程。 |
| [REQ-EVA-002](../design-specs/REQ-EVA-002-annotation-specification.md) | 标注规范 | 待开发（可有共用基础） | 有标注规范设计；未找到配套标注流程实现。 |
| [REQ-EVA-003](../design-specs/REQ-EVA-003-automated-scorer.md) | 自动评分器 | 待开发（可有共用基础） | 未找到自动评分器实现。 |
| [REQ-EVA-004](../design-specs/REQ-EVA-004-failure-attribution.md) | 失败归因 | 待开发（可有共用基础） | 未找到评估失败归因实现。 |
| [REQ-EVA-005](../design-specs/REQ-EVA-005-regression-pipeline.md) | 回归流水线 | 进行中（已有实现，待完整验收） | 已有 pytest/Nox 和 SCA workflow；Golden Dataset 驱动的完整回归流水线待补。 |
| [REQ-EVA-006](../design-specs/REQ-EVA-006-release-gate.md) | 发布门禁 | 进行中（已有实现，待完整验收） | 已有局部扫描策略；四级发布门禁、决策和例外审批未形成完整验收证据。 |
| [REQ-EVA-007](../design-specs/REQ-EVA-007-production-feedback-dataset-rollback.md) | 生产反馈、数据集更新和版本回滚 | 待开发（可有共用基础） | 未找到生产反馈、数据集更新与版本回滚闭环。 |

代码/验证入口：[评估相关目录](../../tests/)。目录和符号检索只用于定位实现，不替代逐项验收。

另有 [WKR-001 Coder 架构](../design-specs/REQ-WKR-001-coder-worker-architecture.md) 和 [REL-008A 异常分类子设计](../design-specs/REQ-REL-008A-test-failure-tool-exception-classification.md)，分别随正文 1.5 和 REL-008 跟踪。

## 4. 冲突处理与开放事项

| 编号 | 问题 | 本轮处理结果 |
|---|---|---|
| C1 | RT 源页已冻结，总基线仍待冻结 | 2026-10-28 用户确认保留；手册/索引/总基线/需求分析已同步。SEC 继续待评审，未自动冻结 |
| C2 | 手册核心 ≥90%，规则指定关键路径 100% | 用户确认总体 ≥70%、核心 ≥90%、分支 ≥60%，指定关键路径保留 100%；已同步手册与规则适配区 |
| C3 | 规则扫描命令 n/a 与真实门禁要求不一致 | 已取消无工具即通过的口径；本轮 SCA 发现 68 条记录，SAST/Secret 工具缺失，均保持开放 |
| C4 | 后续阶段完成勾选无完整验收证据 | 正文勾选改为待验收，历史局部交付继续显式记录日期和测试摘要 |
| C5 | 旧接口清单与完成报告有无依据结论 | 接口清单已重写为 A01～A16，逐项附专项原文、源码及测试证据 |
| C6 | CTX-008 开头缺失，EVA-007 旧状态过期 | Git 全分支历史只找到初始提交 6f506aa，CTX-008 仍缺开头，无法可靠恢复；保留原文完整性缺口。EVA-007 状态已改为设计已有、待接口评审 |
| C7 | 手册旧“并行推进”与用户串行要求不一致 | 已按用户要求每次单任务；交付后暂停 |
| C8 | Web 控制台没有正文独立编号 | 保留既有 MVP 需求及待开发状态；归属和 UI 规范在启动前确认，未擅自插入开发顺序 |

设计与代码存在的差异统一记录为实现缺口，未据现有实现修改冻结契约。最新[接口矩阵与 Security 条件冻结建议](../design-specs/INTERFACE_ALIGNMENT_CHECKLIST.md)是本轮评审依据；旧总结中的未核实完成率不再作为依据。

## 5. 对标分析

访问日期：2026-10-28。本次功能是开发基线与评审流程，选择直接相关的编程产品；下述“借鉴/规避”为本项目设计判断，不代表已实测竞品。

| 产品/官方来源 | 公开实现与交互 | 优点 | 本项目借鉴/规避 |
|---|---|---|---|
| [Codex：计划与目标](https://developers.openai.com/blog/mastering-codex-remote-for-engineering) | Plan 先提出实施路径；用户检查边界；目标描述完成条件；可检查变更及评论 | 路径、完成条件、代码审阅各有明确入口 | 计划必须同时给范围和验收证据；不以计划写完代替目标完成 |
| [Cursor：Plan Mode](https://cursor.com/blog/plan-mode) | 先研究代码/文档并澄清，再形成带文件路径和引用的可编辑 Markdown 计划，审阅后执行 | 方案可修改、可留在仓库追溯 | 评审表每项链接设计/代码/测试；采用单一当前清单，避免多个总结相互覆盖 |
| [Claude Code：Plan before editing](https://code.claude.com/docs/en/common-workflows#plan-before-editing) | 计划模式读取文件并提出方案，批准后修改 | 将调查与实现分开，便于检查改动边界 | 保留用户确认节点；证据不足明确列待核验，不补造冻结会议或测试结果 |

## 6. 本轮单任务设计方案（2026-10-28 已确认）

**任务名称：阶段 0 / 设计—代码对齐评审与状态基线整理。**

### 6.1 问题与边界

目标是建立可用于下一次选题的可信状态表，解决旧编号冲突、设计冻结冲突和无证据的完成标记。以正文顺序为主线，记录全量需求，但深入对齐优先覆盖已实现 RT 与 SEC 交界，符合手册阶段 0 的首个步骤。

本任务的交付是评审和执行基线文档。接口工作为核对已有契约，不新增产品 API；UI 设计规范不适用于本次文档任务。到实际功能开发前，仍须先确认该功能设计、先提交 API 契约，前端开始前查阅 UI/design Skills 并确认 UI 规范。

### 6.2 已批准的执行顺序

1. 按用户对 C1～C4 的决定统一状态词义、冻结口径与质量门槛；记录确认日期和原话摘要。
2. 逐条对照已实现 Runtime/SEC 的共享字段和调用边界，重写旧接口清单，结论分为一致、实现缺口、规范冲突、缺少验证证据。
3. 给每项完成声明附设计、实现、测试证据及测试日期；将未验收项准确挂回正文所属阶段。
4. 同步执行手册、总基线、索引的状态摘要；修正需求分析中的历史状态说明。CTX-008 先查历史来源，恢复/重建如需改动设计则单列待批准，不夹带功能设计变更。
5. 输出差异清单、冻结建议、未关闭问题和文档验证报告；交付后暂停，等待用户验收该子任务。

发现代码缺陷时记录最小复现和所属任务，不在本次文档对齐中同时开发多个功能。新的契约冲突先提交用户决定。

### 6.3 本轮触达文件

| 文件 | 修改内容 |
|---|---|
| 项目开发执行手册.md | 统一正文编号、完成证据和未验收状态；显式区分历史完成与本轮待验收 |
| docs/design-specs/INDEX.md | 同步 60 项状态、冻结依据和文档完整性标记 |
| docs/design-specs/00-integrated-design-baseline.md | 对齐 Runtime 冻结记录与 Security 待评审状态 |
| docs/design-specs/INTERFACE_ALIGNMENT_CHECKLIST.md | 用有源码定位的核查结果替换已撤回的错误结论 |
| docs/需求分析报告.md | 更新历史状态注记，保留原需求范围 |
| 本评审草案 | 记录用户决策、证据矩阵和交付检查结果 |

已同步规则适配区，正文规则保持不变，门槛决定见第 8 节；冻结 REQ 的共享字段不在本次文档状态修正范围。Runtime/Security 草案如需成为正式冻结文本，必须在用户审阅具体范围后形成决议，不能自动升级版本。

### 6.4 验收条件

- 60 个正式 REQ 唯一、无遗漏；额外 Worker/子设计不重复计数。
- 正文顺序能够唯一确定下一未完成子任务；历史 Task 编号有映射。
- 所有新增“✅ 已完成”均具有完成日期、测试摘要和可定位证据；本子任务在交付确认前保持进行中。
- 设计状态、代码状态、测试状态、用户验收状态分开记录；3 个 Docker 跳过仍明确开放。
- RT 冻结与总基线一致，Security 待审范围明确；未裁定冲突不得写成已解决。
- 文档引用有效；旧勘误、CTX-008 缺口、Web 控制台归属均有明确记录。
- 文档验证完成后交付一次；用户接受后才能勾选该子任务并核定下一项。

## 7. 本轮测试与交付报告

本轮没有修改生产代码、测试源码或 REQ 专项契约。文档修改超过 3 个文件，按迭代规则额外重新运行全量回归，并实测分支覆盖率和 SCA。完整命令、输出哈希、依赖漏洞明细及文档核查结果见[结构化报告](../test-reports/stage0-alignment-2026-10-28.json)。

| 测试项 | 用例 | 结果 | 修复动作 |
|---|---|---|---|
| 文档冒烟 | 手册、索引、基线、分析、接口评审和本记录互相导航 | 通过：60 个正式 ID 唯一，60 项版本逐份核对，341 个本地链接有效 | 同步正文编号；修正旧版本及 REL-008/008A 合写歧义 |
| 文档边界 | designed/frozen、已实现/已测试/用户验收分列 | RT 8 项保留冻结；未冻结 52 项含 CTX-008 缺口；当前子任务仍待验收 | 修正旧“未实现”“全部完成”等汇总 |
| 文档异常路径 | 旧勘误、重复 REQ、缺失原文、无证据完成勾选 | 旧清单重写；CTX-008 Git 历史同样不完整，缺口明确保留 | 去除重复旧表和不实完成标记；未编造缺失原文 |
| 规则边界 | 只改适配区；70%/90%/60% 与指定关键路径 100% 同时保留 | 按用户确认执行 | 安全检查不可用改为待验收，不当作通过 |
| 本轮静态检查 | Ruff 全仓；mypy src | 通过：0 诊断；196 源文件 0 错误 | 无新增代码问题 |
| 本轮全量回归 | 2004 个用例，含冒烟、边界、异常和已有重试/失败回归 | **2001 通过、0 失败、3 跳过**；56.89s，1673 条警告 | 原有通过结果未退化；警告未隐藏 |
| 分支与行覆盖 | pytest-cov --cov-branch | 行 **85.56%**；分支 **73.80%** | 总体门槛满足；指定关键路径全部达标仍未验收，文件级辅助证据见 JSON |
| 真实 Docker 路径 | 3 个容器集成用例 | **未验收**：需显式开关及运行中的 Docker daemon | 保持开放，归属正文 1.3 |
| 实际 SCA | 扫描当前环境 88 个条目，含开发依赖 | **门禁未通过**：6 包 68 条已知漏洞；仅本项目可编辑分发包跳过，其依赖仍被检查 | 初次 strict 与 editable 跳过组合导致收集失败；改为显式跳过项目分发包后完成扫描。漏洞分级/修复归属正文 2.1，本轮未升级依赖 |
| SCA 工具异常 | 缓存写入出现 Windows 跨盘警告 | 扫描仍产出完整 JSON 和漏洞结果，不误记为网络失败或无漏洞 | 保留告警；缓存性能问题后续核验 |
| SAST / Secret Scan | 检测 Semgrep/CodeQL/gitleaks 可执行入口 | **未验收**：工具未安装 | 门禁保持开放，不以 Ruff 代替 |
| 弱网/重试/降级 | 本任务无新增网络执行逻辑；已有失败路径由全量测试复核 | 不新增文档专属网络测试；真实生产故障注入未验收 | 未将现有模拟测试等同真实弱网演练 |
| 接口最小复核 | 非法事件 ID、CDP 请求 TTL、Kill Switch 枚举、缓存 TTL | 实际观察确认 A02/A06/A07/A09 缺口 | 已登记正文归属，未同时开发修复功能 |
| 源码与契约保护 | 比较本轮前后源码/测试/REQ 文件指纹 | 通过：418 个文件完全一致；规则正文在适配区外保持不变 | 无越界改动 |
| 链接/格式复测 | 本地路径、源码行号、Markdown 表格、Git 空白检查 | 通过：341 个本地链接、26 个源码行引用、551 行表格、7 份文档 Git 空白检查 | 移除文档尾空格，修正校验脚本转义与 Windows CRLF 处理后复测通过 |

SCA 包明细：aiohttp 3.11.10（41 条）、opentelemetry-api 1.27.0（1 条）、pyjwt 2.10.1（17 条）、pytest 8.3.3（1 条）、python-dotenv 1.0.1（1 条）、starlette 0.41.3（7 条）。这是扫描器记录数，不能据此声称全部为高危；CVSS 分级、可达性与修复验证未完成。

验证方式：

```powershell
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m mypy src
.venv/Scripts/python.exe -m pytest -q --cov=src --cov-branch
.venv/Scripts/python.exe -m pip_audit --local --skip-editable --format json
```

本轮实际执行将报告写入临时证据目录，未覆盖历史测试报告；路径和 SHA-256 见结构化报告。API 启动继续使用[现有 API 说明](../api/README.md)，本任务没有 API/UI 变更。文档检查可用结构化报告中的 document_verification_script 重现；该脚本是本地本轮证据，不是新增产品测试套件。

本次交付结论：**✅ 评审与状态文档已于 2026-10-28 验收；软件仍有明确未关闭缺口，安全门禁未全通过。** 不因此把阶段 0 整体标记完成。上表及 JSON 中的待验收描述是交付时快照；原测试数字、文件哈希和 `user_acceptance: false` 原样保留，后续验收事件以第 8 节为准。

## 8. 用户决策与验收记录

| 决策 | 日期 | 用户确认及执行结果 |
|---|---|---|
| D1 文档与顺序 | 2026-10-28 | 用户明确《项目开发步骤》就是《项目开发执行手册》，按正文路线图重新核定顺序 |
| D2 本轮方案范围 | 2026-10-28 | 对三点方案回复“确认以上三点”；批准阶段 0 首个对齐评审子任务，交付后等待验收 |
| D3 冻结状态 | 2026-10-28 | 保留 Runtime 八份 2026-10-07 冻结版本；Security 待评审、条件冻结另列建议 |
| D4 质量门槛 | 2026-10-28 | 总体行 ≥70%、核心 ≥90%、分支 ≥60%；指定关键路径 100%；安全扫描未执行不得视为通过 |
| 本次交付验收 | 2026-10-28 | **✅ 交付后用户回复“继续”，据此记录对齐评审文档验收**；下一项仅进入需求、对标与方案确认，尚未批准编码 |

2026-10-29 补充：用户要求“将已完成的任务标记✅”，SEC-007 生命周期切片及依赖/扫描扩展据此 ✅ 验收完成；2026-10-28 全量 2100 通过 / 3 Docker 跳过，SAST/SCA/Secret 通过，见[验收记录](../delivery-reports/sec007-lifecycle-acceptance-2026-10-29.json)。

批准方案与验收交付分别记录。代码和设计字段缺口将在相应功能任务的设计确认后处理；本轮仅记录评审结论，未对 Security 发出新冻结决议。
