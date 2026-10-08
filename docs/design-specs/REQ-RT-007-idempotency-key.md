# REQ-RT-007 Idempotency Key 与副作用边界

> 所属基线：`Runtime Contract v1`（已冻结，2026-10-07）  
> 需求编号：`REQ-RT-007`  
> 优先级：P0  
> 设计版本：`v0.1-frozen`  
> 设计状态：已冻结，可作为实现基线（跨模块评审通过，2026-10-07）  
> 前置依赖：`REQ-RT-001`、`REQ-REL-006`（接口设计可先行；REL-006 实现依赖本契约）  
> 研究访问日期：2026-09-23

---

## 1. 需求定义

### 1.1 目标

为可能产生外部可见变更的 Action 定义稳定的逻辑操作身份、去重、结果核对和恢复规则，使至少一次投递、进程崩溃、并行调度、审批等待和恢复不会静默造成重复副作用。

本设计不承诺跨数据库、Agent 运行时和第三方服务的“端到端 exactly-once”。可提供的保证是：平台对同一逻辑意图只接受一个有效执行者；对支持幂等键的下游传递同一键；对不支持下游幂等的操作使用条件写入、操作前后核查、结果未知隔离及人工介入。

### 1.2 需求原文和交付边界

`PENDING-REQUIREMENTS.md` 将该项列为 `REQ-RT-007`，名称为“Idempotency Key 与副作用边界”，优先级 P0，前置依赖 `RT-001、REL-006`，关键交付物为“幂等键、去重、写操作保护”。清单没有列出更长的原始需求描述、目标或验收条款；本文件不将推导内容冒充原文。

本专项定义逻辑操作身份、并发领取、重复请求处理、去重窗口、结果未知处理、存储职责、补偿边界、MVP 并行语义及验收标准。具体表结构、Redis 部署形态、下游 API 协议和 REL-006 各工具包装细节属于实现设计或依赖专项。

### 1.3 公开事实与推断

- **公开事实**：Temporal 文档明确说明 Activity 可能至少一次执行，Activity 在外部副作用发生后、完成回执前崩溃时仍可能重试，建议写操作幂等，并使用稳定的 Workflow/操作标识、条件写入或下游幂等键。
- **公开事实**：Stripe 允许至少 24 小时后清理幂等键；保留期间会比较请求参数，不同参数复用同键会报错；过期后同键可能被视为新请求。因此 24 小时不是所有任务的安全保留期保证。
- **公开事实**：Temporal Saga 建议在正向 Activity 执行前注册补偿，补偿按逆序执行，补偿本身要幂等且能应对正向操作从未发生的情况。
- **设计推断**：本平台的持久账本保留期必须长于 24 小时缓存 TTL，且状态未知的外部写入不能仅凭 TTL 到期自动重放。
- **设计推断**：AI Agent 的 Action 身份应依据持久化的逻辑步骤和显式意图实例，而不能仅基于 Prompt 文本或参数哈希；相同参数可能代表用户有意进行的第二次操作。

---

## 2. 竞品与行业研究摘要

### 2.1 OpenAI Codex

