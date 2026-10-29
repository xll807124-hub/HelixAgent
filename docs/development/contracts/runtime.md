# G-RT 运行时共享契约核对

核对日期：2026-10-29（Asia/Shanghai）。负责人：`codex-grt-20261029-01a185ef`。
交付范围：契约核对文档；待用户验收。本文不修改冻结契约，不批准下游生产实现，不代表 RT-001～008 或 M1 完成。

## 1. 目标、依据和边界

目标是让事件、投影、恢复、幂等、查询及其调用方使用相同身份、版本和错误语义，避免持久化模块各自发明接口。依据为[执行手册](../../../项目开发执行手册.md)、[需求分析](../../需求分析报告.md)、八份 Runtime REQ 和[既有接口评审](../../design-specs/INTERFACE_ALIGNMENT_CHECKLIST.md)。复用既有实现和测试；本轮仅写本文件，台账通过 `scripts/task_board.py` 原子更新。

实施计划：核对八份版本 → 对照源码和调用边界 → 列出差异及兼容用例 → 执行已有 Runtime 测试 → 提交本工作包验收。共享字段、公共错误映射和跨模块事务方案存在歧义时，记录待决项，下游实现前确认；不在此文中自行冻结新接口。

## 2. 冻结版本与兼容矩阵

以下冻结日期均保留为 2026-10-07；设计版本不等于数据 Schema 标识，也不等于生产能力已验收。

| 需求与原文 | 保留版本 | 数据/接口边界 | 主要消费方及对应工作包 |
|---|---|---|---|
| [RT-001](../../design-specs/REQ-RT-001-core-runtime-entities.md) | v0.2-frozen | Task → Workflow → Worker → Action；Artifact/Evidence 引用 | API、Worker、Policy、所有 Runtime 模块 |
| [RT-002](../../design-specs/REQ-RT-002-state-machines.md) | v0.1-frozen | 四层状态及迁移前置条件 | Coordinator、Worker、投影；R-PROJ/R-RECOVER/G-HAR |
| [RT-003](../../design-specs/REQ-RT-003-event-schema-versioning.md) | v0.1-frozen | `runtime.event-envelope.v1`；事件类型版本及 payload Schema 独立 | EventStore、投影、查询、审计；R-EVENT/R-PROJ/R-QUERY/G-OBS |
| [RT-004](../../design-specs/REQ-RT-004-state-projections.md) | v0.1-frozen | `last_sequence`、`projection_version`；投影可重建 | API/UI、恢复；R-PROJ/G-WEB |
| [RT-005](../../design-specs/REQ-RT-005-checkpoint-protocol.md) | v0.1-frozen | `runtime.workflow-checkpoint.v1`；事件水位及资产版本 | CheckpointBuilder/Manager/Recovery；R-CHECK/R-RECOVER |
| [RT-006](../../design-specs/REQ-RT-006-Trace-传播和审计关联.md) | v0.1-frozen | Trace/Span 传播及独立审计关联 | Worker/工具/模型/网关；O-TRACE/G-OBS |
| [RT-007](../../design-specs/REQ-RT-007-idempotency-key.md) | v0.1-frozen | 逻辑意图、公开键、请求摘要、租约和结果核查 | Action dispatch、外部写工具、恢复；R-IDEM/R-COMP |
| [RT-008](../../design-specs/REQ-RT-008-event-query-retention-redaction-permission.md) | v0.1-frozen | 查询授权、分页、脱敏、归档和删除 | API、审计、UI；R-QUERY/G-OBS/G-WEB |

RT-008 页首“设计版本 v0.1”与“状态 v0.1-frozen”并存；经读取完整页首，冻结记录明确，属于版本与状态分列，**不构成需要重新冻结的冲突**。不得把版本栏未写后缀解释为未冻结。

兼容原则：保留旧事件事实和旧读路径；新增可选字段应验证旧消费者；删除、改名、类型或含义变化需版本化与影响评审。未知事件版本、payload 版本和恢复资产版本的处理必须有显式测试，不得假定当前反序列化成功即兼容。具体版本升级/迁移执行遵循 RT-003/005，不在本文引入新版本。

