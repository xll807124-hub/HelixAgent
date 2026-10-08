# AI Agent 平台统一设计基线与未完成需求清单

> 文档版本：v1.7  
> 基线日期：2026-10-05  
> 文档状态：方案整合基线，未进入代码实现  
> 适用范围：`AI_AGENT项目方案.md`、`优化设计思路.md`、`docs/design-specs/README.md`、`INDEX.md` 及 `01-05` 设计规范

---

## 1. 文档目的与权威性

本文档是当前项目设计状态的统一入口，用于解决以下问题：

1. 汇总现有总体方案、优化设计和专项设计文档。
2. 区分“高层设计已形成”“推荐基线已提出”“详细设计未完成”。
3. 明确后续设计工作的版本基线，避免多个文档各自演进。
4. 列出尚未完成的独立功能需求，后续逐项设计和评审。

### 1.1 文档权威级别

从高到低采用以下优先级：

1. 本文档中的“统一设计决策”和“版本基线”。
2. 已单独冻结并经评审的专项设计文档。
3. `AI_AGENT项目方案.md` 中的总体架构和 MVP 边界。
4. `优化设计思路.md` 中的候选方案、行业调研和待验证假设。
5. 其他草稿、示例、候选算法和未验证指标。

当前没有任何专项模块达到“实现已完成”状态。本文档中的“已设计”仅表示形成了可继续细化的高层方案，不表示已经编码、部署或验证。

### 1.2 统一状态定义

| 状态 | 含义 |
|---|---|
| 高层设计已形成 | 目标、边界、主要组件和核心原则已经明确，但接口、数据模型、异常处理或验证方案仍可能缺失 |
| 推荐基线已提出 | 已有候选方案和初步选型，但尚未通过统一评测、架构评审或安全评审冻结 |
| 详细设计进行中 | 正在补齐 Schema、状态流、权限边界、失败处理、验收指标和评测方案 |
| 详细设计已冻结 | 设计评审通过，版本、接口、验收标准和变更流程已固定 |
| 已实现并验证 | 已有代码、测试、环境验证和可追溯证据 |

当前所有模块最高只能标记为“详细设计进行中”或“详细设计已完成、待跨模块冻结”，没有模块可标记为“已实现并验证”。

---

## 2. 项目总体目标与产品边界

### 2.1 产品定位

建设面向软件研发团队的 AI Agent 平台，覆盖：

```text
Issue / 自然语言需求
  -> 代码库理解
  -> 实施计划
  -> 人工确认
  -> 隔离工作区
  -> Agent 执行
  -> 测试与质量检查
  -> Diff 与证据汇总
  -> Pull Request
  -> 人工评审与合并
```

第一阶段的核心承诺是：

> Agent 可以在可控、可审查、可恢复、可审计的边界内完成研发任务，并产出供人工审查的 Pull Request。

### 2.2 MVP 边界

MVP 包含：

- 单组织、单仓库、首个代码托管平台优先 GitHub；
- Bug 修复和小型功能开发；
- 一个主流模型，通过统一 Model Gateway 接入；
- Web 任务控制台；
- 任务创建、规划、审批、执行、暂停、恢复和取消；
- 代码读取、搜索、编辑、Git、测试和有限 Shell 工具；
- Linux 云端生产沙箱执行；后端能力抽象与多维风险路由；网络按已批准连接器声明开放；
- 基础 RBAC、Policy Gateway 和审计；
- Diff、测试证据和 Pull Request 创建。

MVP 不包含：

- 自动合并生产代码；
- 生产数据库或生产环境直接访问；
- 完全无人审批的高风险操作；
- 无边界浏览器自动化；
- 复杂多 Agent 自由协作；
- 多仓库、复杂 Monorepo 和长期组织记忆；
- 自研基础模型；
- 复杂计费系统。

---

## 3. 统一总体架构

项目采用控制平面、执行平面和证据平面分离的架构，并补充资产治理和策略控制：

```text
┌──────────────────────────────────────────────┐
│ 用户体验层                                    │
│ Web 控制台 / 任务 / 对话 / Diff / PR          │
└──────────────────────────────────────────────┘
                      │
┌──────────────────────────────────────────────┐
│ 接入与集成层                                  │
│ GitHub / Issue / Webhook / Model / MCP        │
└──────────────────────────────────────────────┘
                      │
┌──────────────────────────────────────────────┐
│ 控制平面                                      │
│ Identity / Workflow / Coordinator / Policy    │
│ Context / Model Gateway / Approval / Budget   │
└──────────────────────────────────────────────┘
                      │
┌──────────────────────────────────────────────┐
│ 执行平面                                      │
│ Worker / Workspace / Docker / Tools / Git     │
│ Test / Build / Network / Credential Proxy     │
└──────────────────────────────────────────────┘
                      │
┌──────────────────────────────────────────────┐
│ 证据与治理平面                                │
│ Event / Trace / Audit / Artifact / Evidence   │
│ Evaluation / Metrics / Asset Registry         │
└──────────────────────────────────────────────┘
```

### 3.1 六层 Harness 基线

每个 Worker 采用以下职责边界：

1. `Identity Harness`：用户、组织、项目、仓库和任务身份。
2. `Context Harness`：按权限和预算加载上下文。
3. `Tool Harness`：按 Worker 能力暴露工具。
4. `Execution Harness`：工作区、沙箱、网络和资源限制。
5. `Policy Harness`：风险、审批、预算和输出校验。
6. `Evidence Harness`：事件、Trace、Artifact、Evidence 和指标记录。

### 3.2 Agent 执行分层基线

```text
Durable State Machine
  -> Workflow DAG / Coordinator
    -> Worker ReAct Loop
      -> Action
        -> Policy Gateway
          -> Tool / Sandbox
            -> Observation / Evidence
```

边界规则：

- ReAct 只负责单个 Worker 的局部推理和工具选择。
- Workflow DAG 负责 Worker 依赖、并行、汇聚和有限重规划。
- Durable State Machine 负责持久化、暂停、恢复、重试、超时和审批等待。
- 模型不能直接执行 Action。
- Worker 不能绕过 Policy Gateway。
- Worker 之间通过结构化 Artifact 和 Evidence 协作，不共享完整对话历史。

---

## 4. 已形成设计的方向与采用版本

### 4.1 方向一：零信任架构与渐进披露

**状态：高层设计已形成，详细设计未冻结**  
**采用基线：`Context Governance Baseline v0.1`**

已形成的设计：

- 权限判断先于上下文加载；
- 组织、项目、仓库、路径和用户多层作用域；
- 技能目录层、说明层、执行层渐进披露；
- `Context Policy Engine`、`Skill Registry`、`Skill Resolver`、`Context Builder`、`Capability Gateway`、`Context Audit Service`；
- `ContextManifest` 记录加载内容、拒绝原因、版本和 Token 预算；
- 技能不能授予工具之外的权限；
- 外部内容不能覆盖系统和组织安全策略。

当前采用的基线决策：

- 技能选择采用“规则硬过滤 + 语义排序 + 权限裁剪 + 预算选择”；
- 未授权技能直接淘汰，不允许通过语义分数重新进入候选集；
- 组织策略高于项目策略，项目策略高于仓库策略，仓库策略高于路径级普通指令；
- 技能、规则、索引、Prompt 和 ContextManifest 均必须版本化；
- 高风险技能未签名或未审核时不得进入生产运行环境。

尚未冻结：

- 权限策略语言；
- Skill Registry Schema；
- 技能冲突解决的完整规则；
- 上下文预算公式和裁剪算法；
- 权限过滤集成测试；
- 外部内容的敏感信息和提示注入检测协议。

### 4.2 方向二：Coordinator + 专家 Worker

**状态：高层设计已形成，详细设计未冻结**  
**采用基线：`Worker Orchestration Baseline v0.1`**

已形成的设计：

- Coordinator 负责意图分类、任务图编译、预算分配、全局状态和有限重规划；
- Worker 负责单一职责和受限工具执行；
- 首批 Worker：Explorer、Planner、Coder、Tester、Reviewer、Resolver、Release；
- Worker 之间通过结构化 Artifact、Evidence 和版本引用通信；
- Planner 完成并审批后，Coder 才允许写入；
- Release 只能生成 PR，不能直接合并；
- 支持顺序委派、受控并行和有限反馈回路。

当前采用的任务图基线：

```text
Explorer
   |
Planner -- approval --> Coder ----+
   |                                |
   +----------> Tester -------------+--> Reviewer --> Release
```

尚未冻结：

- Workflow Template Schema；
- Worker 输入、输出和预算契约；
- DAG 节点状态和并行调度规则；
- Artifact 存储、版本和冲突处理；
- 分支隔离与 Worker 工作区策略；
- 重规划的最大次数和触发条件。

### 4.3 方向三：ReAct + Workflow DAG + Durable Runtime

**状态：高层设计已形成，详细设计未冻结**  
**采用基线：`Agent Runtime Baseline v0.1`**

已形成的设计：

- Worker 内部采用事件驱动 ReAct；
- 平台采用持久化 Workflow/DAG；
- 任务状态以事件和检查点恢复；
- Action 必须经过授权、执行和 Observation 生命周期；
- 有最大迭代次数、预算、时间、工具调用和重复 Action 终止条件；
- 测试失败进入诊断或 Resolver 流程，不按普通工具异常盲目重试；
- 权限拒绝和审批等待不得自动重试。

当前采用的实现方向：

- MVP 使用 PostgreSQL + 队列实现持久化接口；
- 接口预留迁移到 Temporal 或 LangGraph 等持久运行时的空间；
- 事件事实源、状态投影和检查点恢复作为共同运行时坐标系。

尚未冻结：

- WorkerRuntime 接口；
- WorkflowCompiler 接口；
- Action Executor 接口；
- Event Store 和 Projection API；
- Checkpoint Protocol；
- 事件重放和回放工具；
- 与外部副作用系统的幂等及补偿边界。

### 4.4 方向四：Agent Infra 与四道零信任防线

**状态：高层设计已形成，详细设计未冻结**  
**采用基线：`Agent Infra Governance Baseline v0.1`**

四道防线：

1. `AI Gateway`：模型路由、预算、数据策略、短期凭据和模型调用审计。
2. `Sandbox Execution`：工作区、文件系统、网络、进程和资源隔离。
3. `Communication Control`：Worker、工具、MCP 和外部系统之间的结构化数据流控制。
4. `AI Asset Governance`：模型、Prompt、Skill、Tool、Worker、Workflow、策略、索引和沙箱镜像的版本、签名、审批和撤销。

