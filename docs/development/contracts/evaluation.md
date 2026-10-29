# G-EVA：评估与发布契约核对及实施基线提案

日期：2026-10-29（Asia/Shanghai）。负责人：`codex-geva-20261029-01a185f6`。

交付范围：EVA-001～007 的接口核对、差异处置建议、下游实施边界和验证清单。本文是待用户验收的契约评审材料；第 5～8 节标注的补充设计尚待确认，不能视为已冻结的生产契约。实时状态只认[共享台账](../task-board.json)。

## 1. 本轮目标、授权和写入范围

目标：让 E-DATA、E-SCORE、E-GATE、E-FEED 能使用同一组输入、结果、版本与证据口径制定实施方案，避免把缺失评估、过期批准或不可比较的分数作为发布依据。

- 已按[执行手册](../../../项目开发执行手册.md)领取 G-EVA，模式为 implementation；G 类授权仅涵盖契约文档。
- 唯一业务文件写入范围：`docs/development/contracts/evaluation.md`；台账通过 `scripts/task_board.py` 的锁内更新接口维护。
- 本轮未修改生产代码、正式测试、七项 REQ、共享 Runtime/OBS/SEC 契约或依赖；不创建发布、回滚或外部通知动作。
- 开工发现 G-MEM 已被 `codex-gmem-20261029-01a185f7` 领取，claim 被拒后改领 G-EVA，未写 G-MEM 文件。
- G-EVA 文档验收不等于下游实施批准，不等于七项 REQ 或 M1/M2 的整体验收。

| 任务 | 本轮开工状态 / 负责人 | 实现硬依赖 | 阻塞或下一步 |
|---|---|---|---|
| G-EVA 评估与发布契约 | 开发中 / 本会话 | 无 | 交付本文，等待用户确认差异处置与验收 |
| E-DATA 数据集与标注 | 待开发 / 无 | G-EVA | 本任务验收后仍需自身实施基线确认 |
| E-SCORE 评分与归因 | 待开发 / 无 | G-EVA | 同上；真实模型、Harness 重放由集成验证证明 |
| E-GATE 回归与发布门禁 | 待开发 / 无 | E-DATA、E-SCORE | 门禁、触发器和 Error Budget 的具体补充见本文 |
| E-FEED 生产反馈与回滚 | 待开发 / 无 | G-EVA | 真实 OBS、发布执行器、SEC 联动留到集成验收 |
| G-RT / G-MODEL | 待验收 / codex-grt-20261029-01a185ef | 各自无 | 读取关联材料；不把在审文档当作新增冻结事实 |
| S0-SCHEMA | 待验收 / codex-schema-20261029-a942yseg | 无 | 与本文无写入重叠；保留其他会话成果 |

以上是领取时快照，不能用于判断后续占用。G-EVA 无硬依赖不表示评估产品无跨模块依赖。本文涉及身份、运行时、指标和执行器的联调需求，不擅自修改台账 DAG。

## 2. 需求与现状证据

依据[需求分析报告](../../需求分析报告.md) §5.6、[评估主题规范](../../design-specs/05-evaluation-system.md)以及以下专项页核对。七项设计存在不代表七项已实现。

| REQ 与原文位置 | 专项页头版本 | 可复用内容 | 尚缺内容 / 下游 |
|---|---|---|---|
| [EVA-001](../../design-specs/REQ-EVA-001-golden-dataset.md) §10～13 | v0.1-designed | 五血缘、Oracle、来源快照、清单哈希、封存集 | 数据集仓储、入集与污染闸门、签名验证；E-DATA |
| [EVA-002](../../design-specs/REQ-EVA-002-annotation-specification.md) §2、§7～9 | v0.1-designed | 六层标注、must-have/rubric、人审与一致性 | 与 Oracle 枚举适配、标注权限和复审流程；E-DATA |
| [EVA-003](../../design-specs/REQ-EVA-003-automated-scorer.md) §8、§10～16 | v0.1-designed | JudgmentResult、EvaluationRecord、独立 grader、人工复核 | 状态条件字段、降级语义、评分器校准；E-SCORE |
| [EVA-004](../../design-specs/REQ-EVA-004-failure-attribution.md) §4、§8、§11、§13～18 | v0.1-designed | 症状/阶段/根因三轴、证据链、反事实验证 | AttributionResult 完整 wire schema、候选数量一致性、真实重放；E-SCORE |
| [EVA-005](../../design-specs/REQ-EVA-005-regression-pipeline.md) §8～10、§12～16 | v0.1-designed | FULL/SUBSET/INCREMENTAL、EvaluationReport、ATIF | 执行器、缺失结果计数、基线可比性、CI 接入；E-GATE |
| [EVA-006](../../design-specs/REQ-EVA-006-release-gate.md) §5～10 | v0.1-designed | 四层检查、四种发布决策、审批、四类回滚触发 | 安全阈值对齐、统一触发器、Error Budget、有效审批绑定；E-GATE |
| [EVA-007](../../design-specs/REQ-EVA-007-production-feedback-dataset-rollback.md) §5～10、§14 | v1.0-designed | DriftReport/Trigger、RollbackDecision、VersionBundle、生产入集 | 与 EVA-006 对接、字段补全、稳定版本判定、真实执行；E-FEED |

需求分析摘要曾把 EVA-004/EVA-006 写为 v0.2；专项页头与变更记录仍为 v0.1-designed。本轮保留实际文件版本，不把摘要升级视为批准证据。后续确认应同时固定文件哈希及批准范围。

代码检索结果：未发现 `src/evaluation/` 或正式 Golden Dataset/评分/发布决策模块；现有 `evaluation` 命中主要是 Policy 或 MCP 隔离评估语义。可复用基础是：

- [安全检查入口](../../../scripts/security_gate.py)及[其回归测试](../../../tests/test_security_gate.py)：报告有效性、SAST/SCA/Secret 的失败关闭。
- [统一 API 响应](../../../src/api/schemas/common.py)：`code/message/data/trace_id` 及既有业务错误码。
- [EventEnvelope](../../../src/runtime/event_store/envelope.py)、[任务投影](../../../src/runtime/projection/task_projector.py)：身份/追踪坐标与实际事件消费方式。
- [幂等契约](../../design-specs/REQ-RT-007-idempotency-key.md)：首次派发前持久化逻辑意图；同键不同摘要必须拒绝。
- 现有 pytest/Nox/扫描工作流能提供工程检查证据；不能替代评估数据集、评分器或真实发布回滚。