**公开事实**：OpenAI 公开资料描述 Codex 的隔离执行边界、网络策略、审批策略和运行遥测；Codex 的公开 GitHub 资料显示工作区运行状态需要在恢复和 fork 后保持一致。公开材料没有证明 Codex 对所有外部副作用提供通用幂等键保证。  
**设计推断/借鉴**：仿照“边界控制 + 高风险审批 + 可追溯运行证据”，而不是把模型对话恢复等同于外部世界回滚；恢复发现状态不一致时先核查，再允许写操作。  
来源：[Running Codex safely at OpenAI](https://openai.com/index/running-codex-safely/)、[GPT-5-Codex system card addendum](https://cdn.openai.com/pdf/97cc5669-7a25-4e63-b15f-5fd5bdc4d149/gpt-5-codex-system-card.pdf)，访问日期：2026-09-23。

### 2.2 Microsoft Agent Framework / Durable Task

**公开事实**：Microsoft Agent Framework 的公开 issue 记录了 superstep 中途失败时可能重放已完成工具副作用，并指出工具层需要实现幂等；Durable Task 面向持久状态转换、检查点、失败恢复和有界重试。Temporal 对 Activity 至少一次语义的说明同样强调副作用与完成回执之间的崩溃窗口。  
**设计推断/借鉴**：检查点只能恢复编排状态，不能消除已发生但未记账的下游副作用；每项外部写入必须有独立逻辑操作身份和核查路径。  
来源：[Agent Framework issue 3938](https://github.com/microsoft/agent-framework/issues/3938)、[Durable Task for AI Agents](https://learn.microsoft.com/en-us/azure/durable-task/sdks/durable-task-for-ai-agents)、[Temporal Activity Definition](https://docs.temporal.io/activity-definition)，访问日期：2026-09-23。

### 2.3 Devin Dynamic Workflows

**公开事实**：Devin 文档描述每个 Agent 调用按提示、结构化输出约束和执行设置形成缓存身份；完成调用可从记录结果恢复，未完成或失败调用重新运行；脚本须避免依赖非确定性外部状态。该文档描述的是工作流调用记录/恢复，不等于任意外部写 API 的 exactly-once 保证。  
**设计推断/借鉴**：恢复缓存要绑定稳定的步骤身份及输入摘要，但同输入的独立并行任务不能被错误合并；外部状态读写仍交由可审计工具边界。  
来源：[Devin Dynamic Workflows](https://docs.devin.ai/work-with-devin/dynamic-workflows)，访问日期：2026-09-23。

### 2.4 Cursor 与 Qoder

**公开事实**：Cursor 文档描述沙箱、命令审批、Auto-review 和确定性执行边界；Qoder 文档描述计划审查、执行步骤、Diff 和回滚/复核体验。两者公开资料没有宣称通用的下游副作用幂等协议。  
**设计推断/借鉴**：对用户清楚呈现风险、执行进度、变更和回退/人工接管入口；LLM 分类或提示只能补充治理，不能替代确定性的去重和授权。  
来源：[Cursor Agent Run Modes](https://cursor.com/docs/agent/security/run-modes)、[Cursor LLM Safety and Controls](https://cursor.com/docs/enterprise/llm-safety-and-controls)、[Qoder Quest Overview](https://docs.qoder.com/user-guide/quest/overview)，访问日期：2026-09-23。

### 2.5 Stripe、Azure Saga 与 Temporal Saga

**公开事实**：Stripe 的幂等接口以一次逻辑请求的键识别重试、校验同键参数一致性，键至少 24 小时后可能被清除。Azure 与 Temporal 的 Saga 资料指出补偿是业务语义上的反向操作，并非数据库事务回滚；补偿可能失败、须记录进度并能安全重试。  
**设计推断/借鉴**：24 小时用作 Redis 快速去重记录的 TTL，不作为持久操作历史期限；MVP 补偿只承诺对定义明确、可验证且作用域受限的资源操作，不能把关闭 PR 或重置工作区表述为撤销已发生的外部影响。  
来源：[Stripe Idempotent requests](https://docs.stripe.com/api/idempotent_requests)、[Azure Saga pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/saga)、[Azure Compensating Transaction pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/compensating-transaction)、[Temporal Saga pattern](https://docs.temporal.io/design-patterns/saga-pattern)，访问日期：2026-09-23。

---

## 3. 目标用户与典型场景

| 角色 | 目标 |
|---|---|
| Agent Runtime / Coordinator | 为逻辑操作分配并持久化稳定身份，恢复时不重复提交已完成工作 |
| Tool Adapter / 下游连接器 | 在操作前原子领取执行权，向下游传递键或执行条件写入 |
| Policy Gateway | 确认主体、审批、目标资源和请求摘要与原授权一致 |
| Recovery / Reliability | 将结果未知的 Action 隔离并协调查询、重试或人工处理 |
| 用户/审计人员 | 看到正在核查、已完成、未完成、需人工处理的明确状态和证据 |

典型场景包括：工具响应丢失后的重试、Worker 在下游成功后崩溃、同一步骤并行重复投递、Pipeline 恢复、审批后延迟执行、取消时清理临时资源，以及补偿动作自身超时。

---

## 4. 逻辑操作身份与 Scope

### 4.1 幂等身份的语义

一个幂等键标识**一次逻辑副作用意图**，不是一次网络尝试，也不是整个会话、Worker 或工作流的通用键。平台在首次派发前生成并持久化；模型不得指定、改写或在重试时重新生成。

逻辑身份由租户范围、`workflow_id`、稳定 `step_id`、该步骤内显式分配且持久化的意图实例标识、动作类别及规范化请求摘要共同约束。公开键使用高熵、不泄露业务字段的不可猜测标识；作用域字段和摘要存放在受访问控制的账本中，不把组织/用户明文、密钥或敏感参数编码进公开键。

对同一键再次提交时：请求摘要一致则返回既有结果/状态；摘要不同则拒绝为幂等冲突并记录审计事件，绝不复用旧结果执行新参数。

### 4.2 默认和例外 Scope

**默认 `step_scope`**：同一 Workflow 的同一稳定步骤实例中，同一逻辑操作重试、恢复或重复投递均复用键。步骤中的不同独立意图必须分配不同持久意图实例，即便工具名和参数完全相同。

- **并行分支**：Scope 必须含稳定的分支/节点实例身份；不能使用完成先后顺序或数组位置作为身份。不同分支即便参数相同也使用不同逻辑键，除非工作流明确声明它们是同一共享副作用并引用同一意图实例。
- **Pipeline**：每个有副作用的节点拥有稳定步骤身份和独立键；下游节点的键不因上游重试或调度顺序变化而改变。重放已完成节点时返回已存结果，不重新调用外部服务。
- **Task Scope**：仅用于业务规则明确规定整项 Task 内必须唯一的副作用（例如同一任务只能创建一个目标 PR），必须显式声明业务唯一约束，不作为默认。
- **Call/attempt 不作为去重 Scope**：attempt 只用于审计和计数；不得纳入键身份，否则每次重试都会绕过去重。

MVP 支持有界并行和有向 Pipeline。并行分支上限、并发度和循环/重规划上限由 Workflow/Harness 需求另行定义；本需求要求稳定节点身份及唯一执行领取，不决定该上限数值。禁止以不稳定的模型生成标签作为步骤身份。

### 4.3 24 小时 TTL 与持久账本保留

用户确认采用 24 小时 TTL。该期限仅适用于 Redis 中的热去重/快速结果缓存。PostgreSQL 是持久操作账本与审计关联的权威记录，保留不得短于可恢复 Workflow、审批有效期、下游对账期限及安全/合规留存要求；正式保留期限由 `REQ-RT-008`、`REQ-SEC-008` 对齐后冻结。

Redis 项目丢失、驱逐或 TTL 到期时，不能据此认定操作从未执行。所有写入前先查 PostgreSQL 权威账本；存在 `OUTCOME_UNKNOWN`、正在执行、未终结或未对账记录时禁止以新键重发。只有终态且已超过恢复和审计要求的记录才可按治理策略归档/清理。

---

## 5. 操作状态、原子领取与存储

### 5.1 状态语义

- `RESERVED`：逻辑键、请求摘要和授权引用已持久化，尚未确认派发。
- `EXECUTING`：已有一个持有有效执行租约的执行者。
- `SUCCEEDED`：正向副作用有下游响应或可验证证据；保存可复用结果引用。
- `FAILED_RETRYABLE`：确认未产生副作用，且失败类别允许有限重试。
- `FAILED_FINAL`：确认失败且不可重试，或策略明确禁止重试。
- `OUTCOME_UNKNOWN`：请求可能已到达下游，但没有足够证据确认是否生效。
- `RECONCILING`：正在查询下游或比对本地/远端资源。
- `COMPENSATING` / `COMPENSATED` / `COMPENSATION_FAILED`：补偿的独立状态；不覆盖正向 Action 结果。
- `CONFLICT`：相同逻辑键对应不同请求摘要，拒绝执行并审计。
- `ESCALATED`：自动处理达到边界，等待用户或运维决策。

这些是幂等操作账本状态，不替代 `REQ-RT-002` 的 Action/Workflow 状态机或 `REQ-RT-003` 的事实事件。

### 5.2 原子领取和竞态

首次执行必须在 PostgreSQL 持久化唯一作用域、键、规范化请求摘要、Action/Step/Workflow 引用、审批引用和状态后，才允许产生副作用。并发派发通过唯一约束及条件状态迁移/CAS 确保只有一个执行者取得租约；其他投递读取既有状态并等待、返回缓存结果或进入核查，不可并行越过领取。

租约过期不能证明原执行已停止。接管者必须先核查前次执行记录和副作用状态；若外部调用结果未知，转入 `OUTCOME_UNKNOWN`，不能仅凭租约过期重新执行。

### 5.3 Redis + PostgreSQL 分工

- **PostgreSQL**：持久权威账本、唯一性约束/事务状态迁移、请求摘要、租户/运行/步骤关联、审计引用、结果引用、审批版本、重试与对账历史。只有 PostgreSQL 确认预留成功后才可开始外部写入。
- **Redis**：24 小时热键索引/结果缓存、短时并发协调和读取加速；数据可丢失或过期，不能作为唯一正确性来源。可用性异常时，写操作走 PostgreSQL 直查；PostgreSQL 不可用时，对有副作用 Action fail-closed 暂停。
- **一致性**：数据库事务内记录状态及待投递意图；需要异步投递时采用持久 Outbox/等效事务消息边界，消费者可重复投递但必须携带原逻辑键。Redis 重建以 PostgreSQL 为准。
- **结果载荷**：账本存结构化结果引用、摘要和下游业务标识；大对象存 Artifact/ContentRef；不得无限缓存敏感响应正文。

---

## 6. 处理流程与超时对账

### 6.1 正常执行

1. Worker 提议 Action；运行时解析稳定 Step/分支实例和逻辑意图。
2. Tool Adapter 规范化请求并计算摘要；执行 Policy Gateway 检查，确保目标、主体、请求摘要和审批事实一致。
3. 运行时创建稳定幂等键，在 PostgreSQL 预留并提交，再写出可恢复的派发意图。
4. 原子领取执行租约；向下游传递相同幂等键。下游不支持幂等键时使用条件创建、版本前置条件、唯一业务标识或先查后写；能力不足时拒绝自动写入或要求人工确认。
5. 成功后持久化下游引用、结果摘要和 Evidence/事件关联；再更新 Redis 热缓存。
6. 同键重投：摘要一致且成功则返回原结果；执行中则等待/返回处理中；结果未知则核查；摘要不同则 `CONFLICT`。

### 6.2 用户指定的三次外部对账重试

对账查询失败最多重试 **3 次**（三次查询尝试，不含初次查询；总查询调用最多四次）。采用有抖动的有界退避并遵守下游 `Retry-After`；不在 Agent 主对话循环中忙等，不阻塞其他独立只读步骤。实施时的退避时间由 `REQ-REL-002` 确认，MVP 初始建议约 1 秒、2 秒、4 秒，受外部服务建议和整体 Workflow 截止时间限制。遇到权限拒绝、参数错误或确定性 4xx，不消耗三次重试额度，直接分类处理。

### 6.3 三次查询后仍无法确认的分级处理

1. **短时局部故障**：保留 `OUTCOME_UNKNOWN`，暂停该逻辑操作和所有依赖该结果的写步骤；允许无依赖的只读诊断继续。展示“正在确认操作结果”，提供手动刷新/稍后自动核查，不显示已成功或失败。
2. **可在预算内等待**：Workflow 进入可恢复的 `WAITING_RECONCILIATION`/等待状态，释放 Worker，不占用计算资源；按可靠性策略安排后续核查。不能创建新幂等键绕过旧操作。
3. **稳定性保护**：下游出现持续超时/限流时，对该连接器启用有界并发/熔断和排队，保护平台及下游；不把未知写操作切换到另一个供应商或路径再次提交，除非两端共享相同去重语义且经策略验证。
4. **达到用户可接受等待/Workflow 截止时间**：停止自动轮询，状态转为 `ESCALATED`，通知用户说明目标操作、最后已知时间、已尝试核查次数和未确认事实；提供“继续等待核查”“人工确认外部结果”“安全取消后续流程”选项。不能将“取消任务”解释为撤销已发出的外部请求。
5. **确认已发生**：关联远端 ID/状态与证据，记为 `SUCCEEDED`，复用结果继续。
6. **确认未发生**：经 Policy 和审批仍有效检查后，使用原键恢复/重试；若下游已过其幂等保留期限，必须采用外部资源唯一约束或人工批准，不得盲目重放。
7. **无法长期核查或无可查询 API**：保持未知并升级人工；不得自动假定失败。该策略优先避免重复不可逆副作用，同时让无关工作和系统容量保持稳定。

用户体验要求：UI 清楚区分“动作提交成功”“运行时记录成功”“下游结果已确认”；提供明确的等待/人工处理状态和可恢复入口，避免重复点击创建新意图。

---

## 7. 副作用分类与 MVP 补偿边界

### 7.1 分类

- **只读/可重复**：代码检索、读取、状态查询。通常可重跑，但仍记录 Action/attempt 和权限。
- **本地可覆盖变更**：隔离任务分支中的文件写入、生成文件。通过目标内容哈希、工作区 revision 和条件写入实现重放安全；恢复前校验文件是否被外部改写。
- **可补偿资源变更**：创建任务分支、工作区/临时目录、任务拥有的临时资源；满足所有权、版本和无外部依赖条件时可执行受限补偿。
- **外部可见且可能不可逆**：推送已共享分支、创建/关闭 PR、评论/通知、发布/部署、凭据撤销等。独立审批、幂等传递、核查和审计；不能承诺通用撤销。

### 7.2 MVP 支持的补偿

MVP 是任务工作区/分支级，而不是任意外部业务事务：

1. **删除 Agent 专属临时工作区/临时文件**：只有验证工作区归属当前 Task、没有并发使用、重要变更已形成 Artifact/快照後才清理；否则隔离归档并人工确认。
2. **删除 Agent 专属未共享任务分支**：仅当分支由本 Workflow 创建、未被他人使用、没有用户提交或共享远端依赖时执行；删除前核对分支指针/commit 与创建时记录相符。
3. **撤销该任务签发的短期凭据**：撤销以任务/凭据引用为范围；重复撤销视为成功，不触碰用户原有凭据。长期凭据不由 Agent 管理。
4. **关闭本任务创建的 PR**：仅允许显式策略/人工批准后作为补偿候选；关闭不是删除评论、通知或外部审查痕迹，也不保证恢复仓库原状。默认失败清理不自动关闭 PR。
5. **恢复任务分支内文件变更**：优先放弃隔离 Workspace 或重建分支，而不是反向编辑共享仓库；若需保留现场，则归档差异后人工选择。

所有补偿均须在正向副作用前持久登记，按依赖逆序执行；每个补偿有独立的补偿操作 ID/幂等键，必须能在正向动作未发生时安全 no-op，并在部分成功后继续。补偿失败有限重试，随后 `ESCALATED`、告警并保留现场。正向操作的成功记录不得被补偿状态覆盖。

### 7.3 MVP 不自动补偿/不可逆边界

MVP 不自动撤销已发送通知/邮件/评论、已合并代码、已部署服务、已发布包、用户提交或共享分支上的他人修改；不执行通用数据库回滚、资金操作或业务数据删除。不可逆外部操作若未来进入范围，应作为新的高风险 Action 独立审批、幂等保护、执行后验证和事故流程，不能借本需求的“补偿”名义隐式加入。

---

## 8. 人类在环、安全与审批有效期

用户确认审批有效期默认为 **24 小时**。审批绑定 Action/Step、目标资源、请求摘要、风险/策略版本和幂等键引用。有效期内只有在以上实质性字段不变、主体授权仍有效、策略未撤销且下游执行能力未改变时，才允许同一逻辑意图安全重试并跳过重复审批。

参数、目标、请求摘要、凭据作用域、资源版本或风险发生实质变化，必须建立新意图并重新授权/审批。审批过期、撤销、用户权限变化、策略变化或状态结果未知超过可接受窗口时，不得仅因同键而沿用批准。

幂等查询按组织、项目、仓库、Task 权限过滤；键本身不构成访问凭证。账本和缓存不得暴露参数明文、密钥或敏感个人信息。所有预留、冲突、下游派发、结果核查、补偿、人工决定和访问均形成独立可审计关联，并遵循 `REQ-RT-006` 的事件/Trace/审计分离原则。

---

## 9. 失败处理与依赖边界

| 故障 | 处理 |
|---|---|
| PostgreSQL 不可用 | 有副作用 Action fail-closed；只读诊断可按策略继续 |
| Redis 不可用/丢键 | 回查 PostgreSQL；不可依赖 Redis 判定未执行 |
| 执行租约过期 | 先核查原执行者和外部状态；未知时不接管写执行 |
| 下游明确未接收请求 | `FAILED_RETRYABLE`，在策略额度内复用原键重试 |
| 下游已执行但回执丢失 | `OUTCOME_UNKNOWN`，三次对账后按分级策略等待/升级 |
| 同键参数改变 | 拒绝为 `CONFLICT`，要求新的意图和授权 |
| 下游不支持幂等且无法查询 | 高风险或不可逆写操作禁止自动重试，人工确认 |
| 补偿部分失败 | 保存逐项进度，安全重试；超限升级人工，不掩盖正向副作用 |
| TTL 已过但恢复记录未终结 | PostgreSQL 账本优先；禁止新键重放 |

### 跨模块依赖

- `REQ-RT-001`：复用 Task、Workflow、Action、Step、Worker、资源和 Trace 身份；Action 的 `idempotency_key` 由本专项定义其语义。
- `REQ-RT-003`：追加预留、派发、状态变化、对账和补偿事实事件；事件为事实来源，不能只依赖 Redis。
- `REQ-RT-005`：恢复快照引用操作账本位置及未决副作用；结果未知不得被投影成未开始。
- `REQ-RT-006`：关联 Trace 和独立审计，不受 Trace 采样影响。
- `REQ-REL-001/002/003`：提供失败分类、三次对账失败查询退避及熔断策略；本设计明确最大查询重试数为三次，退避参数需统一。
- `REQ-REL-006`：按本契约实现文件、Git、PR、通知等 Tool Adapter；本设计拥有通用键和边界定义，REL-006 细化各工具动作语义。
- `REQ-REL-007`：承接通用补偿 Saga 生命周期；本设计明确正向/补偿操作各自幂等和 MVP 范围。
- `REQ-SEC-003/008`、`REQ-RT-008`：授权、租户隔离、审计查询、持久化留存和删除策略。

### 接口概念

提供幂等操作预留/查询、原子领取、状态确认、结果核查、补偿登记/执行和用户升级入口。每个命令都引用 Workflow、Step/分支实例、Action、幂等键、请求摘要、Actor/授权、Trace/Event 和下游业务标识；具体协议和端点留给实现与接口专项。

---

## 10. 可观测性与验收标准

### 10.1 指标

- 同逻辑操作重复下游副作用数：目标 0；
- 已确认成功 Action 因恢复而再次派发比例：目标 0；
- 状态未知 Action 未经核查重放数：目标 0；
- 同键不同摘要冲突拦截率：目标 100%；
- 对账尝试次数、成功确认率、等待时长及升级率；
- Redis 命中/丢失、PostgreSQL 预留失败和原子领取冲突；
- 补偿成功率、部分失败率、升级时长及孤立资源数量；
- 并行分支键碰撞/误去重：目标 0。

需按工具类别、结果状态和租户隔离聚合；不得把幂等键明文作为高基数指标标签。完整字段由 `REQ-OBS-003/004` 细化。

### 10.2 可验证验收

1. 首次有副作用 Action 在外部派发前已在 PostgreSQL 持久化键和请求摘要。
2. 模拟重复投递、Worker 重启和恢复，正向外部操作最多发生一次；下游不支持幂等时必须走可验证条件写入或结果核查。
3. 同键同摘要返回既有结果/状态；同键不同摘要必拒绝并生成审计记录。
4. 同一步重试复用键；不同 attempt 不改变键；不同并行分支默认使用不同键；显式共享意图可安全引用同一键且只有一个执行者。
5. Pipeline 恢复会跳过有持久成功结果的节点；节点身份不受并发完成顺序影响。
6. PostgreSQL 故障时有副作用操作被阻断；Redis 清空/过期后仍不会把未决操作误判为新操作。
7. 超时对账最多额外重试三次；权限/确定性错误不重试；三次后进入明确等待或 `ESCALATED`，不盲目重发、不阻塞无依赖只读任务。
8. 下游确认成功、确认未发生、仍未知三种结果分别按本设计进入成功、原键受控恢复、人工升级路径。
9. 24 小时 Redis TTL 到期不删除或改变持久账本中的未终结记录；过期下游键不导致未知操作自动重放。
10. 24 小时审批到期后不能继续跳过审批；实质请求变化、权限撤销或策略版本改变会重新审批。
11. 每种 MVP 补偿可重复调用且安全 no-op；补偿在正向操作之前已登记；失败可恢复并保留逐步证据。
12. 对 PR 关闭、通知、合并、部署等非通用可逆副作用不会宣称自动回滚；未获策略/审批的高风险操作被阻断。
13. 审计可由 Task/Action/Trace 查询到键引用、请求摘要、状态、授权、下游标识、对账和补偿结果；敏感参数与密钥不会明文出现在键/指标中。
14. MVP 并行与 Pipeline 契约测试覆盖重复投递、分支并发、崩溃窗口、租约过期、TTL 到期和状态不一致。

性能目标须经实现基准测试后确认，不在本设计阶段承诺 Redis/PostgreSQL 的具体 p99 数值或部署拓扑。

---

## 11. 版本与演进

- **MVP**：PostgreSQL 权威操作账本 + Redis 24 小时热去重；默认 step scope；支持有界并行和 Pipeline；工具级条件写入/下游键传递；三次对账查询重试；结果未知等待/人工升级；任务 Workspace/未共享分支/短期凭据等受限补偿。
- **后续版本**：跨 Workflow/跨任务业务唯一约束、更多连接器的幂等能力目录、自动对账、可配置 SLA 和更丰富 Saga 补偿。各项须经安全评审与真实任务评测，不预先承诺自动撤销不可逆外部行为。
- 升级 `v1.0-frozen` 前须完成 RT-001/003/005/006、REL-001/002/003/006/007、SEC 和 OBS 交叉评审，确定持久留存与 TTL 关系，完成并发竞态、故障注入、下游回执丢失、Redis 丢失和补偿重放的契约测试。

## 12. 决策记录

| 决策项 | 决策 |
|---|---|
| 幂等热缓存 TTL | 24 小时，仅 Redis 热层；PostgreSQL 账本依恢复/审计策略保留 |
| 默认去重 Scope | `step_scope`，按逻辑步骤实例和意图实例 |
| 外部对账失败 | 最多额外重试 3 次；之后等待/隔离/人工升级，禁止盲目写重放 |
| 补偿范围 | MVP 支持任务专属 Workspace、未共享分支、短期凭据及受控 PR 关闭候选；不承诺不可逆副作用回滚 |
| 审批有效期 | 24 小时；审批绑定请求摘要和目标，事实变化即重新审批 |
| 存储 | PostgreSQL 权威账本，Redis 24 小时热缓存/协调；Redis 不作为正确性来源 |
| 并行/Pipeline | MVP 支持有界并行和有向 Pipeline；稳定分支/步骤 ID，禁止按完成顺序定键 |

---

## 13. 来源

以下公开资料于 2026-09-23 访问；厂商公开文档仅用于确认公开行为和设计原则，不推断其未披露的内部实现：

- [Stripe Idempotent requests](https://docs.stripe.com/api/idempotent_requests)
- [Temporal Activity Definition](https://docs.temporal.io/activity-definition)
- [Temporal Python error handling](https://docs.temporal.io/develop/python/best-practices/error-handling)
- [Temporal Saga pattern](https://docs.temporal.io/design-patterns/saga-pattern)
- [Azure Saga pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/saga)
- [Azure Compensating Transaction pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/compensating-transaction)
- [Microsoft Agent Framework issue 3938](https://github.com/microsoft/agent-framework/issues/3938)
- [Microsoft Durable Task for AI Agents](https://learn.microsoft.com/en-us/azure/durable-task/sdks/durable-task-for-ai-agents)
- [Devin Dynamic Workflows](https://docs.devin.ai/work-with-devin/dynamic-workflows)
- [OpenAI Running Codex safely](https://openai.com/index/running-codex-safely/)
- [OpenAI GPT-5-Codex system card addendum](https://cdn.openai.com/pdf/97cc5669-7a25-4e63-b15f-5fd5bdc4d149/gpt-5-codex-system-card.pdf)
- [Cursor Run Modes and sandboxing](https://cursor.com/docs/agent/security/run-modes)
- [Cursor LLM Safety and Controls](https://cursor.com/docs/enterprise/llm-safety-and-controls)
- [Qoder Quest Overview](https://docs.qoder.com/user-guide/quest/overview)

---

## 14. 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| `v0.1-designed` | 2026-09-23 | 根据用户确认收敛 24 小时 TTL、step scope、三次对账重试、MVP 补偿范围、24 小时审批、Redis + PostgreSQL 和并行/Pipeline 语义；补充公开来源、恢复和验收边界 |