已形成的设计：

- Agent 不持有长期凭据；
- 默认拒绝网络和未授权文件访问；
- Action 前后执行策略校验；
- 支持从单个 Action 到全局的 Kill Switch；
- 凭据必须短期、范围受限、任务绑定并可审计；
- 外部检索内容进入不可信数据区，不能覆盖安全策略；
- 预热沙箱只优化冷启动，不构成安全边界。

当前 MVP 基线：

- 生产执行路径统一为 Linux，沙箱后端通过能力抽象接入并由风险路由选择；首个具体生产后端由部署评审和基准测试决定；
- 文件系统、网络、进程/系统调用和资源执行最小权限，网络目的地必须经过连接器声明、审批固化和运行时下发；
- 通过 AI Gateway 或 Capability Gateway 代理 GitHub、模型和对象存储访问；
- 资产注册表先覆盖 Model、Prompt、Skill、Tool、Worker 和 Workflow；
- 通过任务级审计和 Kill Switch 形成最小治理闭环。

尚未冻结：

- 凭据代理协议；
- Sandbox 配置标准和逃逸测试基线；
- 多租户隔离方案；
- MCP 连接器信任和权限模型；
- 数据驻留、留存和删除策略；
- 资产签名、发布、撤销和回滚协议；
- 事故响应和安全控制矩阵。

---

## 5. 部分形成推荐基线但未完成 Runtime Contract 冻结的方向

### 5.1 运行时基础契约

**状态：P0，REQ-RT-001 至 REQ-RT-008 已完成详细设计，待跨模块评审与冻结；尚未满足 Runtime Contract v1 冻结条件**  
**采用版本：`Runtime Contract v1-draft`；REQ-RT-001：`v0.2-designed`；REQ-RT-002/003/004/005/006/007/008：`v0.1-designed`**

推荐基线：

- `Task -> Workflow -> Worker -> Action` 分层；
- `Artifact` 作为 Worker 之间的结构化产物；
- `Evidence` 作为可验证交付证据；
- `Trace` 贯穿任务、Worker、Action、Tool、Model、Sandbox 和 Approval；
- 事件追加式存储；
- 状态由事件投影生成；
- 检查点用于恢复优化，不取代事件事实源；
- 每个 Action 具备幂等键；
- 所有版本和来源可追溯；
- 事件查询支持多维过滤、分页、时间范围；
- 分层留存（30 天热 + 180 天冷 + 合规保留）；
- 敏感字段读取时脱敏，支持组织级配置；
- 强制租户隔离的查询权限控制；
- 分级审批 + HITL 合规删除流程。

已完成设计的独立需求：

- `REQ-SEC-001` 威胁模型和风险评分，版本：`v0.1-designed`；
- `REQ-SEC-002` RBAC 与资源授权，版本：`v0.1-designed`，详见 [专项设计](./REQ-SEC-002-rbac-resource-authorization.md)；待跨模块评审与冻结。
- `REQ-SEC-003` Policy Gateway，版本：`v0.1-designed`，详见 [专项设计](./REQ-SEC-003-policy-gateway.md)；待跨模块评审与冻结。MVP 采用 OPA/Cedar 之一、独立 Auto-review、粗粒度审批矩阵、审批超时升级、多 Agent 单跳 OBO、差异化决策缓存及三级审计脱敏。
- `REQ-SEC-005` 凭据代理，版本：`v0.1-designed`，详见 [专项设计](./REQ-SEC-005-credential-proxy.md)；待跨模块评审与冻结。MVP 支持 GitHub App + AWS STS（OIDC 联合）+ 通用 OAuth 2.0；PDP/CDP 分离架构；三代理模型（Model B 为主、Model A 用于 OIDC 联合）；Vault 集成（单云云厂商托管）；CDP 多实例 active-active；撤销传播 < 5s；OIDC 联合 MVP 必选；DPoP 接口预留渐进路线。
- `REQ-RT-001` 核心实体 Schema，版本：`v0.2-designed`；
- `REQ-RT-002` Task、Workflow、Worker、Action 状态机与迁移约束，版本：`v0.1-designed`；
- `REQ-RT-003` Event Schema v1 和事件版本策略，版本：`v0.1-designed`；
- `REQ-RT-004` 状态投影与一致性规则，版本：`v0.1-designed`；
- `REQ-RT-005` Checkpoint Protocol，版本：`v0.1-designed`；
- `REQ-RT-006` Trace 传播和审计关联，版本：`v0.1-designed`；（[详细设计](./REQ-RT-006-Trace-传播和审计关联.md)，默认采样率 15%，审计保留 30 天热存储 + 180 天冷存储，MVP 支持跨服务追踪）
- `REQ-RT-007` Idempotency Key 与副作用边界，版本：`v0.1-designed`；（[详细设计](./REQ-RT-007-idempotency-key.md)，作为运行时共享锚点；具体写操作包装器由 `REQ-REL-006` 细化。Redis 仅为 24 小时热层，PostgreSQL 为权威账本；结果未知时不得盲目重放）
- `REQ-RT-008` 事件查询、留存、脱敏和权限边界，版本：`v0.1-designed`；（[详细设计](./REQ-RT-008-event-query-retention-redaction-permission.md)，30 天热存储 + 180 天冷存储；平台默认值 + 组织覆盖配置；混合 Payload 归档；分级审批 + HITL 合规删除；全协议流式传输；多云归档存储；事件层 trace_id 关联）
- `REQ-REL-006` 写操作幂等封装，版本：`v0.1-designed`；（[详细设计](./REQ-REL-006-write-operation-idempotency.md)，稳定逻辑意图键、JCS/类型化规范化、六态账本、fencing lease、Effect Log/Outbox 原子边界、A-D 连接器能力分级和 SLA 驱动对账）
- `REQ-REL-009` 故障注入和恢复验证场景，版本：`v0.1-designed`；（[详细设计](./REQ-REL-009-fault-injection-recovery-verification.md)，HTTP/SDK/系统调用三层故障注入、系统化故障分类法映射 REL-001 症状、行为契约验证、完整恢复路径验证、自动化验证流水线、爆炸半径限制和审计跟踪）

**里程碑**：运行时基础契约（REQ-RT-001 至 REQ-RT-008）全部完成详细设计；可靠性（REL）模块全部 9 项完成详细设计；仍需完成跨模块交叉评审并冻结后，Runtime Contract v1 才可作为稳定实现契约。

### 5.2 安全威胁模型与控制矩阵

**状态：P0；`REQ-SEC-001` 至 `REQ-SEC-010` 均已完成详细设计，待跨模块评审与冻结；总体控制基线待跨模块冻结**  
**采用版本：`Security Threat Model v1`，当前为草案基线**

已识别的主要威胁：

- 身份伪造、权限提升、跨租户泄露；
- 敏感代码外发、密钥泄露、恶意代码注入；
- 沙箱逃逸、危险命令、资源耗尽；
- 恶意依赖和供应链攻击；
- Prompt 注入、模型中毒、模型输出不可信；
- 数据外泄、MCP 越权；
- 审计缺失、数据驻留和数据留存违规。

推荐基线：

- 零信任、默认拒绝、最小权限；
- 所有 Action 经过 Policy Gateway；
- 沙箱后端通过统一能力契约抽象，由多维风险路由选择满足最低隔离要求的生产后端；
- Level 3 由与 `risk_level` 正交的触发矩阵决定，命中即升级；成本闸门不得降低隔离要求，运行中禁止向下降级；
- 网络目的地由连接器声明、审批固化并在运行时下发，不设平台通用预置白名单；凭据由 `REQ-SEC-005` 的外置代理按授权范围提供；
- 生产执行路径统一为 Linux；Windows 本地执行经虚拟化 Linux 环境；策略意图抽象但不宣称平台保障等价；
- SAST、SCA、Secret Scanning 和人工 PR 审查。

已完成设计的独立需求：

- `REQ-SEC-001` 威胁模型和风险评分，版本：`v0.1-designed`；
- `REQ-SEC-002` RBAC 与资源授权，版本：`v0.1-designed`，详见 [专项设计](./REQ-SEC-002-rbac-resource-authorization.md)；待跨模块评审与冻结。
- `REQ-SEC-003` Policy Gateway，版本：`v0.1-designed`，详见 [专项设计](./REQ-SEC-003-policy-gateway.md)；待跨模块评审与冻结。MVP 采用 OPA/Cedar 之一、独立 Auto-review、粗粒度审批矩阵、审批超时升级、多 Agent 单跳 OBO、差异化决策缓存及三级审计脱敏。
- `REQ-SEC-005` 凭据代理，版本：`v0.1-designed`，详见 [专项设计](./REQ-SEC-005-credential-proxy.md)；待跨模块评审与冻结。MVP 支持 GitHub App + AWS STS（OIDC 联合）+ 通用 OAuth 2.0；PDP/CDP 分离架构；三代理模型（Model B 为主、Model A 用于 OIDC 联合）；Vault 集成（单云云厂商托管）；CDP 多实例 active-active；撤销传播 < 5s；OIDC 联合 MVP 必选；DPoP 接口预留渐进路线。
- `REQ-SEC-006` Prompt 注入与恶意仓库防护，版本：`v0.1-designed`，详见 [专项设计](./REQ-SEC-006-prompt-injection-malicious-repo-protection.md)；待跨模块评审与冻结。MVP 采用双引擎检测（静态规则 + LLM零样本分类）、按块阻断 + 密度阈值触发整体拒绝、Monotonic Tightening分层配置、高危不可覆盖中低危限时豁免机制、分级SLA + 异步化策略。
- `REQ-SEC-007` MCP 连接器治理，版本：`v0.1-designed`，详见 [专项设计](./REQ-SEC-007-mcp-connector-governance.md)；待跨模块评审与冻结。MVP 以 OAuth 2.1 风格 MCP Authorization 为远程首选，API Key 仅为 `@deprecated` 过渡适配器；要求 Schema 签名并按 L1-L4 信任等级分级放行，权限细化到单工具；独立 Auto-review 位于 PDP 侧，Policy Gateway 为 PEP；全局黑名单强制，组织策略可进一步收紧，连接器配额按信任等级和能力加权。
- `REQ-SEC-008` 多租户与数据治理，版本：`v0.1-designed`，详见 [专项设计](./REQ-SEC-008-multi-tenant-data-governance.md)；待跨模块评审与冻结。计算 Pool + 存储/密钥 per-team 隔离；Org → Team 两级组织模型；单主区域 + 区域钉扎抽象层；平台代管 per-team DEK/KEK（CMEK 字段预留）；向量嵌入整集删除；RPO ≤ 15min，RTO ≤ 4h（标准）/ ≤ 1h（高敏）；ISO 27001 基线 → SOC 2 → GDPR 法律底线。