## 3. 字段、接口和数据流

| 边界 | 必须保留的坐标/约束 | 现有实现定位 |
|---|---|---|
| 实体 → Action 执行 | task/workflow/worker/step、trace、工具 Schema、source_revision；执行授权引用 `policy_decision_id`；org/project/repository 不得互代 | `src/runtime/entities/{task,workflow,worker,action,artifact,evidence}.py`；`src/tools/executor.py` |
| 命令 → EventStore | `event_id/event_type/event_type_version/schema_version/payload_schema`；租户资源坐标；`actor/producer/causation/correlation_id`；UTC 时间；attempt；可选幂等键 | `src/runtime/event_store/envelope.py::EventEnvelope` |
| EventStore → 消费者 | 服务端分配 `sequence/recorded_at`；按 task 排序；`append(event) -> AppendResult`；`get_by_id/query/get_latest_sequence/count/health_check` | `src/runtime/event_store/store.py::EventStore` |
| 事件 → 投影 | 事件事实为准；重复消费不重复应用；水位与投影状态一致；缺口、乱序和不支持版本显式处理 | `src/runtime/projection/{projector,models,rebuilder,storage}.py` |
| 事件 → Checkpoint → 恢复 | task/workflow/org/project/repository；`source_event_sequence/source_event_id/source_event_hash`；`checkpoint_hash/content_hash`；runtime/workflow/agent/toolset 版本及快照引用 | `src/runtime/checkpoint/{models,builder,manager,recovery}.py` |
| dispatch → 幂等账本 | 租户范围 + workflow + step + intent_instance + action_type 标识逻辑意图；公开 key 与请求 digest 分离；首次派发前持久化；同意图重试复用键 | `src/runtime/idempotency/{generator,manager,storage,digest,reconciler}.py` |
| API → 查询服务 | `EventQueryRequest(task_id,page=1,limit=50,include_payload=False,access_level,occurred_after,occurred_before)`；当前 limit 为 1～1000，时间含时区 | `src/runtime/query/event_query.py::EventQueryService.query_events` |
| 全链路 → Trace/审计 | trace/span 因果关联；采样不能丢失必需审计；敏感数据脱敏，凭据和模型内部思维链不入事件 | `src/runtime/trace/{context,propagation,audit_correlation}.py` |

状态变化沿用 RT-002：Action 提议经授权/审批进入执行，再记录结果；等待审批、暂停或取消时禁止继续对应业务动作。Action 成功不能自动等同 Worker、Workflow 或 Task 完成。幂等结果未知进入 `OUTCOME_UNKNOWN`/核查路径，不能因超时、缓存丢失或租约过期直接重发外部写入。Checkpoint 是恢复优化快照，不能覆盖事件事实。

权限边界：外部输入和模型参数先校验；授权基于真实租户和资源范围；查询先授权，再读取并核对事件范围，按允许级别脱敏。恢复前重新验证权限、审批和资产版本。持久化、留存及删除方案须同时评审 SEC 与 OBS 依赖，不能由 Runtime 文档单独批准。

## 4. 错误语义、实现差异和待决事项

下表区分已存在的 Python 返回值/异常与尚未确定的跨服务错误码；本文不创造 HTTP 映射。

