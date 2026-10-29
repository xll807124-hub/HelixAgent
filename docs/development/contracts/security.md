# G-SEC 安全与租户共享契约核对

日期：2026-10-29。会话：`codex-gmem-20261029-01a185f7`。交付范围：契约评审材料；生产代码、正式测试、原始 REQ、共享类型均未修改。任务状态和确认记录以[实时台账](../task-board.json)为准。

## 1. 任务边界与已有决议

本任务解决安全模块之间“谁提供可信身份、谁批准、谁执行、如何撤销和证明生效”的接口缺口，为各实现工作包形成可评审的基线。G-SEC 的 implementation 模式仅授权本文件，依据[执行手册](../../../项目开发执行手册.md)“依赖驱动调度与多 AI 领取”；不表示九项安全 REQ 已整体冻结。

领取成功后核对的状态如下，仅作本次上下文快照，不能代替实时台账：

| 任务 | 状态 / 负责人 | 硬依赖 | 当前阻塞 / 本次计划 |
|---|---|---|---|
| G-SEC 安全与租户契约 | 开发中 / 本会话 | 无 | 完成核对、方案和验证证据；交付后待用户验收 |
| G-MEM 记忆契约 | 已完成 / 本会话 | 无 | 沿用已获用户确认的 D01～D09，不重开已确认问题 |
| G-RT 运行时契约 | 待验收 / codex-grt-20261029-01a185ef | 无 | 共享身份、事件与分类映射须协同评审；本次只读 |
| S0-SCHEMA 工具批准与 Schema 复审 | 待验收 / codex-schema-20261029-a942yseg | 无 | 保留其在研成果；不修改 MCP 代码与 REQ-SEC-007 |
| P-MEM 记忆实现 | 待开发 / 无 | G-MEM、G-SEC | G-SEC 未验收且自身实施基线未批准；不启动生产实现 |
| S-RBAC / S-CRED | 待开发 / 无 | G-SEC | 待本契约及各自实施基线；登记缺口供后续设计 |
| S-KILL / S-TENANT | 待开发 / 无 | G-SEC、G-RT | 同上；完整 Kill Switch 和租户隔离均未据此验收 |

没有本文件写入范围冲突。其他会话的工作区变更全部保留；未提交、推送或创建第二份协调台账。

直接沿用的已有决议：

- **SEC-004 §6 Q1～Q6**：能力抽象及风险路由；连接器声明→审批→版本化出口策略；隔离不得运行时降级；诊断/安全/合规三类留存但未冻结时长；Linux 生产路径；自适应 WarmPool，分配 p95≤200ms。不得重新解释为“所有容器默认有联网能力”。
- **SEC-009 §20 Q1～Q7**：分层响应指标、NORMAL/DEGRADED/LOCKED、分档触发与解除、分档留存及 Legal Hold、四层 Break-Glass、统一状态机和广播 ACK、Kill 发布模式而 Policy 执行策略。以下只澄清这些决议中尚不完整的边界，不重复请求批准。
- **G-MEM D01～D09**：已于本聊天“确认”后记入台账；本次沿用 Memory 写入不超时自动批准、硬性人工条件先于评分、不可变版本、未知权限拒绝、RT-001 分类为对齐方向、留存数值仍开放等决议。批准范围为后续设计依据，不等于 P-MEM 获准编码。
- 历史 SEC-007 生命周期及凭据失效切片已验收，继续复用；不把 S0-SCHEMA 的待验收成果写成已验收，不因发现新缺口撤销历史限定验收。

## 2. 逐项范围、已有实现与剩余验收

以下 REQ 均为 `designed`，不把文档存在或局部测试通过等同整体冻结。SEC-004、SEC-010 为 v0.2-designed，其余本表核心 REQ 为 v0.1-designed。