## 3. 相关产品对标（查阅日期 2026-10-29）

| 官方资料 | 本轮已验证的公开做法 | 优点与本项目建议 |
|---|---|---|
| [Anthropic：Demystifying evals for AI agents](https://www.anthropic.com/research/demystifying-evals-for-ai-agents)，2026-01-09 | 区分任务、试次、grader 与环境最终结果；区分能力评估与回归评估，成熟能力可以进入回归套件 | 借鉴试次与可核验结果、两类套件分报；模型声称成功不能代替真实副作用核查 |
| [Cursor：How we compare model quality in Cursor](https://cursor.com/blog/cursorbench)，2026-03-11，正文含 2026-05 更新 | 用实际内部使用任务构建离线评估，并与受控线上评估结合；不同评估版本的分数不直接比较 | 借鉴版本内比较与生产反馈闭环；避免把公开榜单或单一评分当成项目发布结论 |

上表只引用公开方法。本文的租户权限、阈值、状态机、字段和回滚规则来自项目约束或明确标注的提案，不是对产品内部实现的断言。旧设计中的成本节约百分比、并发量和竞品内部模块名，本轮未验证为产品事实，也未当作本项目实测结果。

## 4. 直接沿用的规则与历史确认

1. 2026-10-28 已确认质量阈值：总体行 ≥70%、核心行 ≥90%、分支 ≥60%，鉴权/授权、Policy Gateway、幂等、Checkpoint、审计写入的指定关键路径为 100% 行覆盖。扫描未执行、缺工具或失败记未验收。
2. 安全门禁适用[迭代规则](../../../规则文档/AGENTS.md)和手册：SAST 高危 ≥1 或中危 ≥5 阻断；SCA 高危 ≥1 阻断；有效 Secret 命中 ≥1 阻断。既有 SCA 适配器缺少可靠 severity 时阻断所有 advisory，本次不放宽。样例豁免沿用既有按文件和内容指纹复核的机制，不按名称批量忽略。
3. EVA-006 的 `HIGH≤2`、Secret 有命中仍 PASS 的示例不作为有效实施阈值；这是已确认项目规则的应用，无须重新选择宽松阈值。
4. Capability 与 regression 分开报告；能力增长不能抵消 regression 退化。评估器、数据、模型、Prompt 或工具变化必须能追溯；本轮保留迭代规则的阻塞要求。
5. [2026-10-08 用户决策记录](../../design-specs/REQ-EVA-006-007-接口协同评审.md)继续有效：EVA-006 定义统一触发器并负责 Error Budget；`drift_detected` 接入 `should_auto_rollback` 新分支；P0 先自动回滚，4 小时内 VP 补审批；金丝雀回滚由 EVA-007 定义。不重复询问这些方向。
6. 第 5 条是未来产品的运行机制，不授权本会话触发实际回滚或代替用户签审批。G-EVA 只交付契约材料。

## 5. 差异与需确认的具体方案

下表为基线确认清单。所有“建议”仍未写入 REQ 或生产代码；确认后应由相应工作包在既定写入范围和变更流程内落实。本文不会单方面冻结共享字段。

| 编号 | 证据与影响 | 建议处置 | 调用方与兼容规则 |
|---|---|---|---|
| Q1 Oracle 枚举 | EVA-001 §10.5 用 MANUAL_REVIEW/COMPOUND；EVA-002 §2.1 用 HUMAN_REVIEW/COMPOSITE | 规范输出沿用 EVA-001；读取旧标注时显式映射 HUMAN_REVIEW→MANUAL_REVIEW、COMPOSITE→COMPOUND；记录原始版本；未知值拒绝 | E-DATA 写出、E-SCORE 读取；扩读后统一新写，不改历史原始记录 |
| Q2 版本递增 | EVA-001 §11.1 新增样本为 patch；EVA-007 §9.2 为 minor | 内容、成员、Oracle、毕业/降级或难度变化至少 minor；Schema/血缘语义破坏为 major；patch 仅不改变评估语义的元数据修正 | E-DATA、E-FEED、E-GATE；历史版本保留，结果比较仍以清单哈希为准 |
| Q3 记录与缺失证据 | EVA-003 §8.2 所有状态均要求 judgment_result/completed_at；Oracle 不可用可降级 LLM；EVA-005 计数无跳过/无结果 | 以状态约束可选字段；缺失必需 Oracle、cannot_tell 或审核未决不得 PASS；补充第 6 节完成度记录 | E-SCORE→E-GATE；版本化扩展，不用零分或空对象伪造完成 |
| Q4 报告可比性 | EVA-001 §4 禁止混合总分；EVA-005 §9.1 有 overall；EVA-006 §6.3 单维退化仅告警，与迭代规则冲突 | overall 仅计数/成本展示；决策按 eval_type×lineage 分组；同清单、Oracle、rubric、环境、试次策略比较，差异列明；回归退化按项目规则阻断 | E-GATE/C-EVAL/A-ROUTE；禁止静默混分或换数据后宣称提升 |
| Q5 归因边界 | EVA-004 §4.2 top-k=5，§13/§18 top-3；完整 AttributionResult 尚未定义 | 初始基线最多验证 top-3；输出带三轴、判定、候选、反事实运行引用和证据引用；未完成验证为 INCONCLUSIVE | E-SCORE→E-GATE/E-FEED；不能把 RELATED_STEP 当作确认根因 |
| Q6 回滚 wire schema | EVA-007 §6.4/§10.3 的 DriftTrigger 不同；算法有事后审批字段而 §6.5 无；EVA-006 无统一类型 | 采用 §6.4 的窄枚举、保留可选字段；增加统一版本化信封和事后审批字段，详见第 7 节 | E-FEED→E-GATE→执行器；legacy 输入必须适配，不能凭空补身份/证据 |
| Q7 Budget 与稳定目标 | 归属已确认，但窗口、分母、失效行为、稳定 Bundle 及 Prompt 快照仍未定 | 按第 7 节明确比例单位、完整性、权威来源和兼容验证；缺数据不视为预算充足；Bundle 补 Prompt/Policy 引用 | E-GATE/E-FEED/G-OBS/G-SEC/G-MODEL；安全策略回退须额外验证不放宽当前安全底线 |
| Q8 事件与指标映射 | EVA-007 §10.3 写 task.execution.failed；代码消费 TaskFailed；OBS 文档提到 gen_ai.evaluation.result 但未明确血缘维度 | 在边界适配器注册来源与版本映射；未知来源拒绝；血缘保存在评估记录中，指标维度需 G-OBS 确认 | 不修改 RT-003 冻结 envelope 或创造事件别名；G-RT/G-OBS 共同评审后真实接入 |

Q1/Q2/Q3/Q4 为“数据与评分基线”；Q5 为“归因基线”；Q6/Q7/Q8 为“跨模块接口基线”。用户可分组确认。Q4 需确认的是字段和可比性细节，分报及回归阻断规则直接沿用。已确认的安全阈值、Error Budget 归属和 P0 自动回滚方向不包含在重新选择范围内。

## 6. 数据、执行、评分与门禁接口提案

### 6.1 接口边界与可复现性

以下为拟议服务边界，不是已经存在的 HTTP 路由。后续若暴露 HTTP，复用现有 envelope；新增端点/错误码须在所属工作包确认，不由本文冻结。

| 边界 | 输入（最小必需信息） | 输出 | 不变量 |
|---|---|---|---|
| 数据集发布：E-DATA | GoldenDataset + 任务快照 + 已批准标注 + 签名请求 | 版本、manifest_hash、签名引用、成员清单 | 数据集任务 ID 与生产 task_id 分离；只有已验证、可判定和有权限的样本能入集 |
| 执行：E-GATE→E-SCORE/Harness | RunManifest + 任务引用 + 试次号 + 资源预算 | EvaluationRecord + trace/artifact/evidence 引用 | 每次重试是可追溯的 attempt；不覆盖先前失败试次 |
| 评分：E-SCORE | 被测产物引用、Oracle、rubric、scorer/model 版本 | JudgmentResult + 完成度 + 校准引用 | 0≤score/confidence≤1；必需准则缺证据进入审核；grader 不接收被测 Agent 内部推理 |
| 归因：E-SCORE | 失败记录、轨迹、版本固定的重放环境 | AttributionResult、EvidenceChain、RootCauseContract | confirmed 必须有反事实证据；相关性描述不能自动升级根因 |
| 门禁：E-GATE | 完整评估报告、扫描证据、GatePolicy、批准记录 | 版本化发布决策及各检查理由 | 任何必需证据无效均不生成有效发布许可 |
| 反馈：E-FEED→E-DATA | 脱敏后失败事件与来源、去重/污染/Oracle/难度检查 | 候选样本 + 审批状态 | 生产记录不直接成为 APPROVED 数据集；敏感内容仅引用受控存储 |

RunManifest（新增评估专属伴随记录，不扩改 EventEnvelope）最小字段：

- `schema_version`、`evaluation_run_id`、`suite_id`、`suite_version`、`eval_type: CAPABILITY|REGRESSION`、`evaluation_mode: FULL|SUBSET|INCREMENTAL`。
- `organization_id/project_id/repository_id`、`actor_id`、`trace_id` 来自可信执行上下文；不得接受模型自行指定租户身份。
- `dataset_ref: {version, manifest_hash, signature_ref}`；`task_snapshot_refs`；`oracle_version`、`annotation_version`、`rubric_version`、`scorer_version`、`gate_policy_version`。
- `bundle_ref`、`model_snapshot`、`prompt_ref`、`worker_revision`、`tool_schema_refs`、`environment_digest`；缓存键必须覆盖这些影响结果的输入及租户/授权范围。
- `trial_policy: {trial_count, seeds, timeout_seconds, retry_limit}`；`selected_task_ids`、`selection_reason`、`baseline_run_id`（可空）、`created_at`（UTC）。

以上标识/引用为非空值，版本不可被可变别名替代；哈希使用实际算法和内容摘要，`sha256` 为 64 位十六进制；时间必须带时区。正数 timeout/trial_count、非负 retry_limit；上限由审批后的套件策略固定。固定种子保证输入可重建，不承诺远程模型逐 token 确定性。缓存命中也保留版本与来源证明。

### 6.2 状态、计数与错误语义

沿用 EvaluationRecord 状态集合：`PENDING → RUNNING → COMPLETED|FAILED|PARTIAL`。PENDING/RUNNING 不要求最终 judgment 或 completed_at；终态必须带 completed_at 和完成度。取消先停止派发并清理资源，再以 `PARTIAL` 和伴随 `terminal_reason=CANCELLED` 记录；本提案不增加 Runtime Task 状态。

- COMPLETED：本次试次的必需执行与评分均有可判定结果；测试失败可使 `pass=false`，不能与评估器执行失败混淆。
- FAILED：执行设施、输入或校验失败导致无法形成有效结果；PARTIAL：仅有部分结果、超时、取消或等待审核。两者均不能自动满足发布门禁。
- **Q3 补充提案：人审闭环**。PARTIAL 是该次执行记录的终态，审核结果以追加的 `ReviewResolution` 记录关联 `evaluation_id/judgment_id`，包括审核者、权限范围、证据引用、时间及决定。原记录不改写；聚合器生成新的报告版本，同时保留原始状态与有效复核结果。只有授权复核完成且全部必需 Oracle 有效时，该试次才可计为 passed/failed；缺失必需 Oracle 不能用人工批准补造 PASS。报告内容改变后，旧发布许可失效，必须重新执行门禁。重复复核命令按既有幂等契约去重，冲突复核返回 40901，不取最后写入覆盖。
- 每个血缘/评估类型的 `planned=passed+failed+skipped+inconclusive`；`completion_rate=(passed+failed)/planned`，`pass_rate=passed/planned`。planned=0 时两项为 null，**报告完成度**标记 NOT_EVALUATED（不是 EvaluationRecord 的新状态）；不得算作 100%。缺失结果算入 inconclusive，不能从分母删除。
- **Q3/Q4 补充提案：计数单位**。上述 planned 固定为 `(task_reference_id, trial_index)` 的计划试次数；同一试次的重试 attempt 和人审修订都不增加分母。每个试次只汇总一次当前有效结论，历史 attempt 和复核证据仍保留。原 EVA-005 的 total_tasks 继续表示去重任务数，新增伴随统计 trial_count/attempt_count，禁止把试次数静默写成任务数。归因准确率另按 EVA-004 §6.4 报告可判定子集的分母及 INCONCLUSIVE 数量，不能拿该子集代替发布所需的全部计划试次。
- 统计检验仅比较合格同分布/配对证据，样本量不足、缺失基线或无效 CI 返回不可判定；不输出伪造的 p-value。真实模型波动的复测次数须预先固定，禁止只挑最好试次。
- 身份/权限错误：沿用 40301/40302；资源不存在 40401；同键异摘要或过期状态 40901；参数不合法 42201；上游不可用 50301。Domain reason 用内部结构化证据保留；对外 message 不泄露样本、其他租户或安全策略。
- 评分超时沿用 EVA-003 的最多重试 1 次，但受整体 deadline 约束；只对可重试外部故障重试。Oracle 不可用时 LLM 可提供辅助意见，必需 Oracle 闸门保持未决；权限、Schema、签名和审批错误不自动重试。

### 6.3 门禁阈值和决策

本节阈值是“待确认的 EVA 评估配置 + 已确认的工程底线”，不是本次实测成绩。

| 检查 | 原设计配置 / 本轮处理 |
|---|---|
| 冒烟 | 100%；非空计划，所有必需用例有结果 |
| 五血缘能力基线 | 原 EVA-006：REAL_OWN_REPO 95%/0.90；REAL_EXTERNAL 90%/0.85；SYNTH_PROPERTY 85%/0.80；SYNTH_ADVERSARIAL 80%/0.75；SYNTH_STRESS 75%/0.70。保留来源，按 Q4 确认其适用套件后启用 |
| Regression | 分套件与血缘报告，按既有迭代规则阻止退化；上述能力阈值不能掩盖已成功任务的回退 |
| 安全 | 第 4 节已确认阈值；真实扫描有效性先于计数判定；对抗能力分数不能抵消越权、泄露、逃逸等安全硬失败 |
| 性能 | 原 EVA-006 p95/Token 增长 >20%、成本增长 >10% 为告警；仍须满足任务自身硬性能验收标准 |
| 数据与评分质量 | EVA-001 v0.1：真实≥50、安全≥30、每血缘≥5、封存≥10；v1.0：≥100/≥70/每血缘≥10/封存≥20。标注 alpha≥0.7；评分人机一致性≥85%、评分器间 alpha≥0.8，分别报告 |

发布决策沿用 `ALLOW/DENY/CONDITIONAL/OVERRIDE`；结果必须绑定 release/baseline 版本、RunManifest 哈希、policy 版本、证据哈希、目标范围、时间及审批主体。**新增提案**：过期时间、授权版本、有效范围随许可记录，执行发布前再校验，防止报告生成后产物变化仍使用旧许可。

ALLOW 要求全部必需硬检查完成且通过；DENY 记录阻断原因；CONDITIONAL 仅在有效、范围一致的例外批准后成立；等待审批期间仍 DENY。OVERRIDE 保留原文三人且含一位 VP、两小时窗口、仅 hotfix/security_patch/rollback、72h 监控与修复要求。安全硬失败的豁免范围未得到额外批准，不开放通用绕过通道，也不从普通产品审批推导安全豁免。

## 7. 漂移、Error Budget 和回滚接口提案

### 7.1 统一触发器

落实既有用户决定：由 EVA-006 定义 `ReleaseGateTrigger`，DriftTrigger 为第五类 payload。提议必需信封字段：`schema_version/trigger_id/trigger_type/occurred_at/organization_id/project_id/release_version/evidence_refs/trace_id`，携带可信 actor 与既有 Runtime 逻辑幂等键。去重必须使用运行时契约，不新造对外幂等算法。

五类 payload 的判别值提案为 `post_release_regression/alert_storm/health_check_failure/kill_switch/drift_detected`；前四类来自原回滚原因，枚举尚待确认。`drift_detected` 使用 EVA-007 §6.4：

- drift_dimension 仅四种已设计枚举；severity 为 P0/P1/P2。
- metric_name、baseline_value、current_value、degradation_pct、affected_task_types、suspected_cause、evidence_trace_ids 必需；affected_lineage 与 target_version 可选。
- recommended_action 仅 rollback/hold/alert，是推荐，不是授权。CONDITIONAL 只出现在 RollbackDecision，并保持暂停扩量及等待审批。
- degradation_pct 的单位是百分数，pass_rate 和 Budget.remaining_pct 使用 0～1 比例；不得把 50 与 0.50 混用。指标必须携带/绑定具体公式版本，不用一个通用相对变化公式覆盖所有维度：成功率与 regression 分数沿用 EVA-007 §5.2 的 `(baseline-current)/baseline*100`，baseline=0 时标记不可比较；模型行为使用 `(1-similarity)*100`，余弦相似度范围 [-1,1]，因此劣化值可以达到 200；评估集老化使用 `stale_ratio*100`，其 baseline=0 是已设计的合法绝对比例基线。禁止将所有 degradation_pct 强制限制到 [0,100]，也不得将合法的老化信号静默丢弃。NaN/Infinity、超出各指标定义域及未知公式版本拒绝。

`should_auto_rollback` 接收已验证的统一触发器，漂移分支不受“发布后 1 小时”窗口限制；原短窗口检查保留自己的窗口。未知版本、未授权租户、无效证据直接拒绝。

### 7.2 Error Budget

归属 EVA-006 已确认；下面是所缺细节的提案：

`ErrorBudgetSnapshot = {policy_version, metric_name, scope, window_start, window_end, observed_at, slo_target, total_eligible, failed_eligible, remaining_pct, completeness, evidence_refs}`。

- policy 固定具体指标、窗口长度、样本资格、最小样本量与最大数据年龄；这些参数不能由漂移调用者临时传入覆盖。数值按应用 SLO 单独批准，本文不假设统一 99.9% 或统一窗口。
- `allowed_failures=(1-slo_target)*total_eligible`；预算可用时 `remaining_pct=max(0,min(1,1-failed_eligible/allowed_failures))`。slo_target 必须在 (0,1]；样本不足、allowed_failures=0、报告过期或不完整时 remaining_pct=null 并标记不可用。
- **Q7 补充提案：阈值精度**。决策必须使用输入十进制原文的精确有理数或等价定点整数计算。预算≥50%的判定等价于 `2*failed_eligible ≤ allowed_failures`，在相同精确单位下比较；不要用二进制浮点或显示用的舍入值判断权限分支。样例 slo_target=0.9、total=100、failed=5 必须得到恰好 0.5/HOLD；不能用 isclose 验证数值后仍以 `<0.50` 走错误分支。总数/失败数须为非负整数且 failed≤total，不接受 NaN/Infinity；有效性检查先于公式计算。
- P0 直接走已确认自动回滚决策；P1 在新鲜完整预算≥0.50时 HOLD 观察 7 天，<0.50 时 CONDITIONAL、停止扩量并需批准；预算不可用也停止扩量/人工处理，不当作充足。P2 按已设计仅告警。
- Budget 来源须由可信观测/发布服务提供且保留原窗口证据；不据此把观察窗口内不同数据集版本的分数拼成一个通过率。

### 7.3 决策与执行分离

沿用 RollbackDecision 的四个状态，补充原算法已使用但 Schema 缺失的 `requires_post_approval/approval_deadline/auto_approved`，其中 auto_approved 只代表策略命中，不伪造人类 approved_by。P0 的 deadline 为决策时间+4h；迟于期限触发审计告警和升级，不倒填批准时间。

VersionBundle 保留 model/dataset/grader/worker 的固定版本，补充可校验 `prompt_ref/policy_ref` 和 `manifest_hash`（提案），避免声称配置可回滚却没有配置快照。目标应为有验收/健康证据、身份范围一致、ACTIVE+STABLE、兼容当前基础设施的 Bundle；“上一个版本”不足以证明稳定。

**需确认的安全衔接细节**：P0 立即产生回滚决策，执行仍验证目标兼容性、已授权范围和既有不可逆迁移限制。目标不可用、RISKY/BLOCKED 或重复振荡时停止扩量并升级；不随机回退、不绕过 Policy、不降低安全策略。原“24h 内 3 次回滚阻止振荡”与 P0 的衔接按此建议处理。Kill Switch 的具体模式由 G-SEC/SEC-009 对齐，本文不自行跳档。

执行器状态另存为请求、执行中、成功、失败/待人工，不复用发布 ALLOW 或漂移 ROLLBACK 来表示“已回滚”。外部回滚可能成功但回执丢失时，先按幂等契约核查目标实际状态，再决定是否重试；原任务和历史证据保留。EVA-006、EVA-007 共用一次执行意图，不能分别执行两次回滚。

## 8. 权限、数据和共享契约影响

- 服务端传播租户/项目/仓库授权范围；数据集、holdout、产物、报告、审批、回滚目标与缓存都必须在范围内。评估执行权限不等于发布、回滚或导出敏感样本权限。
- 评估工程师可管理授权样本；发布决策/例外依照审批角色；安全样本由安全角色复审；P0 补审批按 EVA-007 VP 权限。跨租户、角色伪造和模型填写 approved_by 均拒绝。
- 不可信仓库、任务描述、模型输出与工具轨迹不得修改 rubric、Oracle、安全规则或评分器自身代码。Oracle 命令必须在已批准隔离执行环境内运行，不在控制平面任意执行。
- 成功/失败/审批/发布/回滚均产生可关联审计证据。审计不可写时不发新发布许可；实际动作结果未知时核查、补记并升级，不声称成功。P0 执行与审计故障的恢复顺序须在 E-FEED 的真实集成方案确认。
- EVA-001 的封存永久留存与 EVA-005 分层轨迹留存面向不同数据对象；身份删除、Legal Hold、证据不可变性由 G-OBS/G-SEC 统一策略决定。本轮不执行任何删除或统一缩短留存。
- 不把 EvaluationRecord 当作冻结 EventEnvelope 的子类扩字段；可通过类型化 payload 或受控 Artifact 引用接入，但 event_type/payload_schema 注册须走 G-RT 评审。EVA-007 的示例事件名不能直接替代生产消费者使用的名字。

迁移顺序建议：先批准本文限定方案→相关任务细化 wire schema/共享变更记录→扩展读取与版本校验→双向契约验证→启用新写入→观察兼容证据→另行批准删除旧读路径。未知 major 拒绝；兼容 minor 的未知可选字段可保留，未知决策/权限枚举不能默认 ALLOW。不得改历史结果以制造一致性。

## 9. 固定输入样例与验收清单

以下 JSON 为纯合成的算术与决策样例，不是 Golden Dataset、正式契约测试或发布证据。展示同一分母下部分结果不能变为通过、混合分数掩盖回归，以及数值边界、人审闭环和漂移单位。不能据此声称端到端验收。budget_cases 的 evidence_complete/data_fresh/enough_samples 是固定测试条件，真实系统必须从可信来源和版本化策略推导。

```json
{
  "completion_cases": [
    {"id":"full","planned":4,"passed":4,"failed":0,"skipped":0,"inconclusive":0,"expected_pass_rate":1.0,"expected_completion_rate":1.0},
    {"id":"partial","planned":4,"passed":2,"failed":0,"skipped":1,"inconclusive":1,"expected_pass_rate":0.5,"expected_completion_rate":0.5},
    {"id":"empty","planned":0,"passed":0,"failed":0,"skipped":0,"inconclusive":0,"expected_pass_rate":null,"expected_completion_rate":null},
    {"id":"completed_failure","planned":4,"passed":3,"failed":1,"skipped":0,"inconclusive":0,"expected_pass_rate":0.75,"expected_completion_rate":1.0}
  ],
  "separate_suites": {
    "baseline":{"capability_passed":2,"capability_total":10,"regression_passed":10,"regression_total":10},
    "candidate":{"capability_passed":8,"capability_total":10,"regression_passed":9,"regression_total":10},
    "expected_mixed_baseline":0.6,
    "expected_mixed_candidate":0.85,
    "expected_regression_delta":-0.1,
    "expected_release_decision":"DENY"
  },
  "budget_cases": [
    {"id":"half","slo_target":0.9,"total_eligible":100,"failed_eligible":5,"evidence_complete":true,"data_fresh":true,"enough_samples":true,"expected_remaining_pct":0.5,"expected_p1_decision":"HOLD"},
    {"id":"just_below_half","slo_target":0.9,"total_eligible":100000,"failed_eligible":5001,"evidence_complete":true,"data_fresh":true,"enough_samples":true,"expected_remaining_pct":0.4999,"expected_p1_decision":"CONDITIONAL"},
    {"id":"just_above_half","slo_target":0.9,"total_eligible":100000,"failed_eligible":4999,"evidence_complete":true,"data_fresh":true,"enough_samples":true,"expected_remaining_pct":0.5001,"expected_p1_decision":"HOLD"},
    {"id":"exhausted","slo_target":0.9,"total_eligible":100,"failed_eligible":12,"evidence_complete":true,"data_fresh":true,"enough_samples":true,"expected_remaining_pct":0.0,"expected_p1_decision":"CONDITIONAL"},
    {"id":"zero_denominator","slo_target":1.0,"total_eligible":100,"failed_eligible":0,"evidence_complete":true,"data_fresh":true,"enough_samples":true,"expected_remaining_pct":null,"expected_p1_decision":"CONDITIONAL"},
    {"id":"empty","slo_target":0.9,"total_eligible":0,"failed_eligible":0,"evidence_complete":true,"data_fresh":true,"enough_samples":false,"expected_remaining_pct":null,"expected_p1_decision":"CONDITIONAL"},
    {"id":"stale","slo_target":0.9,"total_eligible":100,"failed_eligible":5,"evidence_complete":true,"data_fresh":false,"enough_samples":true,"expected_remaining_pct":null,"expected_p1_decision":"CONDITIONAL"},
    {"id":"incomplete","slo_target":0.9,"total_eligible":100,"failed_eligible":5,"evidence_complete":false,"data_fresh":true,"enough_samples":true,"expected_remaining_pct":null,"expected_p1_decision":"CONDITIONAL"},
    {"id":"insufficient_samples","slo_target":0.9,"total_eligible":10,"failed_eligible":0,"evidence_complete":true,"data_fresh":true,"enough_samples":false,"expected_remaining_pct":null,"expected_p1_decision":"CONDITIONAL"}
  ],
  "drift_cases": [
    {"id":"success_rate_drop","dimension":"task_success_rate","baseline":0.8,"current":0.6,"expected_degradation_pct":25},
    {"id":"negative_cosine","dimension":"model_behavior","baseline":1,"current":-0.2,"expected_degradation_pct":120},
    {"id":"zero_staleness_baseline","dimension":"eval_dataset_staleness","baseline":0,"current":0.25,"expected_degradation_pct":25}
  ],
  "review_cases": [
    {"id":"review_pending","original_status":"PARTIAL","authorized_resolution":false,"mandatory_oracle_available":true,"review_pass":true,"expected_bucket":"inconclusive"},
    {"id":"oracle_still_missing","original_status":"PARTIAL","authorized_resolution":true,"mandatory_oracle_available":false,"review_pass":true,"expected_bucket":"inconclusive"},
    {"id":"review_resolved","original_status":"PARTIAL","authorized_resolution":true,"mandatory_oracle_available":true,"review_pass":true,"expected_bucket":"passed"}
  ]
}
```

正式实现须覆盖下列 Given/When/Then 场景；本轮仅检查设计覆盖，均未宣称产品测试已通过。

| ID / 下游 | 触发条件 → 必须响应 | 所需真实证据 |
|---|---|---|
| AC01 / E-DATA | Oracle/签名/脱敏不合格的候选入集 → 拒绝并记录原因；合法候选经批准才发布不可变版本 | 真实签名、存储、角色及污染测试 |
| AC02 / E-DATA/E-SCORE | 旧枚举或未知枚举输入 → 按版本映射或拒绝；跨租户引用 → 拒绝 | 双向 Schema 与授权集成 |
| AC03 / E-SCORE | Oracle 不可用、grader 超时、cannot_tell → 未决/重试有界/人审；授权复核且必需 Oracle 有效 → 新报告版本，原 PARTIAL 与审计保留，重新执行门禁 | 超时、弱网、人审幂等及冲突、旧许可失效；不得凭 LLM 分数或人审豁免缺失 Oracle |
| AC04 / E-GATE | 跳过、零样本、部分执行、取消 → 分母保留、结果完整性不足、无发布许可 | 取消资源回收、恢复与计数测试 |
| AC05 / E-GATE | capability 上升同时 regression 下降 → 单独报告并阻断回归；版本不可比 → 不作提升结论 | 固定试次、版本、集合和分布的比较 |
| AC06 / E-SCORE | 候选仅语义相关或反事实超时 → RELATED_STEP/INCONCLUSIVE；确认根因 → 有最小干预与证据链 | 真实 Harness 隔离重放；top-3 边界 |
| AC07 / E-GATE | 高危/中危阈值边界、Secret 命中、工具缺失、损坏报告 → 按实际规则阻断 | 真实扫描、原始报告与适配器测试分别提供 |
| AC08 / E-GATE | 审批未决/过期/范围或产物改变 → 旧许可失效；签名/租户不符 → 拒绝 | 身份、并发审批和发布执行器集成 |
| AC09 / E-FEED | 合法漂移按各维度公式解析（包括负余弦、零基线老化）；P0 → 立即形成回滚决策，合格目标执行一次，4h 内补审批；目标不合格 → 升级且无错误回退 | 指标定义域、固定时钟、跨进程幂等、真实目标核查 |
| AC10 / E-GATE/E-FEED | P1 Budget=0.50/略低/略高/过期/零分母 → 精确比较得到 HOLD/CONDITIONAL/HOLD/停止扩量待处理 | 完整窗口、样本计数、过期边界；断言实际决策，不能仅近似比较数值 |
| AC11 / E-FEED | 回滚成功后断网或执行器崩溃 → 核查实际目标，恢复审计且不重复副作用 | 故障注入、目标读回和恢复证据 |
| AC12 / E-FEED/E-DATA | 生产失败反馈 → 脱敏、去重、Oracle、污染和难度检查，再人审入集；毕业任务 → 新版本保留旧证据 | 真实生产事件适配、样本审批、版本兼容 |

里程碑：M1 使用真实 E-DATA/E-SCORE 验证 Issue→PR；M2 汇合 E-GATE/E-FEED、OBS/SEC 和发布/回滚执行器；C-EVAL 的检索 A/B 在 M3 汇合。固定 JSON 与替身只用于独立开发，不解除这些真实验收条件。

## 10. 本轮验证报告与复核方式

本轮假设：把已有契约的输入/状态/阈值歧义显式列出后，下游可以逐项确认并避免分数掩盖未完成工作。否证信号为字段无来源、旧决定被遗漏、合成例子被标成真实评估，或发生越界修改；发现后须修正文档再交付。

| 测试项 | 用例 | 结果 | 修复动作 / 限制 |
|---|---|---|---|
| 台账准入 | G-MEM 并发领取；随后 G-EVA 独占领取 | G-MEM 正确拒绝；G-EVA 成功 | 改选空闲任务，未抢占 |
| 需求映射 | EVA-001～007 版本、生产缺口、调用方、历史批准 | 七项均有对应记录 | 发现的差异列 Q1～Q8，待确认，未改共享 REQ |
| 既有门禁回归 | SAST 阈值、SCA advisory、Secret 指纹、超时、缺失/损坏/矛盾报告 | 53 passed，0 failed，0 skipped；pytest 报告 0.64s | 既有适配器测试，不是新增发布功能测试或真实扫描 |
| 本地文档检查（首次交付） | 相对链接、JSON 样例算术、必要章节与 REQ 覆盖 | 首次 19 个本地链接、1 个 JSON 块/8 个合成场景通过；后续复核发现该检查未覆盖实际决策分支，见第 12 节 | 历史结果保留；修订版以第 12 节为准，不作为产品测试 |
| 写入边界 | 交付前后比对 EVA 需求及相关评审文件 SHA-256 | 9 个既有文件摘要一致 | 业务写入仅本文；台账生命周期更新另计 |
| 台账结构检查 | 实时 task_board.py validate | 有效，62 项，依赖无环（检查时快照） | 任务数会随其他会话合法更新变化 |
| 安全/静态/覆盖 | 真实 SAST/SCA/Secret、ruff、mypy、覆盖率 | 本轮未执行，生产质量门禁未验收 | 仅文档写入；不挪用历史全仓结果作为本轮通过 |
| 产品与环境 | 真数据集、模型校准、端到端、弱网/恢复、真实发布/回滚 | 未执行 | 尚无 EVA 产品实现；AC01～12 留给所属任务 |

在仓库根目录可重跑：

```powershell
python -X utf8 scripts/task_board.py show G-EVA
python -X utf8 scripts/task_board.py validate
.venv/Scripts/python.exe -X utf8 -m pytest -q -o addopts='' -p no:cacheprovider tests/test_security_gate.py
```

文档内容可直接在 Markdown 预览中审阅；本轮无应用启动或部署步骤。算术样例按第 6.2/7.1/7.2 节公式复算；文档检查应解析本页 JSON、遍历本地 Markdown 链接并核对 Q1～Q8/AC01～12 的覆盖，不能只检查文件存在。

以下只读命令可复核链接和算术样例，无需新增测试文件：

```powershell
@'
from pathlib import Path
from decimal import Decimal
from fractions import Fraction
import json, re
p = Path('docs/development/contracts/evaluation.md')
s = p.read_text(encoding='utf-8')
links = re.findall(r'\[[^\]]*\]\(([^)]+)\)', s)
local = [x for x in links if not x.startswith(('https://', 'http://', '#'))]
assert all((p.parent / x.split('#')[0]).resolve().exists() for x in local)
v = json.loads(re.findall(r'```json\s*\n(.*?)\n```', s, re.S)[0], parse_float=Decimal)
def exact(value):
    return None if value is None else Fraction(value)
for c in v['completion_cases']:
    n = c['planned']
    assert all(type(c[k]) is int and c[k] >= 0 for k in ['planned','passed','failed','skipped','inconclusive'])
    assert n == sum(c[k] for k in ['passed','failed','skipped','inconclusive'])
    assert (Fraction(c['passed'],n) if n else None) == exact(c['expected_pass_rate'])
    assert (Fraction(c['passed']+c['failed'],n) if n else None) == exact(c['expected_completion_rate'])
t = v['separate_suites']
for name in ['baseline','candidate']:
    c = t[name]
    assert Fraction(c['capability_passed']+c['regression_passed'],c['capability_total']+c['regression_total']) == exact(t['expected_mixed_'+name])
d = Fraction(t['candidate']['regression_passed'],t['candidate']['regression_total']) - Fraction(t['baseline']['regression_passed'],t['baseline']['regression_total'])
assert d == exact(t['expected_regression_delta']) and d < 0
assert t['expected_release_decision'] == 'DENY'
for c in v['budget_cases']:
    assert 0 < exact(c['slo_target']) <= 1
    assert all(type(c[k]) is int and c[k] >= 0 for k in ['total_eligible','failed_eligible'])
    assert c['failed_eligible'] <= c['total_eligible']
    allowed = (1-exact(c['slo_target']))*c['total_eligible']
    available = allowed > 0 and all(c[k] is True for k in ['evidence_complete','data_fresh','enough_samples'])
    value = max(Fraction(0),min(Fraction(1),1-c['failed_eligible']/allowed)) if available else None
    decision = 'HOLD' if available and 2*c['failed_eligible'] <= allowed else 'CONDITIONAL'
    assert value == exact(c['expected_remaining_pct']), c['id']
    assert decision == c['expected_p1_decision'], c['id']
for c in v['drift_cases']:
    b, x = exact(c['baseline']), exact(c['current'])
    if c['dimension'] == 'task_success_rate':
        assert 0 < b <= 1 and 0 <= x <= 1
        degradation = (b-x)/b*100
    elif c['dimension'] == 'model_behavior':
        assert b == 1 and -1 <= x <= 1
        degradation = (1-x)*100
    else:
        assert c['dimension'] == 'eval_dataset_staleness' and b == 0 and 0 <= x <= 1
        degradation = x*100
    assert degradation == exact(c['expected_degradation_pct']), c['id']
for c in v['review_cases']:
    bucket = 'inconclusive'
    if c['authorized_resolution'] and c['mandatory_oracle_available']:
        bucket = 'passed' if c['review_pass'] else 'failed'
    assert bucket == c['expected_bucket'] and c['original_status'] == 'PARTIAL', c['id']
count = sum(len(v[k]) for k in ['completion_cases','budget_cases','drift_cases','review_cases'])+1
print(f'PASS: {len(local)} local links; {count} synthetic arithmetic/decision scenarios')
'@ | python -X utf8 -
```

## 11. 交付与后续准入

本次交付仅本文件：含需求/接口映射、官方对标、兼容及权限设计、固定样例、验收清单和如实的验证报告。待用户验收后才能由台账 accept 登记“已完成”；本轮不得自行填写批准/验收证据。

需用户确认：第 5 节 Q1～Q8 及其引用的第 6～8 节细节，允许按三组确认或逐条修改。批准本文后也须为 E-DATA/E-SCORE/E-GATE/E-FEED 分别提供明确实施范围和任务级基线；共享变更须与相关负责人协调，不凭 G-EVA 验收自动修改其他任务文件。

保留的开放事项：正式数据集来源及授权、受控模型/评分器版本、预算 SLO 数值和观测窗口、真实发布目标、跨模块字段注册、真实签名/审计/持久化适配器均须由下游方案落实。没有这些证据，不能声称整个 EVA 模块、REQ 或里程碑完成。

复盘：先运行 claim 能识别真实并发冲突；设计摘要与专项页版本必须分开核验；下游应优先实现“证据不完整时拒绝发布”的可演示闭环，再优化子集选择与并发性能。

## 12. 2026-10-29 用户请求后的技术验收复核

请求依据：本聊天用户“请你进行验收”。本次执行文档技术验收、问题修正和复测；该请求不是 Q1～Q8 的选择结果，也不是代填用户批准/验收记录的依据。

**结论：修订后的契约评审文档技术检查通过；G-EVA 的“用户确认基线”条件仍未满足，暂不放行下游生产实现。** 台账重新提交为待验收，approval_evidence/completion_evidence 保持未确认。生产质量、安全扫描与产品 AC01～AC12 不属于本次通过结论。

复核输入文件 SHA-256：`5fe9515aeeb86d8677ccdf999881ffc642f899f23337d8ff8edd101a1b3211b0`。此为修改前版本，修订后摘要随台账 submit 证据记录；不把两版证据混用。

| 编号 | 测试项 → 用例 | 初次结果 | 修复动作 → 复测结果 |
|---|---|---|---|
| RV01 | 预算边界 → SLO=0.9、100 个合格样本、5 个失败，P1 预算恰好 50% | 原浮点样例为 0.4999999999999999，误走 CONDITIONAL；原 isclose 校验未发现分支错误 | §7.2 明确精确十进制/有理数及交叉乘法判定；样例校验改为精确值和决策双断言；恰好/略低/略高及失效等 9 个预算场景通过 |
| RV02 | 人审状态闭环 → PARTIAL 等待审核后完成复核 | 原终态描述没有明确如何追加复核和形成最终报告，易发生永久未决或覆盖历史证据 | §6.2 补充 ReviewResolution、授权/Oracle 条件、报告新版本、旧许可失效、重复和冲突处理；待审/缺 Oracle/已复核 3 个决策样例通过；实际存储并发仍需 E-SCORE/E-GATE 集成 |
| RV03 | 漂移公式 → 余弦=-0.2；老化比例=0.25、基线=0 | 原统一 [0,100] 限制错误排除合法的 120% 模型行为劣化，零基线处理也未明确保留老化绝对比例 | §7.1 对齐 EVA-007 §5.2 各维度公式与定义域；成功率/负余弦/零基线老化 3 个样例通过 |
| RV04 | 校验灵敏度 → 仅在内存分别注入“50% 使用严格小于”“人审绕过 Oracle”“禁止负余弦” | 三个故意错误均触发 AssertionError | 3/3 检出；未把变异代码写入文件；证明样例校验能发现这些具体错误，不代表产品故障注入 |
| RV05 | 既有安全门禁回归 → 阈值、无效证据、超时、指纹复核 | 53 passed，0 failed，0 skipped，pytest 0.77s | 与首次 0.64s 记录分开；无须修改既有实现或测试 |
| RV06 | 文档完整性 → 链接、JSON、编号和格式 | 19 个本地链接、1 个 JSON 块、20 个合成算术/决策场景、7 项 REQ、8 项决策、12 项产品验收场景检查通过 | 校验命令见第 10 节；UTF-8/尾随空格检查通过 |
| RV07 | 共享契约与任务协作 → 检查 owner、依赖、写入范围，比较既有 EVA 文件摘要 | 9 份既有需求/评审文件 SHA-256 未变；台账有效，62 项，依赖无环（复核时） | 按执行手册使用 task_board 的 locked/read/validate/write 恢复本任务开发中；只修本页；重新 submit，保留原交付历史和其他任务状态 |
| RV08 | 实现准入 → 核对真实用户决定与新提案 | 历史安全阈值及 2026-10-08 回滚方向已沿用；Q1～Q8 无新增确认记录 | 不调用 approve-design/accept，不将技术检查当作用户决定；具体新增方案仍待确认 |

本轮没有运行真实 SAST/SCA/Secret、全仓静态/覆盖率、真实模型评估、生产发布或回滚；这些检查保持未验收。第 10 节脚本只验证本文样例与数学/决策一致性，不提供生产实现。

技术审阅建议：Q1～Q8 按修订后的提案继续评审，RV01～RV03 的修正分别归入原 Q7/Q3/Q6，不新增生产范围。下游仍需确定 SLO 数值/窗口、数据与模型来源、正式 wire schema 和跨模块注册，并完成各自任务级实施批准。
