# G-CTX 索引与上下文契约核对及实施基线提案

日期：2026-10-29；负责人：`codex-gctx-20261029-01a185f8`。

状态：用户于 2026-10-29 先确认 Q1～Q4，再确认完整 `gctx-review-20261029-r2`（§10～14）。批准记录见 §9、交付见 §15。已领取 implementation 并按锁内登记范围同步源契约和引用；未修改生产代码、正式测试或冻结 Runtime 字段。限定文档基线批准不等于整项 REQ 冻结或产品实现验收。

## 1. 目标、来源与现状

目标是让 C-INDEX、C-SEARCH、C-SELECT、C-EVAL 和 H-SDK 能在明确版本、授权及错误语义的条件下独立实施，并在 M3/M4 使用真实组件汇合。依据执行手册依赖驱动章节及[需求分析报告](../../需求分析报告.md) §5.7，先复用专项设计，不重新设计整套检索平台。

| 需求 | 源文档 | 已有约束 / 核对结论 |
|---|---|---|
| CTX-001 | [实体](../../design-specs/REQ-CTX-001-index-entities-schema.md) §3、5 | v0.1-designed；FileNode、SymbolNode、DependencyNode、RelationEdge、IndexMetadata 及版本坐标 |
| CTX-002 | [语言及基准](../../design-specs/REQ-CTX-002-language-repository-scale-benchmark.md) §3～6 | v0.1-designed；语言分级、仓库规模、固定基准；不等于实测达标 |
| CTX-003 | [解析](../../design-specs/REQ-CTX-003-ast-lsp-dependency-parsing.md) §3～9 | v0.1-designed；AST/LSP、直接及一层传递依赖、循环检测和增量更新 |
| CTX-004 | [混合检索](../../design-specs/REQ-CTX-004-hybrid-retrieval-ranking.md) §4、7 | v0.1-designed；BM25/向量/图及 RRF；与 CTX-001 同名结构不同 |
| CTX-005 | [授权](../../design-specs/REQ-CTX-005-retrieval-permissions-sensitive-paths.md) §3～5 | 文档 v1.0、已设计，不能据此认为已冻结；预过滤及三级敏感路径 |
| CTX-006 | [选择器](../../design-specs/REQ-CTX-006-context-selector-budget.md) §4～6 | 任务类别、候选项、预算配置和 permission_context；需补全跨模块映射 |
| CTX-007 | [增量一致性](../../design-specs/REQ-CTX-007-incremental-index-consistency.md) §3、6 | v0.1-designed；Git SHA 绑定、MVCC、任务级索引锁定及回退 |
| CTX-008 | [压缩原文](../../design-specs/REQ-CTX-008-context-compression-tiered-loading.md) §5.2～16 | 开头缺失；不能声明完整或冻结 |
| CTX-009 | [检索评测](../../design-specs/REQ-CTX-009-retrieval-evaluation.md) §4、7、11 | v0.1-designed；独立离线、安全、端到端及回归评测 |
| HAR-002 | [对话压缩](../../design-specs/REQ-HAR-002-context-compaction.md) §3 | v0.1-designed；70%/85%/95%，工具调用对完整性和快照 |

代码核对：`rg --files src` 未发现 CTX 索引、混合检索、选择器或压缩服务包；`src/workers/react_loop/models.py` 的 Observation.context_summary 和 remaining_budget 只是观察数据字段，不能视为上述功能实现。`src/runtime/trace/context.py` 与 `src/observability/context.py` 是追踪上下文，不是代码检索。此结论限于当前工作树的路径及符号检查，不宣称穷尽所有间接能力。

## 2. 官方对标（2026-10-29 查阅）