| REQ / 原始契约 | 本次核定的边界 | 已有成果与缺口 | 后续承接 / 必须保留的验收 |
|---|---|---|---|
| [SEC-001](../../design-specs/REQ-SEC-001-threat-model-risk-scoring.md) | T01～T15 威胁、I×L 风险、L1～L4 数据分级；硬约束不被评分抵消 | 多处分类类型不同；风险、数据级别、连接器信任级别不能共用数值 | S0-RED；版本化威胁追踪、分类转换及风险例外证据 |
| [SEC-002](../../design-specs/REQ-SEC-002-rbac-resource-authorization.md) | USER/TEAM/SERVICE/AGENT；平台→组织→项目→仓库→路径；拒绝优先、权限交集 | 有 RBAC 模型/评估器；Team 数据边界、委托链及可靠撤权需贯通 | S-RBAC、S-TENANT；逐 Action 重校验、检索前过滤、撤权故障及跨租户测试 |
| [SEC-003](../../design-specs/REQ-SEC-003-policy-gateway.md) | ALLOW/REQUIRE_APPROVAL/DENY；决策绑定、审批恢复、风险缓存 | 基础 Gateway 与 V2 请求/结果不同；没有完整统一决策凭证 | S-RBAC；真实 PEP、审批防重放、超时、缓存及不可用测试 |
| [SEC-004](../../design-specs/REQ-SEC-004-sandbox-isolation-baseline.md) | 已确认 Q1～Q6、能力证据、默认无出口、真实凭据不入沙箱 | Docker 对出口白名单/逃逸检测明确抛 NotImplementedError；不能声明完整能力 | S-BOX、A-POOL；真实 Linux 隔离/出口/清理/逃逸监测及分配基准 |
| [SEC-005](../../design-specs/REQ-SEC-005-credential-proxy.md) | PDP/CDP 分权、最小能力、签发/租约/撤销 | 有真实 GitHub HTTP 适配器；通用 CDP 仍示例铸造，TTL 与批准证明有缺口 | S-CRED；真实受众/范围/有效期、撤销传播与外部服务回执 |
| [SEC-007](../../design-specs/REQ-SEC-007-mcp-connector-governance.md) | L1～L4 信任、工具批准、签名/版本、黑白名单、撤销 | 已有生命周期及凭据切片；S0-SCHEMA 独立待验收；生产 OAuth/签名/出口/审计仍需真实集成 | S0-MCP；16 项 AC 逐项追踪，不能以局部切片覆盖全部 |
| [SEC-008](../../design-specs/REQ-SEC-008-multi-tenant-data-governance.md) | 每 Team 存储/密钥隔离、驻留、留存、删除及备份恢复 | 公共 RBAC 类型不能完整表达 Team 分区；数值留存与其他契约存在歧义 | S-TENANT；真实数据库/对象/缓存/向量/KMS 隔离，RPO≤15min，标准 RTO≤4h / 高敏≤1h |
| [SEC-009](../../design-specs/REQ-SEC-009-kill-switch-incident-response.md) | 六模式、三健康态、作用域、ACK、分阶段恢复及应急授权 | 当前三态/四作用域只覆盖简化闭环；恢复/传播不能据此称完整 | S-KILL；并发阻断、断网、重启、分阶段恢复、独立中止及可核实生效范围 |
| [SEC-010](../../design-specs/REQ-SEC-010-security-control-validation-red-team.md) | L1/L2/L3复杂度×D1～D6攻击域；Tier-1～4；四段处置SLA | 现有单测不能替代完整攻击矩阵或独立评估 | S0-RED、E-GATE；覆盖分母版本、独立性、P0/P1根除复测与发布门禁 |

[SEC-006](../../design-specs/REQ-SEC-006-prompt-injection-malicious-repo-protection.md)是关联输入/输出检测接口，由 S-SCAN 承接；G-SEC 不扩大为该 REQ 全部实现。注入检测是信号，不能产生授权，也不能以模型拒答代替未授权副作用检测。

## 3. 产品对标与外部协议核查

访问日期均为 **2026-10-29**。下面“事实”仅来自官方公开资料；“项目取舍”是本项目设计建议，未推断厂商内部架构，未实际运行竞品进行攻击验证。

