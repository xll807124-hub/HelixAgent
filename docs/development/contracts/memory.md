# G-MEM 记忆契约核对与实施基线建议

核对日期：2026-10-29（Asia/Shanghai）。负责人：`codex-gmem-20261029-01a185f7`。
交付类型：契约评审文档。本文中的建议尚未获用户批准；四份 MEM REQ 保持 `v0.1-designed`，不据此冻结共享契约或批准生产实现。

## 1. 目标、依据与本次边界

目标：使工作、任务、项目记忆的范围、来源、审批、冲突、保留和检索接口可以共同评审，避免下游分别解释不一致的草案。

依据：[执行手册](../../../项目开发执行手册.md)的依赖驱动章节、§4.3 记忆系统及阶段 5；[迭代规则](../../../规则文档/AGENTS.md)；[需求分析](../../需求分析报告.md)§5.8；[需求设计](../../../需求设计方案.md)§4.8。已执行“读取台账及工作区 → claim → 核对原文和代码 → 官方对标 → 专属文档 → 文档验证”。

- 台账 `G-MEM` 无实现硬依赖，`implementation_ready=true` 仅授权契约文档工作。`P-MEM` 的硬依赖仍为 `G-MEM`、`G-SEC`，其实施基线尚未批准。
- 本次唯一交付文件为本文；台账只用 `scripts/task_board.py` 加锁、重读、校验并原子保存。
- 不修改生产代码、正式测试、四份 REQ、其他会话文件或台账依赖，不 commit/push。
- 本次无前端实现，未应用 UI Skill；审批展示需求只作为 G-WEB 的接口输入。
- 文档验收条件：四份 REQ 可追溯；三类记忆与检索后端边界明确；冲突及推荐处理明确；接口、权限、异常、验收用例和剩余门槛可供用户确认。文档验收不代表 MEM 功能或 M4 验收。

## 2. 需求与现状矩阵

| 原文及保留版本 | 可复用设计 | 现状与缺口 |
|---|---|---|
| [MEM-001](../../design-specs/REQ-MEM-001-memory-schema.md)，v0.1-designed | `memory.entity.v1`、来源与溯源、作用域、访问策略、版本和内容哈希 | 四层枚举与手册三类范围不同；内容哈希不变与更新语义未对齐 |
| [MEM-002](../../design-specs/REQ-MEM-002-memory-write-approval.md)，v0.1-designed | 审批请求、三种同意粒度、撤销、拒绝优先 | 超时批准、密码/密钥进入待审批与安全边界冲突；审批尚未绑定内容版本及同意适用范围 |
| [MEM-003](../../design-specs/REQ-MEM-003-memory-retrieval-conflict.md)，v0.1-designed | 语义/BM25/时序检索、五维排序、分层加载、冲突分类 | 查询无精确 ID/分页字段；L3 类型不一致；显式输入冲突算法与 AC08 相反 |
| [MEM-004](../../design-specs/REQ-MEM-004-memory-lifecycle.md)，v0.1-designed | 到期、撤销/删除、归档、驻留与清理 | MVP 与 MEM-001 冲突；两套衰减公式不同；留存期和枚举存在差异 |

代码核对定位：

| 已有实现 | 可复用边界 | 不能据此宣称已具备的能力 |
|---|---|---|
| [Runtime 共享类型](../../../src/runtime/common/types.py) | ID、UTC 时间、Actor、数据分级 | 没有 Memory 实体；`src/memory` 和 `tests/unit/memory` 尚不存在 |
| [Coder 检查点](../../../src/workers/coder/checkpoint_store.py) | ReAct Loop 的 save/load/delete | `MemoryLoopCheckpointStore` 是内存检查点，不是跨任务知识存储；不能用其测试充当 MEM 验收 |
| [RBAC 模型](../../../src/security/rbac/models.py)及[评估器](../../../src/security/rbac/evaluator.py) | Subject、Resource、Operation、租户归属和默认拒绝 | 现有 Operation/ResourceType 没有记忆专用操作/资源；不能把 `memory:approve` 当作已实现权限 |
| [Policy Gateway](../../../src/security/policy_gateway/gateway_v2.py) | `evaluate(PolicyRequest) -> PolicyResult`，ALLOW/DENY/ESCALATE_TO_APPROVAL | MEM 草案的 REQUIRE_APPROVAL 不是此实现的枚举；映射须与 G-SEC 共同核对 |
| [事件信封](../../../src/runtime/event_store/envelope.py)与[幂等生成器](../../../src/runtime/idempotency/generator.py) | 事件坐标、因果、派发前持久化逻辑意图与键的既有契约 | 共享类型和信封的 DataSensitivity 枚举不一致；生成器不能反复生成新键来重试同一次记忆写入 |

本次未将任何其他会话的实现或测试计为自身成果。已有 [G-RT 核对材料](./runtime.md)仍由其负责人维护，不能作为已获用户验收的事实。

