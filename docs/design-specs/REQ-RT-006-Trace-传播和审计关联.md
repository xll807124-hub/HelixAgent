# REQ-RT-006 Trace 传播和审计关联详细设计

> 所属基线：`Runtime Contract v1`（已冻结，2026-10-07）  
> 需求编号：`REQ-RT-006`  
> 优先级：P0  
> 设计版本：`v0.1-frozen`  
> 设计状态：已冻结，可作为实现基线（跨模块评审通过，2026-10-07）  
> 前置依赖：`REQ-RT-001`、`REQ-RT-005`  
> 关键决策：默认追踪采样率 15%；审计日志保留 30 天热存储 + 180 天冷存储；MVP 支持受信任边界内跨服务追踪

---

## 1. 需求定义

### 1.1 目标

为一次研发 Agent 任务建立跨控制平面、Worker、工具、模型网关、沙箱和受信任外部服务的分布式追踪关联，并建立与运行时事实事件分离、可审计且可查询的审计关联规则。系统应支持任务执行诊断、性能分析和操作责任追溯，同时不因追踪采样而丢失必须保留的安全审计事实。

### 1.2 用户价值

- 开发人员可从 Task 追踪到 Workflow、Worker、Action、工具和模型调用，定位失败与延迟来源。
- 安全与合规人员可按主体、资源、任务和授权决定追溯谁在何时执行或尝试了什么操作。
- 平台工程师可分析模型、工具、Worker 和服务边界的延迟与资源消耗。

### 1.3 范围

包含 Trace 身份及传播、Span 父子与 Link 规则、运行时对象关联、审计事件关联键、采样边界、跨服务 MVP 范围、基本故障处理、数据保护原则、留存目标和验收标准。

不包含 OpenTelemetry 每个 Span 的完整属性词典（由 `REQ-OBS-001` 细化）、完整 Trace/Event/Evidence Schema（由 `REQ-OBS-002` 细化）、查询 API 和导出实现（由 `REQ-OBS-006` 细化）、通用遥测脱敏与高基数策略（由 `REQ-OBS-004` 细化）、完整审计防篡改与数据生命周期策略（由 `REQ-OBS-007`、`REQ-SEC-008` 细化），也不定义具体数据库、OTLP Collector 或供应商产品。

---

## 2. 共享契约与术语

本设计复用 `REQ-RT-001` 定义的 `TaskId`、`WorkflowId`、Worker 执行标识、`ActionId`、`TraceId`、`SpanId`、`TraceContext`、`ActorRef`、`ResourceRef`、`RevisionRef` 和租户范围，不另建替代标识。

- **Trace**：同一因果执行链的观测关联集合；不是业务事实流或授权证据。
- **Span**：Trace 内具有开始、结束、父子关系或链接的操作观测单元。
- **审计记录**：对身份、授权、审批、执行结果及重要安全操作的结构化责任记录；不得以采样的 Trace 代替。
- **Correlation**：使用稳定业务 ID、事件 ID、Trace/Span ID 和工具调用关联标识对不同记录进行显式连接。
- **跨服务传播**：通过 W3C Trace Context 兼容的上下文在受信任的内部服务之间传递追踪上下文；传播不等于授权或身份认证。

`TraceId` 与 `SpanId` 遵循 `REQ-RT-001` 已定义的 OpenTelemetry 兼容表示。不得使用 UUIDv7 替代 Trace ID 或 Span ID，也不得根据 ID 推断业务顺序。

---

## 3. 行业调研与可借鉴原则

公开资料说明的是产品公开能力和标准，不证明厂商内部所有实现，也不证明本平台已经实现相同能力。来源访问日期均为 2026-09-23。

### 3.1 OpenTelemetry GenAI 语义约定

OpenTelemetry 的 GenAI 语义约定提供 Agent、Workflow、Model、Tool、Token 用量等可互操作属性及 `invoke_agent`、`invoke_workflow`、`execute_tool` 等操作语义。输入、输出、工具参数和检索文本可能包含敏感信息，标准文档明确提示其敏感性。

**借鉴**：以 OpenTelemetry 与 W3C Trace Context 作为互操作基础；具体属性映射由 `REQ-OBS-001` 冻结；内容型属性默认不采集。

来源：[OpenTelemetry GenAI attributes](https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/)

### 3.2 Claude Code / Agent SDK