| 来源 | 已验证事实与优点 | 项目取舍 |
|---|---|---|
| [Claude Code sandbox](https://code.claude.com/docs/en/sandboxing) | Shell及其子进程受文件和网络边界约束；内置文件工具、MCP和Hook不自动包含在该Shell沙箱中。文档明确边界，便于验证覆盖面 | 借鉴文件+网络同时约束；逐执行入口列能力证据，不能以一个沙箱测试代表所有工具已隔离 |
| [Cursor Run Modes](https://cursor.com/docs/agent/security/run-modes) | 区分白名单、沙箱与Auto-review；明确分类器可能误判，不构成安全边界 | 借鉴审批与隔离分工；本项目保留确定性PDP/PEP及硬拒绝，自动审查不能覆盖强制人工 |
| [GitHub installation token撤销](https://docs.github.com/en/rest/apps/installations#revoke-an-installation-access-token) | 用待撤销的installation token请求 `DELETE /installation/token`；成功响应204 | SEC-005 §4.3 的 `/applications/grants/{grant_id}` 不应当作installation token撤销接口；现有GitHub适配器已使用正确端点，修订应复用它 |
| [AWS STS](https://docs.aws.amazon.com/STS/latest/APIReference/API_AssumeRoleWithWebIdentity.html) | `DurationSeconds` 最短900秒；会话权限是角色与会话策略的交集 | 不能承诺原生STS签发60秒令牌；需要更短期限时用受控代理租约或拒绝，不能静默放宽 |
| [AWS会话撤权](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_use_revoke-sessions.html) | IAM可用TokenIssueTime条件拒绝一段时间前签发的角色会话；影响同角色其他会话，存在策略传播延迟 | 不把“只能等TTL”当完整事实，也不承诺原生单令牌五秒失效；外部撤权需精确范围、回执和延迟证据 |

MCP协议版本需由 S0-MCP 在实现方案锁定；本次沿用SEC-007的受众、PKCE、禁止token passthrough、工具版本绑定要求，不将“最新协议”作为无版本实现依赖。

## 4. 当前源码证据与缺口

检查对象是当前工作区，不声称已检查线上数据库或部署；下表代码缺口尚未在本任务修复。

| 编号 | 可复核证据 | 影响 / 修复归属 |
|---|---|---|
| F01 | [base.PolicyDecision](../../../src/security/policy_gateway/base.py) 为 `REQUIRES_APPROVAL`，[V2](../../../src/security/policy_gateway/gateway_v2.py) 为 `ESCALATE_TO_APPROVAL`，SEC-003为`REQUIRE_APPROVAL`；两种PolicyResult均无专用decision_id字段 | 不能直接字符串互转或把request_id冒充持久化决策ID；S-RBAC显式适配 |
| F02 | [公共类型](../../../src/runtime/common/types.py)为PUBLIC/INTERNAL/CONFIDENTIAL/RESTRICTED；[事件信封](../../../src/runtime/event_store/envelope.py)为PUBLIC/INTERNAL/SENSITIVE/CONFIDENTIAL | 同名CONFIDENTIAL在两种词表中的等级不同；需带来源和版本迁移，不能按名字合并 |
| F03 | [RBAC模型](../../../src/security/rbac/models.py)的Subject/Resource无team_id；Resource敏感度注释为1～5，SEC-001是L1～L4 | TEAM主体不自动提供租户隔离；不得把组织内不同Team视为同一安全分区 |
| F04 | [CDP.issue_token](../../../src/security/credential/pdp_cdp.py)读取独立requested_ttl_seconds，却未读取request.max_ttl_seconds；`_mint_token`返回示例值；审批输入为bool/reason/scope元组 | 内存探针请求60秒得到3600秒；元组不能证明签名、受众和防重放；S-CRED补齐生产路径 |
| F05 | [MCP凭据适配器](../../../src/security/mcp_connector_governance/authorization/credential_adapter.py)显式传TTL，并有按组织/连接器阻断、晚签发处理和partial状态；[GitHub代理](../../../src/security/credential/github_proxy.py)有真实HTTP签发/校验/撤销方法 | 复用已有成果；F04不能泛化为所有MCP路径均忽略TTL；适配器的complete也不能无外部证据地解释为所有供应商令牌已失效 |
| F06 | [Kill状态](../../../src/security/kill_switch/state.py)为IDLE/TRIGGERED/RECOVERING及GLOBAL/ORGANIZATION/PROJECT/REPOSITORY；[ActionExecutor](../../../src/tools/executor.py)传`repository_id=context.task_id` | 旧状态不能机械映射完整M0～M5；repo必须来自可信Task资源关联；S-KILL及调用方修复 |
| F07 | [V2缓存](../../../src/security/policy_gateway/gateway_v2.py)默认300秒；已含请求快照、风险和参数哈希，但类型未完整承载授权/策略/租户/Kill版本 | 保留已有防参数替换修复；仍需风险TTL和可靠失效。普通缓存命中不是执行授权 |
| F08 | [MCP生命周期审计](../../../src/security/mcp_connector_governance/lifecycle/lifecycle_manager.py)的`_audit`失败只记录日志；V2/CDP等仍有进程内审计列表 | 激活/扩权与暂停/撤销须采用不同故障语义；目前不能称全部安全动作有可靠证据提交 |
| F09 | [Docker后端](../../../src/security/sandbox/docker_sandbox.py)明确拒绝无法实施的出口白名单，逃逸检测也未实现 | 拒绝能力有价值；必须保留拒绝，不能使用普通网络配置代替批准出口控制 |

## 5. 候选共享接口（待确认，不是已发布API）

以下是最小语义契约；复用[RT-001](../../design-specs/REQ-RT-001-core-runtime-entities.md)标识与实体、[RT-003](../../design-specs/REQ-RT-003-event-schema-versioning.md)事件版本规则。字段进入正式共享Schema前，须与G-RT及所有调用方评审，先扩展、双读校验，再迁移写方，最后停止旧格式。没有明确映射的旧调用拒绝，不能填默认租户或ALLOW维持兼容。

### 5.1 身份、资源与版本

`SecurityContext`候选必需字段：`schema_version`、可信`subject_ref`、`originating_user_ref`（用户委托场景）、`delegation_ref`（代理场景）、`organization_id`、`team_id`（租户数据路径）、`authorization_version`、`policy_version`、`trace_id`。Task/Workflow/Worker/Action存在时必须携带对应ID；控制平面管理动作可无Task，但仍需actor和审计，不伪造Task。

`ResourceBinding`：`resource_type/id`、组织/Team归属、适用的project/repository/path/revision、`classification_vocab_version`与`classification`、`resource_version`。资源拥有者从服务端注册/存储查出，与上下文逐项一致；Header仅在认证网关验证成员关系后使用，不能信任请求体、提示词、Worker自报租户。Trace用于关联，不提供授权。

路径须仓库相对且规范化；拒绝绝对路径、穿越、歧义、符号链接越界，大小写按仓库/文件系统规则。用户权限∩组织策略∩源代码平台授权∩任务范围∩Worker能力∩委托范围，任何显式拒绝优先；管理角色不隐含租户内容读取。

**分类候选映射（C01）**：SEC-001 L1/L2/L3/L4分别对齐RT-001 PUBLIC/INTERNAL/CONFIDENTIAL/RESTRICTED。事件旧词表SENSITIVE→L3、CONFIDENTIAL→L4；必须依据来源词表版本，裸字符串无法确定时隔离并拒绝消费。RBAC旧1～5数值没有足够语义证据，不按比例换算；由资源权威重标。派生物继承最高等级；连接器信任L1～L4与数据L1～L4是不同维度。

### 5.2 决策、审批与副作用入口

`evaluate(context, action_ref, resources, operation, arguments_digest, plan_ref, runtime_snapshot) -> DecisionRecord`。

`DecisionRecord`包含不可变`decision_id`、`decision=ALLOW|REQUIRE_APPROVAL|DENY`、机器可判定`reason_code`、范围上限、参数/Plan摘要、完整版本绑定、`kill_epoch`、签发/到期时间、决策来源、审批引用和审计引用。具体摘要规范和签名格式须实施方案确认；不能签完之后继续改参数。

`revalidate(decision_ref, current_snapshot) -> execution_permit | SecurityError`在副作用前调用，校验受众、上下文、资源版本、权限/策略/工具版本、租约、Kill状态和幂等绑定。缓存不能绕过此入口。执行成功与后置脱敏分开记账；后置拒绝不能抹去已发生的副作用。

审批建议沿用既有审批实体，语义为pending→approved/rejected/expired/cancelled/superseded；approved仅表示该版本获得批准，执行仍需重校验。拒绝、取消、过期不自动恢复；改参数、资源、计划或范围使旧批准失效。审批者满足RBAC及双人规则，不得自行批准自己的提权。

硬拒绝＞强制人工＞可自动审查规则＞普通ALLOW。SEC-003显式白名单低风险、可逆、只读操作的超时策略继续保留；所有Memory写入及敏感/高风险/不可逆/强制人工动作不得据超时自动批准。Auto-review默认shadow/advisory，不可升级权限或覆盖黑名单、强制人工。

基础Gateway和V2通过显式兼容适配器映射到`REQUIRE_APPROVAL`，保留外部旧枚举读入；缺必需绑定时返回错误，不伪造审批或decision_id。API/HAR/Tool/MCP、Credential、Memory、Runtime和审计全部是影响方。

### 5.3 凭据与撤销

`request_capability(context, decision_ref, audience, target, operations, scopes, max_ttl_seconds, idempotency_key) -> CredentialLeaseRef`；只有受信凭据服务处理真实秘密。调用方拿不透明引用、代理受众、范围、租约到期及审计引用，沙箱/模型/普通日志不得接收真实令牌。保留SEC-005 Model B作为沙箱外受信适配器内部能力；是否迁移既有返回`issued_token`的调用，由C03确认后逐调用方处理。

有效租约期限是请求上限、已批准上限、服务上限、身份/批准剩余期限的最小值；必须正数且未过期。区分`lease_expires_at`与`provider_expires_at`，代理每次使用都检查租约。原生服务无法提供所需期限/受众/范围时选择合格代理或拒绝，不静默扩大。委托SVID、签名/受众、防重放验证、Vault/KMS及供应商适配器是真实实现依赖，不以字符串前缀校验替代。

`revoke(scope, reason, expected_epoch, idempotency_key) -> RevocationReceipt`先提交不可逆转的本代阻断，拒绝新签发及新使用，再并行清缓存和撤销供应商令牌。Receipt至少包含job/epoch、范围、目标实例集合版本、已ACK/未ACK集合、供应商逐项状态/证据、残余有效截止时间、失败原因和重试标记。状态区分requested / locally_blocked / partial / complete / failed；complete必须定义是本地阻断完成还是外部撤销完成，禁止混用。

SEC-005的“缓存清除<5秒”保留为受控平面目标；原文“全局失效≤5秒”与外部令牌TTL/撤销能力不一致，C04明确请求用户裁定，**当前未将其改为更宽松的已冻结SLA**。若坚持外部全局五秒保证，则只准入能提供相应真实证据的代理/供应商组合。撤销超时继续阻断并保留partial，不先报成功再后台遗忘。

### 5.4 Kill、降级与恢复

`check_kill(context, action, scope_refs) -> KillSnapshot`包含事件/epoch、模式M0～M5、健康态、作用域、生成/过期时间、策略引用及阻断原因；Kill服务发布限制，PEP实施限制，不能把M模式数字大小当成权限集合的全序。

SEC-009标题称“七级”，但§5表实际列ACTION、TOOL、CONNECTOR、TASK、WORKFLOW、PROJECT、ORG、GLOBAL八项；按表逐项设计，保留旧REPOSITORY兼容限制直到完成资源映射，不静默删除旧阻断。Team隔离不意味着已存在独立TEAM Kill作用域；涉及Team的应急选择由资源注册表计算最小安全范围，未来扩展另评审。

C05建议在保留三健康态和已有自动恢复决议下细化：关键PEP缓存仍≤2秒，客户端≤30秒；缓存到期或版本无法确认后不启动新的受保护Action，未过期令牌本身不能越过失联的Kill检查。在已通过检查的Action内，仅可按已批准范围完成受控收尾；每次新凭据使用/外发/副作用边界需再校验。不可知外部结果进入对账，不盲重试。

DEGRADED中的可配置只读仅限显式声明、身份/权限有效且不扩大暴露的路径；若RBAC不可用，SEC-002要求保护读取/检索同样拒绝。恢复连通性可以自动恢复健康态，但不能自动解除仍有效的事件、复用过期批准或补执行旧队列。M5仍按SEC-009的人工Quorum、凭据轮换、Artifact复核、Replay与分阶段观察要求执行。

### 5.5 审计、租户与数据生命周期

`commit_security_evidence(event) -> durable_receipt`复用RT事件封装，关联actor、org/team、资源、Task/Action/Trace、decision、审批、凭据引用、Connector/Schema、Kill epoch和结果；禁止真实凭据、完整敏感参数/代码或隐藏思维链。安全决策与可靠提交绑定，进程内列表不构成生产审计保证。

C06建议：扩权、激活、凭据签发及高风险/有副作用执行在审计可靠提交不可确认时暂停或拒绝；撤销、封禁、停机等缩权动作不能因审计故障被阻止，先实施阻断，并通过独立可靠缓冲/告警保全证据。缓冲失败必须报告证据缺失、禁止恢复/扩权，不伪称已审计完成；普通受保护只读仍需满足SEC-002/003，不设置全局审计豁免。

SEC-008既有候选物理边界保持：PostgreSQL每Team schema+RLS、对象前缀、Redis Key、向量Collection/Index、配置Namespace、独立DEK/KEK；是否替换存储方案需独立批准，不能仅加一个team_id字段即视为隔离完成。区域策略传播到模型路由、索引/Memory、备份、日志与证据。迁移/恢复后先验证租户隔离、删除墓碑和撤销代次再开放访问。

C07建议将留存解析为版本化策略：`purpose`、数据类别/等级、org/team、region、热/冷期限及其起算点、最终删除条件、Legal Hold引用、审批、归档与删除作业引用。SEC-008的热30/冷180天、Memory90天与SEC-004未定值、G-MEM未定值不能自动合成统一默认。WORM/Legal Hold未解除时先访问隔离、保留必要证据并给出限制说明；删除证明按主库、索引、缓存、副本、备份逐项记录，不承诺立即不可恢复。具体时长仍开放，缺批准策略不自动硬删除。

### 5.6 错误、重试、取消

| 候选错误 | 可观察语义 | 重试/恢复 |
|---|---|---|
| INVALID_CONTEXT / UNKNOWN_CLASSIFICATION | 缺租户、身份链或分类版本，拒绝；不猜测默认值 | 修复输入及权威映射后新评估 |
| ACCESS_DENIED / RESOURCE_NOT_ACCESSIBLE | 保护资源存在性，外部不泄露跨租户差异 | 不自动重试；内部审计保留原因 |
| APPROVAL_REQUIRED / APPROVAL_EXPIRED / STALE_DECISION | 未获许可；不先执行后补批准 | 人工批准或重新评估；不复用旧摘要 |
| SECURITY_DEPENDENCY_UNAVAILABLE / AUDIT_UNAVAILABLE | 无法确认关键安全事实，暂停/拒绝 | 有界退避；恢复后重新授权，不把重试当放行 |
| KILL_BLOCKED / STALE_KILL_STATE | 当前范围被阻断或状态无法确认 | 遵守恢复流程，不降级执行 |
| CAPABILITY_UNSUPPORTED / TTL_UNSATISFIABLE | 后端/凭据不满足批准能力 | 换已合格适配器或拒绝，不宽化配置 |
| REVOCATION_PARTIAL / EXTERNAL_OUTCOME_UNKNOWN | 保留本地阻断，撤销或外部执行尚未确定 | 幂等重试/查询对账，不能声明成功或重做副作用 |

以上是领域错误，HTTP/SDK映射沿用项目统一响应格式，具体端点需实现方案确认。本次没有发布新HTTP API。取消后必须撤销未使用许可、禁止新动作、收集在途结果；网络断连不等于外部操作取消成功。

## 6. 需要用户裁定的七项建议

这些建议尚未批准；本文件不修改原REQ或冻结共享类型。依据执行手册的基线确认及[迭代规则](../../../规则文档/AGENTS.md)§B，影响接口、安全或数据完整性的冲突必须经用户确认。

| 决策 | 实质冲突 / 选择 | 建议及影响 |
|---|---|---|
| C01 身份与分类 | SEC-008 Team分区、RBAC组织模型、两套敏感度枚举及1～5字段尚不一致 | 采纳§5.1的可信org+team绑定、带版本映射与未知拒绝；与G-RT/S-TENANT协同后再改共享Schema，不以Trace充当鉴权 |
| C02 决策兼容 | 三套审批枚举及缺失决策凭证 | 采纳§5.2的明确适配、持久化decision_id和执行前重校验；保留SEC-003只读例外及已批准G-MEM更严写入规则 |
| C03 凭据交付边界 | SEC-004禁止真实凭据进入沙箱；SEC-005 Model B描述向Agent返回短令牌，AWS章节与AC7模式也不同 | Model B仅在沙箱外受信服务内部使用；Worker经代理引用调用，AWS/GCP/Azure OIDC按Model A；不让现有issued_token接口无审批静默变更 |
| C04 TTL与撤销保证 | 请求TTL实现缺口；供应商最短有效期、缓存失效与“全局五秒失效”不等价 | 采纳双期限、受控平面<5秒目标与逐供应商真实回执；不能提供所需外部时限则拒绝准入。原文SLA文字更正需确认，不把能力不足写成通过 |
| C05 降级细节 | SEC-009允许已有短令牌跑完，同时要求缓存过期fail-closed；与每次Action复核存在歧义 | 采纳§5.4逐边界校验、有限收尾和恢复重评估；保持原三态、自动解除及人工M5，不用令牌TTL延长Kill事实有效期 |
| C06 审计故障 | SEC-003关键动作需可靠审计；现有生命周期统一吞审计错误；阻断安全动作又可能延误遏制 | 采纳扩权/执行失败关闭、缩权先阻断并可靠补证据的区分；审计缺失时禁止恢复，不准报审计完成 |
| C07 留存冲突 | SEC-008固定示例/default值与已确认SEC-004/G-MEM留存开放项，且热/冷起算和删除约束不统一 | 采纳版本化用途策略及逐存储删除证明；不把默认数值自动冻结。实现前按数据类别另确认数值、例外和备份时限 |

验收本核对文档、同意C01～C07作为后续设计依据、批准某个生产切片，是不同范围的确认。本轮建议先确认前两项范围；生产实施仍须相应任务的明确范围、接口及质量门禁。

## 7. 调用方、依赖与实施切片建议

G-SEC无实现硬依赖，可以先交付本文件；共享Schema迁移仍与G-RT、G-HAR等协调，不能把尚待验收的契约视为已冻结。下面只映射既有台账任务，不新增/修改依赖或代其他负责人领取。

| 工作包 / 调用方 | 需消费的契约 | 独立设计与真实汇合边界 |
|---|---|---|
| S-RBAC；API、HAR、Tool、Memory、检索 | 身份资源绑定、决策/审批、缓存版本、领域错误 | 首切片选一个真实Action贯通授权→决策→副作用→审计；不得以V2单测代替PEP接入 |
| S-CRED；MCP、Git工具、Sandbox | 可信批准证明、TTL、代理引用、撤销回执 | 先复用GitHub适配器关闭通用CDP缺口；真实测试租户/凭据和撤销证据在M1汇合 |
| S-BOX、A-POOL；Runtime/Tool | 能力声明、已批准出口、凭据不入沙箱、清理回执 | Linux真实后端能力测试；性能另测，禁止因WarmPool目标降低隔离 |
| S0-MCP；S0-SCHEMA/HAR-005 | Connector/工具/签名/Schema摘要和批准代次 | 复用已验收失效切片；等待S0-SCHEMA真实验收；再补生产OAuth、签名、出口及持久审计 |
| S-KILL；Runtime/Policy/Tool/CDP | 模式/健康态/epoch、作用域、ACK、恢复 | 旧三态保持兼容拒绝，扩展须双方契约测试；M2做真实失联、重启与恢复演练 |
| S-TENANT、R-QUERY、O-AUDIT；Context/Memory/模型路由 | org+team、区域、分类、留存、删除/恢复证明 | 全部真实存储验证隔离；普通管理员不得读取其他Team内容；M2/M3/M4按使用路径汇合 |
| S0-RED、S-SCAN、E-GATE | 威胁/控制/证据版本、L1～L3×D1～D6、不可抵消安全门禁 | 单元/集成/动态对抗分别出报告；Tier-3/4独立性不能由开发自测替代 |

M1仅验收Issue→PR实际使用的安全链；M2要求S0-FREEZE及可控上线能力；M3核对真实检索权限/来源；M4核对多Worker、Memory和租户链。模块完成不等于里程碑完成，各REQ剩余AC继续保留。

## 8. 计划中的验收用例（未执行项不算通过）

| 用例 | 触发条件 → 必须响应 | 真实验收位置 |
|---|---|---|
| V01 | 同org不同Team、伪造Header/Body或缺租户 → 读/搜/写/签发全拒绝且不泄露存在性 | S-RBAC/S-TENANT/M2 |
| V02 | 两种词表的CONFIDENTIAL或无词表版本 → 正确分级或拒绝，不降低等级 | G-RT映射、各存储/日志/Memory |
| V03 | 旧审批枚举、未知值、缺decision_id或摘要变更 → 可验证适配或拒绝；副作用次数为0 | S-RBAC/M1 |
| V04 | 撤权/Policy/Schema/Kill epoch变化与执行并发 → 旧缓存/批准失效，重启也不复活 | S-RBAC/S0-MCP/S-KILL |
| V05 | Memory强制人工写入、超时、取消、Auto-review超范围 → 不写入；合法只读例外按显式规则 | P-MEM/M4、S-RBAC |
| V06 | 请求TTL60、0、负数、双TTL输入不一致或供应商最短900 → 取合法最小值或明确拒绝；不能默认为3600 | S-CRED |
| V07 | 沙箱环境/文件/进程/日志/模型输出检查 → 无真实凭据；受众/范围不匹配不能代理调用 | S-CRED/S-BOX/M1 |
| V08 | 撤销过程中断网、ACK缺失、晚签发、重复请求及进程重启 → 持续阻断、partial可追踪，外部回执与本地完成分开 | S-CRED/S0-MCP/M2 |
| V09 | Kill失联且缓存到期、旧短令牌仍未到期 → 不开始新受保护动作；恢复后重新验证 | S-KILL/M2 |
| V10 | repo级阻断且task_id≠repository_id，或多个模式/范围重叠 → 准确阻断，不能按数字最大值漏限制 | S-KILL/Tool |
| V11 | 审计不可用时激活/签发/写入 → 拒绝；同故障下撤销/封禁 → 生效且报告证据状态 | S-RBAC/S-CRED/S0-MCP/O-AUDIT |
| V12 | DNS重绑定、重定向、私网/元数据出口、未经验证能力 → 拒绝；清理失败沙箱不得复用 | S-BOX/S0-MCP |
| V13 | 留存到期但Legal Hold/必要归档失败 → 不提前硬删；全部副本/版本/备份分项证明，恢复不得复活已删数据 | S-TENANT/P-MEM |
| V14 | 弱网超时、取消时外部写入结果不确定 → 不盲重试；按幂等键和证据对账 | S-CRED/Tool/Runtime/M1 |
| V15 | M5恢复条件缺失、审批重放或阶段演练失败 → 拒绝/回退，独立于目标Worker中止 | S-KILL/M2 |
| V16 | D1～D6任一高风险控制失败、证据断链、环境不可用 → 发布阻断/结果未决；P0/P1缓解不能关闭 | S0-RED/E-GATE；各里程碑 |

## 9. 本次验证报告与复现

本次是文档核对与代码只读验证，不是生产安全验收。没有执行真实攻击、发放/吊销真实凭据、操作生产Kill Switch或删除数据。

| 测试项 | 用例 | 结果 | 修复动作 / 剩余事项 |
|---|---|---|---|
| 领取与范围 | task_board.py show/claim/heartbeat；本文件是否被占用 | 已领取且范围无冲突；修改前已登记开发中 | 最终submit后待用户验收 |
| 需求完整性 | 9项核心REQ及SEC-006关联；既有决议核对 | 已逐项建立范围/调用方/剩余AC映射 | C01～C07待确认；原始契约不变 |
| 外部协议 | 官方GitHub撤销、AWS TTL/会话撤权；Claude/Cursor边界 | 已核实并链接 | 不据此声称供应商真实集成通过 |
| 定向既有测试 | PDP/CDP、GitHub HTTP契约、PolicyGateway，共3个文件 | **53 passed，0 failed，0 skipped；64个utcnow弃用警告，3.16s** | 警告未在本任务修改；HTTP为MockTransport/Mock，非真实GitHub验收 |
| 新的只读TTL探针 | CDP请求max_ttl_seconds=60，未传独立TTL参数 | **现状不满足：返回3600秒；反例已复现** | F04/C04记录到S-CRED设计输入；未越界修生产代码，未写正式测试 |
| 源码结构复核 | 两套分类、两套Policy枚举、RBAC及Kill状态/范围 | 已发现F01～F03、F06；映射建议见§5 | 需批准后扩展共享类型与适配器 |
| 文档链接/REQ散列/台账 | 交付前检查本地链接、10份SEC REQ SHA-256及台账合法性 | 结果在最终交付检查记录补充 | 发现漂移必须复读，不能覆盖其他AI变更 |
| 生产安全/质量门禁 | 全套pytest、覆盖率、Ruff/Mypy、SAST/SCA/Secret、真实Docker/供应商、跨租户恢复、弱网/取消、红队 | **本次未执行** | 不能用53项单测代替；各生产切片按迭代规则执行，关键路径行覆盖100%等门禁继续适用 |

在项目根目录复现已运行的专项测试：

```powershell
.venv\Scripts\python.exe -X utf8 -B -m pytest tests/unit/security/credential/test_pdp_cdp.py tests/unit/security/credential/test_github_contract.py tests/unit/security/test_policy_gateway.py -q -o addopts= -p no:cacheprovider
```

TTL反例只调用进程内示例CDP，无外部I/O，不输出令牌。下面代码用于交互式验证；不是生产签发示例：

```python
from datetime import UTC, datetime
from src.security.credential.pdp_cdp import CapabilityTokenRequest, CredentialCDP
r = CapabilityTokenRequest(
    agent_svid="spiffe://review.invalid/agent", task_id="review-only", worker_id="review-only",
    target_service="github", target_resource="synthetic/repo", requested_action="read",
    requested_scope=["contents:read"], policy_approval_ref="synthetic-unverified-reference",
    justification="G-SEC in-memory contract probe", max_ttl_seconds=60,
)
before = datetime.now(UTC)
result = CredentialCDP().issue_token(r, (True, "synthetic tuple", ["contents:read"]))
# 当前实现返回naive UTC；仅探针按该实现语义加UTC，不代表批准其时间契约。
ttl = round((result.expires_at.replace(tzinfo=UTC) - before).total_seconds())
print({"requested_max_seconds": 60, "actual_seconds": ttl})
assert ttl > 60  # 当前反例；未来修复后的验收应断言ttl <= 60或明确拒绝。
```

## 10. 交付结论

本文件交付安全与租户共享接口的核对、兼容建议、官方对标、冲突清单和验证证据。待用户验收及C01～C07裁定；S-RBAC、S-CRED、S-KILL、S-TENANT、P-MEM等不因文档提交自动获准实施。真实测试、数值留存、供应商能力及共享Schema迁移仍有明确剩余条件。

验收通过后由实时台账记录日期、证据和限定范围；文档中的开发时快照保留用于追溯，不作为新的占用来源。此任务不触发README、部署说明或全项目完成更新。