已完成详细设计的独立需求：

- `REQ-SEC-004` 沙箱隔离基线，版本：`v0.2-designed`，详见 [专项设计](./REQ-SEC-004-sandbox-isolation-baseline.md)；采用多后端能力抽象与风险路由、连接器声明—审批—运行时下发、正交 Level 3 触发和禁止降级、审计三档/WORM/检索 SLA/租户删除级联、Linux 单一生产路径、分配 p95 ≤ 200ms 的自适应 WarmPool；阈值与运营参数待跨模块评审冻结。

- `REQ-SEC-009` Kill Switch 与事故响应，版本：`v0.1-designed`，详见 [专项设计](./REQ-SEC-009-kill-switch-incident-response.md)；待跨模块评审与冻结。采用 Kill Switch State Machine（6 模式 M0-M5）、三态 Fail-Closed（NORMAL / DEGRADED / LOCKED）、七层粒度（ACTION/TOOL/CONNECTOR/TASK/WORKFLOW/PROJECT/ORG/GLOBAL）、三维判定矩阵（严重度×置信度×爆破半径）自动化触发、分层 TTA 指标体系（MTTD/MTTA/MTTC/M5-RTO）、分档证据保留（运营档/事件案卷档/Legal Hold）、M5 分阶段恢复（5-Phase replay 验证）、Break-Glass 四层授权（委托链+Quorum+Break-Glass 账户+带外核验）、API/CLI/UI 统一状态机入口、Kill Switch 与 Policy Gateway 职责边界清晰（M0-M5 枚举通信）。

已完成详细设计的独立需求：

- `REQ-SEC-010` 安全控制验证与红队测试计划，版本：`v0.1-designed`，详见 [专项设计](./REQ-SEC-010-security-control-validation-red-team.md)；采用事件驱动的分层验证体系、L1/L2/L3 × D1-D6 攻击面矩阵、Tier-2 注入回归、独立性硬约束、蓝队容量闸门和响应—缓解—修复—根除四段式风险加权 SLA。

尚未完成的独立需求：

- 无安全（SEC）专项待设计需求。

### 5.3 失败恢复与重试

**状态：P0；`REQ-REL-001` 至 `REQ-REL-009` 全部 9 项已完成详细设计，失败恢复执行协议待跨模块冻结**  
**采用版本：`Failure Recovery Baseline v1-draft`；`REQ-REL-001` 至 `REQ-REL-009`：已完成详细设计**，待跨模块评审与冻结

推荐基线：

- `REQ-REL-001` 以症状、生命周期阶段、根因三个正交维度描述失败；MVP 只冻结低基数可观测症状词表，阶段和根因词表后续评测后扩展；
- 症状与根因分离：症状用于告警聚合和 dedup，根因可基于证据事后修订并审计；
- 每条失败事件持久化分类体系版本和检测器版本；历史事件不重写，通过分析层新旧版本映射保持趋势口径可比；
- 分类扩展采用稳定症状枚举 + 检测器插件注册表；
- 分类器负责失败信号采集和初筛，安全控制判定归 SEC，通过事件契约关联；
- `UNKNOWN_FAILURE` 默认终止当前自动执行、升级并保全现场；组织级配置只能收紧，不能改为继续、成功或自动重试；`unknown_rate` 为一级健康指标，SLO 阈值由基线评测确定；
- 确定性失败不重试；网络、限流和服务暂时不可用交由有界退避策略判定；
- Worker 崩溃从检查点恢复；写操作重试前必须检查工作区和幂等状态；
- 测试失败进入诊断或 Resolver；权限拒绝、审批等待和配额超限不自动重试；失败后按需要执行补偿工作流。

已完成详细设计的独立需求：

- `REQ-REL-001` Failure Taxonomy，版本：`v0.1-designed`，详见 [专项设计](./REQ-REL-001-failure-taxonomy.md)；三维正交分类、MVP 症状词表、分类版本映射、症状/根因分离、双层置信度、未知失败 fail-closed 与 SLO、稳定枚举和检测器插件治理；待跨模块评审与冻结。
- `REQ-REL-002` RetryPolicy，版本：`v0.1-designed`，详见 [专项设计](./REQ-REL-002-retry-policy.md)；时限预算推导重试次数（time_budget_ms 为真正控制量）、Full Jitter（jitter=1.0）、服务端 Retry-After 优先、全局重试预算（≤10%）、熔断器（失败率30%+慢调用率）、客户端令牌桶限流（压制到配额70-80%）、DLQ 保底（Policy/审批/凭据类事件）、一级可观测指标（重试率、重试放大比、429占比）；待跨模块评审与冻结。
- `REQ-REL-003` 重试决策引擎，版本：`v0.2-designed`，详见 [专项设计](./REQ-REL-003-retry-decision-engine.md)；采用幂等闸门三分支与 `IN_DOUBT` 待决队列、锁键与只严不松 DENY 缓存；连续失败与窗口失败率双计数器；Policy Gateway 预裁决、独立有限重试和黄色区间提前限流；三值对账、独立只读探测、权威真相源前置条件、风险分档 SLA；幂等键生命周期与对账/留存联动；待跨模块评审与冻结。
- `REQ-REL-004` Checkpoint 保存与保留策略，版本：`v0.1-designed`，详见 [专项设计](./REQ-REL-004-checkpoint-retention-policy.md)；采用记录类别基线（取证档/运营档/内容档/案卷档）+ 合规要求 + 风险加权延长模型；三条铁律（风险等级只延长不缩短、expires_at 写入时固化、策略变更不追溯缩短）；保护谓词五条件（引用∨关联∨时间地板∨计数地板∨冷静期）；软删除 + 48h 宽限期；deleted_manifest 凭证归档；分片键控并发 + 幂等删除 + 限流锁；双向合规指标（overdue_delete_count=0, premature_delete_count=0）；待跨模块评审与冻结。
- `REQ-REL-005` 恢复决策与失败处理，版本：`v0.2-designed`，详见 [专项设计](./REQ-REL-005-recovery-decision-failure-handling.md)；采用污染半径恢复点、版本/根因/合规三闸门、Effect Log 三段式契约、Pivot、补偿独立安全域、恢复期保护和九态状态机；待跨模块评审与冻结。
- `REQ-REL-006` 写操作幂等封装，版本：`v0.1-designed`，详见 [专项设计](./REQ-REL-006-write-operation-idempotency.md)；采用稳定逻辑意图键、RFC 8785 JCS/类型化规范化、上下文复核、六态账本、fencing lease、Effect Log/Outbox 原子边界、A-D 连接器能力分级和 SLA 驱动对账；待跨模块评审与冻结。
- `REQ-REL-007` Compensation Workflow，版本：`v0.1-designed`，详见 [专项设计](./REQ-REL-007-compensation-workflow.md)；采用三分支补偿决策（自动补偿/前向完成/升级）、依赖图驱动补偿范围、决策谓词驱动审批（审批聚合+break-glass）、per-domain超时配置（0.7×正向超时）、ESCALATED硬SLO+强制收敛、独立补偿机制（`comp:`前缀幂等键、独立熔断器、独立限流）；待跨模块评审与冻结。
- `REQ-REL-008` 测试失败与工具异常分类（工具治理与上线策略），版本：`v0.1-designed`，详见 [专项设计](./REQ-REL-008-test-failure-tool-error-classification.md)；采用工具分波上线策略（W1 只读观测 + 可逆写入 + 测试执行器 → W2 原子化命令 + 网络代理 → W3 审计 Shell）、工具注册表 7 件必填事项（allowlist/denylist、超时与资源上限、输出上限、幂等故事、可逆性标注、Pivot 标注、补偿与对账探针接口）、schema_hash 版本指纹、分类器职责分离（只产出校准分数 + 证据，不持有阈值）、版本化配置契约（tool-registry-v1.yaml）、启动期校验、与 REL-003 重试决策引擎集成（Policy Gateway 工具准入控制）；待跨模块评审与冻结。
- `REQ-REL-008A` 测试失败与工具异常分类（分类引擎），版本：`v0.1-designed`，详见 [专项设计](./REQ-REL-008A-test-failure-tool-exception-classification.md)；作为 `REQ-REL-008` 的子需求，定义 14 步分类决策流程（测试结果特殊处理、工具崩溃检测、超时细分、HTTP 状态码映射、输出有效性检查）、结构化输出解析器（JUnit XML/pytest JSON/Go test JSON/Cargo JSON/TAP）、MCP 工具错误分类（遵循 Anthropic MCP 规范）；待跨模块评审与冻结。
- `REQ-REL-009` 故障注入和恢复验证场景，版本：`v0.1-designed`，详见 [专项设计](./REQ-REL-009-fault-injection-recovery-verification.md)；采用 AgentChaos 三层故障分类（Crash/Omission/Value × Content/Tool-call）× 4 种注入策略（Single/Persistent/Intermittent/Burst）、确定性故障调度（seed-based 重放）、Trigger Verification（防止低估影响）、四值判定（recovered/contained_failure/unrecoverable/inconclusive）、三层注入点（HTTP 代理/工具适配器/进程注入）、首批 20 个场景（网络 3 + 模型 5 + 工具 5 + 安全 4 + 时间 3）、4 项核心不变量（PR 不重复、Policy Gateway fail-closed、预算不超限、checkpoint 覆盖必要状态）、6 项一级指标（pass_rate < 95% 阻断发布、recovery_time_p95、side_effect_duplication_rate、inconclusive_rate、unrecoverable_rate、fault_injector_error_rate）、CI 集成与回归能力；待跨模块评审与冻结。

### 5.4 上下文管理与代码索引

**状态：P1，`REQ-CTX-001`、`REQ-CTX-002` 和 `REQ-CTX-003` 已完成详细设计，算法参数未冻结**  
**采用版本：`Context and Code Index Baseline v1`，当前为实验基线**

已完成详细设计的独立需求：

