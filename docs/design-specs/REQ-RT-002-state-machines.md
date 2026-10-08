# REQ-RT-002 Task、Workflow、Worker、Action 状态机与迁移约束

> 所属基线：`Runtime Contract v1`（已冻结，2026-10-07）
> 需求编号：`REQ-RT-002`
> 优先级：P0
> 设计版本：`v0.1-frozen`
> 设计状态：已冻结，可作为实现基线（跨模块评审通过，2026-10-07）
> 前置依赖：`REQ-RT-001` 核心运行时实体 Schema
> 设计范围：Task、Workflow、Worker、Action 的状态集合、迁移约束、父子状态一致性、暂停/恢复/取消/失败语义
> 不包含：Event Schema、状态投影实现、Checkpoint 格式、RetryPolicy、幂等键算法、Policy DSL 和数据库 DDL

---

## 1. 需求定义

### 1.1 需求目标

建立一套确定性、可审计、可恢复的分层状态机，使平台能够明确判断：

- 当前 Task 是否允许进入下一阶段；
- Workflow 是否具备启动条件；
- Worker 是否可以运行；
- Action 是否可以授权和执行；
- 哪些状态可以暂停、恢复、取消或失败；
- 审批等待、策略拒绝、测试失败和系统故障如何分流；
- Task 完成时是否具备足够的验证证据。

状态不能由模型自由生成，也不能由 UI 或普通业务代码直接覆盖。模型可以提出计划和 Action，但状态迁移必须通过运行时状态机、前置条件校验和策略校验。

### 1.2 用户和系统价值

| 使用方 | 依赖的状态机能力 |
|---|---|
| Coordinator | 判断任务图是否可以推进、暂停或重规划 |
| Worker Runtime | 判断 Worker 是否可以启动、继续和结束 |
| Policy Gateway | 在 Action 执行前确认任务和父级运行状态 |
| Recovery | 定位最近一致的恢复边界，不重复执行未确认的副作用 |
| Audit | 回放状态变化及其操作者、原因和 Trace |
| Evaluation | 对任务阶段、失败分流和完成条件进行一致评测 |
| UI/API | 展示当前投影状态、等待原因和可用控制操作 |

### 1.3 设计完成的最低条件

1. 明确 Task、Workflow、Worker、Action 的状态集合和职责。
2. 明确每个合法状态迁移的前置条件和禁止条件。
3. 明确终态、暂停、恢复、取消、失败和审批等待语义。
4. 明确父子实体之间的状态一致性约束。
5. 明确状态迁移与 `REQ-RT-001` 共享实体、ID、版本和 Trace 的关系。
6. 明确状态事实与查询投影的边界，为 `REQ-RT-003/004` 留出接口。
7. 明确失败和重试的边界，不在本需求内重复定义 `REQ-REL-*` 协议。
8. 能够覆盖 MVP 的 Issue 到 PR 研发闭环。

---

## 2. 行业调研与可借鉴设计

本节只提取公开官方资料中可确认的工程原则，不推断厂商未公开的内部实现，也不将公开先例等同于本项目已经验证的最优方案。

### 2.1 GitHub Copilot Cloud Agent：阶段化研发流程

GitHub 官方资料显示，Copilot Cloud Agent 可以研究仓库、生成实施计划、在临时开发环境中修改分支、运行测试和 Lint、查看 Diff，并在准备好后创建 Pull Request；任务可以后台运行并接受后续迭代。

对本需求的借鉴：

1. Task 表达研发意图，执行过程需要独立的 Workflow/Session 生命周期。
2. 研究、计划、修改、验证和交付应具有可识别的阶段边界。
3. 分支、Diff 和 Pull Request 是交付过程中的结果，不应被“模型已回复”替代。
4. 任务完成必须以可审查产物和验证结果为条件。