| 边界 | 当前实际语义/证据 | 缺口与处理归属 |
|---|---|---|
| EventEnvelope 构造 | 空 event_type/payload_schema、无时区时间、负 sequence、attempt<1 抛 ValueError | 尚未在构造处验证所有 ID、Trace 和版本；R-EVENT 补写入边界校验，保留拒绝证据 |
| 事件追加 | 内存实现返回 `SUCCESS/DUPLICATE/CONFLICT`，带 event_id/sequence/recorded_at；冲突可带 conflict_event_id/error_message | 抽象接口注释声明 DuplicateEventError/IdempotencyConflictError，另有 SequenceConflictError；返回状态与异常的适配策略需 R-EVENT 方案确认，不能只捕获异常忽略 CONFLICT |
| 事件幂等 | `compute_content_hash` 含 event_id、occurred_at、payload 等；内存幂等索引按键保存 | 不得把 Action 请求摘要与事件内容哈希混用；新 event_id 的重投、租户同键、同 event_id 不同内容均需专门评审/用例；R-EVENT/R-IDEM |
| 不可变事实 | EventEnvelope 是可变 dataclass；append 设置 sequence/recorded_at 并保存引用 | 内存保存引用不能证明持久事件不可变；R-EVENT 验证写后修改输入不影响权威事实 |
| 幂等预留 | 同键同摘要复用结果；不同摘要 `CONFLICT`；结果未知须核查 | manager 当前 `project_id/repository_id=organization_id`、`task_id=workflow_id` 为 MVP 占位，不能供生产隔离使用；R-IDEM 方案须传入真实坐标并核对调用方 |
| 幂等键生成 | generator 每次调用生成新的 `idem-` 键，注释却含“相同输入相同键” | 逻辑意图稳定不等于每次重新调用生成器；持久意图到 key 的复用及唯一约束需 R-IDEM 方案明确，不自行改冻结规则 |
| 查询 | 未授权抛 PermissionError；页码/limit/时间非法抛 ValueError；存储异常包装为 ValueError；返回非推进水位拒绝 | 部分错误被统一包装，跨服务错误码尚未统一；R-QUERY/G-WEB 方案评审明确映射与日志脱敏；留存、归档、删除及流式能力仍须完整验收 |
| 执行授权 | 既有接口评审 A04/A05 记录决策引用与 REQUIRE_APPROVAL/REQUIRES_APPROVAL 映射缺口 | G-SEC/S-RBAC 与调用方共同确认；不能由 G-RT 改共享枚举或认定已有完整授权装配 |
| 恢复/投影 | 已有内存后端和恢复、重建测试 | 跨进程事务、真实 DB、事件水位与快照一致性、崩溃恢复未由本轮证明；R-PROJ/R-CHECK/R-RECOVER |

以上是后续实施必须消除或明确适配的差异，不是本轮修改契约的决议。依赖本工作包的任务仍须满足台账其他依赖及各自实施基线确认。

## 5. 官方对标（访问日期 2026-10-29）