- `REQ-CTX-001` 索引实体和关系 Schema，版本：`v0.1-designed`，详见 [专项设计](./REQ-CTX-001-index-entities-schema.md)；采用 FileNode、SymbolNode、DependencyNode、RelationEdge、IndexMetadata 五核心实体；每个实体绑定 `repository_id` 和 `source_revision`（Git commit SHA）；符号采用 qualified name（借鉴 Sourcegraph SCIP）；关系包含 8 种类型（IMPORTS、DEPENDS_ON、DEFINES、CALLS、REFERENCES、USES_TYPE、EXTENDS、IMPLEMENTS）；支持 Merkle 树增量检测（借鉴 Cursor）；索引元数据包含 IndexState（PENDING/BUILDING/ACTIVE/STALE/ARCHIVED/FAILED）；与 Runtime Contract 版本绑定（Task.base_revision → IndexMetadata.source_revision）；待跨模块评审与冻结。

- `REQ-CTX-002` 语言、仓库规模和基准集，版本：`v0.1-designed`，详见 [专项设计](./REQ-CTX-002-language-repository-scale-benchmark.md)；定义语言三级支持（TIER_1: Python/TypeScript/Go，TIER_2: Java/Rust/C++/C#，UNSUPPORTED: 其他）；仓库四级规模（SMALL < 100文件 < 5s索引，MEDIUM 100-1000文件 < 30s索引，LARGE 1000-10000文件 < 120s索引，XLARGE > 10000文件需手动配置）；基准集规范（每 TIER_1 语言至少 10 仓库，总计 50+ 真实任务，难度分布 40%/40%/20%）；性能目标参考 GitHub Copilot 秒级索引、Infino benchmark 数据、SWE-bench Verified 子集；待跨模块评审与冻结。

- `REQ-CTX-003` AST/LSP/依赖解析，版本：`v0.1-designed`，详见 [专项设计](./REQ-CTX-003-ast-lsp-dependency-parsing.md)；**核心架构决策基于2026年行业标杆分析**：
  - **LSP 部署模式**：每仓库独立 LSP 实例 + Redis 缓存层（替代共享服务池）；借鉴企业级部署标准，避免状态混乱，Redis 共享常见库类型信息；
  - **依赖解析精度**：直接依赖 + 一层传递依赖（MVP），支持工程级跨文件上下文感知（Phase 2 扩展到完整传递依赖图）；
  - **循环依赖处理**：静默检测 + 图遍历深度限制；使用 Tarjan 算法检测强连通分量（SCC），不主动告警避免误报，图遍历设置深度限制（默认5层）；
  - **解析流程**：TIER_1 语言（Python/TypeScript/Go）采用 Tree-sitter + LSP 协同（AST 快速提取结构 + LSP 5秒超时语义增强），TIER_2 语言纯 Tree-sitter；
  - **Merkle 树增量检测**：O(log N) 变更检测，仅重新解析变更文件；
  - **性能目标**：SMALL < 5s, MEDIUM < 30s, LARGE < 120s；增量 < 0.5s/1s/2s；LSP 响应 p95 < 2-3s；
  - **质量目标**：解析成功率 ≥ 95%，符号提取召回率 > 0.9，调用图准确率 > 0.9，依赖解析准确率 > 0.95；
  - **行业对标**：Sourcegraph SCIP、Cursor Merkle 树、Codebase-Memory Tree-sitter KG、通义灵码 GraphTransformer、2026 LSP K8s 企业部署、Qoder 混合检索；待跨模块评审与冻结。

- `REQ-CTX-004` 混合检索与排序，版本：`v0.1-designed`，详见 [专项设计](./REQ-CTX-004-hybrid-retrieval-ranking.md)；**核心架构决策基于行业最佳实践分析**：
  - **三通道并行检索**：BM25F多字段评分（symbol_name×3.0, filename×2.0, docstring×1.5, code×1.0）、Dense Vector语义检索（HNSW索引，cosine相似度，1536维嵌入）、Graph调用链遍历（DFS深度3，Tarjan SCC防环，距离衰减0.8）；
  - **Reciprocal Rank Fusion（RRF）**：公式 score(d) = Σ wᵢ/(k + rankᵢ(d))，默认k=60（大型仓库）/10-30（小型仓库），权重根据查询类型动态调整，无需分数归一化；
  - **权限前置过滤**：在RRF融合前对每个通道结果执行RBAC检查，批量权限检查+缓存（TTL=5分钟），零权限泄漏容忍度；
  - **渐进式上下文暴露**：L1 Compact Summary（~50 tokens）→ L2 Timeline Context（~200 tokens）→ L3 Full Code（~500-1000 tokens），按需加载；
  - **性能与质量SLA**：p50 < 200ms, p95 < 500ms；Recall@20 > 85%, Precision@5 > 75%, MRR > 0.70；
  - **行业对标**：Cursor语义+词法双通道、GitHub Copilot自研嵌入模型、Anthropic Contextual Retrieval、Sourcegraph Zoekt BM25F、DeepSeek三阶段流水线；
  - **演进路线**：Phase 1 MVP（BM25+Vector+Graph+RRF） → Phase 2 质量增强（Contextual Embeddings+Cross-Encoder重排） → Phase 3 规模化（分布式检索+增量索引）；待跨模块评审与冻结。

- `REQ-CTX-005` 检索权限与敏感路径，版本：`v1.0-designed`，详见 [专项设计](./REQ-CTX-005-retrieval-permissions-sensitive-paths.md)；**核心架构决策基于零信任Pre-filter原则**：
  - **零信任预过滤检索**：在向量/词法/图检索执行前进行权限校验和敏感路径过滤，避免授权泄露风险和Token浪费；
  - **三级敏感路径过滤**：Level 1硬编码基线（.env*, *.pem, *.key, .ssh/, secrets/, *.sql等，不可绕过）、Level 2组织级规则（管理员配置）、Level 3项目级规则（.aiagentignore配置）；
  - **Fail-Secure策略**：权限服务超时→DENY，Redis缓存失效→降级查询权限服务，敏感路径规则加载失败→仅应用Level 1基线，多租户ID缺失→DENY；
  - **多租户数据隔离**（集成SEC-008）：物理分区（vectors_{organization_id}, code_{organization_id}）或逻辑分区（Payload Filter），强制租户边界；
  - **RBAC权限校验**（集成SEC-002）：Deny > Ask > Allow优先级，allowed_repositories/allowed_paths/denied_paths，支持Exact/Prefix/Glob/Regex匹配；
  - **审计与可观测性**：审计日志字段（trace_id, query_text, total_candidates, filtered_count, denied_reasons, latency_ms）、Prometheus Metrics、OpenTelemetry Trace；
  - **性能优化**：Redis缓存（用户权限TTL=300s，组织敏感路径TTL=300s），Trie树+Bloom Filter快速路径匹配（P99延迟<50ms），批量权限校验；
  - **合规性**：SOC2 Type II（CC6.1访问控制、CC7.2审计日志）、ISO27001（A.9.4.1访问策略、A.12.4.1审计保留90天）、GDPR（审计日志脱敏）；
  - **行业对标**：GitHub Copilot .copilotignore、Sourcegraph Pre-filter架构、Claude Code/Cursor工作区配置、DeepSeek/Kimi Code路径黑名单、Dify+SpiceDB Zero-Trust模型；待跨模块评审与冻结。

- `REQ-CTX-006` Context Selector 与预算，版本：`v0.1-designed`，详见 [专项设计](./REQ-CTX-006-context-selector-budget.md)；**核心架构决策基于行业标杆Token预算管理**：
  - **任务类型驱动Token预算分配**：6种任务类型（BUG_FIX/FEATURE_DEVELOPMENT/REFACTORING/CODE_REVIEW/UNIT_TEST/DOCUMENTATION）差异化预算配置；默认分配比例（任务描述5%-10%/核心代码35%-50%/依赖代码15%-30%/测试代码10%-40%/文档5%-40%）；
  - **多维度优先级计算**：综合评分 = 相关性(0.4)×融合分数 + 依赖(0.25)×依赖分数 + 中心性(0.25)×图分数 + 新鲜度(0.1)×时间分数；任务类型调整权重（BUG_FIX相关性优先0.5，REFACTORING结构优先0.35/0.35）；
  - **渐进式上下文暴露**（借鉴Cursor）：L1 Compact Summary（~50 tokens）→ L2 Timeline Context（~200 tokens）→ L3 Full Code（~500-1000 tokens），按需加载优化Token使用；
  - **三种裁剪策略**：GREEDY（从低优先级移除）、SELECTIVE（保留前K个高优先级）、AGGRESSIVE（截断+摘要降级）；支持摘要降级（L3→L2→L1）；
  - **可解释性记录**：SelectionReason记录每项选择理由、优先级详细分解（relevance/dependency/centrality/freshness）、裁剪原因（如有）；
  - **性能与质量SLA**：延迟p95 < 100ms；Token使用率目标80%-95%；覆盖率 > 85%；裁剪率 < 20%；
  - **行业对标**：Cursor渐进式暴露、Anthropic Contextual Retrieval块级嵌入、通义灵码任务驱动分配、DeepSeek自适应压缩、GitHub Copilot任务复杂度评估；待跨模块评审与冻结。

推荐基线：

- 权限过滤优先于检索结果返回；
- Python、TypeScript/JavaScript、Go 作为 MVP 首批语言；
- 小型和中型仓库为主要目标；
- Tree-sitter 统一 AST 框架（66 种语言支持）；
- LSP（pyright, tsserver, gopls）补充 TIER_1 语言语义信息；
- BM25 + 向量 + 符号/依赖图混合检索；
- Git SHA 作为索引版本；
- Context Selector 按相关度、依赖关系和 Token 预算分层加载；
- Merkle 树用于增量检测变更文件；
- CMV 只作为实验对照，不作为默认实现。

尚未完成的独立需求：

- `REQ-CTX-008` 上下文压缩与分层加载协议；
- `REQ-CTX-009` Recall、Precision、MRR、延迟和任务正确率评测。

### 5.5 记忆管理

**状态：`REQ-MEM-001`、`REQ-MEM-002`、`REQ-MEM-003` 和 `REQ-MEM-004` 已完成详细设计，待跨模块评审与冻结**  
**采用版本：`Structured Memory Baseline v0.3`**

推荐基线：

- 分为工作记忆、任务记忆、项目记忆和组织记忆；
- MVP 默认只允许任务记忆和项目记忆跨步骤保留；
- 每条记忆记录来源、版本、仓库、权限范围、置信度、生命周期和删除状态；
- 结构化、可审计记忆优先；
- RGMem、FadeMem、Hebbian 学习不作为 MVP 生产依赖；
- 记忆不能自动改变安全策略。

