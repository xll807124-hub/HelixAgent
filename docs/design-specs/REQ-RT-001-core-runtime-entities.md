# REQ-RT-001 核心运行时实体 Schema 详细设计

> 所属基线：`Runtime Contract v1`（已冻结，2026-10-07）  
> 需求编号：`REQ-RT-001`  
> 优先级：P0  
> 设计版本：`v0.2-frozen`  
> 设计状态：已冻结，可作为实现基线（跨模块评审通过，2026-10-07）  
> 设计范围：核心实体 Schema、身份关联、版本坐标、引用完整性和不变量  
> 不包含：状态迁移、事件 Schema、检查点、重试策略和具体数据库 DDL

---

## 1. 需求定义

### 1.1 需求目标

为平台所有后续模块建立一套统一的核心运行时实体模型，使一次 Agent 研发任务能够在同一组身份、版本和追踪坐标下表达：

```text
用户任务
  -> Workflow 执行实例
    -> Worker 执行节点
      -> Action 动作提议
        -> Tool 执行
          -> Artifact / Evidence 产物与证据
```

所有核心实体必须能够回答以下问题：

- 这次执行属于哪个组织、项目、仓库和用户？
- 这次运行使用了哪个 Workflow 模板版本？
- 哪个 Worker 在什么代码版本上工作？
- 哪个 Action 产生了某个文件变更或工具结果？
- 某个 Artifact 或 Evidence 是由谁、基于哪个 revision 生成的？
- 这些实体如何关联到一次完整的 Trace？
- 当任务有并行 Worker、重试或恢复时，如何避免实体含义混淆？

### 1.2 用户和系统价值

| 使用方 | 依赖的实体能力 |
|---|---|
| Coordinator | 根据 Task 和 Workflow 组织执行图 |
| Worker Runtime | 根据 Worker 契约限制工具、资源和输出 |
| Policy Gateway | 根据 Task、Worker、Action 的身份和资源范围做决策 |
| Sandbox | 根据 Workspace/Revision 约束执行边界 |
| Recovery | 根据实体 ID、attempt 和 revision 定位可恢复对象 |
| Audit | 追踪用户、动作、资源和授权关系 |
| Evaluation | 按 Task、Worker、Artifact、Evidence 和 Trace 回放、评分 |
| UI/API | 展示任务、节点、动作、产物和证据 |

### 1.3 验收标准

本需求设计完成的最低条件：

1. 明确核心实体的职责和字段。
2. 每个实体都有稳定的唯一标识和所属范围。
3. Task、Workflow、Worker、Action 的父子关系无歧义。
4. `workflow_template_id`、`workflow_id`、`worker_id`、`worker_type` 不再混用。
5. 每个代码相关产物和证据都绑定 `source_revision`。
6. 每个实体都能关联到 `trace_id` 或明确说明为什么不直接持有它。
7. Schema 能表达并行 Worker、Worker attempt 和 Action 重复提议，而不覆盖历史记录。
8. Schema 不提前承担状态迁移、事件排序和重试决策职责。
9. 任何跨模块实体都只能引用本设计定义的共享坐标，不能自行创造替代 ID。
10. 敏感内容、模型内部思维链和长期凭据不进入核心实体的明文内容字段。

---

## 2. 行业调研与可借鉴设计

本节基于 2026-09-22/23 再次联网复核的公开官方资料，提取与核心 Schema 直接相关的工程原则。公开资料只能证明产品公开支持的行为，不能证明厂商内部实现或本项目已经达到同等效果。

本轮新增复核对象：OpenAI Codex Cloud、Google Jules API/官方文档；同时再次核验 Claude Code、GitHub Copilot Cloud Agent、OpenHands SDK 和 LangGraph。

### 2.1 GitHub Copilot Cloud Agent：任务、分支、环境和交付边界

官方公开资料显示，Copilot Cloud Agent 将一次研发工作组织为：

- 接收 Issue 或自然语言请求；
- 在临时开发环境中研究仓库；
- 生成计划；
- 在分支上修改代码；
- 运行测试和 Lint；
- 产生提交、Diff 或 Pull Request；
- 支持自定义 Agent，声明工具、模型和 MCP 能力。

对本项目的借鉴：

1. Task 不应等同于一次模型请求，而应覆盖一次可追踪的研发意图。
2. 代码工作必须绑定 `repository_id`、`base_revision` 和 `working_revision`。
3. Agent 配置、工具集合和模型选择应作为运行时版本引用，而不是隐含在自由文本中。
4. 分支、Diff、测试结果和 PR 是可关联的产物，但不应直接塞入 Task 的非结构化元数据。

来源：