| 来源与已验证公开行为 | 优点 | 本项目借鉴（设计判断） |
|---|---|---|
| [LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)：区分 thread 内 Checkpointer 与跨 thread Store；明确内存 saver 重启后丢失 | 区分恢复快照与长期数据职责 | 区分事件事实、投影和 Checkpoint；内存单测不作为跨进程恢复证据；不据此引入 LangGraph 依赖 |
| [GitHub Copilot 输出评审](https://docs.github.com/en/copilot/how-tos/copilot-on-github/use-copilot-agents/review-copilot-output)：编码完成后请求人工评审，合并前需审查 PR | 代码产出与人工评审职责明确 | Task 完成须有证据及评审条件，工具成功不能直接结束任务 |

这些来源只支持公开行为，不证明产品使用本项目的事件模型、事务实现或数据库。对标结论不覆盖既有冻结契约。

## 6. 下游兼容与验收用例清单

以下为必要验证清单，**不是本轮全部执行通过的结果**。实施任务提交方案时须落实用例、数据集和真实环境证据。

| 编号/工作包 | 触发条件 → 必须响应 | 既有用例入口 |
|---|---|---|
| C01/R-EVENT | 非法标识/版本/载荷 → 拒绝持久化且无部分写入 | `tests/unit/runtime/event_store/test_envelope.py`、`test_store.py`；需扩展真实 DB |
| C02/R-EVENT | 同事件重投、同键异内容、不同租户同键、并发追加 → 按批准语义去重或拒绝，任务内序列一致 | 同上；需跨进程验证 |
| C03/R-PROJ | 给定事件，执行命令/消费，再重放两次 → 相同事件事实与投影；重复、乱序、缺口不能静默跳过 | `tests/unit/runtime/projection/test_projector.py`、`test_rebuilder.py` |
| C04/R-CHECK | 快照哈希、事件水位或资产版本不匹配 → 拒绝恢复/按已批准策略处理，保留诊断 | `tests/unit/runtime/checkpoint/test_models.py`、`test_recovery.py` |
| C05/R-IDEM | 同意图同摘要重试 → 仅一次副作用；同键不同摘要 → 拒绝；并发 → 一个有效执行者 | `tests/unit/runtime/idempotency/test_manager.py`、`test_storage.py`；需真实账本 |
| C06/R-IDEM/R-COMP | 下游已写但回执丢失、租约过期或缓存清空 → 核查结果，不盲目重发；权限错误不自动重试 | `tests/unit/runtime/idempotency/test_reconciler.py`、`test_escalation.py` |
| C07/R-QUERY | 跨租户/跨资源、非法分页、脱敏失败 → 拒绝或完全脱敏，无原值泄漏；分页快照内无遗漏重复 | `tests/unit/runtime/query/test_store_integration.py`、`test_redaction_regressions.py` |
| C08/G-HAR/R-RECOVER | 等待审批、暂停、取消及终态后请求动作 → 不新增禁止的业务副作用；恢复不重复已确认动作 | `tests/unit/runtime/state_machine/test_validators.py`、`tests/unit/runtime/worker/test_worker_executor.py` |
| C09/G-OBS/O-TRACE | Trace 未采样或传播失败 → 必需审计仍完整；日志无敏感值 | `tests/unit/runtime/trace/test_propagation.py`、`test_audit_correlation.py` |
| C10/各生产方与消费者 | 旧版读写、新增可选字段、未知版本、迁移中断 → 保留原事件与回滚/前向兼容路径 | 各工作包补充跨版本 fixture 和集成验证，不以本轮单测替代 |

G-RT 文档验收：八份冻结记录保留；调用字段、错误语义、版本兼容和测试清单可追溯；所有差异有归属且未擅改共享字段；专属文件链接可解析。完成本工作包只解除契约核对依赖，不自动批准任何下游方案。

## 7. 验证与交付记录

未修改生产代码、正式测试、依赖或冻结 REQ；运行既有测试仅为当前工作区的局部回归证据，其他会话修改不归为本会话成果。

| 测试项 | 用例/方法 | 结果 | 修复动作/限制 |
|---|---|---|---|
| 冻结版本 | 读取全部八份 RT REQ，逐份断言对应 frozen 版本及 2026-10-07 日期存在 | 8/8 通过 | 无；保留原文件 |
| 文档链接 | 解析本文件 Markdown 本地链接，按文档目录解析目标 | 11/11 通过 | 无断链 |
| Runtime 局部回归 | `.venv/Scripts/python.exe -m pytest tests/unit/runtime -q --no-cov` | 843 通过，0 失败，0 跳过；1.43 秒；143 条告警 | 告警包括测试辅助类收集提示、Pydantic 与 UTC 时间弃用；本轮未改测试或生产代码，未处理这些既存告警 |
| 静态类型/Lint、SAST/SCA/Secret、全量回归及覆盖率 | 本次为专属契约核对文档交付，未更改可执行代码或依赖 | 本轮未执行 | 不引用历史结果作为本次通过，不声称生产质量门禁或覆盖率达标 |
| 真实 PostgreSQL、跨进程竞态、弱网/超时/取消恢复、端到端与完整 Harness 契约 | C01～C10 按各实施任务及里程碑执行 | 本轮未执行 | 必须在相关任务取得实施批准并集成后验证；843 单测不能替代这些验收 |

复盘：接口注释与具体返回值、稳定逻辑身份与随机公开键、设计版本与冻结状态需要分别核实。后续实施应先将表中差异变成方案中的明确决策与可失败用例，再修改调用双方。

启动/复核：仓库根目录使用 `.venv/Scripts/python.exe -X utf8 scripts/task_board.py show G-RT` 查看状态；使用 `.venv/Scripts/python.exe -m pytest tests/unit/runtime -q --no-cov` 运行既有 Runtime 测试。

剩余事项：各表列出的生产差异、真实持久化/跨进程故障验证、安全与 OBS 共享映射及 M1 汇合验收。用户验收前保持“待验收”，不自行 accept。