已完成详细设计的独立需求：

- `REQ-MEM-001` Memory Schema，版本：`v0.1-designed`，详见 [专项设计](./REQ-MEM-001-memory-schema.md)；定义四类记忆（WORKING/TASK/PROJECT/ORGANIZATION）、五种来源类型、置信度评估、权限模型、生命周期管理和 Provenance 溯源；待跨模块评审与冻结。
- `REQ-MEM-002` 记忆写入审批，版本：`v0.1-designed`，详见 [专项设计](./REQ-MEM-002-memory-write-approval.md)；采用四维评估算法（memory_type、source、confidence、sensitivity）、六步审批流程（触发→扫描→路由→审批→生效→撤销）、三级同意粒度（一次性/会话级/永久）、敏感信息扫描与隔离机制、Policy Gateway 集成、fail-closed 策略；对齐 OpenAI Agents SDK、DeepSeek Harness、Claude Code、Qoder、SP-Mem、Consent Memory 等行业标杆；待跨模块评审与冻结。
- `REQ-MEM-003` 记忆检索与冲突，版本：`v0.1-designed`，详见 [专项设计](./REQ-MEM-003-memory-retrieval-conflict.md)；采用三路并行检索（语义+BM25+时序）、五维评分融合（语义×0.30+关键词×0.15+时序×0.20+置信度×0.20+作用域×0.15）、L1→L2→L3 渐进披露、三轨冲突分类（符号/可信度/协调）、ADD-ONLY 哲学；对齐 Claude Code LLM 路由、Mem0 v3 多信号混合、Zep/Graphiti 时序有效性、MemGPT 分层存储、LatticeMind 冲突感知、Kimi Mem 渐进披露等行业标杆；待跨模块评审与冻结。
- `REQ-MEM-004` 记忆生命周期，版本：`v0.1-designed`，详见 [专项设计](./REQ-MEM-004-memory-lifecycle.md)；采用多维度衰减评分算法（时间×访问频率×置信度×时效性）、确定性过期（expires_at）+ 条件过期（TTL、访问超时）、三阶段删除（软删除→归档→硬删除）、数据驻留合规（区域配置+跨境限制+GDPR 导出）、定时+事件+手动三种清理触发模式；对齐 Zep 双时态模型、MemGPT 分层存储、LangGraph TTL 清理等行业标杆；待跨模块评审与冻结。

扩展候选需求（不计入当前 60 项正式基线）：

- `REQ-MEM-005` 跨项目权限继承和租户隔离；
- `REQ-MEM-006` 错误记忆清理和效果评测。

### 5.6 Harness Engineering

**状态：部分形成设计，专项规范未完成**  
**采用版本：`Harness Contract v0.1`**

推荐基线：

- Identity、Context、Tool、Execution、Policy、Evidence 六层；
- 技能、项目指令、Hooks、LSP、MCP 和工具适配器均为可版本化资产；
- 安全类 Hook 默认 fail-closed；
- 诊断类 Hook 可以降级，但必须记录；
- 工具必须有输入、输出、风险、权限、超时、重试和审计 Schema。

已完成详细设计的独立需求：

- `REQ-HAR-001` Harness 生命周期和标准接口（**v0.1-designed，2026-09-26 完成详细设计**）；
- `REQ-HAR-002` Worker Context Compaction 规范（**v0.1-designed，2026-09-27 完成详细设计**）；
- `REQ-HAR-003` Tool Adapter 和工具 Schema（**v0.1-designed，2026-09-30 完成详细设计**，详见 [专项设计](./REQ-HAR-003-tool-adapter.md)）；
- `REQ-HAR-004` Hook Registry，版本：`v0.1-designed`，详见 [专项设计](./REQ-HAR-004-hook-registry.md)；采用六层注册源(platform/enterprise/team/project/user/plugin)、29个生命周期事件、五种Hook类型(command/http/mcp_tool/approval/inline)、六种失败策略(fail-closed/fail-open/degraded/retry/escalate/wait-approval)、Plugin Hook沙箱隔离(seccomp+AppArmor)、签名验证(SHA-256+RSA-2048/Ed25519)、响应合并协议(block>allow>observe)、manifest schema版本化、事件演进协议(兼容期6-12个月)；对齐OpenAI Agents SDK双层Hook、Claude Code 20+事件与响应合并、LangChain Middleware洋葱模型、Cursor多级优先级、Dify Plugin Daemon、Kimi Plugin Hook隔离行业实践；待跨模块评审与冻结。
- `REQ-HAR-005` LSP/MCP/Skill 统一路由，版本：`v0.1-designed`，详见 [专项设计](./REQ-HAR-005-unified-routing.md)；采用跨协议 Capability Abstraction Layer、12 步发现流程（协议源聚合→权限预检→Policy 预检→延迟加载评估→语义检索→能力聚合→冲突仲裁→Schema 规范化→响应封装→PEP 拦截点注册）、7 步调用路由（协议路由→执行前检查→参数转换→执行委托→结果处理）、延迟加载机制（Token 预算驱动+语义检索 top-N）、冲突仲裁规则（协议优先级 LSP=100>MCP=80>SKILL=60）、发现时+调用时双层权限裁剪、SEC-007 Schema 签名验证集成、12 核心指标+5 告警规则；对齐 MCP 官方规范（tools/list+tools/call+listChanged）、Cursor Enterprise/Team 多层策略、LangGraph Picker Node 动态绑定、OpenAI MCPServerManager、Kimi Code deferred 机制、DeepSeekCode 统一执行路径行业实践；待跨模块评审与冻结。
- `REQ-HAR-006` Harness 契约测试，版本：`v0.1-designed`，详见 [专项设计](./REQ-HAR-006-harness-contract-testing.md)；采用消费者驱动契约测试（CDC）模式、四类测试套件（接口契约IC/安全契约SC/攻击场景AC/轨迹回放TR）、10步契约测试执行流程（契约发现→消费者收集→契约匹配→测试用例生成→测试执行→结果验证→冲突检测→报告生成→证据归档→门禁决策）、8步攻击场景回放流程、6步轨迹回放流程、契约匹配算法（match_score=0.4×schema+0.3×constraint+0.3×behavior）、轨迹相似度算法（0.3×sequence+0.2×resource+0.2×state+0.3×output）、攻击参数化（intensity 0.0-1.0+duration+target）、证据包签名（防篡改）、SemVer版本管理+兼容性检查；对齐OpenAI Codex轨迹录制回放、Cursor场景DSL、LangGraph状态机验证、AutoGen Schema契约、Claude Code安全约束声明、Coze/Dify OpenAPI风格、Manus场景测试、DeepSeek/KIMI上下文预算契约行业实践；待跨模块评审与冻结。

尚未完成的独立需求：

（Harness 工程模块已全部完成详细设计）

### 5.7 可观测性与审计

**状态：`REQ-OBS-001` 至 `REQ-OBS-007` 全部已完成详细设计，待跨模块评审与冻结**  
**采用版本：`Observability and Audit Baseline v0.2`**

推荐基线：

- Workflow、Worker、ReAct Iteration、Action、Tool、Model、Sandbox、Artifact、Evidence 和 Approval 建立 Trace 关联；
- Event、Trace、Metric、Log、Evidence 分层；
- 审计日志与普通运行日志分离；
- 指标按项目、模型、Worker、工具、资产版本和数据等级切分；
- 所有日志执行脱敏、访问控制和留存策略。

已完成详细设计的独立需求：

- `REQ-OBS-001` OpenTelemetry 语义约定，版本：`v0.1-designed`，详见 [专项设计](./REQ-OBS-001-opentelemetry-semantic-conventions.md)；采用 OpenTelemetry GenAI 语义约定作为标准化基础；定义 Task→Workflow→Worker→Action→Tool/Model/Sandbox 分层 Span 结构；默认 15% 采样率，高风险/失败/安全相关操作强制采样；三级内容捕获策略（FULL/FEEDBACK_ONLY/DISABLED），默认关闭；受信任边界内 W3C Trace Context 传播；对齐 OTel GenAI SIG、Cursor Enterprise、DeepSeek Harness、LangSmith、Microsoft Copilot 行业实践；待跨模块评审与冻结。
- `REQ-OBS-002` Trace/Event/Evidence Schema，版本：`v0.1-designed`，详见 [专项设计](./REQ-OBS-002-trace-event-evidence-schema.md)；采用分层数据模型（Trace/Span/Event/Evidence）、44 项 EventType 枚举覆盖 Agent 全生命周期、Evidence 独立建模支持审计合规、多维关联模型（Trace↔Span↔Event↔Evidence）、分层存储策略（热 30 天/温 180 天/冷 7 年）；对齐 OpenTelemetry GenAI、LangSmith、Manus AI、Microsoft Copilot、Dify 行业实践；待跨模块评审与冻结。
- `REQ-OBS-003` 指标字典，版本：`v0.1-designed`，详见 [专项设计](./REQ-OBS-003-metrics-dictionary.md)；采用 GenAI 专有指标字典（15 项核心指标）、维度定义体系（18 个标准维度）、高基数控制算法（黑名单+白名单+溢出策略）、指标分类体系（Usage/Quality/Performance/Cost/Safety）、统计口径标准化（窗口/聚合/分组规则）；对齐 OpenTelemetry GenAI、LangSmith、Grafana、Microsoft Copilot、Dify 行业实践；待跨模块评审与冻结。
- `REQ-OBS-004` 脱敏和高基数控制，版本：`v0.1-designed`，详见 [专项设计](./REQ-OBS-004-redaction-cardinality-control.md)；采用四层敏感度分级（PUBLIC/INTERNAL/CONFIDENTIAL/RESTRICTED）、Key Name 词素分词脱敏（tokenize on _/-/./space/camelCase）、32 层递归上限防 CPU 耗尽、调试模式 24h 审批流、高基数黑名单（trace_id/session_id/user_id 等）+ `__overflow__` 兜底策略、URL Sanitizer 降基数、HMAC-SHA256 scope-specific 哈希（保留可关联性）、流式缓冲跨 chunk 脱敏、15 项功能验收 + 4 项合规验收；对齐 OpenTelemetry、Cursor Enterprise、LangSmith、DeepSeek Harness、Azure Foundry、Grafana Alloy、AISIX Gateway 等 8 家标杆；待跨模块评审与冻结。
- `REQ-OBS-005` 告警和 Kill Switch 联动，版本：`v0.1-designed`，详见 [专项设计](./REQ-OBS-005-alert-killswitch-linkage.md)；采用三维判定矩阵（严重度×置信度×爆破半径）驱动自动化联动、告警规则引擎（支持 PromQL 风格条件表达式）、与 SEC-009 Kill Switch 深度集成（M0-M5 模式映射）、分层通知渠道（PagerDuty/Slack/Email/Webhook）+ 升级机制、告警有效性评估体系（精确率/召回率/噪声比）、自动化联动三条铁律（爆破半径上限/自动解除分档/观察期）、告警生命周期管理（触发/确认/解决/升级）、静默与抑制规则、告警去重与聚合；对齐 OneUptime Circuit Breakers、AgentGazer Kill Switch、Agent Sentinel 置信度门控、Guardplane 控制平面、Grafana SLO Burn Rate、PagerDuty Automation Actions、DeepSeek Prometheus Exporter 行业实践；待跨模块评审与冻结。