## 3. 官方对标

访问日期均为 **2026-10-29**；以下只复述公开文档可验证行为，建议列为本项目判断，不推测产品内部数据库或安全实现。

| 官方来源与已验证事实 | 优点 | 本项目借鉴或规避 |
|---|---|---|
| [Claude Code memory](https://code.claude.com/docs/en/memory)：人工指令与自动记忆分开；记忆索引有启动加载上限，详细主题按需读取；记忆可编辑/删除；文档明确上下文指令不是强制控制 | 控制上下文开销，用户可检查记忆 | 借鉴摘要与详情分层、可撤销；权限由服务端执行，不让记忆提升为安全策略 |
| [Cursor Rules](https://cursor.com/docs/rules)：项目规则位于 `.cursor/rules`，纳入版本控制，可按路径或相关性应用；文档不建议将 AI 指引作为唯一安全控制 | 范围与变更可审查 | 借鉴明确项目范围及版本；不将某项目偏好自动提升为组织规则 |
| [LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)及[Stores](https://docs.langchain.com/oss/python/langgraph/stores)：Checkpointer 管线程状态，Store 管跨线程数据；Store 使用 namespace/key；内存后端与持久化后端用途不同 | 恢复状态与跨会话知识分工清楚 | 复用本项目 Runtime 恢复机制，另设受审批的记忆存储；命名空间本身不等于授权，不引入 LangGraph 依赖 |

证据限制：旧 [Cursor Memories 链接](https://docs.cursor.com/en/context/memories)本次打开重定向到文档首页，搜索摘要不能证明当前产品仍有相同审批行为，因此不将其列为已验证事实。MEM-001 的“七层内部架构”和 MEM-003 的第三方 `kimi-mem` 仓库不能直接当作厂商官方承诺；本轮不沿用这些内部实现断言或历史性能数字，也不修改原 REQ。

## 4. 实质性冲突与建议决议

下表均为**待确认建议**，不是已经生效的修改。D01～D09 建议共同作为后续 P-MEM 方案细化依据；各共享字段正式变更仍需对应负责人参与、版本记录和兼容评审。

| ID | 原文定位及冲突 | 推荐处理 | 影响方/验收影响 |
|---|---|---|---|
| D01 | 手册§4.3/阶段5及需求设计§4.8：三类、组织记忆后续；MEM-001 §15.1：四类及 PUBLIC | 本期启用 WORKING/TASK/PROJECT；ORGANIZATION 和跨租户 PUBLIC 保留为未来枚举，创建/读取均不开放，不能悄悄改成另一种共享含义 | P-MEM、A-ORGMEM、G-SEC；MEM-001 AC-03 的组织记忆仍未完成 |
| D02 | MEM-001 §15 排除向量、自动冲突和衰减；MEM-003 §16 纳入混合检索；MEM-004 §16 纳入衰减/归档；手册要求最终检索、冲突和清理 | 拆为 A 基础治理薄片与 B 完整检索/生命周期薄片，见§9。A 采用显式 expires_at、到期排除和撤销；B 补齐其余范围。A 不代表 P-MEM 全部完成，不删除 B 的验收项 | P-MEM、M4；保留全部未交付 AC。研究型 RGMem/FadeMem/Hebbian 继续不启用 |
| D03 | MEM-002 §5.2 允许超时默认批准，§8.1/AC04 允许密码密钥进入审批；MEM-001 §8/§13 禁止这些内容持久化。另见 MEM-002 §6.1：阈值评分不能保证§8.1低置信推断及always_ask的强制人工要求，数值反例见§12 | 超时只能 EXPIRED/拒绝或受控延长待决，不能自动批准；密码/密钥拒绝且不进入候选、审计正文或索引。扫描失败/超时不可经人工批准绕过，须成功复扫；普通待审内容必须已脱敏并有隔离与留存策略。DENY/扫描拦截优先，随后强制人工规则先于评分：AGENT_INFERRED且confidence<0.6或命中always_ask时必须人工审批，阈值/乘数不能覆盖；评分仅决定非强制候选的路由 | G-SEC、S-RBAC、P-MEM、G-WEB；需要同步 MEM-002 AC04/AC08及§6.1算法，属于待确认安全语义裁决 |
| D04 | MEM-001 §6.1/§8 要求 content_hash 永不变化，§7.3 又允许内容更新和历史版本；MEM-004 §2.3 将版本历史列为后续 | 明确不可变单元是 `(memory_id, version)` 的内容；修订生成新版本、重新审批及新哈希，旧版本不改写。A 保留必要的版本/来源/审批证据；不要求历史浏览 UI。硬删除覆盖所有历史正文 | MEM-001～004、G-RT、O-AUDIT；涉及共享哈希语义，确认前不改原契约 |
| D05 | MEM-003 §7.2/§8.3 对 USER_EXPLICIT 自动拒绝推断，AC08 却要求人工仲裁；自动替换可能绕过 MEM-002 审批 | 显式输入与 Agent 内容冲突按 AC08 人工仲裁，原有效版本继续可用，待决新版本不进入普通检索；AUTO_REPLACE/MERGE 仅是提案，仍须授权、审批和版本并发校验。协调冲突保留双方并标记，不由置信度擅自删除 | P-MEM、G-WEB、E-SCORE；自动解决率 >80% 单独评测，不能为了指标跳过仲裁 |
| D06 | MEM-003 §6 没有 memory_id/分页参数，L3 的 content_preview:string 与§7.1 完整 MemoryContent 冲突；scope_priority 可达1.2，BM25 原始值无界但总分要求[0,1] | 分离 get/search；预览始终 string，L3 增加明确类型的 detail；有界分页；归一化各信号并固定并列排序。作为可选扩展/适配方案评审，不就地更改字段类型 | P-MEM、G-CTX、C-SELECT、WEB；见§6的建议接口及 V07/V08 |
| D07 | MEM-002 §8/§10：软删30天、审计180天；MEM-004 §6/§11：30/90/180天、审计7年；SEC-008 §7：记忆90天、审计分层保留。MEM-004 §10 又允许归档失败直接硬删除 | 不选任意数字冒充统一基线；用显式版本化保留策略区分到期、撤销、审计与合法保留。实际数值及备份清除窗口交 G-SEC/G-OBS 确认；缺失策略禁止启动自动物理删除。归档若为必需，失败进入重试/人工处理，不能提前删除。撤销立即停止新检索 | G-SEC、G-OBS、O-AUDIT、P-MEM；删除证明必须区分在线副本已清除和备份未清除。不将草案期限表述为法律结论 |
| D08 | MEM-004 §6.1 乘法衰减与§7.1 减法衰减不一致，低访问因子在减法中反而减慢衰减；HARD_DELETED/DELETED_FAILED 不在 MEM-001 枚举 | A 不运行自动衰减。B 实施前以可注入时钟对比两式，明确初始化、同一时间重复执行幂等及访问频率影响，再确认一个算法；保留删除工作状态与实体状态分离的建议，不直接加共享枚举 | P-MEM、G-RT、E-SCORE；B 的衰减和性能验收继续开放 |
| D09 | MEM-002/004 使用 LOW/MEDIUM/HIGH；RT-001 冻结枚举为 PUBLIC/INTERNAL/CONFIDENTIAL/RESTRICTED，事件实现另含 SENSITIVE；MEM 缺少 Team、跨任务 trace、权限码映射 | MEM 实体沿用 RT-001 分级，不把风险评分 HIGH 当作数据分级；未知值拒绝。映射、Team 继承、项目记忆跨任务来源 trace 与本次调用 trace、审批资源绑定由 G-SEC/G-RT/G-OBS 联合确认，不能使用“同名等价”或伪造 task_id 的适配 | 安全、Runtime、观测及所有 MEM 调用方；共享边界待决表见§8 |

## 5. 三类记忆与后端边界建议

| 类型 | 必备范围 | 可见性及生命周期 | 持久化边界 |
|---|---|---|---|
| WORKING | organization/project/task/worker，继承所属 Team/仓库限制 | PRIVATE 且仅绑定 Worker；任务/Worker 不匹配即拒绝；权限由服务端识别 | 运行过程原始上下文和恢复快照仍属 Runtime；显式建模为 Memory 时走同一校验入口，不额外复制全部对话 |
| TASK | organization/project/task，必要时 repository | PRIVATE 仅 owner；SHARED 仅任务范围内且授权允许的主体；“任务内所有 Worker”不能覆盖 PRIVATE 规则 | 任务范围持久化，不能靠把 task_id 置空提升为项目记忆 |
| PROJECT | organization/project，必要时 repository | SHARED 仅在该项目及授权范围；组织同属不自动等于项目可读 | 跨任务复用；升级范围作为新提案重新审批，保留原任务/版本来源 |

`source` 继续为 USER_EXPLICIT / USER_IMPLICIT / AGENT_EXTRACTED / AGENT_INFERRED / SYSTEM_GENERATED。来源与置信度分开保存，`provenance` 至少一项。外部内容即便标为 RULE/GUIDELINE，也不能修改系统/组织策略或成为未经授权的工具调用。

存储建议：沿用项目 PostgreSQL 技术方向作为任务/项目记忆权威存储；迁移、表结构、依赖安装在 P-MEM 实施方案批准后才进行。数据库不是由 C-SEARCH 提供的隐含服务。

- `MemoryRepository` 管实体、不可变版本、审批/同意、可见性撤销及删除任务；最终提交事务应同时保存可恢复的审计交付记录，禁止有状态改变无审计证据。事务/outbox 方案须与 Runtime/OBS 对齐，本轮不新增第二套全局事件溯源系统。
- `MemoryRetrievalBackend` 管可重建的关键词/语义/时序候选，返回 memory_id/version/信号；不拥有审批权、租户授权权或生命周期事实。正文从权威存储按当前可见性加载。
- `AuthorizationPort`、`PolicyPort`、`AuditPort` 为服务层依赖边界。后端输入只能使用服务端构造的已授权范围，不接受模型自行声明的租户或身份。
- 三条检索通道可以有独立适配器；不增加 C-SEARCH 为 P-MEM 硬依赖。数据库全文检索若不满足真正 BM25，必须标注算法，不以普通全文分数冒充 BM25 验收；pgvector/embedding 供应商及依赖另审。
- A 的精确/关键词检索、离线固定向量和 mock 都不能证明 B 的真实语义检索完成。真实 Context Selector/Worker 联调在 M4 汇合，届时必须验证真实组件。

## 6. 接口、数据和错误语义建议

以下为待评审的模块接口；不是已存在的 Python/HTTP API，不预占 URL 或更改 G-WEB 公共响应契约。

### 6.1 复用与建议扩展

复用 Memory 的 `schema_version`、`memory_id`、`memory_type`、`scope`、资源 ID、`content`、`source`、`provenance`、`confidence`、`sensitivity`、`lifecycle`、`access_policy`、`version`、UTC 时间及 Trace 字段。正文 1～10000 字符、摘要不超过500字符、置信度有限且在[0,1]。完整 Schema 以 MEM-001 为原文，不在此另造平行实体。

建议在**命令上下文/版本与审批记录**中补齐以下内容；MEM仍为待冻结设计，不擅改其共享字段，也不改动已冻结的Runtime契约：

- `RequestContext`：经认证的 principal、organization/project/task/worker/repository 边界、当前 trace、授权/策略版本、deadline 和取消信号。Team 从可信资源归属取得；映射待 G-SEC 确认。
- 写入命令：`operation_id/idempotency_key`、候选内容、`expected_version`（创建时明确为无既有版本）；沿用 RT-007/REL-006 的逻辑意图及请求摘要规则，首次派发前持久化键，禁止每次重试重新生成。
- 审批绑定：候选版本、内容哈希、资源范围、有效期和策略版本；展示脱敏后的准确内容/变更及影响范围，不能只展示摘要。内容或范围变更使旧批准失效；决策提交时重新授权。
- 同意记录：ONE_TIME 原子消费；SESSION 绑定真实会话 ID/结束条件；PERMANENT 仍受明确租户、类型/来源/操作范围与撤销约束。`ALL` 不得跨租户，也不能覆盖 DENY 或强制人工审批。
- 删除任务：目标版本集合、撤销生效时间、策略版本、保留限制、分存储清除回执、重试次数及下一次时间。其状态不借用未定义的 MemoryState。

### 6.2 服务接口

| 接口建议 | 输入 → 输出 | 权限、异常与幂等约束 |
|---|---|---|
| `propose_write` | 候选 Memory、RequestContext、expected_version、幂等键 → 写入结果或 approval_request_id | 校验→授权/策略→成功扫描→冲突检查→审批；拒绝优先，强制人工规则优先于评分及自动同意；PENDING 是业务待决，不能作为可重试错误自动写入 |
| `decide_approval` | approval_request_id、绑定的版本/哈希、APPROVE/REJECT/CANCEL、上下文、幂等键 → 审批结果/已提交版本 | 原子比较状态及版本；同决策重投复用结果，不同决策返回冲突；迟到、权限撤销、内容变更拒绝 |
| `get_memory` | memory_id、可选 version、L1/L2/L3、上下文 → 一个授权版本或不存在 | 精确查找不要求伪造 query 文本；无权与不存在对普通用户采用一致表现；历史/删除内容仅专门授权审计路径 |
| `search_memories` | 原 MemoryRetrievalQuery、显式分页、上下文 → items、warnings、next_cursor | query 1～500，top_k/page_size 1～100，分页绑定查询与授权范围；不存在无界 list/all；每页重新校验权限 |
| `resolve_conflict` | 冲突 ID、版本集合、策略提案、上下文、幂等键 → 待审或提交结果 | 不能绕过审批；expected_version 失败拒绝，保留冲突证据；跨租户候选不暴露 |
| `revoke_memory` | memory_id、版本范围、原因、上下文、幂等键 → 撤销回执及清除进度 | 成功回执意味着之后开始的检索不再返回它；后台清除未完成不能报告物理删除完成 |
| `run_cleanup_batch` | 已批准策略版本、任务游标、batch_limit、可信系统身份 → 进度/回执 | 有界批次、期限和取消；重新检查保留限制；失败可恢复；生产启用须满足删除策略门槛 |

统一结果建议表达 `operation_id`、`trace_id`、业务状态、可选 data、可选脱敏 error 和 warnings；具体字段命名及 HTTP 状态由 G-WEB/G-SEC 对齐后再定。

L1/L2 的 `content_preview` 最大为200/1000字符，L3 仍返回字符串预览并以可选 `detail: MemoryContent` 承载全文。返回结果增加版本及来源引用，避免分层加载错取新版本。`total_candidates/filtered_count` 仅统计当前授权范围，不能暴露其他租户数量。

排序建议保留原五权重 `0.30/0.15/0.20/0.20/0.15`；每个信号归一化到[0,1]：余弦截断后转换；非负 BM25 使用 `s/(1+s)`；scope 分数截断到1；未来更新时间拒绝/校正为明确错误，不能产生超范围 freshness。并列按 memory_id/version 固定排序。该归一化是待确认算法，不是假定已有实现；降级通道缺失时保留其权重且信号置0、标 warnings，B 的评测须分别报告正常与降级质量。

### 6.3 错误、超时与取消

| 逻辑语义（尚非公共错误码） | 行为 | 自动重试 |
|---|---|---|
| 输入/版本不支持 | 写入前拒绝，无部分提交；未知分类/类型不降级放行 | 否 |
| 无权限/范围不符/策略拒绝 | 不返回正文、候选数或敏感原因；保留脱敏安全审计 | 否 |
| 审批待决/过期/撤销 | 不产生可检索正文；审批过期保留终态 | 否 |
| 内容版本或幂等摘要冲突 | 返回冲突，要求调用者读取现状后明确新意图 | 否 |
| 授权/扫描不可用 | 失败关闭，不返回缓存绕过权限，不允许“人工确认扫描成功” | 只可对可重试依赖做有界重试，不能越过审批 |
| 单路检索超时 | 沿用 MEM-003 单路200ms、整体500ms上限；取消未完成通道，可用通道带警告返回 | 不启动超出整体deadline的重试 |
| 全部通道失败 | 返回可区分的不可用结果，不把空集当作成功无命中；缓存仅在当前授权和撤销水位均可验证时使用 | 遵循 REL-002/003 的有界策略 |
| 写入回执丢失/进程中断 | 读取持久化操作结果；结果未知先核查，再决定是否恢复 | 同意图同键，禁止盲目再次写入 |
| 取消 | 提交前停止且释放资源；提交后不能撤销事实，按 operation_id 查询结果 | 不自动重发 |

索引/缓存延迟删除不能造成撤销失效：查询候选后必须回查权威状态与版本；在返回前检查撤销水位。撤销成功后开始的请求不得命中旧缓存；已经发出的内容无法召回，应在影响说明中如实记录。授权服务故障时不能用60秒缓存兜底放行。

## 7. 状态、权限和安全

- 候选与 Memory 分开：候选 PENDING 不进入 ACTIVE 索引；审批 PENDING → APPROVED/REJECTED/EXPIRED/CANCELLED，终态不可就地改写。APPROVED 只表示决策完成，持久化提交结果另行记录，崩溃恢复须核查。
- A 的 Memory 状态为 ACTIVE → EXPIRED 或 DELETED；已到 expires_at 即不可检索，即便后台尚未补写过期事件。后续访问不自动复活到期/撤销数据。
- B 才处理 STALE/ARCHIVED、恢复及衰减；归档恢复重新授权并检查 expires_at/保留限制。硬删除是清除任务结果，不自行新增 MemoryState。
- 租户/Team/项目/任务授权和 PRIVATE owner 条件取交集；Admin 身份不自动获得 PRIVATE 正文。读、写、审批、仲裁、导出、软删、硬删分别授权，不能借通用 EXECUTE_TASK 替代。
- 检索/日志/审计中都不得包含密钥、原始敏感扫描片段、模型内部思维链；来源引用同样受权限校验。缓存键必须包含租户、主体/权限版本、资源范围、查询及版本，撤销使其失效。
- 外部内容和模型生成 Memory 均视为不可信数据。ASI01/ASI06：记忆注入不能提升指令权限；ASI03：身份交集和租户传播；ASI09：审批展示精确差异；批量清理/自动替换启用前须评审 ASI10 与 Kill Switch 覆盖，覆盖未证明时不得上线。
- 数据驻留约束包含正文、embedding、缓存、审计与备份，不能套用 MEM-004“临时缓存可跨区”来绕过组织策略。

## 8. 依赖、兼容与共享文件边界

台账硬依赖不变：G-MEM 无；P-MEM 依赖 G-MEM/G-SEC。下表为接口协同及真实集成条件，不自行追加全局串行依赖。

| 边界/对接工作包 | 必须落实的输入 | 未落实时的界限 |
|---|---|---|
| G-SEC / S-RBAC / S-TENANT | 记忆权限码、Team 继承、MEM↔Policy 决策枚举、数据分级、驻留及保留策略 | 不改 RBAC 共享枚举，不以 memory:write 字符串冒充授权实现；生产写入/清除不能启用 |
| G-RT / R-IDEM / R-EVENT | 版本并发与幂等账本、事件提交/审计交付一致性；无活动 Task 的管理操作如何绑定真实 Runtime 坐标 | 不伪造 task_id/project_id 或自行改变 EventEnvelope；独立测试不能证明跨进程恢复 |
| G-OBS / O-AUDIT | 来源 trace 与调用 trace 区分、审计事件载荷/版本、保留时间、失败恢复 | 本文的逻辑事件名称不等于冻结 payload_schema；无法保证审计的变更不得静默提交 |
| G-CTX / C-SELECT | Memory 结果到 Context Selector 候选的适配、来源/权限、分层加载和 token 预算 | 不把 Memory 当作代码 Symbol；不改其共享接口；M4 前须真实集成，原始→可逆压缩→有损摘要顺序保留 |
| G-EVA / E-DATA / E-SCORE | 记忆质量 >80%的定义、标注集/版本、样本量、置信区间、正常/降级分组 | 推荐“正确、相关且有效的返回条目/人工评审返回条目”作为待审口径；不可将命中率或自动审批率等同质量 |
| G-WEB / WEB | 记忆审批内容、来源/版本、撤销进度、无权限/超时等结果 | 仅提供服务端契约输入；UI设计另行确认，无前端文件写入 |

兼容/迁移：四份 REQ 本轮不变。D04/D06/D09 影响字段含义或消费者，不因“尚未写代码”省略正式变更记录；先扩展可选字段/适配器，明确旧读路径与未知版本拒绝，确认调用方后再收缩。本次仅确认本仓库尚无`src/memory`目录，未连接真实数据库，不能对生产Memory表或外部消费者的存在情况作结论。

## 9. 后续实施切片与可观察验收

建议先完成 A：三类范围校验 → 写入提案/审批 → 持久化 → 精确/关键词读取 → 撤销 → 再读不可见的纵向闭环。B 完成真实语义/BM25/时序融合、冲突及生命周期完整功能。拆分只是本轮建议；正式新增子任务须在共同台账锁内登记接口、验收、依赖和不重叠范围，不能私建台账副本。

P-MEM 现有可写范围为 `src/memory`、`tests/unit/memory`。若实施需要迁移、集成测试、API、共享策略或依赖文件，必须先协调归属并原子调整范围；不能把这些文件藏入本工作包。正式测试只能在对应实施任务已领取且基线批准后编写。

| 用例 | Given/When → Then（待实施验证） | 所属范围 |
|---|---|---|
| V01 | 三类有效绑定创建→接受；伪造 org/project/task/worker、ORGANIZATION/PUBLIC、未知分级→拒绝且不写入 | A；MEM-001 AC01/03/11/14/15 |
| V02 | 内容长度0/10001、无 provenance、NaN/越界置信度、无时区时间、未知schema→输入失败；边界1/10000合法 | A；MEM-001 Schema不变量 |
| V03 | 扫描命中凭据/失败、Policy DENY、审批过期→没有可检索正文；低置信推断或always_ask→必须人工审批，修改乘数/阈值/自动同意不能绕过 | A；MEM-002 AC01/03/04/08/10，D03需确认 |
| V04 | 展示版本A后内容变为B/权限被撤销→旧批准不能提交；一次性同意并发消费仅一次；跨会话/租户复用失败 | A；审批与同意安全 |
| V05 | 同幂等键同摘要重复/并发→一次副作用、相同结果；不同摘要/expected_version过时→冲突 | A；RT-007/REL-006 |
| V06 | 提交前/后崩溃、审计投递失败或回执丢失→核查持久结果、可恢复审计且不重复写；给定事件/命令/新事件并重放两次一致 | A；恢复与审计真实集成 |
| V07 | PRIVATE他人、错误任务/项目、RBAC不可用、越权游标→不返回内容/计数；授权变更后分页和缓存不绕过校验 | A/B；安全边界 |
| V08 | L1/L2/L3读取→类型/长度和同版本一致；每个信号及总分[0,1]、并列稳定；向量/BM25/时序单路超时及全部超时→有界降级或明确失败 | B；MEM-003 AC01～05/12 |
| V09 | 显式输入与推断矛盾→人工仲裁，旧版本仍有效；AUTO_REPLACE提案仍需批准；协调冲突保留双方 | B；MEM-003 AC06～09/14，D05需确认 |
| V10 | 撤销成功后新查询/详情/旧缓存/延迟索引→不可见；取消或进程重启后不复活；同一时钟推进到expires_at即排除 | A；MEM-002 AC07，MEM-004 AC03/04 |
| V11 | 归档失败、保留策略缺失/变化、合法保留、批量中断→不提前硬删；重试恢复无重复副作用；正文/历史/索引/缓存/备份状态逐项证明 | B；MEM-004 AC05～08/11/12 |
| V12 | 同时刻重复衰减、不同访问频率/置信度、临界值→确定且符合已批准算法；压力清理有授权/取消/Kill Switch | B；MEM-004 AC01/02/09/10/13/14 |
| V13 | 真实数据集、真实检索/授权/Worker/Selector→质量>80%、NDCG@10>0.75、检索p95<200ms及相关原REQ指标；安全泄漏单独零容忍 | B/M4；计量口径须先批准 |

A 交付保留的开放条件：组织记忆、PUBLIC、STALE/ARCHIVED、真实向量/BM25融合、自动冲突和仲裁完整链路、衰减、压力清理、删除/备份证明、性能/质量及真实 M4 集成。组织记忆归 A-ORGMEM；其余不得仅因 A 通过就关闭 P-MEM 或整项 REQ。

生产实施自测须按迭代规则执行 lint/typecheck、真实 SAST/SCA/Secret、适用单测/契约/集成/故障及覆盖率；鉴权/授权、幂等、Checkpoint、审计关键路径100%行覆盖。弱网/重试、超时/取消、恢复和降级在上述用例中有对应入口。不得把替身结果或未运行扫描标为通过。

## 10. 本次验证报告与复核方式

本轮为单个文档交付，未编写/运行产品功能测试；以下仅验证交付材料的可追溯性与协作状态。

| 测试项 | 用例 | 结果 | 修复动作 |
|---|---|---|---|
| 文档结构与本地引用 | UTF-8、代码围栏、必备章节、所有本地Markdown链接可解析 | 首次交付通过：11节、9项决议、13组验收用例、16/16本地链接；本次增加§12复核记录 | 内容复核修正见§12 |
| 原文保留 | 四份MEM REQ在本次核对前后SHA-256一致；版本均为v0.1-designed | 通过：4/4哈希一致，4/4版本保留 | 无改动；未来如变化则重新评审，不回退他人修改 |
| 代码证据 | 只读AST确认现有Runtime/DataSensitivity、RBAC操作和源码路径；确认无Memory实现目录 | 通过：两个分级枚举确实不同，缺少记忆操作/资源，网关使用ESCALATE_TO_APPROVAL，两个目录未建立 | 差异已记入D09/§8；本次未修生产代码 |
| 共享台账 | `validate`、G-MEM负责人/写入范围/依赖校验 | 通过：62项，依赖无环；负责人/模式/专属写入范围/无硬依赖与领取一致 | 无失败项；交付状态通过submit更新 |
| 官方资料 | Claude Code/Cursor Rules/LangGraph官方页面正文可读取；旧Cursor Memories链接重定向 | 通过（当前事实来源）；旧链接未验证记忆审批能力 | 用当前Rules作为对标，删除“摘要=当前能力”的推断 |
| 生产质量门禁 | Ruff/mypy/SAST/SCA/Secret、单测/覆盖率、数据库、E2E、安全/恢复/性能 | **未执行；生产能力未验收** | 本轮无生产变更，后续实施必须执行，不能引用历史绿灯代替 |

复核命令（项目根目录）：

```powershell
.venv/Scripts/python.exe -X utf8 scripts/task_board.py show G-MEM
.venv/Scripts/python.exe -X utf8 scripts/task_board.py validate
Get-Content -Encoding UTF8 docs/development/contracts/memory.md
rg -n 'class (DataSensitivity|Operation|ResourceType)' src/runtime/common/types.py src/runtime/event_store/envelope.py src/security/rbac/models.py
```

本文无服务启动步骤、环境变量或新增依赖。P-MEM 的数据库启动/迁移/回滚、检索模型及部署验证方式须随实施方案提交；本轮不创建 `.env` 占位或虚构可运行服务。

本地链接及交付结构可复核为（不创建测试文件）：

```powershell
@'
from pathlib import Path
import re
p = Path('docs/development/contracts/memory.md')
s = p.read_text(encoding='utf-8')
assert '\ufffd' not in s and s.count(chr(96) * 3) % 2 == 0
assert all(re.search(r'^## ' + str(i) + r'\. ', s, re.M) for i in range(1, 13))
assert all('| D' + str(i).zfill(2) + ' |' in s for i in range(1, 10))
assert all('| V' + str(i).zfill(2) + ' |' in s for i in range(1, 14))
targets = re.findall(r'\[[^\]]+\]\(([^)]+)\)', s)
local = [x for x in targets if not x.startswith(('http://', 'https://', '#'))]
assert all((p.parent / x.split('#', 1)[0]).is_file() for x in local)
print('PASS: structure; local links', len(local))
'@ | .venv/Scripts/python.exe -X utf8 -
```

原文 SHA-256 基线（文档正文全量字节，包含原换行格式；本次两次读取一致）：

| 文件 | SHA-256 |
|---|---|
| REQ-MEM-001-memory-schema.md | `8c5f98b7221dd8cca28c3166306e4123601d8069cd86b23454bfd5dea695aeb7` |
| REQ-MEM-002-memory-write-approval.md | `86a2a6e9d2c08de73fab38313ccdcc9768c6c445c9976cb5d2cf6a6741e195a2` |
| REQ-MEM-003-memory-retrieval-conflict.md | `aa4e93345e8b6f20bf29e8de825feae5abb66f9baae7e10cade6fa1450f2a43a` |
| REQ-MEM-004-memory-lifecycle.md | `c47a9b0667dedd842c321bc6b165f9808d22a7a745d28fc5c5c3feb46d559ffa` |

## 11. 交付与用户决议边界

G-MEM 文档核对交付后提交“待验收”，仅真实用户验收后记录日期及证据并 accept。请区分：接受本核对报告、同意 D01～D09 建议、批准 P-MEM 某个具体切片实施，是不同范围的确认。

推荐本次先确认 D01～D09 作为 P-MEM 方案细化依据；§8 的共享映射、保留数值和质量口径仍需落实，四份REQ不会因此自动冻结。其他独立任务可继续领取；P-MEM在G-MEM/G-SEC完成且自身实施基线批准前不能编写生产代码。

## 12. 验收复核记录（2026-10-29）

用户请求：“请你进行验收”。复核对象为本次G-MEM契约材料；本请求不被记录为“用户已确认D01～D09”或“用户已验收通过”。复核前文档SHA-256为`73bc2cb4274325e5573a527d660ff905bde68f88ea0c129e83218db09b87bc63`。

技术结论：**修正后的文档质量复核通过，可以继续进行用户评审；完整实施基线尚不具备通过条件。** G-MEM保留待验收；P-MEM保持未批准实现。生产代码、原REQ和其他会话文件未修改。

| 测试项 | 用例/检查 | 结果 | 修复动作与剩余条件 |
|---|---|---|---|
| R1：强制人工审批可被评分覆盖（实施前阻塞项） | 按MEM-002 §6.1代入3组参数，对照§8.1及always_ask含义 | 复现3/3反例；原报告遗漏该冲突 | 已补充D03、propose_write和V03的优先级及参数边界；原REQ算法未改，正式实现与契约修订仍待批准 |
| R2：设计状态准确性 | §6.1“已冻结Memory”与页首v0.1-designed对照 | 原表述不一致 | 已改为MEM待冻结、Runtime已冻结；复核无该错误表述 |
| R3：环境事实证据 | §8“生产库尚无Memory表”是否有真实DB查询证据 | 无证据，原结论超出检查范围 | 已限定为仓库目录事实，明确数据库/外部消费者未检查 |
| 文档可复现性 | 执行§10内嵌检查脚本，检查12节/9项建议/13组用例和本地引用 | 通过：12节、9项建议、13组用例、16/16本地链接 | 修正后已复跑，未发现结构/引用失败 |
| 原文与代码追溯 | 4份REQ哈希/版本、5个枚举AST、记忆目录存在性 | 通过：4/4原文哈希及版本不变，5/5枚举检查匹配，记忆目录未建立 | 保持原REQ不变；真实代码差异仍开放 |
| 台账与实施准入 | 共享台账合法、原owner占用、P-MEM硬依赖及implementation_ready | 修正前后均62项有效，P-MEM仍不可实施 | 通过脚本锁内恢复G-MEM开发中修正文档，再submit；不调用accept/approve-design |
| 生产检查 | 产品单测、真实授权/审批/存储、覆盖率、SAST/SCA/Secret、E2E | 未执行、未验收 | 本轮仅文档复核，后续实施必须补齐 |

R1的确定性反例：采用TASK（类型分10）、AGENT_INFERRED（来源分25）、敏感度不加分、auto_threshold=20。下表参数只是草案允许但未限定的反例输入，不是生产默认配置，也不是产品功能测试。

| 用例 | confidence | multiplier | human_threshold | always_ask | 草案adjusted_score | 草案路由 | 必须满足的人工规则 |
|---|---|---|---|---|---|---|---|
| 低置信推断 | 0.59 | 1 | 50 | 否 | 47.3 | AUTO_WITH_NOTIFICATION | confidence<0.6，应HUMAN_REQUIRED |
| 乘数降低风险 | 0.59 | 0.1 | 50 | 否 | 4.73 | AUTO_APPROVED | confidence<0.6，应HUMAN_REQUIRED |
| 强制询问但阈值提高 | 0.9 | 1 | 60 | 是 | 50 | AUTO_WITH_NOTIFICATION | always_ask，应HUMAN_REQUIRED |

计算依据：`base_score=10+25+(1-confidence)*30`；`adjusted_score=base_score*multiplier`；always_ask时仅取`max(adjusted_score,50)`，并不能保证达到可配置的human_threshold。D03新增建议保留既有“必须人工”语义，确认后应把硬条件放在数值评分之前；不能用扩大阈值测试容忍范围来消除反例。

本次不重新裁定D01～D09，也未将G-SEC、共享映射、留存数值、质量口径等开放项视为已解决。验收证据与待决事项分开保留，文档复核通过不能解除生产实现门槛。