Anthropic 公开文档说明其追踪可以关联交互、模型请求、工具、权限等待和子代理 Span，并可向 Bash/PowerShell 子进程、MCP HTTP 请求传播 W3C Trace Context；追踪默认关闭，内容字段默认受控。

**借鉴**：把审批等待与工具执行耗时分开；为模型重试和子 Agent 保留可解释层级；使用显式信任边界控制传播；默认不记录提示词、工具输入和输出正文。

来源：[Claude Code monitoring](https://code.claude.com/docs/en/monitoring-usage)、[Agent SDK observability](https://code.claude.com/docs/en/agent-sdk/observability)

### 3.3 Microsoft Azure SRE Agent

Microsoft 文档公开描述 Azure SRE Agent 将工具执行、审批和其他 Agent 活动写入 Application Insights，并以 TraceId、SpanId、ParentSpanId、ThreadId 等字段进行关联；动作流程包含权限检查、执行或审批、执行后验证和审计。

**借鉴**：审计记录必须有主体、目标资源、授权决策、动作结果和验证结果的关联；查询应能沿 Trace 和业务身份双向定位；Agent 自述不能作为审计事实。

来源：[Audit agent actions](https://learn.microsoft.com/en-us/azure/sre-agent/audit-agent-actions)、[Execute mitigations](https://learn.microsoft.com/en-us/azure/sre-agent/execute-mitigations)

### 3.4 Cursor Enterprise

Cursor 官方文档公开了通过 OpenTelemetry 导出用量指标和结构化事件的能力，并区分管理审计、使用遥测和开发活动记录；其事件使用会话关联标识和去重标识。文档也提示开发活动日志可能包含敏感内容，应优先记录元数据。

**借鉴**：区分可采样的诊断遥测与不可随采样丢失的安全审计；提供稳定事件去重和会话/任务关联键；对内容采集设置显式门控。

来源：[OpenTelemetry Export](https://cursor.com/docs/enterprise/opentelemetry-export)、[Compliance and Monitoring](https://cursor.com/docs/enterprise/compliance-and-monitoring)

### 3.5 OpenTelemetry Agent Demo 与 LangSmith

OpenTelemetry 官方 Agent Demo 展示了工作流根 Span、框架步骤、模型调用和 MCP 工具调用共享导出管道的结构。LangSmith 文档描述 OTLP Collector 的批处理和多目的地扇出，以及父 Span 晚于子 Span 到达时的关联处理。

**借鉴**：应用侧使用一致的 Span 上下文，Collector 负责批处理与路由；存储和接收端不能假设父 Span 必定先到；追踪后端与审计事实存储职责分离。

来源：[OpenTelemetry Agent Service](https://opentelemetry.io/docs/demo/services/agent/)、[LangSmith OpenTelemetry tracing](https://docs.langchain.com/langsmith/trace-with-opentelemetry)

### 3.6 设计结论

采用标准化 Trace Context 和 OpenTelemetry 导出边界，业务 ID 与 Trace ID 分离；对模型、工具、审批和服务操作建立父子追踪；审计采用独立的可靠记录链路；追踪内容默认最小化；跨服务传播只在经过登记和信任评估的边界允许。以上是基于公开材料的设计推断，不是对任何产品私有实现的断言。

---

## 4. 追踪与审计架构

### 4.1 Span 层级

一次用户提交的任务由平台创建根 Trace。建议的逻辑层级如下，具体 Span 名称及语义属性由 `REQ-OBS-001` 定义：

```text
Task / agent invocation
└── Workflow execution
    ├── Worker execution
    │   ├── Planning / reasoning operation（只记录操作元数据，不记录隐藏思维链）
    │   ├── Policy decision / human approval wait
    │   ├── Action
    │   │   ├── Tool execution
    │   │   ├── Model request（可含多次 attempt 子事件或子 Span）
    │   │   └── Sandbox operation
    │   └── Artifact / Evidence production
    └── Cross-service client operation
```

Span 父子关系表达执行包含关系和因果关系，不表达授权结论。并行 Worker 作为同一 Workflow Span 下的并行子树；无法形成严格父子包含但存在因果关联的工作使用 Span Link，不伪造父子关系。工具执行中的策略等待与实际执行时长应可分别分析。

### 4.2 业务关联字段

Trace/Span 必须在适用时关联稳定业务坐标：`organization_id`、`project_id`、`repository_id`、`task_id`、`workflow_id`、Worker 执行标识、`action_id`、事件标识及工具调用关联 ID。调用链上的身份和资源字段应通过受控、低基数的引用表达；不得将自由文本、完整路径或用户输入直接作为高基数属性。

审计记录至少能关联：发生时间、组织/项目/仓库范围、操作者或服务身份、Task/Workflow/Action、目标资源引用、策略版本及决策引用、审批主体与决定（如适用）、执行结果、验证证据引用、Trace/Span 和事件因果引用。字段级最终契约由 `REQ-OBS-002` 定义。

### 4.3 事件、追踪与审计关系

- `REQ-RT-003` 的不可变运行时事件继续作为业务事实来源；事件引用 Trace 上下文，但 Trace 不替代事件。
- Trace 是可采样、可异步导出、可按诊断需要保留的运行观测视图，不作为授权或副作用完成的唯一证据。
- 安全审计记录与 Trace 遥测逻辑分离，并使用相同业务关联坐标实现关联。Trace 被采样、导出失败或过期，不得删除/跳过必须保留的审计记录。
- 决策和执行结果需要可验证时，引用 `PolicyDecision`、`Evidence` 和事件，而不只依赖 Span 属性。

---

## 5. Trace Context 生命周期与传播流程

### 5.1 根上下文创建

1. Task 被平台接受并完成基础身份/范围校验后，若入口没有可信的上游上下文，则生成新的 Trace ID 和根 Span ID。
2. 若入口携带外部 Trace Context，只有来自已登记的可信接入边界且通过格式、大小和策略校验时才允许继续关联；否则创建新 Trace，并可通过受控 Span Link 保留因果关系。
3. 将 Trace 关联写入 Task/Workflow 运行上下文和相应事实事件；业务 Task ID 保持独立。

### 5.2 内部传播

1. 控制平面调度 Worker 时注入当前上下文；Worker 为自身执行创建 Span。
2. Action、策略评估、审批等待、工具、模型网关、沙箱和 Artifact/Evidence 生成均在对应操作上下文下创建 Span 或关联事件。
3. 队列、进程、容器和异步任务边界使用显式上下文注入/提取；不得依赖线程局部或进程环境中的偶然状态。
4. 并行分支继承同一 Trace ID，但各自生成独立 Span ID；重试 attempt 应可区分且关联原始操作。
5. Checkpoint 保存必要 Trace 关联和事件坐标；恢复后延续同一业务 Workflow 的可追溯关系。若实际运行跨越独立 Trace 生命周期或 Trace 后端限制，则使用明确 Link 和稳定业务 ID 保持关联，不伪造连续 Span 时长。

### 5.3 跨服务传播范围

MVP 支持控制平面、Worker Runtime、工具/模型网关、沙箱管理组件及已登记的内部遥测/审计服务之间的跨服务追踪。对 GitHub 等第三方、MCP 服务及模型供应商，仅在集成被明确登记、协议支持、策略批准且不会向不可信方暴露内部敏感上下文时，才传播允许的 W3C Trace Context。第三方不支持或拒绝传播时，使用客户端 Span、请求关联 ID 和业务引用，不影响操作审计。

Trace Context 不是凭据，不具有授权能力；接收 Trace Context 不得据此授予访问权限。不得默认向任意域名、任意 MCP 服务器或模型供应商透传内部 Trace/Baggage。Baggage 默认关闭，仅允许经白名单批准的低敏、低基数字段。

### 5.4 采样决策

- 默认追踪采样率为 **15%**，用于常规诊断遥测；抽样单位是完整 Trace，而非单个 Span，避免产生无法解释的碎片链路。
- 高风险任务、安全策略拒绝、审批、任务失败、恢复、Kill Switch、异常副作用状态及明确诊断请求可按规则提高追踪保留优先级。采样优先级不改变权限决策。
- 追踪采样不适用于必需审计记录、状态事件、审批结果或安全证据；这些按其自身持久性与留存契约记录。
- 采用头部采样作为 MVP 的可预测基础。尾部采样仅可作为 Collector/后端的后续优化，不作为正确性、安全审计或本需求验收的前置条件。
- 采样配置按组织/环境治理并版本化；任务运行期间策略变更不得静默改写既有 Trace 的采样决定。

15% 是经用户确认的产品默认值，不是行业测得的最优比例。上线后应依据 Trace 价值、采集成本、流量和数据策略评估。

---

## 6. 审计关联与查询需求

### 6.1 必须审计的操作类别

至少覆盖 Task 创建/取消、权限与策略决定、审批请求与结果、Action 授权/拒绝、工具开始/结束/失败、凭据签发/撤销引用、沙箱创建/销毁及策略变更、外部副作用、Checkpoint 恢复决定、Kill Switch 操作和最终交付状态。审计目录及字段由后续 `REQ-OBS-002`、`REQ-OBS-007` 和安全需求完成。

每个存在副作用或权限影响的操作应记录开始/结果或明确记录结果未知；不可仅记录成功操作。审计事实应来自平台控制点和工具执行器，而非模型生成的叙述。

### 6.2 关联查询能力

系统设计应允许授权用户按 Task、Trace、Actor、Action、目标资源引用、事件/策略决定引用和时间范围定位相关审计记录，并从审计记录跳转到关联 Trace，从 Trace 反查业务实体和审计引用。查询 API、分页、过滤、导出、权限校验和防篡改规则分别由相关 OBS/SEC 需求定义。

### 6.3 留存目标

审计日志默认保留 **30 天热存储 + 180 天冷存储**。热存储用于常规查询和事故响应；冷存储用于保留期内的合规/调查访问，访问延迟目标由部署方案确定。期限从审计记录生成时间起计算，迁移热/冷层不得改变记录内容或关联标识。

这是当前产品默认策略，不代表所有司法辖区或客户的合规充分性。组织级法规、数据驻留、法律保全和删除义务优先于默认值，需由 `REQ-SEC-008` 与 `REQ-OBS-007` 定义覆盖、例外审批和审计要求。Trace 遥测留存不在本需求中被设为与审计相同期限。

---

## 7. 数据保护、权限与隔离

1. Trace、审计查询均执行组织、项目、仓库、Task 和敏感级别权限校验；Trace ID 不构成访问令牌。
2. 默认只记录模型标识、耗时、Token 用量、操作类型、工具名、结果类别、稳定业务引用等诊断元数据；不记录隐藏思维链、完整 Prompt、模型原始请求/响应、完整代码、凭据值或环境变量。
3. 工具参数、工具结果、检索内容、文件内容和外部服务响应默认不进入 Span 或审计正文。确需采集的诊断内容必须由独立策略显式启用、限定范围和期限、脱敏并记录其访问审计；具体机制由 `REQ-OBS-004`、`REQ-SEC-008` 定义。
4. Trace Baggage 采用白名单，禁止凭据、个人敏感信息、任意用户文本和高基数资源明细。
5. 导出接收方须登记并校验传输安全、身份认证、租户范围及数据处理责任。导出失败不得阻塞 Agent 执行，也不得使必需审计事实静默丢失。
6. 删除、归档、法律保全和数据驻留遵循安全与治理基线，审计查询权限和操作本身也必须留下审计记录。

---

## 8. 失败处理与性能成本

### 8.1 故障行为

- Trace 导出端不可用：异步队列/缓冲按有界策略重试；耗尽时计数并告警，Agent 主执行路径不得等待远端观测后端。
- 审计持久化失败：对要求审计的安全敏感或副作用操作采用 fail-closed，阻止操作继续或进入明确的安全暂停状态；对不影响授权/副作用的非关键诊断遥测可以降级。不得把审计失败等同于 Trace 导出失败。
- 缺少父 Span 或父 Span 晚到：保留 Span Context 和业务关联，允许接收端延迟关联；记录孤儿/未关联计数，不按时间启发式伪造因果父级。
- 上下文格式无效、超限或来自不可信入口：拒绝提取并创建新的根 Trace；保留受控的入口关联证据。
- Span 导出部分失败或重复：使用追踪 SDK/Collector 的重试和接收端去重能力；审计记录拥有独立事件 ID/去重语义，按 `REQ-RT-003` 与 `REQ-OBS-002` 定义。
- 恢复或重试：延续业务关联并区分 attempt；不得因追踪重放而重新执行工具或外部副作用。

### 8.2 成本与延迟

- 采集和导出异步批处理，不能将远程 OTLP 可用性置于任务完成路径。
- 通过 15% 全 Trace 默认采样、低基数属性、Span 数量/大小上限和默认内容关闭控制成本。
- 必需审计记录采用独立可靠路径，不能受追踪采样率限制。
- 目标值作为待基准验证的设计验收目标：正常 Agent 执行的追踪 SDK CPU 开销 p95 不超过 5%；追踪记录生成对动作调度路径增加的本地延迟 p95 不超过 10 ms；审计写入延迟目标由事件/审计存储实现共同验证。以上是本项目目标，不是当前测量结果。

---

## 9. 版本化、可观测性与评估指标

采样策略、传播策略、信任边界和审计分类均须具备可追踪版本或等效配置修订引用，并关联受影响运行。新增/变更 OpenTelemetry 语义属性由 `REQ-OBS-001` 处理；任何运行时实体、事件 Schema 或审计契约的不兼容修改均按对应版本策略升级。

至少监控：

- Trace 根 Span 创建率、完整 Trace 比例、父 Span 关联率和孤儿 Span 比例；
- 业务实体关联成功率（Task/Workflow/Worker/Action）；
- 跨服务 Context 提取/注入成功率及被拒绝传播次数；
- OTLP 导出成功率、积压量、丢弃量和导出延迟；
- 必需审计覆盖率、审计持久化失败数、按业务 ID 查询到审计链路的成功率；
- 采样后 Trace 数、平均 Span 数/大小、存储量及单位任务成本；
- 敏感内容拦截/脱敏事件数及其误报复核结果。

目标：关键权限/审批/副作用事件审计覆盖率 100%；可追踪运行实体关联到有效 Trace 或显式记录传播例外的比例至少 99%；在采样和异步导出下，审计记录完整性不低于 100%（相对于审计事件源和成功持久化定义），不得以 Trace 导出成功率代替审计覆盖率。具体统计口径由 `REQ-OBS-003`、`REQ-OBS-007` 冻结。

---

## 10. MVP 范围与验收标准

### 10.1 MVP 必须支持

- Task 到 Workflow、Worker、Action、Model、Tool、Sandbox 的 Trace 关联；
- W3C Trace Context 在本平台受信任内部服务间传播；
- 对登记且获准的外部边界执行受控跨服务传播；不支持时保留客户端追踪及业务关联；
- 并行 Worker、重试 attempt、审批等待和 Checkpoint 恢复的关联语义；
- 15% 默认 Trace 采样，并提供高风险/失败等规则提高追踪优先级；
- Trace 遥测与不可采样丢失的审计记录分离；审计默认 30 天热存储 + 180 天冷存储；
- 默认不记录思维链、Prompt 正文、完整工具输入/输出、代码和凭据；
- 授权用户能够由 Task/Trace/Actor/Action 关联定位审计和追踪记录；具体 API 由后续需求定义。

### 10.2 验收标准

1. 新 Task 可获得合法 Trace 上下文，业务 Task ID 与 Trace ID 不混用。
2. 内部同步、队列和子进程边界可验证 Trace Context 注入、提取和父子关系。
3. 并行 Worker 使用独立 Span；重试 attempt 可区分；无因果关系的分支不被伪装为父子关系。
4. 对外部上下文格式无效、未登记或不可信的传播请求会被拒绝或建立新根 Trace，不导致越权。
5. 受信任外部服务的传播只在登记、策略许可及协议支持时发生；第三方追踪不可用不影响动作审计。
6. 将默认采样配置设为 15% 时，常规 Trace 按完整 Trace 采样；高优先级规则可覆盖采样但不会改变授权。
7. 将 Trace 采样率设为 0 或模拟 OTLP 故障时，必需审计记录仍完整写入独立审计路径。
8. 对授权决策、审批、工具/副作用操作和恢复决策可通过关联键追溯到 Actor、资源、运行时事件及相关 Evidence。
9. 默认采集配置下，测试用 Prompt、工具正文、代码片段和凭据不会出现在 Trace/审计内容字段；敏感字段策略拒绝不安全的显式采集。
10. 未授权主体不能通过 Trace ID 或业务关联字段读取跨租户 Trace/审计数据。
11. 审计记录按默认热/冷层级策略迁移时保持内容及关联标识；默认保留目标为 30 天热存储 + 180 天冷存储。
12. Trace 后端不可达不阻塞任务；必需审计写入失败时，受保护副作用不会在无审计状态下继续。
13. 对缺失/晚到父 Span，系统保留关联信息并计量孤儿 Span，不以时间窗口猜测父级。
14. 恢复回放不重复执行工具或外部副作用。

---

## 11. 依赖与跨模块边界

| 需求 | 本设计提供/依赖的内容 | 边界 |
|---|---|---|
| `REQ-RT-001` | 复用 Trace、Span、Actor、Task、Workflow、Worker、Action、资源和租户坐标 | 不重新定义核心实体 |
| `REQ-RT-003` | 事件关联 Trace、父子因果及事件引用 | 事件仍是业务事实来源 |
| `REQ-RT-005` | 检查点恢复时的 Trace 关联和恢复上下文 | 不定义检查点 Schema 或恢复算法 |
| `REQ-RT-007` | 可将动作重试和副作用检查关联至同一任务诊断视图 | 不定义幂等算法 |
| `REQ-RT-008` | 为事件查询、权限与留存提供追踪关联坐标 | 不定义事件查询 API |
| `REQ-OBS-001` | 提供生命周期、传播和 Span 层级边界 | 由其冻结具体 OTel Span 名称和 GenAI 属性映射 |
| `REQ-OBS-002` | 提供 Trace、Event、Evidence、Audit 的关联需求 | 由其冻结字段 Schema |
| `REQ-OBS-004` | 提供默认最小采集和敏感内容关闭原则 | 由其设计完整脱敏、高基数和采样治理 |
| `REQ-OBS-006` | 提供按 Task/Trace/Actor/Action 关联查询需求 | 由其定义查询 API、过滤和导出 |
| `REQ-OBS-007` | 提供热/冷审计留存默认目标 | 由其定义完整性、归档和保留实现 |
| `REQ-SEC-002/003/008` | 提供授权边界、传播信任边界和法规覆盖要求 | 授权、策略、驻留及删除规则由安全需求冻结 |

---

## 12. 方案比较与决策

### 方案 A：只用业务事件串联

优点是依赖少；缺点是难以表达跨服务耗时、并行调用、模型请求和工具内部阶段，不适合作为性能诊断视图。

### 方案 B：Trace 同时充当审计事实

优点是数据表面上统一；缺点是追踪采样、异步导出、后端保留策略和遥测内容治理会导致审计事实可能缺失或被不当删除，且 Span 不能证明授权或副作用结果。

### 方案 C：标准化 Trace + 独立审计事实 + 共享关联坐标（推荐）

以 OpenTelemetry/W3C Trace Context 表达运行因果和性能，以事件/审计记录表达业务事实与责任，以稳定业务 ID、事件 ID、Trace/Span ID 相互关联。该方案符合项目事件事实源、零信任、证据化交付和审计要求，并允许 Trace 按 15% 默认采样而不牺牲审计完整性。

---

## 13. 设计限制与待跨模块确认项

以下内容留给相关专项，不阻塞本需求完成详细设计：

- OTel GenAI 语义约定当前属性的具体版本和稳定性选择，由 `REQ-OBS-001` 确认；
- 审计记录完整字段、不可变/防篡改机制和完整性校验，由 `REQ-OBS-002`、`REQ-OBS-007` 确认；
- 审计查询的端点、权限矩阵、分页及冷存储查询体验，由 `REQ-OBS-006` 与安全需求确认；
- 适用法规、区域驻留、法律保全与例外保留，由 `REQ-SEC-008` 确认；
- 具体 Collector、后端、供应商、导出协议和成本基准由实现/部署设计及评测确认。

---

## 14. 版本与变更记录

### 14.1 当前状态

`REQ-RT-006` 当前版本为 `v0.1-designed`：本专项详细设计已完成，待与 Runtime Contract、事件、审计查询、安全和 OpenTelemetry 语义专项交叉评审后冻结。设计完成不代表已实现或运行指标已经验证。

### 14.2 冻结条件

1. 与 `REQ-RT-001/003/005` 完成实体、事件、恢复和 Trace 上下文交叉评审；
2. 与 `REQ-OBS-001/002/004/006/007` 对齐属性、Schema、脱敏、查询、留存与完整性边界；
3. 与 `REQ-SEC-002/003/008` 完成授权、可信传播、数据驻留和保留例外评审；
4. 完成内部服务传播、外部边界拒绝/许可、采样与审计解耦、父 Span 晚到和导出故障契约测试设计；
5. 用代表性 Agent 运行验证追踪开销、审计覆盖率和默认采样/留存策略。

### 14.3 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| `v0.1-designed` | 2026-09-23 | 基于 OpenTelemetry、Claude Code、Azure SRE Agent、Cursor、OpenTelemetry Agent Demo 和 LangSmith 公开资料，完成 Trace 传播、审计关联、采样、受信任跨服务边界、数据保护、默认留存与验收设计；采样率、留存和 MVP 跨服务追踪范围按用户确认收敛 |