- `REQ-OBS-006` 审计查询 API，版本：`v0.1-designed`，详见 [专项设计](./REQ-OBS-006-audit-query-api.md)；采用四层 API 架构（RESTful 查询 API + GraphQL 灵活查询 + Streaming API + Webhook 推送）、统一查询过滤模型（时间范围/Actor/Action/Outcome/标签）、权限隔离模型（RBAC 资源级授权 + 敏感数据二次审批）、审计日志完整性验证接口（哈希链验证 + Merkle Proof）、分页与游标策略、查询成本限制（默认 10s 超时/1000 条上限）；对齐 Datadog Audit Trail API、AWS CloudTrail、Azure Monitor Logs、Splunk、Elastic SIEM 行业实践；待跨模块评审与冻结。
- `REQ-OBS-007` 审计留存和完整性，版本：`v1.0-designed`，详见 [专项设计](./REQ-OBS-007-audit-retention-integrity.md)；采用四层分层留存策略（Hot 0-30d/Warm 31-180d/Cold 181d-3y/Archive 3-7y+ WORM）、防篡改哈希链设计（SHA-256 单记录哈希 + prev_hash 链式哈希 + 创世记录）、外部锚定机制（RFC 3161 TSA 时间戳 + WORM 存储 + 可选区块链）、周期性 Merkle Tree 构建（1 小时 Epoch）+ Merkle Root 外部发布防回滚、GDPR 兼容 Tombstone 机制（保留 content_fingerprint + 销毁敏感内容 + 维持链连续性）、Legal Hold 架构（case_id 范围锁定 + 审批流程 + 跨层保全）、PII 隔离 Tier（独立加密密钥 + 30 天最小留存 + 删除权优先）、自动分层迁移策略（TimescaleDB 压缩 + pg_cron 导出 Parquet + S3 Object Lock）、完整性验证算法（单条验证 + 链式验证 + Merkle Proof）；对齐 AWS Agentic AI Lens、IETF Agent Audit Trail、Microsoft Agent Governance、OpenAI/Anthropic/Google AI、字节 Coze/阿里百炼/月之暗面 Kimi、LangGraph/Dify/Claude Code 实践及 EU AI Act Art. 12、GDPR Art. 17、SOC 2 CC7.2、ISO 27001:2022 A.8.15、PCI DSS v4.0.1 Req. 10、SEC Rule 17a-4(f)、CFTC Rule 1.31 合规标准；待跨模块评审与冻结。

尚未完成的独立需求：

（无）

### 5.8 评估体系

**状态：`REQ-EVA-001` 至 `REQ-EVA-007` 已完成详细设计（`REQ-EVA-007` 于 2026-10-08 完成，v1.0-designed）；待跨模块评审与冻结**  
**采用版本：`Evaluation and Release Gate Baseline v0.2`（EVA-007 升级为基线后为 v0.3-planning）**

已完成详细设计的独立需求：

- `REQ-EVA-001` Golden Dataset，版本：`v0.1-designed`，详见 [专项设计](./REQ-EVA-001-golden-dataset.md)；采用 Oracle 入集闸门、五类血缘分开报告、污染控制安全事件管理、IRT 多维难度校准、对抗样本三层隔离和两条红线Verifier 独立测试机制；待跨模块评审与冻结。
- `REQ-EVA-002` 标注规范，版本：`v0.1-designed`，详见 [专项设计](./REQ-EVA-002-annotation-specification.md)；采用六层标注Schema（Oracle验证层、上下文需求层、质量评估层6维度、难度评估层IRT+5维复杂度、失败归因层、一致性元数据层）、Must-have/Nice-to-have分离、LLM-as-Judge校准（位置偏差/verbose偏差/自我偏好偏差检测）、Krippendorff's alpha ≥ 0.7一致性要求、Iterate-Grade-Revise评估循环、人工标注→LLM辅助→人工复审三层体系；对齐Claude Code Outcomes、Kimi K3 GRM、OpenAI Trace Grading、CursorBench、DeepSWE、SPICE、BACON/A-BB行业实践；待跨模块评审与冻结。
- `REQ-EVA-003` 自动评分器，版本：`v0.1-designed`，详见 [专项设计](./REQ-EVA-003-automated-scorer.md)；采用独立grader架构（对标Claude Outcomes上下文隔离）、三层混合评分策略（确定性检查优先+LLM-as-Judge分级+人工校准）、per-criterion独立评分、五层评分体系覆盖（工具/Worker/Workflow/端到端/安全对抗）、评分器校准机制（50样本、Spearman相关≥0.85、假阳性率≤2%、假阴性率≤3%）、Security Judge独立设计（三层隔离、两条红线）；对齐Claude Outcomes、Codex Skillgrade、Cursor @cursor/july、Qoder Better Harness、SWE-bench行业实践；待跨模块评审与冻结。
- `REQ-EVA-004` 失败归因，版本：`v0.1-designed`，详见 [专项设计](./REQ-EVA-004-failure-attribution.md)；采用反事实验证作为判定条件（非置信度加分项）、三维正交分类体系（症状×阶段×根因）、分层指标报告（top-1/3/MRR + per-根因类最低值）、约束必须附带可判定checker、种子来源分级、约束保质期管理、置信度校准闭环、复合门槛定义准确率分母、holdout集隔离测试；对齐AgentRx、LongRCA Bench、MAST行业实践；待跨模块评审与冻结。
- `REQ-EVA-005` 回归流水线，版本：`v0.1-designed`，详见 [专项设计](./REQ-EVA-005-regression-pipeline.md)；采用三层评估管道（确定性验证→自动评分→失败归因）、轨迹感知子集选择（节省50-90%成本）、ATIF轨迹格式+回放机制、统计显著性回归检测、三种并行策略（静态/成本驱动/优先级）、CI/CD深度集成（GitHub Action + Webhook）、评估仪表板；对齐OpenAI Codex三层管道、Cursor软硬门禁、DeepSeek容器隔离、Kimi K3 rubric评分、SWE-bench轨迹感知子集、Manus自愈调试行业实践；待跨模块评审与冻结。
- `REQ-EVA-006` 发布门禁，版本：`v0.1-designed`，详见 [专项设计](./REQ-EVA-006-release-gate.md)；采用四级门禁体系（Level 1冒烟测试→Level 2回归测试→Level 3性能基准→Level 4安全扫描）、软硬门禁分离（硬门禁阻断/软门禁告警）、血缘感知阈值（5类血缘差异化配置）、多维度回归检测（通过率+评分分布+轨迹相似度）、决策状态机（ALLOW/DENY/CONDITIONAL/OVERRIDE）、例外审批流程与Break-Glass紧急通道（Quorum审批≥3人含1位VP）、自动回滚机制（4类触发器）、CI/CD集成（GitHub Actions等）；对齐Cursor软硬门禁分离、SWE-bench血缘感知阈值与统计检验、OpenAI Codex分层管道行业实践；待跨模块评审与冻结。

### EVA 模块闭环缺口说明（2026-10-05 补充，2026-10-06 补充证据与接口评估）

`REQ-EVA-001` 至 `REQ-EVA-006` 构成的是**发布前质量门闭环**（Golden Dataset → 标注规范 → 自动评分器 → 失败归因 → 回归流水线 → 发布门禁），覆盖"代码提交到发布放行"的全过程。

**证据来源（精确引用，供复核）**：Anthropic 工程博客《Demystifying evals for AI agents》（发布日期 2026-01-09，访问日期 2026-10-05，URL：https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents，证据等级 A·官方一次来源）：

> "These methods map to different stages of agent development. Automated evals are especially useful pre-launch and in CI/CD... **Production monitoring kicks in post-launch to detect distribution drift and unanticipated real-world failures.** ... **User feedback and transcript review are ongoing practices to fill the gaps**: triage feedback constantly, sample transcripts to read weekly..."（原文"How evals fit with other methods"章节，方法对比表后段）

> "After an agent is launched and optimized, **capability evals with high pass rates can 'graduate' to become a regression suite** that is run continuously to catch any drift."（原文"Capability vs. regression evals"章节）

原文把"production monitoring"列为与"automated evals"并列、但覆盖不同阶段的独立方法（前者 pre-launch，后者 post-launch），且明确两者需要组合使用（"Swiss Cheese Model"类比：单层评估方法无法覆盖所有问题）。**该文章未直接定义"production feedback"是否必须内置于评估模块**——这一点是本次修改前的推断，现予以更正标注。

**现有六项需求的覆盖验证（经读取实际设计文档确认，非推断）**：
1. `REQ-OBS-003`（指标字典）第 124 行已定义 `gen_ai.evaluation.result`（评估分数、标签、解释）指标，**已预留生产态评估结果的采集接口**，EVA-007 可直接复用，不需要新增 OBS 层指标。
2. `REQ-EVA-006`（发布门禁）第 9 节已定义自动回滚机制，4 类触发器为：发布后 1 小时内回归测试失败、5 分钟内 >10 条 CRITICAL 告警、健康检查连续 3 次失败、Kill Switch 人工触发。**这 4 类触发器均为"发布后短时间窗口内"的检测**，不覆盖"模型快照不变、运行数周后由供应商侧静默更新引发的行为漂移"场景（即 Anthropic 原文"distribution drift"所指的场景）——此为真实存在的时间窗口缺口，而非凭空推断。
3. `REQ-OBS-005`（告警和 Kill Switch 联动）第 1052 行已声明"`REQ-EVA-003` 可使用告警精确率/召回率作为评分输入"，即 OBS→EVA 方向已有数据流向约定，但**EVA→REL/OBS 的反向触发路径（评估发现生产漂移后如何触发回滚）尚未在任一已完成文档中定义**。