- [GitHub Copilot Cloud Agent](https://docs.github.com/en/copilot/concepts/agents/cloud-agent/about-cloud-agent.md)
- [GitHub Copilot custom agents](https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/customize-cloud-agent/create-custom-agents)

### 2.2 OpenHands SDK：Action、Observation、Tool 和 ConversationState

OpenHands 官方 SDK 将 Agent 执行抽象为：

- Agent 产生结构化 ActionEvent；
- Tool 接收经过 Schema 校验的 Action；
- Tool 返回结构化 Observation；
- ConversationState 管理运行状态和不可变追加式事件日志；
- ToolDefinition 将 Action、执行器和 Observation 连接起来。

对本项目的借鉴：

1. `Action` 必须是独立的一等实体，不能只是模型响应中的一段 JSON。
2. 工具输入和工具输出需要有明确契约，不能使用任意自由文本作为跨模块接口。
3. Action 的提出者、工具名称、工具调用关联和结果引用必须分开表达。
4. 运行状态不应只存在 Agent 对象内存中；但持久化事件和状态投影属于后续 `REQ-RT-003/004`，本需求只为它们预留稳定引用。
5. `Worker` 或 Agent 的运行配置与 `Action` 的单次动作不能混为同一个对象。

来源：

- [OpenHands Agent](https://docs.openhands.dev/sdk/arch/agent)
- [OpenHands Events](https://docs.openhands.dev/sdk/arch/events)
- [OpenHands Tool System](https://docs.openhands.dev/sdk/arch/tool-system)
- [OpenHands Conversation](https://docs.openhands.dev/sdk/arch/conversation)

### 2.3 LangGraph：State、Context 和 Store 的生命周期分离

LangGraph 官方文档区分：

- `State`：单次图运行中会变化、可被检查点保存的数据；
- `Context`：一次运行的静态依赖和身份上下文；
- `Store`：跨运行持久化的应用数据；
- `thread_id`：连接同一条持久化运行轨迹的稳定标识。

对本项目的借鉴：

1. 运行中的动态状态和静态运行上下文应分开；因此 Task 的身份/范围字段不能与临时模型响应、工具缓存混在一起。
2. 一次运行需要一个稳定的 `workflow_id`，不能每次模型调用重新生成运行身份。
3. 跨任务长期记忆不应放入核心运行时实体；本项目由后续 Memory 模块单独定义。
4. 节点状态和检查点属于后续运行时机制，核心实体只提供 `workflow_id`、`worker_id`、`attempt` 和 Artifact 引用。

来源：

- [LangGraph StateGraph](https://reference.langchain.com/python/langgraph/graph/state/StateGraph)
- [LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [LangGraph Context](https://docs.langchain.com/oss/python/concepts/context)

### 2.4 Claude Code：专用 Agent、工具边界和运行配置

Claude Code 官方资料公开了分层设置、子代理、工具限制、模型选择、技能和工作区隔离等工程方向。

对本项目的借鉴：

1. `worker_type` 表示职责类别，`worker_id` 表示一次具体 Worker 实例，两者必须分离。
2. 工具权限、模型、技能和工作区属于 Worker 的运行配置引用，不应通过 Action 自由扩大。
3. 配置需要可追踪版本，因此实体应记录 `agent_profile_version`、`toolset_version` 或等价引用。
4. 本项目不复制 Claude Code 的内部对象名称，而采用自己的跨模块契约。

来源：

- [Claude Code subagents](https://code.claude.com/docs/en/sub-agents)
- [Claude Code settings](https://code.claude.com/docs/en/settings)
- [Claude Code security](https://code.claude.com/docs/en/security)

### 2.5 OpenAI Codex Cloud：环境、提交版本和权限边界

OpenAI 官方资料显示，Codex Cloud：

- 在隔离云环境中执行任务；
- 检出用户选择的分支或 commit SHA；
- 使用环境配置管理依赖、工具、变量和 Secret；
- 设置阶段可联网，Agent 阶段默认关闭网络；
- Agent 网络访问可以按环境、域名和 HTTP 方法限制；
- 任务完成后返回摘要和 Diff，并支持后续修改或创建 PR；
- 支持后台和并行任务。

对本项目的借鉴：

1. `base_revision` 必须是具体 commit，而不是动态分支名。
2. 环境配置、Secret 引用和 Agent 执行上下文必须区分。
3. `Workspace`、`Revision`、`Task` 和 `Artifact` 不能通过一个 JSON 字段混合表达。
4. 网络策略和凭据配置应作为可追踪运行上下文引用，而不是写入 Action 参数。

来源：

- [Codex Cloud](https://developers.openai.com/codex/cloud)
- [Cloud environments](https://developers.openai.com/codex/cloud/environments)
- [Agent internet access](https://developers.openai.com/codex/cloud/internet-access)
- [Codex manual](https://developers.openai.com/codex/codex-manual.md)

### 2.6 Google Jules：Session、Activity、SourceContext 和计划审批

Google Jules 官方 API 将：

- `Session` 定义为一次在指定上下文中持续执行的编码任务；
- `SourceContext` 定义仓库和起始分支；
- `Activity` 定义 Session 内的计划、审批、进度和产物活动；
- `requirePlanApproval` 定义计划是否需要人工批准；
- Session 状态区分排队、规划、等待批准、执行、暂停、完成和失败；
- Activity API 支持分页查看执行活动和产物。

对本项目的借鉴：

1. Task 与 Workflow 必须分离：Task 表达研发意图，Workflow 表达一次执行 Session。
2. 任务来源和代码来源必须使用结构化 `SourceReference`/`RevisionRef`，不能只有自由文本。
3. 计划批准应由后续状态机和 Evidence 表达，不能把 `approved: true` 作为 Task 的普通元数据。
4. 运行过程活动应由后续 Event Schema 表达，核心实体只保存稳定引用。

来源：

- [Jules Sessions API](https://jules.google/docs/api/reference/sessions/)
- [Jules REST sessions](https://developers.google.com/jules/api/reference/rest/v1alpha/sessions)
- [Jules Activities API](https://jules.google/docs/api/reference/activities/)
- [Jules Getting started](https://jules.google/docs/)

### 2.7 调研结论

本项目 `REQ-RT-001` 采用以下共同原则：

- 业务意图、执行流程、职责实例、单次动作、结构化产物和验证证据分层；
- 强类型、可校验、可引用的对象优先于自由文本串联；
- 静态身份上下文、动态运行状态和长期记忆分离；
- 运行配置、工具能力、模型版本和代码 revision 都必须可追踪；
- 环境、Workspace、网络策略和凭据引用必须与代码 Revision 分离表达；
- 计划批准、执行活动和产物输出应有独立的结构化引用，不用布尔字段或自由文本替代；
- Schema 只定义对象边界和引用，不吞并后续状态机、事件溯源和恢复逻辑。

---

## 3. 设计边界

### 3.1 本需求包含

- `AgentTask`
- `Workflow`
- `WorkflowStep`
- `WorkerDefinitionRef`
- `WorkerRun`
- `Action`
- `PolicyDecision`
- `Artifact`
- `Evidence`
- `TraceContext`
- `RevisionRef`
- `ContentRef`
- `TenantScope`、`ActorRef`、`Budget` 和 `ResourceRef`
- 共享 ID、版本、时间、资源和来源字段
- 实体引用关系
- 字段级敏感信息约束
- 不变量和 Schema 校验规则

### 3.2 本需求不包含

以下内容必须由其他需求设计，不能在本需求中提前定义成最终协议：

| 内容 | 归属需求 |
|---|---|
| Task/Workflow/Worker 状态迁移 | `REQ-RT-002` |
| Event Schema、顺序和事件版本 | `REQ-RT-003` |
| 状态投影和重建 | `REQ-RT-004` |
| Checkpoint 格式和恢复流程 | `REQ-RT-005`、`REQ-REL-004/005` |
| Trace 的 Span、采样和 OpenTelemetry 映射 | `REQ-RT-006`、`REQ-OBS-001` |
| Action 幂等键算法和副作用保护 | `REQ-RT-007`、`REQ-REL-006` |
| 权限策略和 PolicyDecision 规则 | `REQ-SEC-002/003` |
| 工具输入输出的具体 Schema | `REQ-HAR-003` |
| 代码索引实体和关系 | `REQ-CTX-001` |
| 记忆实体 | `REQ-MEM-001` |

### 3.3 核心边界原则

1. 核心实体记录“谁、在哪个任务、哪个运行、哪个版本、产生什么引用”，不记录全部过程日志。
2. 事实历史由事件承载，但事件结构不在本需求冻结。
3. 当前状态可作为查询投影字段存在，但不能在本需求中定义为唯一事实来源。
4. 大型内容通过 `content_ref` 引用对象存储；核心实体保存哈希、媒体类型和大小等可验证元数据。
5. 任何外部资源引用必须带资源类型和资源范围，不能仅保存不透明 URL。
6. 模型内部思维链、长期密钥、未脱敏 Prompt 和完整敏感代码不得写入通用 `metadata`。

---

## 4. 统一类型和共享坐标

以下类型是所有核心运行时实体共同使用的基础。它们在 `Runtime Contract v1` 下只定义语义和格式；数据库类型、序列化库和具体 DDL 属于后续实现设计。

### 4.1 标识类型

| 类型 | 格式 | 语义 |
|---|---|---|
| `EntityId` | UUIDv7 字符串 | 业务实体主标识，时间有序但不表达业务顺序 |
| `TaskId` | `EntityId` | Task 标识 |
| `WorkflowId` | `EntityId` | 一次 Workflow 执行实例标识 |
| `WorkerId` | `EntityId` | 一个 Worker 执行实例标识 |
| `ActionId` | `EntityId` | 一次 Action 提议标识 |
| `ArtifactId` | `EntityId` | 一个不可变 Artifact 标识 |
| `EvidenceId` | `EntityId` | 一条 Evidence 标识 |
| `TraceId` | 32 位小写十六进制字符串 | 一条端到端 Trace 标识；兼容 OpenTelemetry 语义 |
| `SpanId` | 16 位小写十六进制字符串 | 一个执行 Span 标识，属于 Trace 的局部标识 |

说明：

- UUIDv7 用于业务实体，便于按创建时间索引；不能把 UUID 的时间部分当作业务排序依据。
- `TraceId`/`SpanId` 遵循追踪系统格式，不使用 UUID 替代。
- 任何实体的业务排序必须由后续事件或 DAG 序号定义，不能由 UUID 推断。

### 4.2 版本坐标

| 字段 | 语义 | 是否可变 |
|---|---|---|
| `schema_version` | 当前实体 Schema 版本，例如 `runtime.task.v1` | 创建后不可变 |
| `workflow_template_id` | Workflow 模板逻辑标识 | 创建后不可变 |
| `workflow_template_version` | 模板的具体版本 | 创建后不可变 |
| `agent_profile_id` | Agent/Worker 配置逻辑标识 | 创建后不可变 |
| `agent_profile_version` | 配置具体版本 | 创建后不可变 |
| `toolset_id` | 工具集合逻辑标识 | 创建后不可变 |
| `toolset_version` | 工具集合具体版本 | 创建后不可变 |
| `source_revision` | 实体产物所基于的代码版本，通常为 Git commit SHA | 对 Artifact/Evidence 不可变 |
| `base_revision` | Task/Workflow 开始时的目标基线版本 | 创建后不可变 |
| `working_revision` | 当前工作分支或工作区的代码版本引用 | 作为投影字段可更新，历史变化由后续事件记录 |

关键区分：

- `workflow_template_id` 是模板，不是执行实例。
- `workflow_id` 是一次执行实例，不是模板版本。
- `worker_type` 是职责类型，不是 Worker 实例。
- `worker_id` 是一次 Worker 实例，不是用户或模型名称。
- `source_revision` 表示“产物基于什么代码”，不能被当前分支最新版本覆盖。
- `working_revision` 表示“当前工作区在哪里”，只适合 Task/Workflow 的当前投影。

### 4.3 时间类型

所有时间使用 UTC 的 RFC 3339 格式，数据库使用带时区时间类型。

- `created_at`：实体首次创建时间；不可变。
- `updated_at`：查询投影最后更新时间；不作为事件顺序依据。
- `started_at`、`completed_at`：生命周期时间；具体合法性由状态机定义。

不允许使用本地时间、无时区时间或客户端时间作为跨服务一致性判断依据。

### 4.4 预算类型

```text
Budget
- max_input_tokens: integer >= 0
- max_output_tokens: integer >= 0
- max_total_tokens: integer >= 0
- max_cost_microusd: integer >= 0
- max_duration_seconds: integer >= 0
- max_tool_calls: integer >= 0
```

设计决策：

- 金额使用整数微美元或项目统一货币的最小单位，不使用浮点数。
- 预算是授权上限，不是实际消耗；实际消耗由后续 Usage/Evidence/Metric 模型记录。
- `max_total_tokens` 必须不小于输入和输出预算的可解释上限；精确校验由预算模块定义。
- `Budget` 可出现在 Task、Workflow、Worker，不应默认向子对象无限继承；继承和扣减规则属于后续设计。

### 4.5 资源引用类型

```text
ResourceRef
- resource_type: enum
- resource_id: string
- scope: string
- locator: string?
- revision: string?
```

`resource_type` 初始允许：

- `organization`
- `project`
- `repository`
- `branch`
- `file`
- `directory`
- `artifact`
- `external_service`

约束：

- `locator` 不能单独作为授权依据。
- 文件和目录引用必须绑定 `repository_id` 和任务允许的工作区范围。
- 外部服务引用不能包含长期凭据。

---

## 5. 核心实体 Schema

以下 Schema 使用接近 JSON Schema/TypeScript 的中立表示，仅用于冻结概念和字段语义，不代表最终语言或 ORM。

### 5.1 AgentTask

#### 职责

Task 表示用户提出的一项研发意图和其完整交付边界。它是用户、组织、项目、仓库、预算和 Workflow 的业务根实体。

#### Schema

```text
AgentTask
- schema_version: string = "runtime.task.v1"
- task_id: TaskId
- organization_id: EntityId
- project_id: EntityId
- repository_id: EntityId
- creator_id: EntityId
- source_type: SourceType
- source_reference: SourceReference?
- title: string (1..200)
- description: string (1..20000)
- risk_level: RiskLevel
- workflow_template_id: string
- workflow_template_version: string
- workflow_id: WorkflowId?
- base_revision: string
- working_branch: string?
- working_revision: string?
- budget: Budget
- status_projection: TaskStatus?
- created_at: Timestamp
- updated_at: Timestamp
- started_at: Timestamp?
- completed_at: Timestamp?
- metadata: SafeMetadata
- trace_id: TraceId
```

#### 枚举

```text
SourceType = ISSUE | NATURAL_LANGUAGE | PULL_REQUEST | REVIEW_COMMENT | WEBHOOK
RiskLevel = LOW | MEDIUM | HIGH | CRITICAL
TaskStatus = CREATED | AUTHORIZING | PLANNING | WAITING_APPROVAL |
              PREPARING_WORKSPACE | EXECUTING | VALIDATING | CREATING_PR |
              WAITING_REVIEW | COMPLETED | PAUSED | CANCELLED | FAILED
```

`TaskStatus` 在本需求中只是投影字段类型；合法迁移和终态规则由 `REQ-RT-002` 定义。

#### SourceReference

```text
SourceReference
- source_type: SourceType
- provider: string?
- external_id: string?
- url: string?
- snapshot_hash: string?
```

必须保存来源快照或可验证引用，不能只保存一个可能随后变化的外部 URL。

#### Task 不变量

1. `organization_id`、`project_id`、`repository_id`、`creator_id` 必填。
2. 项目和仓库必须属于同一组织，具体授权由 `REQ-SEC-002` 校验。
3. `workflow_id` 在 Workflow 实例创建前可以为空，创建后必须存在且只能指向当前执行实例。
4. `base_revision` 创建 Task 时必须确定；不能用“最新代码”这种动态字符串替代。
5. Task 的描述是用户输入，不得被当作系统策略或权限声明。
6. `status_projection` 不得直接作为事实历史写入覆盖；它只能由后续投影器维护。
7. `metadata` 只能存放允许的非敏感扩展字段，不得成为未定义实体的逃生通道。
8. Task 不能直接保存完整对话历史、模型思维链或长期凭据。

### 5.2 Workflow

#### 职责

Workflow 表示一个 Task 的一次具体执行实例，绑定一个固定的 Workflow 模板版本和一组运行范围。

#### Schema

```text
Workflow
- schema_version: string = "runtime.workflow.v1"
- workflow_id: WorkflowId
- task_id: TaskId
- organization_id: EntityId
- project_id: EntityId
- repository_id: EntityId
- workflow_template_id: string
- workflow_template_version: string
- agent_profile_id: string
- agent_profile_version: string
- toolset_id: string
- toolset_version: string
- base_revision: string
- working_branch: string?
- working_revision: string?
- status_projection: WorkflowStatus?
- budget: Budget
- trace_id: TraceId
- created_at: Timestamp
- updated_at: Timestamp
- started_at: Timestamp?
- completed_at: Timestamp?
- parent_workflow_id: WorkflowId?
- metadata: SafeMetadata
```

```text
WorkflowStatus = CREATED | READY | RUNNING | WAITING_APPROVAL |
                  PAUSED | COMPLETED | FAILED | CANCELLED
```

#### Workflow 不变量

1. 一个 `workflow_id` 只代表一次执行实例。
2. 一个 Workflow 只能属于一个 Task，`task_id` 创建后不可变。
3. Workflow 的模板 ID、模板版本、Agent Profile 版本和 Toolset 版本创建后不可变。
4. Workflow 必须继承 Task 的组织、项目、仓库和 `base_revision`，不允许静默改写作用域。
5. `parent_workflow_id` 只有在明确支持子 Workflow 时使用；MVP 默认禁止无限递归创建。
6. 同一个 Task 的多个历史尝试如果未来需要支持，必须创建新的 Workflow 实例或由 `attempt` 模型表达，不能复用旧 Workflow ID 覆盖历史。
7. Workflow 不直接承载完整 DAG；节点定义属于 Workflow Template，节点实例属于 Worker/Step 设计。

### 5.3 Worker

#### 职责

Worker 表示 Workflow 中一个具有明确职责、工具集、资源边界和预算的执行实例。

#### Schema

```text
Worker
- schema_version: string = "runtime.worker.v1"
- worker_id: WorkerId
- workflow_id: WorkflowId
- task_id: TaskId
- step_id: string
- worker_type: WorkerType
- attempt: integer >= 1
- parent_worker_id: WorkerId?
- input_artifact_ids: ArtifactId[]
- output_artifact_ids: ArtifactId[]
- allowed_tools: string[]
- allowed_resources: ResourceRef[]
- agent_profile_id: string
- agent_profile_version: string
- toolset_id: string
- toolset_version: string
- source_revision: string
- budget: Budget
- status_projection: WorkerStatus?
- trace_id: TraceId
- created_at: Timestamp
- updated_at: Timestamp
- started_at: Timestamp?
- completed_at: Timestamp?
- metadata: SafeMetadata
```

```text
WorkerType = EXPLORER | PLANNER | CODER | TESTER | REVIEWER | RESOLVER | RELEASE
WorkerStatus = CREATED | READY | RUNNING | WAITING_APPROVAL |
                PAUSED | COMPLETED | FAILED | CANCELLED
```

#### Worker 不变量

1. `worker_id` 唯一标识一个执行实例；`worker_type` 只表示职责类别。
2. `worker_id`、`workflow_id`、`task_id` 的关系必须可反向校验。
3. `attempt` 从 1 开始递增；同一 `step_id` 的不同尝试不能复用 `worker_id`。
4. Worker 的 `allowed_tools` 和 `allowed_resources` 是能力声明，不是最终授权结果；最终授权由 Policy Gateway 决定。
5. `allowed_resources` 不得超出所属 Task/Workflow 的资源范围。
6. `CODER` 和 `RESOLVER` 的可写范围必须由后续策略模块进一步限制；Schema 不能通过 `worker_type` 自动授予写权限。
7. Worker 输入只能引用已存在且版本有效的 Artifact；不能把完整上游对话作为隐式输入。
8. Worker 输出通过 Artifact/Evidence 引用表达，不能只写入 `metadata`。
9. Worker 的 `source_revision` 表示该实例开始处理时所依据的代码版本；不能因后续修改而覆盖。

### 5.4 Action

#### 职责

Action 表示 Worker 提议的一次结构化动作，是模型/Worker 与 Policy Gateway、工具执行器之间的契约对象。

#### Schema

```text
Action
- schema_version: string = "runtime.action.v1"
- action_id: ActionId
- task_id: TaskId
- workflow_id: WorkflowId
- worker_id: WorkerId
- step_id: string
- type: ActionType
- tool_name: string
- tool_schema_version: string
- arguments: JsonObject
- target_resources: ResourceRef[]
- source_revision: string
- risk_level: RiskLevel
- requires_approval: boolean
- policy_decision_id: EntityId?
- idempotency_key: string?
- expected_observation_schema: string?
- status_projection: ActionStatus?
- trace_id: TraceId
- created_at: Timestamp
- updated_at: Timestamp
- proposed_at: Timestamp
- authorized_at: Timestamp?
- started_at: Timestamp?
- completed_at: Timestamp?
- metadata: SafeMetadata
```

```text
ActionType = READ | ANALYZE | WRITE | EXECUTE | DELEGATE | REQUEST_APPROVAL | REPORT
ActionStatus = PROPOSED | AUTHORIZED | WAITING_APPROVAL | REJECTED |
               EXECUTING | SUCCEEDED | FAILED | CANCELLED
```

#### Action 不变量

1. Action 必须同时绑定 `task_id`、`workflow_id`、`worker_id`、`step_id` 和 `trace_id`。
2. `worker_id` 所属 Workflow 必须等于 Action 的 `workflow_id`。
3. `tool_name` 必须与 Worker 的工具集合和后续 Tool Registry 对齐。
4. `arguments` 必须可根据 `tool_schema_version` 校验；不能接受未声明的任意参数。
5. `target_resources` 必须显式列出动作目标；不能用空数组表达“全部资源”。
6. `source_revision` 必须存在，尤其是 `WRITE`、`EXECUTE` 和 `REPORT` 类型。
7. `requires_approval` 是风险判断结果的缓存字段，不是 Worker 自行放行的依据。
8. `policy_decision_id` 在执行前必须存在；允许/拒绝/审批语义由 `REQ-SEC-003` 定义。
9. `status_projection` 不得替代 Action 事件历史；状态变化规则由 `REQ-RT-002/003` 定义。
10. `idempotency_key` 的生成和副作用保护由 `REQ-RT-007` 定义；本需求只允许该字段作为稳定引用。
11. 不允许把模型内部思维链写入 `arguments`、`metadata` 或通用可见字段。
12. Action 的成功只表示动作执行结果可接受，不表示 Task、Workflow 或 Worker 已完成。

### 5.5 Artifact

#### 职责

Artifact 是 Worker 之间传递的不可变、可引用、带版本来源的结构化产物。

#### Schema

```text
Artifact
- schema_version: string = "runtime.artifact.v1"
- artifact_id: ArtifactId
- task_id: TaskId
- workflow_id: WorkflowId
- producer_worker_id: WorkerId
- producer_action_id: ActionId?
- type: ArtifactType
- content_schema: string
- content_schema_version: string
- source_revision: string
- content_hash: string
- content_size_bytes: integer >= 0
- content_inline: JsonObject?
- content_ref: ContentRef?
- sensitivity: DataSensitivity
- trace_id: TraceId
- created_at: Timestamp
- metadata: SafeMetadata
```

```text
ArtifactType = PLAN | CODE_CHANGES | TEST_RESULTS | DIFF |
               REVIEW_FINDINGS | FAILURE_ANALYSIS | RELEASE_SUMMARY
DataSensitivity = PUBLIC | INTERNAL | CONFIDENTIAL | RESTRICTED

ContentRef
- storage_provider: string
- object_key: string
- media_type: string
- byte_size: integer >= 0
- content_hash: string
- encryption_key_ref: string?
```

#### Artifact 不变量

1. Artifact 创建后不可原地修改；内容变化必须产生新的 `artifact_id`。
2. `content_hash` 必须与内嵌内容或外部对象内容一致。
3. `content_inline` 与 `content_ref` 至少有一个存在，不能同时为空。
4. 大型内容优先使用 `content_ref`；核心实体仍保留哈希、大小、类型和敏感级别。
5. `producer_worker_id` 必须指向同一 Workflow 的 Worker。
6. `producer_action_id` 如果存在，必须属于同一 Task、Workflow 和 Worker 链路。
7. Artifact 的 `source_revision` 不可变；下游使用时必须检查版本兼容性。
8. Artifact 不得携带超出生产 Worker 权限范围的隐含授权。
9. Artifact 内容中的外部文本、仓库文档和用户输入必须能标记来源和可信级别；具体内容溯源由 Context/Security 模块补充。
10. `REVIEW_FINDINGS`、`TEST_RESULTS` 等结果不能仅由模型自报生成高可信结论，验证证据应由 Evidence 表达。

### 5.6 Evidence

#### 职责

Evidence 是经过某个验证者或确定性工具确认、可用于判断任务质量和完成条件的结构化证据。

#### Schema

```text
Evidence
- schema_version: string = "runtime.evidence.v1"
- evidence_id: EvidenceId
- task_id: TaskId
- workflow_id: WorkflowId
- producer_worker_id: WorkerId?
- source_action_id: ActionId?
- artifact_id: ArtifactId?
- type: EvidenceType
- source: EvidenceSource
- source_revision: string
- verification_method: VerificationMethod
- verifier_type: VerifierType
- verifier_id: string
- result: EvidenceResult
- content_schema: string
- content_schema_version: string
- content_hash: string
- content_inline: JsonObject?
- content_ref: ContentRef?
- trace_id: TraceId
- created_at: Timestamp
- verified_at: Timestamp
- expires_at: Timestamp?
- metadata: SafeMetadata
```

```text
EvidenceType = PLAN_APPROVED | TEST_PASSED | TEST_FAILED | LINT_PASSED |
               BUILD_PASSED | SCAN_CLEAN | REVIEW_APPROVED | APPROVAL_GRANTED |
               DIFF_VERIFIED | PR_CREATED

EvidenceSource = TOOL | WORKER | USER | SYSTEM | EXTERNAL_PROVIDER
VerificationMethod = DETERMINISTIC_CHECK | HUMAN_REVIEW | POLICY_DECISION |
                      SIGNATURE_VERIFICATION | STRUCTURED_ANALYSIS
VerifierType = SYSTEM | USER | SERVICE | WORKER
EvidenceResult = PASSED | FAILED | PARTIAL | REVOKED | EXPIRED
```

#### Evidence 不变量

1. Evidence 必须绑定 `source_revision`。
2. `TEST_PASSED`、`BUILD_PASSED`、`SCAN_CLEAN` 等证据必须说明执行工具或验证服务。
3. `verifier_type=WORKER` 时，不能自动满足高风险或最终交付门禁，除非策略明确允许。
4. Evidence 不能只依赖模型文字声明；必须有 `verification_method` 和来源。
5. Evidence 被撤销或过期后不能继续满足完成条件。
6. 如果 Evidence 关联 Artifact，二者必须属于同一 Task/Workflow，且版本一致或满足显式兼容关系。
7. Evidence 创建后不可覆盖；修正结果必须创建新的 Evidence。
8. `expires_at` 为空表示没有已定义的自然过期时间，不表示永久有效；策略模块仍可以按 revision 或配置撤销。
9. `APPROVAL_GRANTED` 必须能关联审批主体和决策来源；审批协议由 `REQ-SEC-003` 定义。

### 5.7 TraceContext

#### 职责

TraceContext 是实体之间的执行关联信息，不是业务状态，也不替代 OpenTelemetry Span 模型。

#### Schema

```text
TraceContext
- trace_id: TraceId
- span_id: SpanId
- parent_span_id: SpanId?
- task_id: TaskId
- workflow_id: WorkflowId?
- worker_id: WorkerId?
- action_id: ActionId?
- artifact_id: ArtifactId?
- evidence_id: EvidenceId?
- tool_call_id: string?
- model_request_id: string?
- baggage: SafeMetadata
```

实体中的 `trace_id` 是必需的最小关联字段；完整 TraceContext 可以由运行时和观测层按请求传播。

#### Trace 不变量

1. 所有核心实体必须至少持有 `trace_id`。
2. `span_id`、`parent_span_id` 和采样规则属于追踪实现，不得被业务实体拿来表达状态顺序。
3. 子实体的 `trace_id` 必须与所属运行链路一致，跨 Trace 传递必须有明确的 Link 语义。
4. `baggage` 只允许保存经过白名单过滤的低敏元数据，不能保存凭据或完整代码。
5. `task_id` 是业务归属，`trace_id` 是观测关联，两者不能互相替代。

---

## 6. 实体关系模型

```text
Organization
  └── Project
        └── Repository
              └── AgentTask
                    └── Workflow
                          └── Worker (1..n)
                                ├── Action (0..n)
                                ├── Artifact (0..n)
                                └── Evidence (0..n)

Task / Workflow / Worker / Action / Artifact / Evidence
  └── TraceContext (通过 trace_id 关联)
```

### 6.1 关系约束

| 关系 | 基数 | 约束 |
|---|---:|---|
| Task → Workflow | 1:N（MVP 当前 1:1） | Task 创建运行实例后绑定当前 `workflow_id`；历史实例不能覆盖 |
| Workflow → Worker | 1:N | Worker 必须属于同一 Workflow |
| Worker → Action | 1:N | Action 必须由一个 Worker 实例提议 |
| Worker → Artifact | 1:N | Artifact 必须声明生产 Worker |
| Artifact → Evidence | 0:N | Evidence 可引用 Artifact，但版本必须可解释 |
| Action → Evidence | 0:N | Evidence 可引用产生证据的 Action |
| Task → Trace | 1:N | Task 是业务范围，Trace 可有多个 Span |

### 6.2 MVP 的一个重要选择

MVP 的业务接口只允许一个 Task 绑定一个“当前 Workflow 实例”，但底层 Schema 保留历史 Workflow 的能力。这样可以：

- 支持未来的重新运行和对比评估；
- 不覆盖失败运行的历史；
- 避免把 `workflow_id` 误用成模板 ID；
- 为恢复和回放保留稳定边界。

“一个 Task 是否允许多个 Workflow 并存”“旧 Workflow 是否可以重启”属于后续状态机和恢复设计，不在本需求中定案。

---

## 7. 统一字段校验规则

### 7.1 通用规则

- ID 必须符合对应格式，禁止空字符串、客户端自定义递增 ID 或可预测业务编号作为主 ID。
- 所有 `*_id` 的跨实体引用必须能在同一组织权限范围内解析。
- 所有时间必须为 UTC、有时区。
- 所有枚举字段拒绝未知值；新增值必须升级 Schema 或使用兼容策略。
- 所有自由文本字段必须有最大长度。
- 所有 JSON 对象必须通过对应 `content_schema` 或 `metadata_schema` 校验。
- 未知扩展字段只能放入显式版本化的 `metadata`，不能改变核心字段语义。

### 7.2 安全与敏感数据规则

核心实体不得明文保存：

- 模型 API Key、Git Token、OAuth Refresh Token；
- 环境变量中的 Secret、Password、Private Key；
- 未脱敏的内部凭据；
- 模型隐藏思维链或内部推理令牌；
- 未经数据分类允许的完整敏感代码片段。

允许保存：

- 凭据引用，例如 `credential_ref`，但不保存凭据值；
- 脱敏后的摘要；
- 内容哈希、对象存储引用、数据分类和审计关联；
- 可供用户审查的必要 Diff，但必须服从数据策略。

### 7.3 版本和来源规则

- `schema_version` 表示对象结构版本，不表示对象业务状态。
- `workflow_template_version` 表示工作流逻辑版本，不表示运行结果。
- `agent_profile_version` 表示 Worker 行为配置版本，不表示模型版本本身。
- 模型版本、Prompt 版本和索引版本如影响运行结果，必须通过扩展的 `runtime_asset_refs` 或后续 Asset Schema 显式引用；不能藏在自由文本中。
- `source_revision` 必须是可验证的代码版本标识；不能使用“latest”“main”作为产物证据的版本。

---

## 8. 不变量总表

以下不变量是后续所有模块必须遵守的共享约束：

### 身份不变量

1. 每个实体有唯一、稳定、不可复用的 ID。
2. 每个执行实体都能回溯到 `task_id`、`workflow_id` 或其合法父级。
3. `worker_type` 不替代 `worker_id`，模板 ID 不替代 Workflow ID。

### 版本不变量

1. 代码产物和验证证据绑定不可变 `source_revision`。
2. Workflow、Agent Profile、Toolset 的版本在一次运行中不可静默改变。
3. 当前工作版本和历史产物版本分开表达。

### 边界不变量

1. Action 的目标资源必须显式表达。
2. Worker 的能力声明不等于实际授权。
3. Artifact/Evidence 不能隐含扩大权限。
4. 核心实体不保存长期凭据和未受控敏感内容。

### 可追踪不变量

1. 每个核心实体至少有 `trace_id`。
2. Action 必须能追溯到 Worker、Workflow、Task。
3. Artifact/Evidence 必须能追溯到生产者、来源版本和验证方法。
4. Task 的业务归属和 Trace 的观测归属不能混用。

### 不可变性不变量

1. Artifact 和 Evidence 内容不可原地更新。
2. Action、Worker 和 Workflow 的历史身份不可复用覆盖。
3. 投影字段可更新，但不代表事实历史已被修改；具体事件机制由后续需求定义。

### 责任边界不变量

1. 本 Schema 不决定状态迁移是否合法。
2. 本 Schema 不决定某个 Action 是否被允许执行。
3. 本 Schema 不决定失败是否重试。
4. 本 Schema 不决定某条 Evidence 是否满足最终交付门禁。
5. 本 Schema 不决定上下文、记忆和索引的内部结构。

---

## 9. 推荐的中立序列化结构

以下是一个 Task 及其运行引用的示例。它用于说明实体边界，不是最终 API 响应格式。

```json
{
  "schema_version": "runtime.task.v1",
  "task_id": "0198b2d2-6a6e-7c12-9c6b-5a0e2d8a4d10",
  "organization_id": "0198b2d2-6a6e-7c13-9c6b-5a0e2d8a4d11",
  "project_id": "0198b2d2-6a6e-7c14-9c6b-5a0e2d8a4d12",
  "repository_id": "0198b2d2-6a6e-7c15-9c6b-5a0e2d8a4d13",
  "creator_id": "0198b2d2-6a6e-7c16-9c6b-5a0e2d8a4d14",
  "source_type": "ISSUE",
  "source_reference": {
    "source_type": "ISSUE",
    "provider": "github",
    "external_id": "issue-1842",
    "snapshot_hash": "sha256:..."
  },
  "title": "修复登录权限校验",
  "description": "登录成功后应校验用户所属项目权限。",
  "risk_level": "MEDIUM",
  "workflow_template_id": "github.issue-to-pr",
  "workflow_template_version": "1.0.0",
  "workflow_id": "0198b2d2-6a6e-7c17-9c6b-5a0e2d8a4d15",
  "base_revision": "git:abc123",
  "working_branch": "agent/task-0198b2d2",
  "working_revision": "git:def456",
  "budget": {
    "max_input_tokens": 50000,
    "max_output_tokens": 20000,
    "max_total_tokens": 70000,
    "max_cost_microusd": 5000000,
    "max_duration_seconds": 3600,
    "max_tool_calls": 200
  },
  "status_projection": "EXECUTING",
  "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
  "metadata": {
    "labels": ["bug", "auth"],
    "data_classification": "CONFIDENTIAL"
  }
}
```

示例刻意不包含：

- 明文 Token；
- 完整对话；
- 模型思维链；
- 未定义的 Action 历史；
- 未经验证的“任务已完成”字段。

---

## 10. 设计方案比较与最终选择

### 方案 A：单一 Task 大对象

把任务、对话、工具调用、代码变更、测试和 PR 全部塞入一个 Task JSON。

**不选择原因：**

- 无法清楚表达并行 Worker 和独立重试；
- 权限和生命周期边界混乱；
- 大对象更新容易覆盖历史；
- 不利于事件投影、评估和跨模块引用。

### 方案 B：纯对话消息模型

以消息和模型上下文作为唯一数据结构，工具调用和结果都作为消息。

**不选择原因：**

- 消息不是可靠的业务实体；
- 无法严格校验资源、revision、预算和证据；
- 不能把工具执行、Artifact 和验证证据独立交给治理模块；
- 不适合恢复、审计和确定性评估。

### 方案 C：分层强类型实体模型

使用 Task、Workflow、Worker、Action、Artifact、Evidence、TraceContext 分层，并通过不可变引用和版本坐标关联。

**最终选择：方案 C。**

选择理由：

1. 与 OpenHands 的 Action/Observation 和事件驱动边界一致；
2. 与 LangGraph 的 State/Context/Store 生命周期分离原则一致；
3. 与 GitHub Copilot Cloud Agent 的任务、分支、环境和交付边界一致；
4. 能承载 Claude Code 所体现的专用 Agent、工具集合和权限边界；
5. 满足本项目可审查、可恢复、可审计和可评估的产品承诺；
6. 可以让后续状态机、事件、恢复、Policy、Context 和 Evaluation 使用同一套坐标。

---

## 11. 与后续需求的接口约束

### `REQ-RT-002` 状态机

必须使用本设计的实体 ID 和 `status_projection` 语义；不得重新定义 Task/Workflow/Worker/Action 的状态主体。需要补充：

- 合法状态集合；
- 状态迁移条件；
- 终态和恢复状态；
- 状态迁移与实体时间字段的关系。

### `REQ-RT-003` 事件 Schema

必须能够表达本设计实体的创建、引用和状态变化；不得把投影字段当成事件事实。需要补充：

- 事件 Envelope；
- 事件 Payload；
- 事件版本和兼容策略；
- 事件顺序和幂等语义。

### `REQ-RT-004` 状态投影

必须从事件生成 Task、Workflow、Worker、Action 的查询状态；不能通过直接写投影绕过事件事实。

### `REQ-RT-005` Checkpoint Protocol

必须使用本设计的 `workflow_id`、`worker_id`、`attempt`、Artifact 引用和 `source_revision`；不能把检查点定义为另一种任务实体。

### `REQ-SEC-002/003` 权限与 Policy

必须使用：

- `organization_id`、`project_id`、`repository_id`；
- Worker 的 `allowed_tools`、`allowed_resources`；
- Action 的 `target_resources`、`risk_level`、`policy_decision_id`。

Schema 中的能力声明不能直接被解释为允许执行。

### `REQ-REL-001/002/006` 失败、重试和幂等

必须以 `action_id`、`worker_id`、`attempt`、`source_revision` 和后续定义的 `idempotency_key` 为坐标。不得通过覆盖原 Action 或原 Artifact 来表示重试。

### `REQ-CTX-001` 上下文索引

索引结果必须引用 `repository_id` 和 `source_revision`；不得使用没有版本的“当前代码”结果作为可回放上下文。

### `REQ-EVA-001/003`

评估样本和评分结果必须能够引用 Task、Workflow、Artifact、Evidence、Trace 和资产版本。

---

## 12. 验收与评测方案

### 12.1 Schema 契约测试

必须验证：

1. 所有必填字段缺失时拒绝；
2. 非法 ID、时间、枚举和负数预算拒绝；
3. 跨实体引用不一致时拒绝；
4. Artifact 内容为空或哈希不一致时拒绝；
5. Evidence 缺少来源版本或验证方式时拒绝；
6. Action 缺少目标资源、工具 Schema 或 Trace 时拒绝；
7. Worker 的 Artifact 引用不属于同一 Workflow 时拒绝；
8. Task 的 repository 不属于 organization 时进入授权错误，而不是静默接受；
9. 敏感字段扫描能够拦截明显 Token、Private Key 和密码模式；
10. 未知 Schema 版本不会被当作旧版本静默解析。

### 12.2 属性与不变量测试

至少覆盖：

- 任意合法 Worker 都能追溯到一个 Task 和 Workflow；
- 任意 Action 都能追溯到一个 Worker；
- 任意 Artifact/Evidence 都能追溯到生产来源和 revision；
- 同一个不可变 Artifact 的内容变化会产生新 ID；
- `worker_type` 变化不会改变 `worker_id` 的历史含义；
- `workflow_template_version` 改变不会修改已有 Workflow；
- `source_revision` 不会被当前 `working_revision` 覆盖；
- Task 业务归属和 Trace 观测归属可以独立查询。

### 12.3 代表性评测场景

| 场景 | 预期结果 |
|---|---|
| 单 Worker 只读探索 | 创建 Task、Workflow、Worker 和 READ Action，可生成 Artifact |
| Coder 修改两个文件 | Action 和 CODE_CHANGES Artifact 绑定同一 source revision 起点 |
| Tester 在新 revision 上运行 | TEST_RESULTS Artifact 和 Evidence 绑定新 revision |
| 同 Workflow 两个并行 Worker | 两个 Worker ID 不重复，输入 revision 可独立记录 |
| Worker 第一次失败后新 attempt | 新 Worker ID，原 Worker 和其产物保留 |
| Action 被要求访问越界资源 | Action 可被记录为提议，但不能通过 Schema 或实体字段伪造授权 |
| Artifact 内容更新 | 创建新 Artifact，不修改原 Artifact |
| Evidence 被撤销 | 原 Evidence 保留，新增 REVOKED 结果或后续撤销记录由事件模块表达 |

### 12.4 设计目标指标

这些是后续实现和评测目标，不是当前已达成的运行指标：

- Schema 校验结果可确定、可重复；
- 核心实体引用完整性检查不产生跨组织引用；
- 典型实体序列化和校验 p95 小于 20ms（单实体、不含外部存储）；
- 95% 以上的失败样例可以定位到具体实体和字段；
- 通过实体 ID、revision 和 trace 可以构建完整的 Task 执行视图。

---

## 13. 版本和变更规则

### 13.1 当前版本

`REQ-RT-001` 当前版本为 `v0.2-designed`，本需求范围内的详细设计已完成；该版本可以作为后续专项设计的输入，但仍需与状态机、事件、投影、恢复、权限和观测模块完成交叉评审后，才能升级为 `v1.0-frozen`。

### 13.2 升级到 `v1.0-frozen` 的条件

必须完成：

1. Schema 评审；
2. 与 `REQ-RT-002`、`REQ-RT-003`、`REQ-RT-004` 的交叉一致性评审；
3. 与安全、恢复、上下文和评估模块的引用评审；
4. Schema 契约测试和不变量测试设计；
5. 敏感字段和数据分类规则评审；
6. 明确 JSON Schema/Protobuf/ORM 的实现承载方式；
7. 解决所有字段语义冲突后发布 `v1.0-frozen`。

### 13.3 兼容规则

- 新增可选字段：小版本升级；
- 新增枚举值：需要消费者兼容评审；
- 修改字段含义、类型或必填性：主版本升级；
- 拆分实体或改变父子关系：主版本升级；
- 修改 `source_revision`、ID 或 Trace 语义：必须重新评审全部依赖模块。

---

## 14. 设计决策收敛

本轮联网复核后，以下原待决事项已形成设计决策：

1. **逻辑契约格式**：采用 JSON Schema 语义作为跨模块契约；语言侧允许生成 Pydantic/TypeScript 类型，暂不冻结具体代码生成器。
2. **Task 与 Workflow 基数**：底层保留历史 Workflow 的 1:N 能力；MVP 产品接口限制一个 Task 只有一个当前 Workflow。
3. **代码版本表达**：采用 `RevisionRef` 语义，至少包含仓库、commit SHA、分支辅助信息和捕获时间；Git SHA 是 MVP 必填事实字段，分支名不能替代 SHA。
4. **内容存储**：小型结构化内容可内联，大型 Artifact/Evidence 使用 `ContentRef`；具体大小阈值作为部署配置，不进入实体语义。
5. **数据敏感级别**：采用 `PUBLIC | INTERNAL | CONFIDENTIAL | RESTRICTED` 初始枚举，组织扩展必须通过 Schema 兼容机制完成。
6. **外部 ID**：采用 `provider + external_id` 命名空间组合，禁止使用没有 Provider 的裸数字。
7. **运行身份**：采用 `WorkflowStep + WorkerRun + attempt` 细分流程节点、Worker 实例和尝试，不再使用含义不明确的单一 `worker_id` 表达全部语义。
8. **环境与代码分离**：Workspace、环境、网络策略、凭据引用和 `RevisionRef` 独立建模，不把环境状态塞入 Task 或 Action 的自由元数据。

仍需跨模块确认、但不阻塞本需求设计完成的内容：

- 最终数据库/序列化实现选择；
- Artifact/Evidence 的具体对象存储供应商；
- 统一 Trace 与 OpenTelemetry 的字段映射；
- 状态机、事件、恢复、权限和幂等模块的具体协议。

这些事项不再作为本需求的模糊占位字段，而由对应后续需求负责。

---

## 15. 设计完成范围与结论

### 15.1 已完成设计的功能

以下功能已在 `REQ-RT-001 v0.2-designed` 中完成设计：

- [x] Task、Workflow、WorkflowStep、WorkerDefinitionRef、WorkerRun 的职责和边界；
- [x] Action、PolicyDecision、Artifact、Evidence、TraceContext 的职责和引用；
- [x] 组织、项目、仓库和用户的租户范围坐标；
- [x] Task、Workflow、Step、WorkerRun、Action 的父子关系和基数；
- [x] `worker_type`、`worker_id`、`worker_run_id`、`attempt` 的语义分离；
- [x] Workflow 模板、Agent Profile、Toolset、Policy 和 Schema 版本引用；
- [x] `base_revision`、`source_revision`、`working_revision` 的代码版本边界；
- [x] RevisionRef、ContentRef、ResourceRef、Budget、ActorRef 等共享类型；
- [x] Artifact/Evidence 的不可变内容、哈希、来源和验证方式；
- [x] 跨实体租户、链路、版本、Trace 和敏感字段不变量；
- [x] 与后续状态机、事件、恢复、权限、上下文、评估模块的接口约束；
- [x] 公开厂商设计原则的适用范围、证据等级和不复制内部实现的边界；
- [x] 关键待决事项的基线决策和版本收敛规则。

### 15.2 与旗舰 Agent 设计理念的符合性

本方案与公开资料能够确认的厂商共性基本一致：

- 与 Claude Code 的专用子代理、工具限制、权限继承和配置版本方向一致；
- 与 GitHub Copilot Cloud Agent 的自定义 Agent、工具/MCP 声明、临时环境和 PR 交付边界一致；
- 与 OpenAI Codex Cloud 的隔离环境、分支/commit 绑定、环境配置和默认网络收敛原则一致；
- 与 Google Jules 的 Session、SourceContext、Activity、计划审批和异步执行模型一致；
- 与 OpenHands 的 Action/Observation、强类型工具、不可变事件和持久 ConversationState 一致；
- 与 LangGraph 的 State、Context、Store、稳定运行标识和可中断恢复边界一致。

### 15.3 是否为“最优解”

不能在缺少本项目真实任务、Schema 契约测试和跨模块评审的情况下宣称全局最优。

当前可以确认的是：

> `方案 C：分层强类型实体模型` 是在公开证据和本项目安全、可恢复、可审计目标下的推荐基线，已经完成本需求范围内的设计收敛；后续优化应通过评测和版本变更进行，而不是重新各自定义实体。

正式冻结条件由第 13 节规定，后续状态机、事件、恢复、权限和观测设计必须在本基线上扩展，不得替换共享坐标。

原推荐基线如下：

> 采用 `Task -> Workflow -> Worker -> Action` 的执行分层，以 `Artifact` 传递结构化产物，以 `Evidence` 表达可验证结果，以 `TraceContext` 提供跨模块观测关联；所有实体使用稳定 ID、明确的组织/项目/仓库范围、不可变的配置版本和代码 `source_revision`。

该方案吸收了 GitHub Copilot Cloud Agent 的任务—分支—交付边界、OpenHands 的 Action—Tool—Observation 强类型执行边界、LangGraph 的 State—Context—Store 生命周期分离，以及 Claude Code 的专用 Agent 和工具边界原则。

但本项目不直接复制任何厂商内部实现，也不在本需求中提前冻结状态机、事件、检查点、权限算法或重试算法。只有在后续需求完成交叉评审后，`Runtime Contract v1` 才能升级为 `v1.0-frozen`。

---

## 16. 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| `v0.2-designed` | 2026-09-22 | 联网复核 Claude Code、GitHub Copilot、OpenAI Codex Cloud、Google Jules、OpenHands 和 LangGraph；补充 WorkflowStep、WorkerDefinitionRef、WorkerRun、RevisionRef、ContentRef、环境/代码分离、计划活动引用和旗舰 Agent 设计符合性分析；将关键待决事项收敛为基线决策，并标注本需求已完成设计 |
| `v0.1-draft` | 2026-09-22 | 根据统一设计基线和公开官方资料，建立核心运行时实体 Schema 草案 |