| 来源与已验证事实 | 优点 | 本项目建议（推断，待基线批准） |
|---|---|---|
| [Cursor Ignore files](https://prod.cursor.com/help/customization/ignore-files)：忽略规则控制 AI 上下文；终端与 MCP 可在该文件控制之外读取 | 清晰区分上下文过滤和执行工具边界 | 路径过滤不能代替 Policy Gateway；按调用路径独立鉴权 |
| [Sourcegraph precise navigation](https://sourcegraph.com/docs/code-navigation/precise-code-navigation)：SCIP 是语言无关索引协议，支持精确代码导航 | 索引器与消费端通过显式协议协作 | 明确符号标识、位置和索引版本，避免解析器私有类型泄漏到消费端 |

没有验证 Cursor 当前检索内部架构、厂商具体存储引擎或各产品准确率。原 REQ 中关于 DeepSeek、Kimi、通义灵码等内部实现及收益数字不作为本次已验证事实。无需前端开发，本次不涉及 UI Skill 或新增 UI 规范。

## 3. CTX-008 完整性调查

当前原文共 494 行，第一行是 `└── 成本：本地计算`，第二行是代码围栏；直接进入 §5.2，无标题、版本头及 §1～5.1 完整内容。

`git log --all --format=%H -- docs/design-specs/REQ-CTX-008-context-compression-tiered-loading.md` 在本地可见历史仅找到 `6f506aa`（唯一可解析的短 Git 提交 ID），`git show` 中同样为 494 行及相同缺失开头。仓库内另有[完成摘要](../../design-specs/REQ-CTX-008-COMPLETION-SUMMARY.md)，其中列出三级阈值、分层压缩、快照等要点，但不是原始完整 Schema，不能用摘要伪装恢复原文。未访问远端或不可见历史。

恢复提案：保留原文，先在任务专属材料中补拟目标/输入输出/错误/阈值章节，逐条注明来源与新增建议；用户确认后，另按 REQ 变更纪律补入正式文件。当前写入范围不包含源 REQ，故本次没有“补齐”原文。

## 4. 接口映射与数据边界

以下是源设计的消费关系和待确认适配建议；不把同名 TypeScript 伪代码视为可直接共用的已编译接口。

| 边界 | 输入 | 输出 / 不变量 | 调用方 |
|---|---|---|---|
| 解析 → 索引 | repository_id、不可变 source_revision、规范化相对路径、文件内容及解析器配置 | File/Symbol/Dependency/Relation；file_hash 对应实际内容；有 embedding 时记录模型 | C-INDEX |
| 索引 → 检索 | schema_version、repository_id、source_revision、index_version、indexed_at | 查询绑定同一已验证索引快照；不混入新版本符号 | C-SEARCH、C-EVAL |
| 检索入口 | CTX-001 RetrievalQuery 的 query_text、模式、filters、top_k；CTX-004 的配置和身份信息另行映射 | CTX-001 chunks/score/sources 与 CTX-004 items/fusion_score/recall_info 不能隐式替换 | C-SEARCH、C-SELECT |
| 检索 → 选择器 | ContextSelectorInput：task_context、retrieval_candidates、budget_config、permission_context | selected_context、statistics、selection_reasons、warnings、trace_id | C-SELECT、Worker |
| 选择器 → 符号压缩 | 已授权候选、任务类别、Token 压力、版本坐标 | SymbolCompressionResult 的 l1_summary/l2_context/l3_markers；引用仍绑定原版本 | C-SELECT |
| CTX → HAR | queryHAR002Status、notifyCompressionPending、delegateToHAR002、完成回调 | 历史压力委托 HAR，检索压力由 CTX 处理；两者兼有先 HAR 后 CTX | H-SDK |
| 评测 | EvaluationTask：task_id、task_type、dataset_id、repository_scope、config、schedule、用户/组织 | EvaluationReport；固定数据、配置与版本，可复现指标及失败 | C-EVAL、G-EVA 消费者 |

提议在模块外层增加经批准的适配器，不就地修改源字段：保留两种结果 DTO；`items[].chunk_id` 对应 `chunks[].chunk_id`，融合分映射至 score，召回路名映射至 sources。total_candidates 是候选数，total_hits 语义未对齐，不能直接复制。索引版本从绑定快照取得，不能从当前最新索引猜测。授权身份必须由可信请求上下文提供，不能相信模型提交的 organization_id。适配具体 Schema、缺失字段及错误码需与 G-RT/G-SEC 消费方核对后确认。

路径应在解析、检索及按需加载边界规范化并限制仓库根目录；拒绝越界和符号链接逃逸。索引/缓存/快照键必须包含租户、仓库与版本，权限变化须失效或重新校验；L3 按需读取不能绕过初次检索授权。上述为安全实施建议，不是新增已冻结字段。

## 5. 状态、异常、并发和兼容

源 IndexState：pending、building、validating、active、stale、archived、failed。构建产物经验证再发布，读取固定快照；构建失败不能替换 active 指针。任务锁定索引，回退只选择与声明代码版本一致的可用快照；无可用快照时不得悄悄返回其他 revision。具体事务/CAS 与存储实现由 C-INDEX 方案确认。

Merkle 示例按旧 children 数组位置遍历，需补验新增、删除、改名及重排；不能将伪代码直接作为增量完整性证明。`index_version` 是构建标识，`source_revision` 是 Git SHA，重建同 SHA 的绑定/唯一性需澄清 CTX-007 的“一对一”含义。

| 条件 | 必须响应 / 提议语义 | 重试与降级边界 |
|---|---|---|
| 缺失租户、无权限或授权服务超时 | DENY；不返回片段、路径或跨租户计数 | 不重试权限拒绝；服务故障不放宽授权 |
| 规则服务或配置加载失败 | 用户已确认拒绝该次检索，见 §9 | 不以仅基线规则继续放行；源 REQ 待受控同步 |
| 单路召回超时 | 有界截止时间，记录失败路及降级原因 | 只有授权完整的剩余路可以形成降级结果；不能声称完整三路成功 |
| 所有召回失败 / revision 不可用 | 明确失败，与合法空结果区分 | 不以空数组冒充成功；不得无上限重试 |
| Token 超限、压缩失败 | 采用显式降级/拒绝；保留系统约束、审批事实和完整工具调用对 | 不为继续运行截掉安全约束；HAR/CTX 协调防重入 |
| 取消 / 快照校验失败 | 终止本次产出；不发布部分状态或加载损坏快照 | 引用原始快照恢复须重新鉴权 |

沿用 CTX-004 §7 的 RET-* 和其他源专项错误定义，不在本材料分配新生产错误码。输入 top_k、候选数、图遍历深度、Token 预算、请求及模型超时都需要明确有限上界；数值及错误映射未获确认前不由调用方各自发明。复用现有 trace_id，审计不记录密钥或未经脱敏查询内容。Schema 演进采用 Expand/Contract，不能重命名或删除既有冻结 Runtime 字段。

## 6. 首轮实质性事项（已由用户确认建议，保留发现记录）

| 编号 | 证据与影响 | 建议决定 |
|---|---|---|
| Q1 | CTX-008 原文及唯一可见历史都缺失开头，CompressionRequest/Result/LayerMarker 等缺完整定义；阻塞 C-SELECT/HAR 生产契约 | 允许先在本专属文档重建缺失章节供再次确认，随后走源 REQ 变更；或提供可信完整原文 |
| Q2 | CTX-005 §3.2 第 136 行规定规则加载失败“仅应用 Level 1 基线”；执行手册/安全规则要求默认拒绝，组织/项目禁区可能泄漏 | 规则加载失败一律拒绝该次检索，不采用仅基线放行；需明确批准源契约修订及影响评审 |
| Q3 | CTX-001 §5 使用 chunks/total_hits，CTX-004 §4 使用 items/total_candidates；默认返回量也不同 | 保留源 DTO，确认显式适配方案，不把总候选数映射成授权命中数；后续确认完整字段表 |
| Q4 | CTX-008 §14.1 为 70/80/95%，HAR-002 §3.1 为 70/85/95%；职责不同但协作时容易重复触发 | 保留各自阈值，CTX 负责检索/符号、HAR 负责对话，协调去重；不擅自统一数值 |

CTX-005 使用 Rust/Qdrant/Elasticsearch/Neo4j 示例，手册技术栈为 Python/PostgreSQL/pgvector；本次按手册处理语言与实现方向，相关示例不构成引入新生产依赖的授权。存储选型及性能必须后续实验验证。

## 7. 验收标准与固定验证用例

以下是待实施验收清单，不是已经运行的测试。固定仓库 fixture 建议含两个租户、各一个仓库、两个 revision、普通文件/敏感文件、两级调用和循环引用；fixture 标识仅用测试值，不引入正式需求字段。

| 编号 | 触发条件 → 必须响应 | 证据要求 / 责任 |
|---|---|---|
| T01 | 同 revision 重复解析 → 文件哈希、符号关系可重现 | 解析版本和固定输入输出；C-INDEX |
| T02 | 新增/删除/改名/子树重排 → 增量结果等价全量结果 | 差异集与双份索引比较；C-INDEX |
| T03 | 构建中并发读取、构建失败 → 老任务始终见完整原快照 | 故障注入及版本轨迹；C-INDEX |
| T04 | 两租户相同 query/chunk_id → 不跨租户读取或缓存命中 | 权限/缓存/计数/日志检查；C-SEARCH |
| T05 | 组织禁区加载失败 → 按 Q2 已确认规则拒绝 | 权限依赖故障注入；C-SEARCH |
| T06 | 查询 .env、路径越界及 L3 二次加载 → 不暴露内容或路径 | 原始结果和脱敏审计；C-SEARCH/C-SELECT |
| T07 | 固定三路候选 → RRF 排名可复算、DTO 不丢版本 | 配置、候选分和预期名次；C-SEARCH |
| T08 | 单路超时/全路失败/合法空集 → 三种结果可区分 | 有界超时、取消与降级记录；C-SEARCH |
| T09 | Token 恰在阈值上下、预算不足 → 不超预算，保留安全信息和完整调用对 | Tokenizer 版本及边界输出；C-SELECT/H-SDK |
| T10 | HAR 已压缩/重复回调/快照损坏 → 无重入和重复发布，不用损坏状态恢复 | 协调状态及校验失败证据；C-SELECT/H-SDK |
| T11 | 固定相关集和排名 → Recall/MRR/NDCG 可独立复算 | 指标定义、k、零相关项处理、数据集版本；C-EVAL |
| T12 | 接入真实解析/索引/授权/Worker → 完成检索到任务正确率验证 | M3/M4 集成，替身通过不能代替 |

已有源目标：CTX-004 Recall@20 >85%、Precision@5 >75%、MRR >0.70、p95 <500ms；性能数值是验收目标，不是本次实测。报告必须说明硬件、数据规模、请求数、冷热缓存、并发、失败/降级比例与分位算法。能力评估和回归分开报告，能力上升不抵消回归下降；血缘和语言规模分层遵循 G-EVA 批准契约。

## 8. 本次检查报告及继续方式

| 测试项 | 用例 / 方法 | 结果 | 修复动作 / 剩余事项 |
|---|---|---|---|
| 占用互斥 | G-EVA claim 遇他人占用；随后领取 G-CTX | 前者拒绝、后者成功 | 未写 G-EVA 文件 |
| 完整性 | 当前 CTX-008 与 git log/show 比较 | 发现缺失，历史不能恢复 | Q1 决策后补拟，未改原文 |
| 契约一致性 | CTX-001/004、CTX-005 与安全规则、HAR-002 对读 | 发现 Q2～Q4 | 提交影响和建议，未自行裁决 |
| 本地引用 | 检查本文件 12 个相对 Markdown 路径 | 初检 1 个失效，修正 CTX-006 文件名后复测 12/12 通过 | 无剩余失效本地引用 |
| 生产测试、覆盖率、SAST/SCA/Secret、性能及真实集成 | 本次仅文档核对，未运行 | 未执行，不报告通过 | 生产实现及里程碑阶段执行对应门禁 |

复核命令：`python -X utf8 scripts/task_board.py show G-CTX`；完整性使用 §3 的 git 命令；引用检查以本文件父目录解析所有相对链接。无需启动新服务，无依赖安装。

台账检查：`python -X utf8 scripts/task_board.py validate` 通过，62 项任务，依赖无环；这只验证台账结构，不代表任何产品功能通过。

首轮停点：等待 Q1～Q4；现已收到用户确认，后续工作见 §9～14。G-CTX 未获整包验收，不解锁下游 implementation 硬依赖。其他独立工作包继续按实时台账领取。

## 9. 用户决策及本轮边界

真实确认定位：本聊天上一答复请求确认四项建议，紧接的用户消息为“确认”（2026-10-29）。该确认批准下列原则，不解释为本次尚未呈现的完整 Schema 已批准，也不作为整项需求或工作包验收。

| 决策 | 已确认内容 | 本次落实 |
|---|---|---|
| Q1 | 在专属方案中重建 CTX-008 缺失章节，再提交确认 | §10；所有补拟字段标为提案，保留原文及历史证据 |
| Q2 | 敏感路径规则加载失败时拒绝本次检索 | §12 的规则故障、缓存及二次加载边界 |
| Q3 | 保留两种检索结果，通过显式适配衔接 | §11 逐字段映射、分页及计数语义 |
| Q4 | 保留 CTX/HAR 各自阈值，协调避免重复触发 | §10.3 协作状态机及版本冲突处理 |

本次文档基线标识为 `gctx-review-20261029-r2`（评审标识，不是 Runtime Schema 版本）。G-CTX 的实现模式原本只授权契约材料；现通过脚本 release/claim 转为设计模式，随后 submit-design。没有把确认冒充 approve-design 或 accept 事件。

## 10. CTX-008 缺失章节补拟（供确认，不声称恢复原文）

### 10.1 目标和来源

补拟 §1～5.1 的最小内容：在有限模型窗口内保留任务约束、决策及可验证引用，对文件/符号上下文执行分层压缩，并与 HAR 对话压缩协调。来源为 CTX-008 留存 §6～16、完成摘要及 HAR-002；原文缺失的类型完整性、限额和并发字段是本轮设计建议。

覆盖六种已存在任务类型：BUG_FIX、FEATURE_DEVELOPMENT、REFACTORING、CODE_REVIEW、UNIT_TEST、DOCUMENTATION。保留原文 §5.2 的任务优先级矩阵。MVP 不引入自主压缩决策、动态阈值、学习模型或长期记忆，也不为本提案增加生产依赖。

### 10.2 输入、输出和引用

下表中“提案”字段为本次补拟；现有 DTO 保持原名与字段，补拟对象位于适配/协调层。标识复用 Runtime 的真实坐标，禁止以 org 代替 project 或以 workflow 代替 task。

| 对象 | 字段与类型 | 约束及来源 |
|---|---|---|
| CompressionScope（提案） | organization_id、project_id、repository_id、task_id、workflow_id、worker_id?: string；source_revision、index_version: string | 请求上下文经授权后注入；索引与代码版本匹配；不扩改冻结 Runtime 实体 |
| ContextRevision（提案） | context_version: integer；scope: CompressionScope | context_version ≥0，协调层维护的上下文递增版本，不等同事件 sequence |
| CompressionRequest（补拟） | request_id、trace_id: string；base: ContextRevision；task_type: 六类枚举；trigger: pressure/overflow/manual；context_tokens、max_context_tokens、reserved_output_tokens、reserved_tool_tokens: integer；tokenizer_version: string；items: ContextItem[] | 均必填；计数非负，max_context_tokens >0；保留预算和必须小于窗口；request_id 为关联标识，不作为新的幂等键生成规则 |
| ContextItem（提案） | item_id: string；kind: system/constraint/decision/tool_pair/symbol/document；content: string；required: boolean；estimated_tokens: integer；source_refs: SourceRef[] | required 项不可自动丢弃；system/constraint/审批决定强制 required；tool_pair 是完整调用及结果单元，不按消息数拆开 |
| SourceRef（提案） | file_id、file_path、file_hash: string；symbol_id?: string；range: CTX-001.SourceRange；source_revision、index_version: string | 规范化相对路径；哈希与绑定快照一致；符号可选，文件引用不可缺；SourceRange 先原样透传，不擅改行列起点 |
| LayerMarker（补拟） | marker_id: string；source: SourceRef；target_layer: L2/L3；estimated_tokens: integer | marker 不是授权令牌；展开必须按当前权限重新检查，revision 不可替换成 latest |
| CompressionResult（补拟） | request_id、trace_id: string；base_context_version: integer；committed_context_version?: integer；outcome: success/partial/skipped/failed/cancelled；before_tokens、after_tokens: integer；items: ContextItem[]；layers: SymbolCompressionResult；snapshot_ref?: string；warnings: string[]；failure_kind?: string | success/partial 只有 CAS 发布成功后才带 committed_context_version；其他结果不得更新权威上下文；失败/取消返回空 items，旧上下文由调用方保留 |

SymbolCompressionResult 继续沿用原文的 l1_summary、l2_context、l3_markers；源示例的 `estimated_tokens: 50/200` 是估计示意，不作为精确计数或固定字面量类型。提案将实际估计置于运行时计数，使用 tokenizer_version 复算，实际总 Token 不得超过可用输入预算。

每个请求必须在服务端授权范围内取材；模型生成的摘要仅为不可信派生数据，不能覆盖系统约束、审批事实或产生新权限。输入包含必须保留但已无权访问的内容时拒绝请求，不以压缩方式继续传播。

### 10.3 触发、分层和 HAR 协作

压力定义提案：`usable = max_context_tokens - reserved_output_tokens - reserved_tool_tokens`；`pressure = context_tokens / usable`。usable ≤0 为非法输入。CTX 阈值保持 70%/80%/95%，HAR 保持 70%/85%/95%；两者统一使用该请求记录的预算坐标，避免一个含输出预留、另一个不含预留的隐式误差。阈值使用整数比较：`100 * context_tokens >= threshold_pct * usable`。

| CTX 条件 | 必须响应 |
|---|---|
| pressure <70% | 不自动压缩；手动请求仍允许按授权执行 |
| 70% ≤ pressure <80% | 只产生压力提示，不自动修改上下文 |
| 80% ≤ pressure <95% | 在工具调用边界安排常规压缩 |
| pressure ≥95% 或 overflow | 优先压缩，停止继续向模型派发超预算输入；仍不得截断活跃工具调用对 |

压缩流水线沿用 L0 清理 → L1 摘要 → L2 符号。此处流水线等级与展示层级 L1/L2/L3 是两套概念：展示层 L1 是摘要、L2 是定义与依赖、L3 是完整代码的按需引用。先去除确证冗余，再选择可压缩非 required 项；保留项自身超预算时返回 failed，不能删除安全约束硬凑成功。预览使用相同输入/版本/配置，只返回估计变更和风险，不写快照或发布状态；实际执行重新校验权限、预算与版本。

协调状态机提案：`IDLE → WAITING_BOUNDARY → HAR_RUNNING（如需）→ CTX_RUNNING（如需）→ VALIDATING → COMMITTED`；任一步失败或取消进入 FAILED/CANCELLED，释放本次租约并保留旧版本。仅有历史压力时委托 HAR；仅检索压力时由 CTX 处理；混合压力先 HAR 后重新测量，只有仍需压缩时执行 CTX。

协调层每个 `(organization_id, task_id, workflow_id)` 同时一个压缩操作，使用存储租约和 fencing token；最终提交以 context_version 做 CAS。收到已过期租约/旧版本回调、重复完成回调或取消后的回调时不发布内容；返回重复/版本冲突诊断。context_version 未变化的重复请求复用既有终态结果；内容变化必须重新评估。真正持久化写操作沿用 RT-007/REL-006 的已批准逻辑意图、首次派发前持久化及重试复用规则，本材料不定义替代幂等算法。

五分钟冷却沿用原文用于抑制常规重复压缩；不允许因冷却把超过窗口的输入交给模型，紧急时无法安全压缩即停止并返回明确失败。HAR 的 active_tool_calls 不为空时先等边界，在截止时间前未完成则返回 skipped，不截断、不强行取消外部工具。

### 10.4 快照、限额及异常

沿用 CTX-008 原文 §8 的 summary、preserved_decisions/context/constraints、original_messages_ref、checksum、created_at、expires_at 等语义。快照是应用层恢复资产，不能当成 RT-005 WorkflowCheckpoint 本体；与 Runtime 快照使用 asset 引用关联。storage_path 只保留服务内部，外部返回授权校验后的 snapshot_ref，不能返回可任意读取的路径。

提案：校验和覆盖完整语义载荷（含保留约束、源引用、版本和租户范围），采用明确的 canonical JSON/UTF-8 序列化和 SHA-256；原示例只摘要部分字段，不能证明全载荷防篡改。SHA-256 用于完整性比对，可信摘要存储与写权限仍须隔离，不能把无密钥哈希宣称为攻击者可写存储中的真实性证明。原文 90 天为保留目标，不能覆盖安全删除和冻结 RT 留存规则；实际生效期限受批准的资源留存策略约束。

| 限额/异常 | 基线候选规则（新增限额为提案） |
|---|---|
| 候选/负载 | 每次最多 1000 项、总 UTF-8 内容最多 8 MiB；超限拒绝，不先无界加载后裁剪 |
| 请求期限 | 服务端端到端最多 10s；调用方可缩短；模型/存储使用剩余期限，取消信号传播；本切片远程失败不自动重试 |
| 质量验证 | 必需项和工具对完整、版本一致、Token 不超预算才可提交；LLM 摘要不作授权依据 |
| 快照失败 | 默认拒绝破坏性替换；仅可返回不提交的预览或保留完整原始材料的可逆展示结果，不报告可恢复快照成功 |
| 摘要失败 | 模板化安全提取后仍需全部验证；失败即拒绝发布，不按“最后 N 条”任意截断 |
| 失效/缺失 marker | 重新按固定 revision 定位并验 hash；无法验证即明确失败，不回退最新代码 |
| 状态持久化或审计失败 | 不宣称提交成功；状态与必需审计采用事务/outbox，交由实现方案落实，不把异步 best-effort 日志当作完成证据 |

错误用 failure_kind 记录语义分类：INVALID_INPUT、ACCESS_DENIED、RULES_UNAVAILABLE、REVISION_UNAVAILABLE、VERSION_CONFLICT、DEADLINE_EXCEEDED、INTEGRITY_FAILURE、BUDGET_UNSATISFIABLE、DEPENDENCY_FAILURE。它们是待确认协调层分类，不是新增 HTTP/RET-* 枚举；HTTP/API 映射由实施方案对齐 G-SEC/G-WEB。

## 11. 检索 DTO 显式适配提案

两种源结果结构以模块命名空间区分为 CTX001.RetrievalResult / CTX004.RetrievalResult，不修改源字段。适配器另接 trusted scope、bound index snapshot、授权后 chunk 元数据和 tokenizer 配置，不能仅凭 CTX004 的未完整定义 CodeChunk 猜测文件信息。

| CTX001 目标字段 | 明确来源 | 拒绝/兼容规则 |
|---|---|---|
| chunks[].chunk_id | CTX004.items[].chunk_id | 相同快照去重；顺序保持融合排名 |
| file_id / file_path / range | 固定 index_version 中该 chunk 的已授权元数据 | 缺失、hash 或 revision 不符则适配失败；禁止从自然语言推断 |
| content | 已校验元数据对应片段正文 | 不是完整 CodeChunk 对象的 JSON 字符串 |
| score | fusion_score | 原值透传，不伪装成概率或 relevance_score；排序不重新归一化 |
| sources | recall_info 中具有有效正整数 rank 的 bm25/vector/graph 路名 | 固定路名顺序；分数缺失可保留，rank 非法拒绝，不虚构未成功召回路 |
| estimated_tokens | 绑定 tokenizer 对正文估计 | 非负整数，不使用字符数充当 Token |
| symbols / related_symbols | 同一索引快照的授权符号结果 | 无来源则省略，不用空假对象补齐 |
| index_version | bound snapshot.index_version | source_revision / repository_id 与源结果不匹配则拒绝 |
| retrieval_latency_ms | 从请求进入到完成检索适配的单调时钟计时 | 不能从未定义的 metrics 字段猜读；含适配开销 |
| total_hits | 当前授权范围中、去重后且裁剪/分页前的匹配 chunk 数 | 候选窗口模式下仅统计有限候选全集，需在外层显式标记，不宣称全库精确总数 |
| query_embedding | 经允许向量路的查询 embedding | 无可用或不允许外传时省略 |
| source_distribution | 返回 chunks 中按 sources 统计 | 多路命中可以重复计入不同路，总和可大于 chunks 数 |

适配外层（提案）携带 query_id、repository_id、source_revision、index_version、page、page_size、count_scope=`bounded_candidates`、complete、failed_sources 和可选 next_cursor；原 DTO 保留在 payload 中。`complete` 只表示指定配置的召回路是否全部完成，不表示穷尽全库。total_candidates 保留在 CTX004 DTO，不传成 total_hits；外部错误不返回被过滤资源的路径和计数。

请求侧规则：CTX001 入口省略 top_k 时默认 10，CTX004 入口省略 final_top_k 时默认 20；显式 top_k 转成 final_top_k，不能两处默认叠加。建议返回量范围 1～100，每路召回上限 100、合并去重候选上限 300；graph.max_depth 范围 0～2、max_breadth 范围 1～10，并限制总访问节点 1000。这些新增上限是本次基线候选，不是既有性能证明。

LEXICAL/SEMANTIC/GRAPH 仅开启对应路；HYBRID 按显式配置启用；SYMBOL 需要精确符号查询入口，禁止静默当 GRAPH 或 LEXICAL。本次没有已实现的 SYMBOL 查询能力，C-SEARCH 方案需落实该入口及精确/模糊匹配规则。默认 latest 只在可信入口解析一次为具体 SHA/index_version，再传入后续所有阶段。

分页在固定的有限候选快照上进行，按融合分降序、chunk_id 升序稳定排序；cursor 绑定租户、查询配置摘要及索引版本，不能用 cursor 提供越权范围。建议候选快照 TTL 为 5 分钟；过期返回明确失效，重新查询不能续用旧页号。权限变化重新校验；不能继续使用撤销前缓存读取结果。适配器只读，不触发外部写入。

## 12. 安全修订影响与迁移清单

Q2 的原则已确认；正式 REQ 待按变更纪律同步，本文件给出受控修改清单供后续领取，当前不越过专属文档写入范围。

| 受影响边界 | 修订与兼容影响 | 验证要求 |
|---|---|---|
| CTX-005 §3.2 | 将规则加载失败“仅应用 Level 1 基线”改成 DENY；会使配置故障时的原可用查询失败，属于有意收紧 | Level 1/2/3 任一所需规则缺失都不调用召回后端 |
| CTX-006 权限缓存及选择器 | 缓存不能恢复绕过失败的规则；完整策略版本/撤销有效性不可证明时 DENY | 规则故障 + 旧正向授权缓存不能放行 |
| CTX-004 检索和 marker 展开 | 每路检索前都应用相同授权/规则快照；L3 展开重新检查 | 超时、旧 cursor、权限撤销和跨租户标记均拒绝 |
| CTX-008 §9 降级 | “最后 20/5 条”仅是源示例，不能丢掉约束、审批事实或调用配对；不具备恢复依据时不能声称快照可恢复 | 必须项超预算、活跃调用对、存储故障验证 |
| HAR-002/G-HAR | 对话压缩门限维持 85%，通过协调层避免双写 | 混合压力、重复回调、租约过期和取消的 CAS 用例 |
| G-RT/R-CHECK | 应用压缩资产引用 Runtime Checkpoint，不改冻结 Schema | 恢复时哈希/版本/授权均通过；source_event_sequence 不由 context_version 代替 |
| G-EVA/C-EVAL | 分开报告召回不完整、合法空集、访问拒绝及基础设施失败 | 指标分母和失败比例可复核，不能排除超时后宣称达标 |

规则缓存只允许在完整性、版本和当前授权有效性均可验证时作为规则来源；规则加载已报错或失效则本次拒绝，不能 fallback 到旧规则掩盖错误。组织/项目规则显式配置为空且成功加载，与加载失败是不同状态。审计只记录可公开错误、trace_id、策略版本及授权范围摘要；不记录敏感正文、原始 query 或隐藏资源计数。

源同步顺序建议：登记既有 CTX-005/008 的变更记录（不新增正式需求编号）→ 检查所有调用引用 → 在台账锁内扩展/拆分精确写入范围并检查占用 → 更新源 REQ 与受影响引用 → 交叉核对 → 验收本契约工作包。生产方案和依赖批准仍属于 C-*、G-HAR/G-SEC 等各自工作包，不自动由本文件解除。

## 13. 可复算样例与文档验证

以下样例用于检查提案内部一致性，不是生产服务测试。检索融合示例：BM25 为 A,B，vector 为 B,A，graph 为空；RRF k=60 时 A、B 均为 `1/61+1/62`，按 chunk_id 取 A 再 B。授权后有限候选 A、B，分页大小 1，第一页 chunks=[A]、total_hits=2、count_scope=bounded_candidates；不能把原始未授权候选数写入 total_hits。第一页 A 同时来自两路，source_distribution 为 bm25:1、vector:1。

预算示例：窗口 12000、输出预留 1000、工具预留 1000，可用输入 10000。6999 不提示，7000 提示，7999 仍只提示，8000 开始 CTX 常规压缩，8499 不触发 HAR 常规压缩，8500 触发 HAR，9500 进入紧急协调。9500 时若 required 内容本身 10001，则拒绝发布，不截断 required 项。

版本示例：请求以 context_version=7 开始；HAR 提交 8 后 CTX 必须基于 8 重算；旧版本 7 的回调不覆盖 8。同 revision 重建可以有不同 index_version，每个 index_version 只能绑定一个 source_revision；这是对“一对一”歧义的本次澄清建议，消费者固定完整坐标，不以 SHA 当唯一构建标识。

| 检查项 | 用例 | 本轮结果 | 修复/剩余 |
|---|---|---|---|
| 文档结构 | 本地引用、围栏配对、§9～14 存在 | 12/12 本地引用有效；无代码围栏；六节均存在 | 不能替代 Schema 编译或产品测试 |
| 预算/阈值 | 7 个阈值边界及 1 个不可满足预算，共 8 例 | 独立算术脚本复算 8/8 通过 | 不调用生产代码，不宣称服务行为通过 |
| 融合/计数 | 双路并列、分页及多路来源分布 | 精确分数均为 123/3782；排序 A/B；命中 2、页大小 1、来源计数合计 2 | 算术断言通过，适配器尚未实现 |
| 并发方案 | 版本 7/8、重复回调、取消、租约 fencing | 设计走查 | 待真实存储并发测试 |
| 安全/恢复 | 规则失败、撤销、快照篡改、审计失败 | 设计走查，运行测试未执行 | 待 C-SEARCH/C-SELECT/H-SDK 集成 |

验证环境：仓库根目录通过 `python -X utf8 -` 执行标准库 pathlib/re/Fraction 独立脚本；未安装依赖。`scripts/task_board.py validate` 再次通过（62 项、依赖无环）。本次路径状态检查只显示本专属文档未跟踪，CTX-005/008 源文件无本次修改。SAST/SCA/Secret、生产测试与覆盖率均未执行；本轮只验证文档和样例算术，不报告生产门禁通过。

## 14. 本轮交付和后续准入

本轮交付：Q1～Q4 确认记录、CTX-008 缺失输入输出补拟、阈值与协调状态机、检索适配字段表、安全收紧影响清单及可复算样例。新增字段、限额、计数范围、快照安全和协调规则需作为 `gctx-review-20261029-r2` 完整候选基线确认；不重复询问 Q1～Q4 原则。

确认对象限定为本专属方案，不等同 CTX-001～009/HAR-002 全项冻结或产品验收。下一实施步骤是按台账登记源文档同步范围、落实变更记录并验收契约工作包；随后下游分别满足硬依赖及自身方案确认后再编写生产代码。未获本轮具体方案确认前不改源 REQ、生产代码或正式测试。


## 15. r2 批准后的源同步交付（2026-10-29）

### 15.1 确认、范围与变更

真实批准定位：本聊天上一答复明确请求确认“新增具体方案 gctx-review-20261029-r2，之后推进源契约同步”，用户紧接回复“确认”。已通过 approve-design 留存真实证据；经台账锁内重读与占用检查扩展源文件范围，再 claim implementation。未自行执行 accept。

| 源文档 | 本次版本与变化 |
|---|---|
| CTX-001 | v0.2-designed；保留源 DTO，明确 total_hits、计数范围、top_k 及版本适配 |
| CTX-004 | v0.2-designed；候选量/返回量/图遍历边界、分页及双 DTO 映射 |
| CTX-005 | v1.1-designed；规则失败 DENY、禁止仅基线或旧缓存放行 |
| CTX-006 | v0.2-designed；授权缓存边界、可用预算、完整工具对和协作引用 |
| CTX-007 | v0.2-designed；构建版本单向绑定代码 SHA、同 SHA 可重建、Merkle 新增/删除/重排检查 |
| CTX-008 | v0.2-designed；重建 §1～5.1、输入输出及异常、修订不安全降级，保留旧示例并标出适用限制 |
| HAR-002 | v0.2-designed；独立阈值、fencing/CAS、工具边界、快照与 Runtime 资产关系 |
| 统一基线 / 主题总览 / INDEX / PENDING | 仅同步相关版本、安全规则及重建状态；统一基线 v1.8→v1.9，其余引用修订 r1；保留其他会话既有改动及未涉及模块历史统计 |

没有新增需求编号、修改正式需求总数、增加依赖或修改生产代码。源文件显式引用本批准方案作为涉及条款的现行修订，其余未涉及要求保留。上文 §1、§3、§6、§8 是首轮读取/问题发现记录，其中旧版本和“开头缺失”描述应按本节判断当前状态。

### 15.2 引用影响复核

`rg -l 'CTX-008|CTX-005|HAR-002' docs/design-specs -g '*.md'` 命中 30 份文档。已同步本次七份源文档及四份现行导航/总览中需要变更的内容。其他命中按引用关系复核：CTX-002/003/009 依赖仍指向原文件、无需换接口名；Runtime/REL/SEC 冻结字段和职责不变；G03 等接口参考及组件边界保留职责关系；完成摘要/历史评审保留原日期证据，不重写为新验收结果。厂商历史示例和旧伪代码不作为生产能力证明。

执行手册、需求分析等仍有本轮之前的完整性状态快照；执行手册及调度文件被 DOC-ROUTE 待验收任务占用，本次不修改。实时 G-CTX 状态以台账和本节为准；后续整体汇总由治理范围负责人或完成授权交接的会话更新，不能覆盖其未提交成果。

### 15.3 检查记录

以下检查面向共享工作树；期间其他会话仍在开发。结果不能外推为本项目整体验收。

| 测试项 | 用例 / 命令 | 结果 | 修复动作及限制 |
|---|---|---|---|
| 文档引用/结构 | 12份文档相对链接、围栏配对、CTX-008标题/§1～5/类型名检查 | 首轮309/309链接有效、12份围栏成对、结构与七类补拟对象检查通过 | 报告追加后再次验证；不等于JSON Schema或适配器实现通过 |
| 差异空白 | git diff --check -- 本任务登记路径 | 初检8处尾空格，局部修正后通过 | 不格式化其他会话文件 |
| 算术样例 | §13预算8例、RRF/分页/来源计数 | 上一轮已通过，方案语义未改变 | 未当作生产服务测试 |
| Ruff | .venv/Scripts/python.exe -m ruff check . | 初检1处E501；交付前复核7处E501，位于model_client.py及model_gateway目录 | 其他会话W-MODEL持续开发中且占用上述范围；未越界修改，不报告全仓静态检查通过 |
| mypy | .venv/Scripts/python.exe -m mypy src | 202源文件通过 | 共享工作树时间点结果，不代表生产集成 |
| pytest | .venv/Scripts/python.exe -m pytest -q --disable-warnings | 2218通过、3跳过、3564告警，44.82秒 | 3项Docker测试未显式启用（需AI_AGENT_RUN_DOCKER_TESTS=1及运行中daemon），未计为通过；非真实检索/压缩集成 |
| SAST/SCA/Secret | scripts/security_gate.py，独立临时目录 | 初检SAST高/中0、低44；SCA 0漏洞（96依赖，跳过本项目editable项）；历史Secret 19/19已审样例。工作树专项复测21/21已审样例，0未审项、698文件，通过 | 初检未审项为§3的40位Git提交哈希误识别，git验证后改短ID；未加豁免。整套复扫因SCA连接超时中止，不能称整套复扫通过 |
| 覆盖率/真实检索/压缩集成 | 本次无可执行实现变更 | 未执行 | 不声称业务路径、覆盖率、性能或M3/M4已通过 |

### 15.4 验证入口及剩余范围

文档阅读入口为本文件及上表源文件；无需启动新服务。台账复核：`python -X utf8 scripts/task_board.py show G-CTX` 和 `validate`。文档检查按每个文件目录解析相对链接；源差异用 `git diff -- docs/design-specs/REQ-CTX-* docs/design-specs/REQ-HAR-002-context-compaction.md` 检视，但不得提交其他会话改动。

本工作包交付范围是限定契约核对、批准后的源同步及文档验证。生产适配器、索引/解析存储、授权/压缩状态机、哈希可信存储、真实恢复及性能由下游任务各自领取和确认实施。T01～T12仍是未完成的功能验收清单。G-CTX交付后仅提交待验收，不能因方案批准直接完成，不能自动批准 C-* 实施或宣称 REQ-CTX 全项完成。


扫描原始证据（脱敏，工作区外）：首轮 `C:/Users/93478/AppData/Local/Temp/gctx-security-20261029-r2/`；整套复扫错误 `gctx-security-20261029-r2-recheck/`；工作树Secret专项复测 `gctx-security-20261029-r2-secret-recheck/`（同一Temp目录）。专项复测调用现有脚本的 snapshot/read_report/evaluate_secrets 和同版本Gitleaks，不改工具或指纹规则。初检命中为可唯一解析的Git对象ID，非凭据；未执行任何凭据吊销操作。

交付结论：本任务登记的12份文档与引用检查通过、限定文档同步已交付，提交待验收；共享工作树全仓Ruff仍失败、Docker三项未执行、整套安全复扫遭SCA网络超时，均保持未通过/未执行状态，不宣称全项目质量门禁通过。须由对应范围负责人解决全仓Ruff，真实Docker和业务集成由相关实施/里程碑补验。用户验收G-CTX时范围限定为本节文档产物，不能把这些限制消除或外推为产品可发布。