**结论（降级为更谨慎的表述）**：现有六项需求之间已有部分接口预留（OBS-003 的评估指标、OBS-005 的评分输入声明），缺口不是"完全空白"，而是**缺少"评估模块主动发起、面向生产态漂移的回滚触发路径"这一个具体环节**。`REQ-EVA-007` 的职责应聚焦于补齐这一条路径，而非重新设计生产反馈采集或回滚执行机制本身：

- `REQ-EVA-007` 生产反馈、数据集更新和版本回滚，版本：`v0.0-planned`，文件待创建，纳入 60 项正式基线（EVA 模块由 6 项扩展为 7 项）。
- **核心职责（已收窄范围，避免与 OBS/REL 职责重叠）**：
  1. 生产任务结果与用户反馈的采集规则（复用 `OBS-003` 已定义的 `gen_ai.evaluation.result` 指标通道，不新增采集基础设施）；
  2. Golden Dataset 增量更新与去污染校验（复用 `EVA-001` 的污染控制机制）；
  3. 分布漂移判定逻辑（对标快照不变但行为漂移的识别算法，输出结构对齐 `EVA-004` 失败归因格式）；
  4. **向 `EVA-006` 发布门禁的回滚机制提交第 5 类触发器**（"生产态分布漂移触发器"，补齐当前仅覆盖发布后短窗口的 4 类触发器），具体接口字段由 EVA-007 详细设计时与 EVA-006 协同确认，不单方面假设 EVA-006 的现有数据结构可直接扩展；
  5. 模型/提示/评估集捆绑版本化记录（供回滚时识别"原子回滚单元"，避免部分回滚产生未测试组合）。
- **明确不包含**：不新增 OBS 层指标采集基础设施（复用现有）、不重新设计 Kill Switch 或告警联动机制（复用 `SEC-009`/`OBS-005`）、不定义回滚的执行层技术方案（部署/发布系统由 Runtime/Harness 模块承接）。
- 下游关联 `EVA-001`（Golden Dataset 更新入口）、`EVA-004`（归因结果反哺）、`EVA-006`（新增第 5 类回滚触发器，需求详细设计阶段需与 EVA-006 作者协同确认接口字段，存在触发器 Schema 变更的风险，暂定为中等风险、非阻塞性）；待详细设计。
- **决策可逆性**：若详细设计阶段发现分布漂移判定逻辑的技术可行性不足（例如依赖的时序分析基础设施未选型），允许将本需求降级回候选区，由架构组批准，并需同步回退本节及下方三处文档计数的修改。

---

## 6. 版本路线与基线使用规则

### 6.1 当前统一版本

本项目采用一个总基线版本和多个专项草案版本：

- 总体架构：`Platform Design Baseline v1.0`；
- 运行时契约：`Runtime Contract v1-draft`；
- 安全：`Security Threat Model v1-draft`；
- 失败恢复：`Failure Recovery Baseline v1-draft`；
- 上下文索引：`Context and Code Index Baseline v1-experimental`；
- 零信任上下文：`Context Governance Baseline v0.1`；
- Worker 编排：`Worker Orchestration Baseline v0.1`；
- Harness：`Harness Contract v0.1`；
- 记忆：`Structured Memory Baseline v0.1`；
- 可观测性：`Observability and Audit Baseline v0.1`；
- 评估：`Evaluation and Release Gate Baseline v0.1`。

### 6.2 版本采用规则

1. 没有经过详细设计评审的版本只能作为设计输入，不能作为实现契约。
2. `v0.x` 表示候选或专项草案，不得作为跨模块稳定接口。
3. `v1-draft` 表示主版本结构已经形成，但 Schema、迁移和验收仍未冻结。
4. 只有标记为 `v1.0-frozen` 的版本才能作为实现和集成依据。
5. 算法、模型、沙箱和检索方案没有通过统一评测时，只能称为推荐基线，不能称为最优方案。
6. 运行时实体、事件、Trace、Revision 和 Version 是所有专项模块共享的锚点，任何专项设计不能自行定义一套替代坐标系。

### 6.3 冻结顺序

```text
Runtime Contract v1
   -> Security Threat Model v1
   -> Failure Recovery Baseline v1
   -> Context and Code Index Baseline v1
   -> Evaluation and Release Gate v1
```

其中：

- `REQ-SEC-003` 与 `REQ-SEC-004` 均已完成详细设计，待跨模块评审与冻结；沙箱路由、授权、凭据、租户和事件边界分别依赖 `REQ-SEC-001/002/003/005/008`。
- 安全与失败恢复可以在运行时契约草案上并行细化，但最终冻结必须引用 Runtime Contract v1；
- 上下文索引必须使用统一的 `organization_id`、`repository_id`、`source_revision`、权限上下文和 Trace；
- 评估体系必须使用统一的 Task、Artifact、Evidence、Failure 和 Trace；
- 任何算法冻结前必须通过 Golden Dataset、性能基准和安全门禁。

---

## 7. 当前未设计完成的需求总表

以下需求是当前正式基线中仍需逐项设计的最小单元。已完成详细设计但尚待跨模块冻结的 `REQ-RT-001` 至 `REQ-RT-008`、`REQ-SEC-001` 至 `REQ-SEC-010`、`REQ-REL-001` 至 `REQ-REL-007`、`REQ-EVA-001`、`REQ-CTX-001` 不再列入待设计项。正式基线历史汇总口径为 59 项。清单以 `PENDING-REQUIREMENTS.md` 为准。每个需求都应形成独立设计文档、验收标准和版本记录。

### P0：运行时、安全、可靠性、Harness、可观测性和评估

 > P0 逐项清单以本表唯一需求编号为准；`REQ-RT-001` 至 `REQ-RT-008`、`REQ-SEC-001` 至 `REQ-SEC-008` 中已完成详细设计的专项，列于本文件第 5.1/5.2 节和 `PENDING-REQUIREMENTS.md` 的已完成表，不属于本表待办。

| 编号 | 需求 | 前置依赖 | 后续交付物 |
|---|---|---|---|
| `REQ-SEC-009` | Kill Switch 与事故响应 | RT-002、SEC-003 | 停止、凭据撤销、现场保存和恢复流程 |
| `REQ-SEC-010` | 安全控制验证与红队测试计划 | SEC-001 至 SEC-009 | 攻击场景、控制验证、红队演练 |
| `REQ-REL-001` | Failure Taxonomy | REL-001 已完成设计 | 失败枚举、识别条件和处理方式 |
| `REQ-REL-002` | RetryPolicy | REL-001、RT-007 | 时限预算推导、Full Jitter、服务端优先、全局预算、熔断器、DLQ |
| `REQ-REL-003` | 重试决策引擎 | REL-001、REL-002、RT-007、SEC-003、SEC-009 | 幂等闸门、待决队列、分层计数器、对账和降级规则 |
| `REQ-REL-004` | Checkpoint 保存与保留策略 | RT-005、REL-001 | 失败场景保存时机、保留、清理和容量策略 |
| `REQ-REL-005` | 恢复决策与失败处理 | RT-005、RT-004、REL-001、SEC-005 | 恢复点判定、失败回退和人工处理 |
| `REQ-REL-006` | 写操作幂等封装 | REL-001、REL-003、RT-007 | ✅ 已完成详细设计（见 REQ-REL-006-write-operation-idempotency.md） |
| `REQ-REL-007` | Compensation Workflow | REL-001、REL-005、SEC-009 | ✅ 已完成详细设计（见 REQ-REL-007-compensation-workflow.md） |
| `REQ-REL-008` | 测试失败与工具异常分类（工具治理） | REL-001、REL-003 | ✅ 已完成详细设计（见 REQ-REL-008-test-failure-tool-error-classification.md） |
| `REQ-REL-008A` | 测试失败与工具异常分类（分类引擎） | REL-001、REL-003、RT-003、RT-007 | ✅ 已完成详细设计（见 REQ-REL-008A-test-failure-tool-exception-classification.md） |
| `REQ-REL-009` | 故障注入和恢复验证场景 | REL-001 至 REL-008 | ✅ 已完成详细设计（见 REQ-REL-009-fault-injection-recovery-verification.md） |
| `REQ-EVA-001` | Golden Dataset | RT-001、REL-001 | ✅ 已完成详细设计（见 REQ-EVA-001-golden-dataset.md） |
| `REQ-EVA-002` | 标注规范 | EVA-001 | ✅ 已完成详细设计（见 REQ-EVA-002-annotation-specification.md） |
| `REQ-EVA-003` | 自动评分器 | EVA-001、EVA-002 | ✅ 已完成详细设计（见 REQ-EVA-003-automated-scorer.md） |
| `REQ-EVA-004` | 失败归因 | RT-003、REL-001、EVA-003 | 归因类别、证据、置信度和报告 |
| `REQ-EVA-005` | 回归流水线 | EVA-003、EVA-004 | 测试套件、回放、并行和报告 |
| `REQ-EVA-006` | 发布门禁 | EVA-005、SEC-001 | 阈值、阻断规则、例外和回滚 |

### P1：上下文和记忆

> 当前待设计的 P1 共 13 项，正式逐项清单以 `PENDING-REQUIREMENTS.md` 为准；Harness 与可观测性属于 P0，已在正式清单中按 P0 管理。