来源：[GitHub Copilot Cloud Agent](https://docs.github.com/en/copilot/concepts/agents/cloud-agent/about-cloud-agent)

### 2.2 Google Jules：Session、Activity 与计划审批

Google Jules 的公开 API 将一次编码任务表示为 Session，并通过 Activity 表达计划、审批、进度和产物；公开状态包括排队、规划、等待批准、执行、暂停、完成和失败等阶段，同时支持计划审批要求。

对本需求的借鉴：

1. 计划审批必须是正式的等待状态，而不是普通工具失败。
2. 异步任务需要可观察、可暂停和可恢复的状态边界。
3. 计划批准、执行活动和产物应由独立结构化对象或后续事件引用表达。
4. 状态机需要区分“等待人工”和“执行失败”。

来源：[Google Jules Sessions API](https://jules.google/docs/api/reference/sessions/)

### 2.3 OpenHands SDK：事件驱动的 Action-Observation 循环

OpenHands 官方 SDK 将 Agent 执行抽象为事件驱动的 Reasoning-Action-Observation 循环：Agent 从事件历史读取上下文，生成结构化 Action，经过安全分析后调用工具，再产生 Observation 事件。

对本需求的借鉴：

1. Action 必须拥有独立生命周期，不能只作为模型消息的一部分。
2. Action 的授权、等待确认、执行和结果状态应分开表达。
3. 一次 Agent step 应可中断，状态不能只存在进程内存。
4. Action 成功只能表示单次工具执行成功，不能推断 Worker 或 Task 完成。

来源：[OpenHands Agent Architecture](https://docs.openhands.dev/sdk/arch/agent)

### 2.4 LangGraph：持久运行、检查点与中断

LangGraph 官方文档区分运行状态、静态上下文和持久化 Store，并使用 Checkpointer 支持线程连续性、人工介入、时间回溯和故障恢复。

对本需求的借鉴：

1. 状态机必须使用稳定的 `workflow_id`，不能用每次模型请求的 ID 代替运行身份。
2. 中断、审批等待和恢复是正式运行语义，不是异常补丁。
3. 状态投影与事实事件必须分离；检查点用于恢复优化，不能替代事件事实源。
4. 状态机不能把长期记忆或任意运行缓存混入核心状态定义。

来源：[LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)

### 2.5 OpenAI Codex Cloud：隔离环境与可审查交付

OpenAI 官方资料显示，Codex Cloud 为任务提供隔离环境，允许并行运行，任务结束后由用户查看摘要和 Diff，并决定是否继续或创建 Pull Request；环境配置、依赖、变量和 Secret 独立管理。

对本需求的借鉴：

1. 执行状态与交付状态必须分离。
2. 工作区、环境、代码版本和任务状态不能混为一个自由文本字段。
3. “Agent 已停止”不等于“任务已交付”。
4. 并行运行需要稳定的 Workflow 和 Worker 状态边界。

来源：[OpenAI Codex Cloud](https://developers.openai.com/codex/cloud)

### 2.6 Claude Code：专用子代理与受限执行

Claude Code 官方资料公开了专用子代理、工具限制、模型和权限配置、后台执行以及高风险操作确认等工程方向。

对本需求的借鉴：

1. `worker_type` 是职责类型，`worker_id` 是具体运行实例，二者不能混用。
2. Worker 状态不能自动扩大工具和资源权限。
3. 高风险 Action 需要进入审批等待或拒绝分支。
4. 子代理失败、审批等待和正常完成应由不同状态表达。

来源：[Claude Code Subagents](https://code.claude.com/docs/en/sub-agents)

### 2.7 调研结论

本项目采用以下成熟工程原则：

- 业务意图、执行实例、职责节点和单次动作分层建模；
- 任务阶段和工具动作生命周期分离；
- 审批等待、暂停和恢复是可持久化状态；
- 模型只能提出 Action，不能直接改变状态或执行工具；
- 状态事实由事件承载，查询状态由投影产生；
- 完成状态必须依赖验证证据和交付条件；
- 失败分类、重试和检查点分别由可靠性需求负责。

这些原则属于公开产品或开源项目可验证的工程方向，不表示本项目已获得同等性能、可靠性或安全结果。最终参数和实现仍需通过本项目的契约测试、故障注入和端到端评测冻结。

---

## 3. 设计边界与共享坐标

### 3.1 本需求包含

- Task 状态机；
- Workflow 状态机；
- Worker 状态机；
- Action 状态机；
- 合法状态迁移及前置条件；
- 父子实体状态一致性；
- 终态、暂停、恢复、取消、失败和审批等待语义；
- 状态迁移请求的确定性校验流程；
- 与事件事实、状态投影、策略和恢复模块的接口边界；
- MVP 状态范围和验收指标。

### 3.2 本需求不包含

| 内容 | 归属需求 |
|---|---|
| Task、Workflow、Worker、Action 核心字段和引用 | `REQ-RT-001` |
| Event Envelope、Payload、事件版本和兼容策略 | `REQ-RT-003` |
| 从事件生成查询状态的投影器实现 | `REQ-RT-004` |
| Checkpoint 格式、保存时机和恢复协议 | `REQ-RT-005`、`REQ-REL-004/005` |
| Trace 传播和 OpenTelemetry Span 语义 | `REQ-RT-006`、`REQ-OBS-001` |
| Action 幂等键生成和副作用保护 | `REQ-RT-007`、`REQ-REL-006` |
| 失败枚举和失败识别算法 | `REQ-REL-001`、`REQ-REL-008` |
| 退避、熔断和重试次数 | `REQ-REL-002/003` |
| 权限模型、Policy DSL 和具体审批矩阵 | `REQ-SEC-002/003` |
| Workflow DAG 调度算法和并行资源分配 | 编排/Harness 后续专项设计 |
| 数据库 DDL、队列实现和 API 路由 | 实现设计阶段 |

### 3.3 共享坐标约束

本需求必须使用 `REQ-RT-001` 已定义的共享坐标，不得重新定义替代字段：

- `task_id`
- `workflow_id`
- `worker_id`
- `action_id`
- `step_id`
- `attempt`
- `trace_id`
- `base_revision`
- `source_revision`
- `working_revision`
- `status_projection`

状态机只定义状态和迁移，不改变这些字段的语义。

### 3.4 状态事实与查询投影

`REQ-RT-001` 中的 `status_projection` 是查询投影字段，不是事实历史。状态迁移必须遵循以下边界：

```text
迁移请求
  -> 读取当前投影
  -> 校验当前状态和实体版本
  -> 校验迁移前置条件
  -> 校验权限、策略、预算和父级状态
  -> 产生状态迁移事实
  -> 由 REQ-RT-003 持久化事件
  -> 由 REQ-RT-004 更新 status_projection
```

本需求不规定事件字段，但要求后续事件能够表达：

- 状态迁移的实体和父级引用；
- `from_state` 与 `to_state`；
- 迁移原因和操作者；
- `trace_id`；
- 迁移请求的幂等关联；
- 必要的版本和因果关系。

---

## 4. 状态机总览

平台采用四层状态机：

```text
Task State Machine
    |
    v
Workflow State Machine
    |
    v
Worker State Machine
    |
    v
Action State Machine
```

| 层级 | 表达内容 | 不负责表达 |
|---|---|---|
| Task | 用户研发意图和整体交付生命周期 | 单个工具调用的执行细节 |
| Workflow | 一次具体执行实例的生命周期 | 用户原始需求本身 |
| Worker | 一个职责节点的执行生命周期 | 整个任务的最终交付判断 |
| Action | 一次结构化动作的提议、授权和执行结果 | Task 是否完成 |

四层状态必须互相约束，但不能互相替代。例如：

- `Action=SUCCEEDED` 不代表 `Worker=COMPLETED`；
- `Worker=COMPLETED` 不代表 `Workflow=COMPLETED`；
- `Workflow=COMPLETED` 不代表 Task 已具备最终交付证据，除非 Task 完成条件也满足。

---

## 5. Task 状态机

### 5.1 状态集合

```text
CREATED
  -> AUTHORIZING
  -> PLANNING
  -> WAITING_APPROVAL
  -> PREPARING_WORKSPACE
  -> EXECUTING
  -> VALIDATING
  -> CREATING_PR
  -> WAITING_REVIEW
  -> COMPLETED
```

控制和异常状态：

```text
任意可暂停状态 -> PAUSED
任意非终态 -> CANCELLED
可恢复运行状态 -> FAILED
```

### 5.2 状态语义

| 状态 | 语义 | 是否可继续产生业务 Action |
|---|---|---:|
| `CREATED` | Task 已创建，尚未开始授权 | 否 |
| `AUTHORIZING` | 校验用户、组织、项目、仓库、分支、风险和预算 | 否 |
| `PLANNING` | Explorer/Planner 分析任务并生成计划 | 仅允许计划阶段所需的受限 Action |
| `WAITING_APPROVAL` | 计划或高风险动作等待人工批准 | 否 |
| `PREPARING_WORKSPACE` | 创建隔离工作区、分支和执行环境 | 仅允许准备环境的受限 Action |
| `EXECUTING` | 按已批准计划执行 Worker | 是，受 Policy Gateway 约束 |
| `VALIDATING` | 运行测试、Lint、构建、扫描并汇总证据 | 仅允许验证阶段 Action |
| `CREATING_PR` | 创建提交、分支推送和 Pull Request | 仅允许交付阶段 Action |
| `WAITING_REVIEW` | PR 已生成，等待人工评审 | 否，除非进入明确的评审反馈流程 |
| `COMPLETED` | 所有完成条件满足 | 否 |
| `PAUSED` | 主动暂停，等待恢复 | 否 |
| `CANCELLED` | 主动取消，不再继续业务执行 | 否 |
| `FAILED` | 当前运行无法继续，等待诊断、恢复或人工处理 | 否 |

“是否可继续产生业务 Action”不等于“允许任意工具调用”。即使在可执行状态，Action 仍必须经过工具 Schema、资源、Policy、预算和执行器侧的再次校验。

### 5.3 Task 正常迁移

| 当前状态 | 目标状态 | 必要条件 |
|---|---|---|
| `CREATED` | `AUTHORIZING` | Task 核心字段、来源和 `base_revision` 已通过 Schema 校验 |
| `AUTHORIZING` | `PLANNING` | 身份、组织、项目、仓库、任务范围和预算授权通过 |
| `PLANNING` | `WAITING_APPROVAL` | 计划需要人工确认，或任务策略要求计划审批 |
| `PLANNING` | `PREPARING_WORKSPACE` | 计划已生成且不需要审批 |
| `WAITING_APPROVAL` | `PREPARING_WORKSPACE` | 等待的是计划审批；所有审批通过且计划版本未变化 |
| `WAITING_APPROVAL` | `EXECUTING` | 等待的是执行阶段 Action 审批；审批通过且 Workflow/Worker/Action 重新校验通过 |
| `WAITING_APPROVAL` | `CANCELLED` | 审批被拒绝且策略要求终止，或用户取消 |
| `PREPARING_WORKSPACE` | `EXECUTING` | 工作区、分支、环境、网络和凭据引用准备完成 |
| `EXECUTING` | `VALIDATING` | 必需执行 Worker 完成，且代码变更可验证 |
| `VALIDATING` | `EXECUTING` | 验证失败被判定为可进入 Resolver/修复流程，且未超过恢复边界 |
| `VALIDATING` | `CREATING_PR` | 必需测试、扫描和质量检查满足 PR 创建条件 |
| `CREATING_PR` | `WAITING_REVIEW` | PR、Diff、摘要和验证证据创建成功 |
| `WAITING_REVIEW` | `COMPLETED` | 人工评审和最终交付条件满足 |

### 5.4 Task 控制和异常迁移

#### 暂停

以下状态允许进入 `PAUSED`：

```text
AUTHORIZING
PLANNING
WAITING_APPROVAL
PREPARING_WORKSPACE
EXECUTING
VALIDATING
CREATING_PR
WAITING_REVIEW
```

`CREATED` 是否允许暂停由 API 层决定，MVP 不提供无意义的创建后暂停；`COMPLETED`、`CANCELLED` 和 `FAILED` 不允许进入 `PAUSED`。

暂停必须：

1. 阻止新的业务 Action 提交；
2. 保留当前 Workflow、Worker、Artifact 和 Evidence 引用；
3. 记录暂停原因、操作者和 `trace_id`；
4. 对正在执行的 Action 按执行器策略完成安全收尾或中止；
5. 保存后续恢复所需的版本和工作区引用。

#### 取消

所有非终态 Task 均可由用户或具备权限的系统控制器请求 `CANCELLED`，但执行器可能需要先完成凭据撤销、进程停止和工作区清理等补偿动作。

取消后：

- 不得产生新的业务 Action；
- 允许产生受控的清理和审计动作；
- 原有 Action、Artifact、Evidence 和 Trace 不得删除或覆盖；
- 不得自动恢复为任何执行状态。

#### 失败

Task 进入 `FAILED` 前，必须存在可定位的失败原因和失败层级。失败原因的枚举和识别算法由 `REQ-REL-001` 定义，本需求只要求状态机保留失败分支。

`FAILED` 不等价于永久不可恢复。是否创建新的 Workflow、从检查点恢复或进入人工处理，由 `REQ-RT-005` 和 `REQ-REL-005` 决定；但 `FAILED` Task 本身不得直接被状态字段覆盖回执行态。

### 5.5 Task 完成条件

Task 不得仅因模型或 Worker 返回“完成”而进入 `COMPLETED`。至少必须满足：

1. 必需 Workflow 节点已结束；
2. 代码变更对应的 `source_revision` 可验证；
3. 必需测试或质量检查已生成有效 Evidence；
4. 所需审批已完成；
5. Policy Gateway 没有未解决的拒绝；
6. PR 或最终交付 Artifact 已成功生成；
7. 没有未处理的高风险问题或阻塞性评审意见；
8. 预算、时间和执行范围未越界；
9. 完成条件所需的 Evidence 未被撤销或过期。

---

## 6. Workflow 状态机

### 6.1 状态集合

```text
CREATED
  -> READY
  -> RUNNING
  -> WAITING_APPROVAL
  -> PAUSED
  -> COMPLETED
  -> FAILED
  -> CANCELLED
```

### 6.2 状态语义

| 状态 | 语义 |
|---|---|
| `CREATED` | Workflow 实例已创建，但模板、输入或执行资源尚未全部准备完毕 |
| `READY` | 模板、配置、输入、版本、预算和运行范围已经冻结，可调度 Worker |
| `RUNNING` | 至少存在一个可运行或正在运行的 Worker |
| `WAITING_APPROVAL` | Workflow 因计划、权限或高风险 Action 等待人工批准 |
| `PAUSED` | Workflow 被主动暂停，等待恢复 |
| `COMPLETED` | 所有必需节点完成且 Workflow 级证据满足 |
| `FAILED` | Workflow 在当前运行实例内无法继续 |
| `CANCELLED` | Workflow 被明确取消 |

### 6.3 Workflow 迁移条件

#### `CREATED -> READY`

必须确认：

- `workflow_template_id` 和 `workflow_template_version` 已确定；
- `agent_profile_id/version` 已确定；
- `toolset_id/version` 已确定；
- `base_revision` 已确定且可验证；
- 任务组织、项目、仓库和资源范围已冻结；
- Workflow 预算已分配；
- 运行 Trace 已建立；
- 必要输入 Artifact 已存在且版本兼容。

#### `READY -> RUNNING`

必须至少存在一个满足以下条件的 Worker：

- `step_id` 可调度；
- 输入 Artifact 已锁定；
- Worker 的工具和资源能力已声明；
- Worker 资源范围不超过 Task/Workflow 范围；
- Policy Gateway 允许启动；
- 执行环境已经准备完成。

#### `RUNNING -> WAITING_APPROVAL`

发生以下任一情况时进入：

- 计划需要人工批准；
- Worker 产生需要审批的高风险 Action；
- Worker 请求额外资源或工具权限；
- 输出提交需要人工确认；
- Policy Gateway 返回 `REQUIRE_APPROVAL`。

#### `WAITING_APPROVAL -> RUNNING`

必须满足：

- 所有必需审批已通过；
- 审批范围覆盖当前计划或 Action；
- Workflow、Worker、输入 Artifact 和 `source_revision` 仍然有效；
- 权限、预算和工具版本已重新校验；
- 不存在更高优先级的暂停、取消或 Kill Switch。

审批被拒绝时，Workflow 按策略进入 `FAILED` 或 `CANCELLED`，不得直接回到 `RUNNING`。

#### `RUNNING -> COMPLETED`

必须满足：

- 所有必需 Worker 已完成；
- 所有必需 Artifact 和 Evidence 已产生；
- DAG 节点依赖满足；
- 没有待处理 Action、审批或阻塞性失败；
- Workflow 级完成条件已由确定性规则确认。

#### `RUNNING -> FAILED`

可在以下情况下发生：

- 当前 Workflow 无法通过失败恢复边界继续；
- 必需节点失败且没有可用 Resolver/重规划路径；
- 工作区或运行环境不可恢复；
- 预算、时间、并发或资源限制耗尽；
- Policy Gateway 或 Kill Switch 要求终止；
- Workflow 版本或输入 Artifact 已失效，不能安全继续。

### 6.4 Workflow 与 Task 的关系

- Task 未进入允许执行的阶段时，Workflow 不得进入 `RUNNING`；
- Task 被 `CANCELLED` 后，其当前 Workflow 不得恢复；
- Workflow 完成前，Task 不得进入 `COMPLETED`；
- Workflow 失败不自动覆盖 Task 的历史，也不自动将 Task 标记为永久失败；
- 一个 Task 的历史 Workflow 不得复用旧 `workflow_id` 覆盖原执行实例；
- MVP 产品接口只允许一个当前 Workflow，但底层 Schema 保留历史 Workflow 的表达能力。

---

## 7. Worker 状态机

### 7.1 状态集合

```text
CREATED
  -> READY
  -> RUNNING
  -> WAITING_APPROVAL
  -> PAUSED
  -> COMPLETED
  -> FAILED
  -> CANCELLED
```

### 7.2 `CREATED -> READY`

必须满足：

- 所属 `workflow_id` 和 `task_id` 可以反向校验；
- `step_id` 有效；
- `worker_type` 已确定；
- `attempt >= 1`；
- 输入 Artifact 已存在且版本有效；
- `source_revision` 已确定；
- 工具和资源能力已声明；
- Worker 预算已分配；
- Worker 配置和 Toolset 版本已冻结。

### 7.3 `READY -> RUNNING`

必须满足：

- Workflow 当前允许运行；
- Worker 资源通过授权；
- 执行环境已创建；
- 没有未解决的审批或策略拒绝；
- Worker 未超过预算和时间限制；
- 该 `step_id` 的依赖已完成。

### 7.4 `RUNNING -> WAITING_APPROVAL`

以下情况进入等待：

- 生成高风险 Action；
- 请求访问当前范围以外的资源；
- 请求扩大工具能力；
- 需要用户确认局部计划或输出；
- 策略要求对文件、网络、凭据或外部系统操作进行审批。

等待期间：

- 不得继续提交依赖该审批的 Action；
- 不得通过自动重试绕过审批；
- 原 Worker、`attempt` 和上下文引用保持不变；
- 审批完成后需重新校验版本、预算和权限。

### 7.5 `WAITING_APPROVAL -> RUNNING`

必须满足：

- 所有必需审批已通过；
- 审批范围与当前 Worker 请求一致；
- Worker、输入 Artifact、`source_revision`、预算和权限重新校验通过；
- Workflow 仍处于允许继续的状态。

审批被拒绝时，Worker 按策略进入 `FAILED` 或 `CANCELLED`，不得自行恢复运行。

### 7.6 `RUNNING -> COMPLETED`

必须同时满足：

- Worker 输出符合声明的 Schema；
- 所需 Artifact 或 Evidence 已生成；
- 必需验证器已通过；
- 没有未处理 Action；
- 没有未解决的阻塞问题；
- 输出引用的 `source_revision` 正确且可验证。

### 7.7 `RUNNING -> FAILED`

只能在以下情况发生：

- 失败恢复边界耗尽；
- 输入 Artifact 无效或版本冲突；
- 工作区不可恢复；
- Policy Gateway 明确终止；
- 预算或执行时间耗尽；
- Worker 进程异常且不能从一致恢复边界继续；
- Worker 输出无法满足契约，且有限修复路径已经耗尽。

Worker 失败后，是否创建新的 `attempt`、Resolver 或新的 Workflow 由可靠性模块决定。原 Worker ID 和历史输出不得复用覆盖。

### 7.8 Worker 状态与权限边界

- `allowed_tools` 和 `allowed_resources` 是能力声明，不是最终授权结果；
- Worker 状态变化不能自动增加工具、文件、网络或凭据权限；
- `CODER` 和 `RESOLVER` 不因类型自动获得写权限；
- Worker 只能在所属 Task/Workflow 的资源范围内运行；
- Worker 之间只能通过结构化 Artifact/Evidence 传递结果，不通过共享完整对话隐式改变状态。

---

## 8. Action 状态机

### 8.1 状态集合

```text
PROPOSED
  -> AUTHORIZED
  -> WAITING_APPROVAL
  -> REJECTED
  -> EXECUTING
  -> SUCCEEDED
  -> FAILED
  -> CANCELLED
```

### 8.2 Action 生命周期

```text
Worker 提议 Action
  -> 工具和参数 Schema 校验
  -> 目标资源校验
  -> Policy Gateway 决策
  -> ALLOW / REQUIRE_APPROVAL / DENY
  -> 授权、等待或拒绝
  -> 执行器再次校验
  -> 工具执行
  -> Observation / Evidence
  -> 结果归档
```

### 8.3 `PROPOSED` 状态约束

Action 进入 `PROPOSED` 时必须：

- 绑定 `task_id`、`workflow_id`、`worker_id`、`step_id` 和 `trace_id`；
- 提供 `tool_name` 和 `tool_schema_version`；
- 显式声明 `target_resources`；
- 提供可验证的 `source_revision`；
- 可通过工具参数 Schema 校验；
- 关联当前 Worker 的有效 `attempt`。

### 8.4 `PROPOSED -> AUTHORIZED`

必须满足：

- 工具存在且版本匹配；
- 参数符合工具 Schema；
- 目标资源在授权候选范围内；
- 风险等级已确定；
- 预算足够；
- Task、Workflow 和 Worker 当前状态允许该 Action；
- Policy Gateway 返回 `ALLOW`；
- `policy_decision_id` 已记录。

`AUTHORIZED` 只表示获得执行许可，不表示工具已经执行成功。

### 8.5 `PROPOSED -> WAITING_APPROVAL`

Policy Gateway 返回 `REQUIRE_APPROVAL` 时进入。

审批请求至少需要能够关联：

- Action 和 Worker；
- 目标资源；
- 风险级别；
- 预期影响；
- 所需审批角色；
- 批准后的有效范围；
- 撤销和取消方式；
- 任务、Workflow 和 Trace。

Action 在等待期间不得执行、不得自动重试、不得通过变更状态字段绕过审批。

### 8.6 `PROPOSED -> REJECTED`

以下情况直接拒绝：

- 目标资源越界；
- 工具不在 Worker 的允许集合；
- 参数不合法；
- 风险超过任务上限；
- 网络、凭据或环境策略不允许；
- Task、Workflow 或 Worker 已暂停、取消或终止；
- 违反组织级安全策略；
- `source_revision` 无法验证。

策略拒绝不是普通工具异常，不得由 RetryPolicy 自动重试。

### 8.7 `WAITING_APPROVAL -> AUTHORIZED`

必须满足：

- 审批已通过且审批范围覆盖该 Action；
- Action 参数、目标资源、`source_revision` 和工具版本未发生变化；
- Task、Workflow、Worker 状态仍允许执行；
- Policy Gateway 重新确认授权并写入 `policy_decision_id`。

如果 Action 内容或目标资源发生变化，必须创建新的 Action 提议，不得复用原审批结果。审批被拒绝时，Action 进入 `REJECTED` 或 `CANCELLED`，不得自动进入执行。

### 8.8 `AUTHORIZED -> EXECUTING`

执行器接受 Action 前必须再次校验：

- Action ID 和 `policy_decision_id`；
- Task、Workflow、Worker 的当前状态；
- 工具和 Schema 版本；
- 目标资源范围；
- 短期凭据有效期和绑定任务；
- 预算剩余量；
- Kill Switch 和全局停止状态。

### 8.8 `EXECUTING -> SUCCEEDED`

仅表示执行器确认该 Action 的工具结果符合执行器层面的成功条件。它不表示：

- Worker 已完成；
- Workflow 已完成；
- Task 已完成；
- PR 可以合并；
- 业务结果已经正确。

业务正确性和质量门禁必须由 Artifact、Evidence、Tester、Reviewer 和后续完成条件判断。

### 8.9 `EXECUTING -> FAILED`

Action 失败时至少需要为后续失败分类模块保留：

- 失败层级和初步原因；
- 工具返回码或结构化错误；
- 失败摘要；
- 目标资源；
- 已产生的部分副作用；
- 当前 `source_revision` 和工作区引用；
- 是否需要 Resolver、补偿或人工处理。

本需求不定义失败枚举、重试次数和退避参数。

### 8.10 Action 取消

未执行的 Action 可以进入 `CANCELLED`。执行中的 Action 是否可以立即中止取决于执行器和安全策略，但取消请求必须阻止后续业务推进，并留下可审计结果。

Action 重试不得覆盖原 Action。若后续允许重试，必须由 `REQ-RT-007` 和 `REQ-REL-006` 定义新的 Action/attempt/幂等关联。

---

## 9. 暂停、恢复、取消和失败协议边界

### 9.1 暂停

暂停是可恢复控制状态，不是失败。

暂停时：

1. 阻止新的业务 Action 提交；
2. 保留 Task、Workflow、Worker、Artifact、Evidence 和 Trace 引用；
3. 保存恢复所需的工作区、版本和预算引用；
4. 记录暂停原因、操作者和时间；
5. 对正在执行的 Action 执行安全收尾或中止；
6. 不修改或删除历史实体。

### 9.2 恢复

恢复必须满足：

- 任务未被取消或完成；
- Workflow 模板、Agent Profile 和 Toolset 版本仍然有效；
- Policy Gateway 重新校验当前权限；
- 工作区和 `working_revision` 仍可验证；
- 预算、超时和并发限制仍然满足；
- 所依赖的 Artifact/Evidence 未被撤销或失效；
- 从最近一致的 Worker/Action 边界继续，而不是盲目从 Task 起点执行。

检查点格式和具体恢复过程由 `REQ-RT-005`、`REQ-REL-004/005` 定义。本需求只定义恢复必须回到合法状态和一致边界。

### 9.3 取消

取消后：

- 不允许产生新的业务 Action；
- 可以执行凭据撤销、进程停止、工作区清理和审计记录等受控补偿动作；
- 原有历史不可覆盖或删除；
- 不允许自动恢复为执行状态。

### 9.4 失败

失败必须保留层级：

```text
Task failure
  -> Workflow failure
    -> Worker failure
      -> Action failure
        -> Tool / Environment / Policy / Test failure
```

不能把所有失败压缩为一个无法定位根因的 `FAILED` 字符串。失败分类、重试、补偿和恢复由可靠性专项设计负责。

---

## 10. 父子状态一致性约束

### 10.1 Task 与 Workflow

1. Task 未进入允许执行的阶段，Workflow 不得进入 `RUNNING`。
2. Task 进入 `PAUSED` 时，当前 Workflow 不得继续推进新的业务 Action。
3. Task 进入 `CANCELLED` 后，当前 Workflow 必须进入取消或清理路径，不得恢复执行。
4. Workflow 未完成时，Task 不得进入 `COMPLETED`。
5. Workflow 完成不自动意味着 Task 完成，Task 仍需检查全局交付 Evidence。
6. Workflow 失败不能通过覆盖 `workflow_id` 消除历史执行；重跑需使用新的 Workflow 实例或由后续恢复协议明确表达。

### 10.2 Workflow 与 Worker

1. Workflow 未处于 `READY` 或 `RUNNING` 等允许调度的状态时，Worker 不得进入 `RUNNING`。
2. Workflow 进入 `WAITING_APPROVAL` 时，依赖该审批的 Worker 必须停止推进。
3. 所有必需 Worker 完成且节点依赖满足后，Workflow 才可以进入 `COMPLETED`。
4. 任一必需 Worker 失败时，Workflow 必须进入恢复、重规划或失败分支。
5. Worker 不能通过自己的状态声明扩大 Workflow 权限。
6. 并行 Worker 必须绑定明确的 `step_id`、输入 Artifact 和 `source_revision`。

### 10.3 Worker 与 Action

1. Worker 非 `RUNNING` 时不得提出需要执行的 Action。
2. Action 必须属于一个具体 Worker 实例和 `attempt`。
3. Action 被拒绝不能转化为授权或成功。
4. Action 成功不能自动推断 Worker 完成。
5. 写 Action 失败不能直接重新进入 `EXECUTING`，必须经过幂等和副作用检查。
6. Worker 进入 `WAITING_APPROVAL` 时，依赖审批的 Action 必须处于 `WAITING_APPROVAL` 或尚未提交状态。
7. Worker 进入 `CANCELLED` 或 `FAILED` 后不得产生新的业务 Action。

### 10.4 Action 与 Artifact/Evidence

1. Action 成功后可以产生 Artifact 或 Evidence，但二者必须保留各自不可变 ID。
2. Artifact/Evidence 的 `source_revision` 必须与实际验证或产出版本一致。
3. Evidence 不足时，不能仅凭 Action 成功进入 Task 完成状态。
4. Artifact/Evidence 被撤销或过期时，相关完成条件必须重新评估。
5. Artifact/Evidence 的内容变化必须产生新对象，不能通过更新旧对象改变历史事实。

---

## 11. 状态迁移决策流程

推荐所有状态变化采用以下确定性流程：

```text
TransitionRequest
  -> 读取当前 status_projection
  -> 校验实体版本和父级引用
  -> 校验 from_state 与 to_state
  -> 校验状态迁移表
  -> 校验前置条件
  -> 校验父级状态
  -> 校验权限、策略和审批
  -> 校验预算、版本和资源
  -> 生成迁移事实
  -> 由 Event Store 持久化
  -> 由 Projection 更新查询状态
```

### 11.1 迁移请求必须包含的语义

具体 Event Schema 由 `REQ-RT-003` 定义，但迁移接口必须能表达：

- 目标实体类型和实体 ID；
- 当前状态和目标状态；
- 父级实体引用；
- 迁移原因；
- 操作者或系统 Actor；
- `trace_id`；
- 关联的 Action、Policy Decision、Approval 或 Evidence；
- 版本和因果关联；
- 防止重复处理的请求关联。

### 11.2 确定性规则

1. 非法 `from_state -> to_state` 必须拒绝。
2. 缺少必需前置条件必须拒绝。
3. 父级状态不允许时，子级迁移必须拒绝或进入受控等待。
4. 重复提交同一迁移请求不得产生重复业务效果。
5. 状态投影更新失败不能伪造迁移成功；事实和投影的一致性由 `REQ-RT-004` 负责。
6. UI、模型输出和客户端传入的 `status` 不能直接覆盖事实状态。
7. 状态迁移不得改变实体创建后不可变的 ID、版本、来源和 `source_revision` 语义。
8. 状态迁移不得写入长期凭据、模型隐藏思维链或未脱敏敏感内容。

---

## 12. MVP 范围和非目标

### 12.1 MVP 包含

- Task、Workflow、Worker、Action 四层状态机；
- 状态集合和状态语义；
- 正常推进、暂停、恢复、取消、失败和审批等待边界；
- 父子状态一致性约束；
- Action 执行前的状态检查；
- Task 完成条件的状态层表达；
- 与 `REQ-RT-001` 的共享实体和版本坐标；
- 为事件、投影、恢复、策略和可靠性模块定义接口约束；
- Issue 到 PR 场景的有限 Workflow 状态路径。

### 12.2 MVP 不包含

- 复杂 DAG 调度和动态拓扑算法；
- 多 Workflow 并行竞争策略；
- Event Store 的具体实现；
- Checkpoint 的字节格式和保存策略；
- RetryPolicy、退避、熔断和补偿实现；
- Policy DSL 和完整审批矩阵；
- 多租户状态存储实现；
- 数据库、队列、API 或 UI 代码；
- 代码实现、部署实现和性能基准结果。

---

## 13. 验收与评测方案

### 13.1 状态迁移契约测试

至少验证：

1. 所有合法迁移能够通过；
2. 所有未定义迁移被拒绝；
3. 缺少必需 Artifact、Evidence、Approval 或 Policy Decision 时拒绝；
4. 父级状态不允许时，子级迁移被拒绝或进入定义的等待状态；
5. `Action=SUCCEEDED` 不会直接把 Worker、Workflow 或 Task 推到完成；
6. `Task=CANCELLED` 后不能提交新的业务 Action；
7. 审批等待不能自动变成执行或普通失败；
8. 暂停后新的业务 Action 被阻止；
9. 恢复前重新执行权限、版本、预算和工作区检查；
10. 状态迁移不改变不可变实体 ID、版本和来源字段。

### 13.2 属性和不变量测试

至少覆盖：

- 任意合法 Action 都能追溯到有效 Worker、Workflow 和 Task；
- 任意可运行 Worker 都属于允许运行的 Workflow；
- 任意完成 Task 都能找到满足条件的 Workflow、Artifact 和 Evidence；
- 取消和终态不会重新回到业务执行状态；
- 相同迁移请求重复提交不会产生重复业务效果；
- Worker 新 attempt 不覆盖旧 Worker、Action 或 Artifact；
- `source_revision` 不会因 `working_revision` 更新而改变；
- 状态投影字段更新不会删除历史事实的表达能力。

### 13.3 代表性场景

| 场景 | 预期结果 |
|---|---|
| 创建 Bug 修复任务 | Task 从 `CREATED` 进入 `AUTHORIZING`，不能直接进入 `EXECUTING` |
| 计划需要人工确认 | Task/Workflow 进入 `WAITING_APPROVAL`，相关 Action 不执行 |
| 审批通过且计划未变化 | 重新校验权限和版本后进入工作区准备或执行 |
| Coder 产生文件写入 Action | Action 经过 Policy Gateway，未授权时保持等待或拒绝 |
| 测试失败但可修复 | Task 从 `VALIDATING` 返回受控执行/Resolver 路径，不直接标记完成 |
| 测试环境不可恢复 | Worker/Workflow 进入 `FAILED`，保留失败原因和恢复边界 |
| 用户暂停执行 | 新业务 Action 被阻止，工作区和历史引用保留 |
| 用户取消任务 | 任务不再执行，仅允许清理、撤销凭据和审计动作 |
| Action 工具执行成功 | Action 可进入 `SUCCEEDED`，但 Worker/Task 仍需完成各自条件 |
| 所有验证证据齐全并创建 PR | Task 才能进入评审或最终完成路径 |
| Worker 第一次失败后重试 | 新 attempt/运行实例表达新尝试，原历史不被覆盖 |
| Kill Switch 生效 | 新 Action 被阻断，相关运行进入暂停或终止处理路径 |

### 13.4 设计目标指标

以下是后续实现和评测目标，不是当前已达成的运行指标：

- 合法/非法迁移判断确定性：100%；
- 非法迁移拦截率：100%；
- 高风险 Action 审批拦截率：100%；
- 取消后新业务 Action 阻断率：100%；
- 状态投影重建结果与事实一致率：100%；
- 重复迁移请求不产生重复业务效果：100%；
- 状态迁移请求 p95：目标小于 100ms，不含外部工具执行；
- 失败样例能够定位到实体层级和原因的比例：不低于 95%。

目标指标需要在 `REQ-RT-003/004`、`REQ-REL-*` 和 `REQ-EVA-*` 完成后通过契约测试、故障注入和回放评测确认，不能在当前文档中视为已验证结果。

---

## 14. 与后续需求的接口约束

### `REQ-RT-001` 核心实体 Schema

本需求必须使用 `REQ-RT-001` 的：

- Task、Workflow、Worker、Action ID；
- `step_id`、`attempt` 和父子关系；
- `status_projection` 语义；
- `source_revision`、`base_revision` 和 `working_revision`；
- Artifact、Evidence 和 Trace 引用。

不得重新定义 Task、Workflow、Worker 或 Action 的状态主体。

### `REQ-RT-003` Event Schema

事件模块必须能够表达本需求中的状态迁移事实，包括实体、父级、状态前后值、原因、Actor、Trace、版本和因果关联。本需求不冻结事件字段名称或序列化格式。

### `REQ-RT-004` 状态投影

投影器必须从事件生成 `status_projection`，不能由 API 或 Worker 直接覆盖状态。投影器必须能够重建 Task、Workflow、Worker 和 Action 的当前查询状态。

### `REQ-RT-005` Checkpoint Protocol

检查点恢复必须回到本需求定义的合法状态和一致边界，并使用 `workflow_id`、`worker_id`、`attempt`、Artifact 引用和 `source_revision`。检查点不能定义一套替代状态机。

### `REQ-RT-007` 与 `REQ-REL-006` 幂等

状态迁移请求、Action 执行和重试不得通过覆盖历史对象表达。具体幂等键、去重窗口和副作用保护由后续需求定义。

### `REQ-SEC-002/003` 权限与 Policy

状态机只消费权限和策略决策，不定义完整授权模型。尤其是：

- Worker 的能力声明不是授权结果；
- Action 的 `requires_approval` 不是 Worker 的放行依据；
- `policy_decision_id` 必须关联实际策略决策；
- Action 执行前和执行器侧都需要策略/授权校验。

### `REQ-REL-001/002/003/005`

本需求提供失败、暂停和恢复的状态边界，但不定义失败分类、重试规则、退避算法、熔断、补偿和具体恢复协议。

### `REQ-EVA-*`

评估模块应使用状态迁移、等待原因、失败层级、Artifact、Evidence 和 Trace 作为回放与评分坐标，不能只根据最终文本判断任务是否成功。

---

## 15. 方案比较与最终选择

### 方案 A：单一总状态字段

把 Task、Workflow、Worker 和 Action 的所有生命周期压缩到一个 `status` 字段。

不选择原因：

- 无法表达父子实体同时处于不同生命周期；
- 审批、暂停、工具执行和任务完成边界混乱；
- 无法支持并行 Worker 和独立 Action 历史；
- 容易把单次工具成功误判为任务完成；
- 不利于故障恢复、审计和状态投影。

### 方案 B：纯对话或模型输出驱动状态

让模型通过文本或 JSON 自行声明“下一状态”。

不选择原因：

- 模型输出不是事实源；
- 容易绕过权限、预算和审批；
- 无法稳定拒绝非法迁移；
- 不利于回放和确定性评测；
- 无法可靠表达取消、暂停和恢复等控制语义。

### 方案 C：四层分离状态机 + 事件事实源 + 状态投影

Task、Workflow、Worker 和 Action 各自拥有职责明确的状态机，状态事实通过事件保存，查询状态由投影生成，策略和恢复模块在迁移前提供约束。

**最终选择：方案 C。**

选择理由：

1. 与 `REQ-RT-001` 的分层实体模型一致；
2. 与 GitHub Copilot Cloud Agent 的阶段化研发流程一致；
3. 与 Google Jules 的 Session、Activity 和审批等待模型一致；
4. 与 OpenHands 的 Action/Observation 生命周期一致；
5. 与 LangGraph 的中断、检查点和恢复边界一致；
6. 与 Claude Code 的受限子代理和高风险确认原则一致；
7. 能支持可审计、可恢复、可评估的 MVP 目标；
8. 将状态、事件、策略、恢复和投影责任清楚分离，降低跨模块耦合。

该方案是当前基于公开证据和项目约束的推荐基线，不代表未经本项目评测的全局最优解。

---

## 16. 设计决策记录

```text
需求编号：REQ-RT-002
功能点：Task、Workflow、Worker、Action 状态机与迁移约束
当前状态：详细设计已完成，待跨模块冻结
前置依赖：REQ-RT-001
候选方案：
  A. 单一总状态机
  B. 纯对话/模型输出驱动状态
  C. 四层分离状态机 + 事件事实源 + 状态投影
公开证据等级：A
推荐基线：方案 C
选择理由：
  1. 保持 REQ-RT-001 的共享实体和版本坐标
  2. 支持审批等待、暂停、恢复、取消和失败分流
  3. 支持并行 Worker、独立 Action 历史和可回放执行
  4. 保持模型、策略、执行器、事件和投影的责任边界
适用边界：
  MVP 单组织、单仓库、Issue 到 PR、有限 Workflow/Worker DAG
替代方案：
  Temporal、LangGraph 或 PostgreSQL + Queue 作为后续运行时承载方案
安全约束：
  默认拒绝；状态迁移前策略校验；审批等待不可绕过；
  Worker 状态不能扩大权限；取消/暂停后阻止新的业务 Action
失败与恢复：
  分层失败；暂停是可恢复控制状态；恢复必须回到合法一致边界；
  具体分类、重试、检查点和补偿由 REQ-REL-* / REQ-RT-005 负责
验收指标：
  合法迁移确定性、非法迁移拦截、父子状态一致性、审批拦截、
  取消后 Action 阻断、状态重建一致性和重复请求无重复业务效果
目标版本：REQ-RT-002 v0.1-designed
```

---

## 17. 版本和冻结条件

### 17.1 当前版本

`REQ-RT-002` 当前版本为 `v0.1-designed`。本需求范围内的状态集合、迁移边界、父子约束和验收设计已经完成，但仍需与事件、投影、检查点、权限、失败恢复和评估模块完成交叉评审后，才能升级为 `v1.0-frozen`。

### 17.2 升级到 `v1.0-frozen` 的条件

必须完成：

1. 与 `REQ-RT-001` 核心实体 Schema 的引用一致性评审；
2. 与 `REQ-RT-003` Event Schema 的状态迁移表达评审；
3. 与 `REQ-RT-004` 状态投影和重建规则评审；
4. 与 `REQ-RT-005` Checkpoint/Recovery 边界评审；
5. 与 `REQ-SEC-002/003` 权限和审批矩阵评审；
6. 与 `REQ-REL-001/002/003/005` 失败和恢复语义评审；
7. 合法/非法迁移契约测试设计完成；
8. 暂停、恢复、取消、审批和 Kill Switch 场景完成故障注入设计；
9. 明确状态枚举兼容和迁移版本规则；
10. 解决所有状态语义冲突后发布 `Runtime Contract v1.0-frozen`。

### 17.3 兼容规则

- 新增非终态状态：必须评估所有消费者和父子状态约束；
- 新增终态：需要重新评估恢复、审计、投影和 UI 行为；
- 修改已有状态语义：主版本升级；
- 修改合法迁移或完成条件：至少小版本升级，并执行回放回归；
- 删除状态或改变父子约束：主版本升级；
- 状态名可以兼容映射，但不能静默改变历史状态含义。

---

## 18. 设计完成范围与结论

### 18.1 本需求已完成设计的内容

- [x] Task 状态集合和正常推进路径；
- [x] Workflow 状态集合和运行边界；
- [x] Worker 状态集合、`step_id` 和 `attempt` 约束；
- [x] Action 提议、授权、审批、拒绝、执行和结果状态；
- [x] 暂停、恢复、取消、失败和终态语义；
- [x] Task 完成条件的状态层约束；
- [x] Task/Workflow/Worker/Action 父子状态一致性；
- [x] 状态迁移与事件事实、投影、策略和恢复的责任边界；
- [x] MVP 范围、非目标、契约测试和代表性评测场景；
- [x] 基于公开官方资料的工程原则和证据边界。

### 18.2 本需求尚未冻结的内容

以下内容不属于本需求缺失，而是明确交由后续专项设计：

- Event Schema 具体字段和版本策略；
- Projection API、重建和一致性实现；
- Checkpoint 格式和恢复协议；
- RetryPolicy、Failure Taxonomy 和 Compensation；
- Policy DSL、资源授权和审批矩阵；
- Workflow DAG 调度、并行冲突和运行时实现；
- 数据库、队列、API 和 UI 实现。

### 18.3 最终结论

`REQ-RT-002` 采用：

> **Task、Workflow、Worker、Action 四层分离状态机 + 事件事实源 + 状态投影 + 可恢复的审批/暂停边界。**

该方案保持 `REQ-RT-001` 的共享坐标和状态投影语义，能够覆盖 MVP 的 Issue 到 PR 流程，并为后续事件、恢复、策略、可靠性和评估模块提供明确接口。它是当前推荐设计基线，不代表已经实现、部署或通过全部运行验证。

---

## 19. 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| `v0.1-designed` | 2026-09-22 | 基于统一设计基线、REQ-RT-001 和公开官方资料，完成四层状态机、迁移约束、父子状态一致性、暂停/恢复/取消/失败语义和验收设计 |