| 编号 | 需求 | 前置依赖 | 后续交付物 |
|---|---|---|---|
| `REQ-CTX-001` | 索引实体和关系 Schema | RT-001 | ✅ 已完成详细设计（见 REQ-CTX-001-index-entities-schema.md） |
| `REQ-CTX-002` | 语言、仓库规模和基准集 | CTX-001、EVA-001 | ✅ 已完成详细设计（见 REQ-CTX-002-language-repository-scale-benchmark.md） |
| `REQ-CTX-003` | AST/LSP/依赖解析 | CTX-001、CTX-002 | ✅ 已完成详细设计（见 REQ-CTX-003-ast-lsp-dependency-parsing.md） |
| `REQ-CTX-004` | 混合检索与排序 | CTX-001、CTX-003 | ✅ 已完成详细设计（见 REQ-CTX-004-hybrid-retrieval-ranking.md） |
| `REQ-CTX-005` | 检索权限与敏感路径 | SEC-002、SEC-008 | ✅ 已完成详细设计（见 REQ-CTX-005-retrieval-permissions-sensitive-paths.md） |
| `REQ-CTX-006` | Context Selector 与预算 | CTX-004、RT-007 | Token 预算、排序、裁剪和可解释性 | ✅ v0.1-designed | 2026-10-03 |
| `REQ-CTX-007` | 增量索引一致性 | CTX-001、RT-001 | Git SHA、更新、回退和并发读取 | ✅ v0.1-designed | 2026-10-04 |
| `REQ-CTX-008` | 上下文压缩与分层加载 | CTX-006、HAR-002 | 摘要、符号级压缩和恢复规则 | 待设计 | - |
| `REQ-CTX-009` | 检索评测 | CTX-002、EVA-001 | Recall、Precision、MRR、延迟和任务正确率 | ✅ v0.1-designed | 2026-10-04 |
| `REQ-MEM-001` | Memory Schema | RT-001、SEC-008 | ✅ [已完成详细设计](./REQ-MEM-001-memory-schema.md) |
| `REQ-MEM-002` | 记忆写入审批 | MEM-001、SEC-003 | ✅ [已完成详细设计](./REQ-MEM-002-memory-write-approval.md) | v0.1-designed | 2026-10-04 |
| `REQ-MEM-003` | 记忆检索与冲突 | MEM-001、CTX-006 | 排序、冲突合并和覆盖规则 | ✅ v0.1-designed | 2026-10-05 |
| `REQ-MEM-004` | 记忆生命周期 | MEM-001、SEC-008 | 衰减、过期、删除和数据驻留 | ✅ v0.1-designed | 2026-10-05 |
| `REQ-HAR-001` | Harness 生命周期 | RT-001、SEC-003 | ✅ [已完成详细设计](./REQ-HAR-001-harness-lifecycle.md) | **v0.1-designed** | **2026-09-26** |
| `REQ-HAR-002` | Context Compaction | CTX-008、REL-004 | ✅ [已完成详细设计](./REQ-HAR-002-context-compaction.md) | **v0.1-designed** | **2026-09-27** |
| `REQ-HAR-003` | Tool Adapter | RT-001、SEC-003 | ✅ [已完成详细设计](./REQ-HAR-003-tool-adapter.md) | **v0.1-designed** | **2026-09-30** |
| `REQ-HAR-004` | Hook Registry | HAR-001、SEC-001 | ✅ [已完成详细设计](./REQ-HAR-004-hook-registry.md) | **v0.1-designed** | **2026-10-04** |
| `REQ-HAR-005` | LSP/MCP/Skill 统一路由 | HAR-003、SEC-007 | ✅ [已完成详细设计](./REQ-HAR-005-unified-routing.md) | **v0.1-designed** | **2026-10-05** |
| `REQ-HAR-006` | Harness 契约测试 | HAR-001 至 HAR-005、EVA-003 | ✅ [已完成详细设计](./REQ-HAR-006-harness-contract-testing.md) | **v0.1-designed** | **2026-10-05** |
| `REQ-OBS-001` | OpenTelemetry 语义约定 | RT-006 | ✅ [已完成详细设计](./REQ-OBS-001-opentelemetry-semantic-conventions.md) |
| `REQ-OBS-002` | Trace/Event/Evidence Schema | RT-003、RT-006 | ✅ [已完成详细设计](./REQ-OBS-002-trace-event-evidence-schema.md) |
| `REQ-OBS-003` | 指标字典 | RT-001、EVA-005 | ✅ [已完成详细设计](./REQ-OBS-003-metrics-dictionary.md) |
| `REQ-OBS-004` | 脱敏和高基数控制 | SEC-008、OBS-003 | ✅ [已完成详细设计](./REQ-OBS-004-redaction-cardinality-control.md) | **v0.1-designed** | **2026-10-05** |
| `REQ-OBS-005` | 告警和 Kill Switch 联动 | SEC-009、OBS-003 | ✅ [已完成详细设计](./REQ-OBS-005-alert-killswitch-linkage.md) | **v0.1-designed** | **2026-10-05** |
| `REQ-OBS-006` | 审计查询 API | RT-006、SEC-008 | ✅ [已完成详细设计](./REQ-OBS-006-audit-query-api.md) | **v0.1-designed** | **2026-10-05** |
| `REQ-OBS-007` | 审计留存和完整性 | SEC-008、RT-003 | ✅ [已完成详细设计](./REQ-OBS-007-audit-retention-integrity.md) | **v1.0-designed** | **2026-10-05** |
| `REQ-OBS-007` | 审计留存和完整性 | SEC-008、RT-003 | 防篡改、保留期、归档和校验、WORM存储、Merkle哈希链、Legal Hold、删除证明 | v1.0-designed |

---

## 8. 后续单需求设计的统一模板

后续每个 `REQ-*` 必须单独形成设计，不得只追加概念描述。每个需求至少包含：

1. 需求目标和用户场景；
2. 范围与非目标；
3. 前置依赖和共享坐标；
4. 核心实体、Schema 和版本；
5. 状态流或数据流；
6. 权限、安全和数据边界；
7. 失败、重试、恢复和幂等行为；
8. 与其他模块的接口；
9. MVP 范围和后续扩展；
10. 验收标准；
11. 评测数据和指标；
12. 公开依据、候选方案和最终决策；
13. 变更记录和版本号。

统一决策记录格式：

```text
需求编号：
功能点：
当前状态：
前置依赖：
候选方案：
公开证据等级：A / B / C
推荐基线：
选择理由：
适用边界：
替代方案：
安全约束：
失败与恢复：
验收指标：
目标版本：
```

证据等级定义：

- A：公开产品或官方文档明确支持的工程原则；
- B：公开论文、开源项目或可复现参考实现；
- C：内部推测、二手资料或尚未核验的概念。

---

## 9. 当前设计结论

### 9.1 已经明确并继续采用的设计

以下方向作为总体架构基线继续采用：

1. 控制平面、执行平面和证据平面分离；
2. 零信任、默认拒绝、最小权限和渐进披露；
3. Coordinator + 受限专家 Worker；
4. Worker 内部 ReAct，平台层 Workflow DAG；
5. 事件事实源 + 状态投影 + 检查点恢复；
6. Action 前后双重策略校验；
7. Artifact、Evidence 和 Trace 作为跨模块共享锚点；
8. Docker 严格隔离作为 MVP 起点，强隔离方案需基准测试；
9. 混合代码检索作为实验基线，不能未经评测宣称最优；
10. 五层评估和发布门禁；
11. 长期记忆、自动学习、多 Agent 自由协作和 WarmPool 暂不作为 MVP 强依赖。

### 9.2 尚未达到设计冻结的内容

以下内容必须在后续专项设计中完成并通过评审后，才能进入实现：

- Runtime Contract v1 的追踪、幂等和查询约束；状态迁移、事件、投影和 Checkpoint 约束已分别由 `REQ-RT-002/003/004/005` 完成详细设计；
- 安全威胁控制矩阵和沙箱最终选型；
- RetryPolicy、Recovery 决策和 Compensation；
- Context Selector、索引一致性和混合检索参数；
- Harness 生命周期和工具适配契约；
- 记忆写入、冲突、删除和权限继承（MEM-001/002/003 已完成详细设计，待 MEM-004）；
- OpenTelemetry、审计查询和数据留存；
- Golden Dataset、评分器、失败归因和发布门禁。

### 9.3 推荐后续设计顺序

```text
1. REQ-RT-001 核心实体 Schema（已完成设计，待跨模块冻结）
2. REQ-RT-002 状态机与迁移约束（已完成设计，待跨模块冻结）
3. REQ-RT-003 Event Schema 与版本策略（已完成设计，待跨模块冻结）
4. REQ-RT-004 状态投影（已完成设计，待跨模块冻结）
5. REQ-RT-005 Checkpoint Protocol（已完成设计，待跨模块冻结）
6. REQ-SEC-001 威胁模型和风险评分（已完成详细设计，待跨模块评审与冻结）
7. REQ-SEC-002 RBAC 与资源授权（已完成详细设计，待跨模块评审与冻结）
8. REQ-REL-001 Failure Taxonomy
9. REQ-REL-002 RetryPolicy
10. REQ-CTX-001 索引实体和关系 Schema（已完成详细设计，待跨模块评审与冻结）
11. REQ-CTX-002 语言、仓库规模和基准集（已完成详细设计，待跨模块评审与冻结）
12. REQ-CTX-003 AST/LSP/依赖解析（已完成详细设计，待跨模块评审与冻结）
13. REQ-EVA-001 Golden Dataset
14. 其余安全、恢复、上下文、Harness、观测、记忆和评估需求
```

这样安排的原因是：运行时契约提供所有模块共享的身份、版本、状态和事件坐标；安全和恢复需要依赖这些坐标；上下文和评估又必须引用任务、版本、权限和证据模型。

---

## 10. 本文档的维护规则

1. 新专项设计开始前，必须先登记 `REQ-*` 编号。
2. 专项文档不得重新定义 Task、Action、Trace、Revision 等共享概念。
3. 若专项设计需要改变共享契约，必须先提出 Runtime Contract 变更。
4. 每次专项设计冻结后，更新本文档的状态、版本和依赖关系。
5. 候选方案没有评测证据时，必须标记为实验基线或待验证假设。
6. 不得将“已有调研”“已有高层方案”描述为“已实现”或“已验证”。
7. 只有通过设计评审、契约测试、评测和安全门禁后，专项版本才能从 `draft` 升级为 `frozen`。

---

## 11. 来源文档

- `AI_AGENT项目方案.md`
- `优化设计思路.md`
- `docs/design-specs/README.md`
- `docs/design-specs/INDEX.md`
- `docs/design-specs/01-runtime-contracts.md`
- `docs/design-specs/02-security-threat-model.md`
- `docs/design-specs/03-failure-recovery-retry.md`
- `docs/design-specs/04-context-and-code-indexing.md`
- `docs/design-specs/05-evaluation-system.md`

公开行业参考原则来自已记录的：

- Claude Code 官方设置、子代理与安全文档；
- GitHub Copilot Cloud Agent 官方文档；
- OpenHands SDK Agent、Tool System 和持久化文档；
- LangGraph Persistence、Durable Execution 和 Interrupts 文档。

---

**文档版本**: v1.8  
**最后更新**: 2026-10-08（REQ-EVA-007 生产反馈、数据集更新和版本回滚已完成详细设计，EVA模块100%完成；总进度 60/60 = 100%，全部正式基线需求已完成详细设计）  
**维护团队**: 架构组
