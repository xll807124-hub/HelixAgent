# REQ-HAR-003: Tool Adapter（工具适配器）详细设计

> **需求编号**: REQ-HAR-003  
> **需求名称**: Tool Adapter（工具适配器）  
> **优先级**: P0  
> **状态**: v0.1-designed（待跨模块评审与冻结）  
> **创建日期**: 2026-09-30  
> **依赖**: REQ-RT-001（核心实体 Schema）、REQ-SEC-003（Policy Gateway）  
> **被依赖**: REQ-HAR-004（Hook Registry）、REQ-HAR-005（LSP/MCP/Skill 统一路由）、REQ-HAR-006（Harness 契约测试）

---

## 一、设计目标

### 1.1 核心定位

**Tool Adapter 是平台所有外部能力的统一适配层**，负责将异构工具（原生工具、MCP 工具、LSP 工具、Skill 工具）抽象为统一的内部调用契约，确保：

- 所有工具调用经过 Policy Gateway 授权
- 所有工具执行具备安全隔离、超时控制和错误分类
- 所有工具调用链路可观测、可审计、可回放

**Tool Adapter 一次注册 = 一个可治理的工具资产**，必须具备完整的版本、安全和生命周期管理。

### 1.2 设计原则

| 原则 | 说明 |
|------|------|
| **统一抽象** | 所有工具类型通过统一的 ToolDefinition 描述 |
| **最小权限** | 工具执行使用最小必要凭据和权限 |
| **可观测性** | 每次调用产出完整 Trace 和审计记录 |
| **可治理** | 工具注册、版本、废弃流程受治理 |
| **安全优先** | 高风险工具默认人工审批，沙箱隔离执行 |

---

## 二、行业调研与可借鉴设计

### 2.1 竞品研究总结

| 大厂产品 | 工具 Schema | 安全机制 | 注册发现 | 核心亮点 |
|----------|-----------|---------|---------|---------|
| **MCP**（Anthropic） | JSON Schema + name/description/inputSchema | 用户授权 + 访问控制 | 注册表 + 能力协商 | 协议标准化 |
| **LangChain** | Pydantic BaseModel + args_schema | 输入验证 + 沙箱执行 | ToolRegistry | 类型安全 |
| **OpenAI** | JSON Schema function parameters | API Key + 权限范围 | function calling 列表 | 事实标准 |
| **AutoGen** | Code Executor + Tool Call | Docker 沙箱 + 超时限制 | Tool Registry | 隔离执行 |
| **Cursor** | MCP + Native Tools | MCP 授权 + 审批流 | 多协议融合 | 多协议支持 |
| **CrewAI** | BaseTool + Role-based | Guardrails + Memory | 工具角色绑定 | 团队编排 |
| **Dify** | OpenAPI 兼容 + Plugin | 工具权限策略 | Plugin Marketplace | 插件生态 |
| **Claude Code** | MCP + Bash + File Tools | 沙箱 + 人工审批 | 内置 + MCP | 安全实践 |

**核心设计原则总结**：
1. **Schema 标准化**：JSON Schema 作为参数规范的事实标准（MCP/OpenAI/LangChain）
2. **安全分层**：RBAC + Policy Gateway + 沙箱 + 审批（MCP/Cursor/AutoGen）
3. **注册发现**：工具注册表 + 能力标签 + 版本化（MCP/LangChain/CrewAI）
4. **错误处理**：分类错误 + 重试指导（LangChain/AutoGen/REL-008）
5. **可观测性**：完整 Trace + 指标 + 审计（LangSmith/Cursor）

**参考资料**（访问日期：2026-09-30）：
- [Model Context Protocol Specification](https://modelcontextprotocol.io/specification/2026-07-28)
- [LangChain Tools Concepts](https://python.langchain.com/docs/concepts/tools/)
- [OpenAI Function Calling Guide](https://platform.openai.com/docs/guides/function-calling)
- [AutoGen Documentation](https://microsoft.github.io/autogen/0.2/docs/Getting-Started/)
- [Cursor Documentation](https://docs.cursor.com)
- [CrewAI Documentation](https://docs.crewai.com/)

---

## 三、核心实体 Schema

### 3.1 ToolDefinition（工具定义）

工具注册表中存储的工具元数据，描述工具的能力、约束、安全属性和版本信息。

**核心字段**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `tool_id` | UUID | 是 | 工具唯一标识 |
| `tool_name` | String | 是 | 工具名称（命名空间内唯一） |
| `tool_version` | SemVer | 是 | 语义版本（x.y.z） |
| `description` | String | 是 | 自然语言描述（用于模型理解） |
| `category` | ToolCategory | 是 | READ / WRITE / EXECUTE / APPROVAL |
| `input_schema` | JSONSchema | 是 | JSON Schema 定义输入参数 |
| `output_schema` | JSONSchema | 是 | JSON Schema 定义输出结构 |
| `error_schema` | ErrorSchema | 是 | 错误分类 Schema |
| `risk_level` | RiskLevel | 是 | LOW / MEDIUM / HIGH / CRITICAL |
| `requires_approval` | Boolean | 是 | 是否需要人工审批 |
| `approval_roles` | Array<String> | 否 | 审批角色列表 |
| `timeout_ms` | Integer | 是 | 超时毫秒数 |
| `retry_policy` | RetryPolicy | 否 | 重试策略 |
| `idempotency_key_template` | String | 否 | 幂等键模板 |
| `capabilities` | Array<String> | 否 | 工具能力标签 |
| `dependencies` | Array<UUID> | 否 | 依赖工具 ID |
| `sandbox_level` | SandboxLevel | 是 | 需要的沙箱级别 |
| `deprecated` | Boolean | 是 | 是否废弃 |
| `deprecation_message` | String | 否 | 废弃说明 |
| `sunset_date` | Date | 否 | 停用日期 |
| `replacement_tool_id` | UUID | 否 | 替代工具 ID |
| `owner` | String | 是 | 负责人 |
| `tags` | Array<String> | 否 | 标签 |
| `documentation_url` | URL | 否 | 文档链接 |
| `created_at` | Timestamp | 是 | 创建时间 |
| `updated_at` | Timestamp | 是 | 更新时间 |
| `schema_version` | String | 是 | Schema 版本号 |

### 3.2 ToolCallRequest（工具调用请求）

Worker 发起的工具调用请求，包含调用上下文和执行控制信息。

**核心字段**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `call_id` | UUID | 是 | 调用唯一标识 |
| `tool_id` | UUID | 是 | 工具标识 |
| `tool_version` | String | 否 | 工具版本（默认 latest） |
| `task_id` | UUID | 是 | 关联任务 |
| `workflow_id` | UUID | 是 | 关联 Workflow |
| `action_id` | UUID | 是 | 关联 Action（来自 REQ-RT-001） |
| `caller_identity` | Identity | 是 | 调用者身份 |
| `workspace_id` | UUID | 是 | 工作区标识 |
| `repository_id` | UUID | 是 | 仓库标识 |
| `arguments` | Object | 是 | 输入参数（符合 input_schema） |
| `idempotency_key` | String | 是 | 幂等键 |
| `timeout_ms` | Integer | 否 | 超时覆盖 |
| `priority` | Priority | 否 | 执行优先级 |
| `trace_context` | TraceContext | 是 | 链路追踪上下文 |
| `requested_at` | Timestamp | 是 | 请求时间 |

### 3.3 ToolCallResponse（工具调用响应）

工具执行后的响应，包含执行结果、错误信息和执行指标。

**核心字段**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `call_id` | UUID | 是 | 调用唯一标识 |
| `status` | CallStatus | 是 | SUCCESS / FAILURE / TIMEOUT / CANCELLED |
| `output` | Object | 否 | 输出结果（符合 output_schema） |
| `error` | ToolError | 否 | 错误详情（失败时） |
| `retryable` | Boolean | 否 | 是否可重试 |
| `duration_ms` | Integer | 是 | 执行时长 |
| `tokens_used` | Integer | 否 | Token 消耗 |
| `evidence_id` | UUID | 否 | 关联 Evidence ID |
| `audit_context` | AuditContext | 是 | 审计上下文 |
| `completed_at` | Timestamp | 是 | 完成时间 |

### 3.4 ToolError（工具错误）

结构化的错误信息，包含错误分类、重试指导和溯源信息。

**核心字段**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `error_code` | ErrorCode | 是 | 错误码 |
| `error_category` | ErrorCategory | 是 | NETWORK / TIMEOUT / VALIDATION / PERMISSION / RESOURCE / SYSTEM / UNKNOWN |
| `message` | String | 是 | 人类可读消息 |
| `details` | Object | 否 | 结构化错误详情 |
| `retryable` | Boolean | 是 | 是否可重试 |
| `retry_after_ms` | Integer | 否 | 建议重试等待时间 |
| `stack_trace` | String | 否 | 堆栈（调试用） |
| `request_id` | UUID | 否 | 关联请求 ID |
| `occurred_at` | Timestamp | 是 | 发生时间 |

### 3.5 ToolRegistryEntry（工具注册表条目）

工具注册表存储的条目，包含工具定义和治理信息。

**核心字段**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `registry_id` | UUID | 是 | 注册条目唯一标识 |
| `tool_id` | UUID | 是 | 工具唯一标识 |
| `tool_definition` | ToolDefinition | 是 | 完整工具定义 |
| `registration_status` | RegistrationStatus | 是 | REGISTERED / VALIDATING / APPROVED / ACTIVE / DEPRECATED / RETIRED |
| `approved_by` | String | 否 | 审批人 |
| `approved_at` | Timestamp | 否 | 审批时间 |
| `registration_source` | Source | 是 | INTERNAL / MCP / LSP / PLUGIN |
| `source_metadata` | Object | 否 | 来源元数据 |

### 3.6 枚举类型定义

#### ToolCategory（工具分类）
| 值 | 说明 | 示例 |
|----|------|------|
| `READ` | 只读工具 | 文件读取、搜索、查询 |
| `WRITE` | 写入工具 | 文件编辑、数据库写入 |
| `EXECUTE` | 执行工具 | Shell 命令、测试执行 |
| `APPROVAL` | 审批工具 | 人工审批、确认操作 |
| `NETWORK` | 网络工具 | HTTP 请求、API 调用 |
| `CUSTOM` | 自定义工具 | 业务特定工具 |

#### RiskLevel（风险等级）
| 值 | 说明 | 默认审批 |
|----|------|---------|
| `LOW` | 低风险（只读、信息查询） | 否 |
| `MEDIUM` | 中风险（可逆写入） | 可配置 |
| `HIGH` | 高风险（不可逆操作） | 是 |
| `CRITICAL` | 极高风险（生产操作） | 是 + 多重审批 |

#### CallStatus（调用状态）
| 值 | 说明 |
|----|------|
| `PENDING` | 待执行 |
| `AUTHORIZED` | 已授权 |
| `EXECUTING` | 执行中 |
| `SUCCESS` | 执行成功 |
| `FAILURE` | 执行失败 |
| `TIMEOUT` | 执行超时 |
| `CANCELLED` | 已取消 |
| `REJECTED` | 被拒绝 |

#### ErrorCategory（错误分类）
| 值 | 说明 | 重试策略 |
|----|------|---------|
| `NETWORK` | 网络错误 | 退避重试 |
| `TIMEOUT` | 超时 | 退避重试 |
| `VALIDATION` | 参数校验失败 | 不重试 |
| `PERMISSION` | 权限不足 | 不重试 |
| `RESOURCE` | 资源耗尽 | 退避重试 |
| `SYSTEM` | 系统异常 | 退避重试 |
| `UNKNOWN` | 未知错误 | 默认升级 |

#### SandboxLevel（沙箱级别）
| 值 | 说明 | 隔离强度 |
|----|------|---------|
| `NONE` | 无沙箱（不推荐） | 无 |
| `LIGHT` | 轻量沙箱 | 进程隔离 |
| `STANDARD` | 标准沙箱 | Docker |
| `STRICT` | 严格沙箱 | gVisor/Kata |
| `HARDENED` | 加固沙箱 | 多层隔离 |

#### RegistrationStatus（注册状态）
| 值 | 说明 |
|----|------|
| `REGISTERED` | 已注册（待校验） |
| `VALIDATING` | 校验中 |
| `APPROVED` | 已审批（待发布） |
| `ACTIVE` | 已发布（可调用） |
| `DEPRECATED` | 已废弃（警告） |
| `RETIRED` | 已停用（不可调用） |
| `REJECTED` | 被拒绝 |

---

## 四、工具注册与发现机制

### 4.1 工具注册流程

工具注册分为七个阶段，确保工具质量和安全合规。

**流程步骤**：

1. **开发者提交**
   - 开发者编写 ToolDefinition（JSON 格式）
   - 包含完整 Schema、风险等级、审批要求
   - 提交到工具注册服务

2. **Schema 校验**
   - 语法校验：JSON Schema 格式正确性
   - 必填字段校验：所有必填字段存在
   - 命名规范校验：符合命名空间规则
   - 版本规范校验：符合 SemVer 规范

3. **安全审核**
   - 风险等级评估：自动评估 + 人工审核
   - 权限范围审查：最小权限原则
   - 依赖审查：依赖工具安全性
   - 输入输出审查：防止数据泄露

4. **测试验证**
   - 单元测试：工具逻辑正确性
   - 集成测试：与平台集成
   - 性能测试：超时、资源消耗
   - 安全测试：注入攻击、越权

5. **审批发布**
   - 自动审批：LOW 风险 + 测试通过
   - 人工审批：MEDIUM/HIGH/CRITICAL 风险
   - 多重审批：CRITICAL 风险需要多人审批
   - 审批记录：审批人、时间、意见

6. **索引更新**
   - 工具注册表更新
   - 能力索引建立
   - 缓存预热
   - 通知订阅者

7. **持续治理**
   - 使用统计收集
   - 异常检测
   - 版本更新
   - 废弃管理

### 4.2 工具发现机制

Agent 根据任务上下文发现可用工具的过程。

**发现流程**：

1. **上下文收集**
   - 任务类型、目标、约束
   - Worker 类型、可用工具集
   - 用户权限范围

2. **候选筛选**
   - 按 category 过滤匹配类型工具
   - 按 capabilities 过滤具备能力的工具
   - 按 risk_level 过滤可接受风险的工具
   - 按 workspace_id 过滤当前工作区可用工具

3. **权限匹配**
   - 查询用户 RBAC 权限
   - 检查工具级别权限要求
   - 过滤出有权限的工具

4. **版本选择**
   - 默认选择 latest stable 版本
   - 可指定 version constraint（如 ^1.0.0）
   - 排除 deprecated 和 retired 工具

5. **能力评分**
   - 计算工具能力与任务需求的匹配度
   - 综合考虑历史成功率
   - 考虑资源消耗和延迟

6. **返回结果**
   - 返回排序后的工具列表
   - 包含 Schema 用于模型理解
   - 包含风险提示

### 4.3 工具版本管理

基于 SemVer 规范的版本管理策略。

**版本策略**：
| 版本类型 | 格式 | 说明 |
|---------|------|------|
| 主版本 | x.0.0 | 破坏性变更（Schema 不兼容） |
| 次版本 | x.y.0 | 新增功能（向后兼容） |
| 修订版本 | x.y.z | Bug 修复（向后兼容） |

**废弃流程**：
1. 标记 deprecated：工具仍可调用，但显示警告
2. 设置 sunset_date：明确停用日期
3. 指定 replacement_tool_id：提供替代工具
4. 通知使用者：发送废弃通知
5. 强制迁移：sunset_date 后强制使用替代工具

---

## 五、权限校验与 Policy Gateway 集成

### 5.1 权限校验流程

工具调用前的多层权限校验，确保最小权限原则。

**校验层级**：

| 层级 | 检查内容 | 失败处理 |
|------|---------|---------|
| L1 调用者身份 | 调用者是否有效用户/Worker | 拒绝 |
| L2 RBAC 权限 | 用户角色是否有工具权限 | 拒绝 |
| L3 资源权限 | 对目标资源（文件、仓库）有权限 | 拒绝 |
| L4 工具权限 | 工具级别权限（read/write/execute） | 拒绝 |
| L5 审批要求 | 是否需要人工审批 | 触发审批 |

### 5.2 Policy Gateway 集成

工具调用必须经过 Policy Gateway（来自 REQ-SEC-003）的授权。

**集成流程**：

1. **请求准备**
   - 组装 PolicyDecision 请求
   - 包含 user、task、tool、arguments、context

2. **Policy 决策**
   - 调用 Policy Gateway
   - 获取决策：ALLOW / DENY / REQUIRE_APPROVAL

3. **决策处理**
   - ALLOW：直接执行
   - DENY：拒绝并返回错误
   - REQUIRE_APPROVAL：发送审批请求，等待结果

4. **审批等待**
   - 异步等待审批结果
   - 超时自动拒绝（可配置）
   - 审批通过后执行
   - 审批拒绝后返回错误

5. **审计记录**
   - 记录决策详情
   - 记录审批人、时间、意见
   - 用于安全审计和合规报告

### 5.3 权限模型设计

**工具级别权限类型**：

| 权限 | 说明 | 适用工具 |
|------|------|---------|
| `tool:read` | 可调用只读工具 | READ 类 |
| `tool:write` | 可调用写入工具 | WRITE 类 |
| `tool:execute` | 可调用执行工具 | EXECUTE 类 |
| `tool:approve_low_risk` | 可审批低风险工具 | 审批者 |
| `tool:approve_high_risk` | 可审批高风险工具 | 高级审批者 |
| `tool:admin` | 工具管理权限 | 管理员 |

**权限继承**：
- 用户 → 角色 → 权限 → 工具权限
- 组织级权限 > 项目级权限 > 仓库级权限

---

## 六、沙箱执行与安全隔离

### 6.1 沙箱级别路由

根据工具的 sandbox_level 选择合适的沙箱执行环境（对接 REQ-SEC-004）。

**路由策略**：

| SandboxLevel | 适用工具 | 隔离技术 | 资源限制 |
|--------------|---------|---------|---------|
| `NONE` | 内部受信任工具 | 无 | 默认 |
| `LIGHT` | 只读查询工具 | 进程隔离 | CPU 1核/内存 1GB |
| `STANDARD` | 标准工具 | Docker | CPU 2核/内存 4GB |
| `STRICT` | 高风险工具 | gVisor | CPU 2核/内存 4GB + 系统调用过滤 |
| `HARDENED` | CRITICAL 工具 | Kata | CPU 4核/内存 8GB + 多层隔离 |

### 6.2 沙箱执行流程

工具在隔离环境中执行的全过程。

**执行步骤**：

1. **资源分配**
   - 根据 sandbox_level 申请资源
   - 检查资源配额
   - 分配 CPU、内存、磁盘、网络

2. **环境准备**
   - 挂载工作目录（只读或读写）
   - 注入环境变量
   - 配置网络（白名单）
   - 注入凭据（来自 REQ-SEC-005）

3. **执行启动**
   - 启动沙箱实例
   - 注入工具代码
   - 设置超时定时器
   - 启动观测

4. **执行监控**
   - 监控 CPU、内存使用
   - 监控网络访问
   - 监控系统调用
   - 监控文件操作

5. **结果回收**
   - 收集执行结果
   - 收集执行日志
   - 收集资源使用指标
   - 校验输出格式

6. **资源清理**
   - 撤销凭据
   - 清理文件系统
   - 销毁沙箱实例
   - 释放资源

### 6.3 凭据管理

工具执行使用最小权限凭据，由凭据代理（REQ-SEC-005）按需提供。

**凭据策略**：

| 工具类型 | 凭据范围 | 有效期 |
|---------|---------|--------|
| 只读工具 | 只读 Token | 任务期间 |
| 写入工具 | 写入 Token（限范围） | 工具调用期间 |
| 执行工具 | 执行凭据 | 沙箱生命周期 |
| 网络工具 | API Key（限域名） | 调用期间 |

---

## 七、错误处理与重试机制

### 7.1 错误分类体系

基于 REQ-REL-008 的分类体系，对工具错误进行结构化分类。

**分类维度**：

| 维度 | 取值 | 说明 |
|------|------|------|
| 类别 | NETWORK/TIMEOUT/VALIDATION/PERMISSION/RESOURCE/SYSTEM/UNKNOWN | 错误类型 |
| 可重试 | true/false | 是否可自动重试 |
| 可恢复 | true/false | 是否可通过补偿恢复 |
| 严重度 | low/medium/high/critical | 错误严重程度 |
| 升级 | true/false | 是否需要人工介入 |

### 7.2 重试决策

根据错误类型和重试策略决定是否重试。

**重试决策矩阵**：

| 错误类别 | 默认重试 | 重试策略 | 最大次数 |
|---------|---------|---------|---------|
| NETWORK | 是 | 指数退避 | 3 |
| TIMEOUT | 是 | 指数退避 | 2 |
| VALIDATION | 否 | - | 0 |
| PERMISSION | 否 | - | 0 |
| RESOURCE | 是 | 长退避 | 3 |
| SYSTEM | 是 | 指数退避 | 2 |
| UNKNOWN | 否（升级） | - | 0 |

**重试策略细节**：
- 使用 Full Jitter 退避（jitter=1.0）
- 优先使用服务端 Retry-After 提示
- 遵守全局重试预算（≤ 10%）
- 记录每次重试的审计日志

### 7.3 降级策略

重试失败后的降级处理流程。

**降级流程**：

1. **首选降级**
   - 尝试备用工具（同能力、不同实现）
   - 降级沙箱级别（如果安全允许）
   - 使用缓存结果（如果有）

2. **次选降级**
   - 分解任务为更小的子任务
   - 跳过非关键步骤
   - 返回部分结果

3. **升级处理**
   - UNKNOWN 错误默认升级
   - CRITICAL 失败强制升级
   - 重试次数耗尽升级
   - 触发人工审批或干预

---

## 八、可观测性与审计

### 8.1 核心指标

工具调用全链路的关键指标。

**指标清单**：

| 指标 | 类型 | 标签 | 说明 |
|------|------|------|------|
| `tool_call_total` | counter | tool_name, status | 总调用次数 |
| `tool_call_success_rate` | gauge | tool_name | 调用成功率 |
| `tool_call_latency_p95` | histogram | tool_name | 调用延迟 p95 |
| `tool_call_timeout_rate` | gauge | tool_name | 超时率 |
| `tool_call_error_rate` | gauge | tool_name, error_category | 错误率 |
| `tool_approval_latency` | histogram | tool_name | 审批延迟 |
| `tool_discovery_latency` | histogram | - | 发现延迟 |
| `tool_active_count` | gauge | category | 当前活跃工具数 |

**性能目标**：

| 指标 | 目标 | 说明 |
|------|------|------|
| 工具发现延迟 | < 50ms (p95) | 缓存命中 |
| 权限校验延迟 | < 20ms (p95) | RBAC 缓存 |
| Policy Gateway 延迟 | < 100ms (p95) | 不含审批等待 |
| 工具执行延迟 | 按工具声明 | 工具自身 |
| 整体调用延迟 | < 200ms + 执行 | 不含执行 |

### 8.2 告警规则

异常情况下的告警策略。

**告警规则**：

| 规则 | 条件 | 严重度 | 通知方式 |
|------|------|--------|---------|
| 调用成功率低 | success_rate < 99% | warning | 邮件 |
| 调用成功率极低 | success_rate < 95% | critical | PagerDuty |
| 超时率高 | timeout_rate > 1% | warning | 邮件 |
| 高风险工具异常 | 高风险工具调用异常 | critical | PagerDuty |
| 审批积压 | pending_approvals > 10 | warning | 邮件 |
| 未授权尝试 | 权限拒绝率 > 5% | critical | 安全告警 |

### 8.3 链路追踪

每次工具调用都纳入 OpenTelemetry Trace（对接 REQ-OBS-001）。

**追踪 Span**：

| Span 名称 | 属性 | 说明 |
|-----------|------|------|
| `tool.discover` | tool_name, capabilities | 工具发现 |
| `tool.authorize` | tool_name, decision | 权限校验 |
| `tool.policy` | tool_name, decision | Policy 决策 |
| `tool.execute` | tool_name, sandbox_level | 工具执行 |
| `tool.observe` | tool_name, status | 结果观测 |

**追踪字段**：

- `trace_id`：全局链路追踪 ID
- `call_id`：单次调用标识
- `tool_id` + `tool_version`：工具版本
- `task_id` + `action_id`：关联任务
- `decision_id`：Policy 决策 ID

### 8.4 审计日志

完整的工具调用审计日志，支持合规和安全审计。

**审计内容**：

| 字段 | 说明 |
|------|------|
| 调用者身份 | 用户、Worker、IP |
| 工具标识 | tool_id、tool_version |
| 调用参数 | 完整 arguments（脱敏后） |
| 执行结果 | output 或 error |
| 执行环境 | sandbox_id、hostname |
| 凭据使用 | 凭据 ID、范围 |
| 审批信息 | 审批人、时间、意见 |
| 链路追踪 | trace_id、span_id |

**审计保留期**：
- 普通审计：30 天热存储 + 180 天冷存储
- 安全审计：1 年热存储 + 7 年冷存储
- 合规审计：根据合规要求确定

---

## 九、人类在环（HITL）设计

### 9.1 触发场景

需要人工介入的工具调用场景。

**强制审批场景**：

| 场景 | 触发条件 | 默认行为 |
|------|---------|---------|
| CRITICAL 风险 | risk_level = CRITICAL | 必须审批 |
| 新工具首次调用 | 该工具在本项目首次调用 | 必须审批 |
| 异常调用模式 | 调用参数异常（如大批量删除） | 必须审批 |
| 跨项目调用 | 调用超出项目边界 | 必须审批 |
| 敏感资源 | 操作敏感文件/数据 | 必须审批 |

### 9.2 审批界面

为审批者提供清晰的工具调用信息。

**审批界面要素**：

| 要素 | 说明 |
|------|------|
| 工具名称 | tool_name + version |
| 工具描述 | description |
| 调用参数 | 完整 arguments（人类可读格式） |
| 风险等级 | risk_level + 风险解释 |
| 预期影响 | 调用结果的预期影响 |
| 调用者 | 用户名、角色、历史 |
| 历史调用 | 该工具近期调用记录 |
| 审批选项 | 批准/拒绝/修改参数 |

### 9.3 审批策略

可配置的审批策略，支持自动化和灵活性。

**策略配置**：

| 策略项 | 可选值 | 默认 |
|--------|--------|------|
| CRITICAL 审批人数 | 1/2/M (多人) | 2 |
| 审批超时 | 5min/15min/1h/24h | 15min |
| 超时行为 | 自动拒绝/自动批准/升级 | 自动拒绝 |
| 批量审批 | 启用/禁用 | 禁用 |
| 信任用户免审批 | 白名单 | 仅内部工具 |

### 9.4 通知机制

审批过程中的通知策略。

**通知场景**：

| 场景 | 通知对象 | 通知方式 |
|------|---------|---------|
| 审批请求 | 审批者 | 站内信 + 邮件 |
| 审批超时 | 审批者 + 任务创建者 | 邮件 |
| 审批通过 | 任务执行者 | 站内信 |
| 审批拒绝 | 任务执行者 + 创建者 | 站内信 + 邮件 |
| 异常调用 | 安全团队 | PagerDuty |

---

## 十、处理流程

### 10.1 工具调用主流程

从 Agent 意图识别到结果返回的完整流程。

**步骤说明**：

1. **意图识别**
   - Agent 基于当前任务识别需要调用的工具
   - 解析目标工具的能力需求

2. **工具发现**
   - 根据上下文筛选可用工具
   - 返回工具列表及 Schema

3. **Schema 注入**
   - 将工具 Schema 注入模型上下文
   - 模型根据 Schema 生成参数

4. **权限校验（L1-L4）**
   - 调用者身份验证
   - RBAC 权限检查
   - 资源权限检查
   - 工具权限检查

5. **Policy 决策**
   - 调用 Policy Gateway
   - 获取决策结果

6. **审批处理（如需要）**
   - 发送审批请求
   - 等待审批结果
   - 超时处理

7. **沙箱准备**
   - 根据 sandbox_level 分配资源
   - 准备执行环境

8. **工具执行**
   - 注入凭据和参数
   - 设置超时控制
   - 启动执行
   - 监控执行

9. **结果处理**
   - 校验输出格式
   - 分类错误（如失败）
   - 生成 Evidence

10. **审计记录**
    - 记录完整调用链路
    - 更新工具使用统计
    - 触发告警（如异常）

11. **返回结果**
    - 返回给调用者
    - 追加事件到事件流

### 10.2 异步执行流程

对于长耗时工具的异步执行支持。

**异步模式**：

| 模式 | 说明 | 适用场景 |
|------|------|---------|
| 同步执行 | 等待结果返回 | 短耗时工具 |
| 异步执行 | 立即返回，后续查询 | 长耗时工具 |
| 流式执行 | 流式返回结果 | 大输出工具 |
| 回调执行 | 完成时回调 | 集成外部系统 |

**异步流程**：

1. 提交异步任务
2. 立即返回 task_handle
3. 后台执行工具
4. 完成后发送通知
5. 通过 task_handle 查询结果
6. 结果保留期（可配置）

### 10.3 批量调用流程

多个工具调用的批量执行优化。

**批量场景**：
- 多文件读取
- 多测试执行
- 多 API 查询

**批量策略**：

| 策略 | 说明 | 适用 |
|------|------|------|
| 串行执行 | 按顺序执行 | 有依赖关系 |
| 并行执行 | 同时执行 | 无依赖关系 |
| 分批执行 | 分批并行 | 资源受限 |
| 流式执行 | 流式返回 | 大批量 |

---

## 十一、状态管理

### 11.1 工具生命周期状态机

工具从注册到废弃的全生命周期。

**状态定义**：

| 状态 | 说明 | 可执行 |
|------|------|--------|
| REGISTERED | 已注册（待校验） | 否 |
| VALIDATING | 校验中 | 否 |
| APPROVED | 已审批（待发布） | 否 |
| ACTIVE | 已发布 | 是 |
| DEPRECATED | 已废弃 | 是（警告） |
| RETIRED | 已停用 | 否 |
| REJECTED | 被拒绝 | 否 |

**状态迁移**：

| 当前状态 | 触发事件 | 目标状态 | 前置条件 |
|---------|---------|---------|---------|
| REGISTERED | validate() | VALIDATING | Schema 提交 |
| VALIDATING | validate_pass() | APPROVED | 校验通过 |
| VALIDATING | validate_fail() | REJECTED | 校验失败 |
| APPROVED | publish() | ACTIVE | 审批通过 |
| ACTIVE | deprecate() | DEPRECATED | 标记废弃 |
| DEPRECATED | retire() | RETIRED | 到达 sunset_date |
| ACTIVE | reject() | REJECTED | 安全事件 |

### 11.2 调用生命周期状态机

单次工具调用的状态流转。

**状态定义**：

| 状态 | 说明 |
|------|------|
| PENDING | 待执行 |
| AUTHORIZED | 已授权 |
| EXECUTING | 执行中 |
| SUCCESS | 执行成功 |
| FAILURE | 执行失败 |
| TIMEOUT | 执行超时 |
| CANCELLED | 已取消 |
| REJECTED | 被拒绝 |

**状态迁移**：

| 当前状态 | 触发事件 | 目标状态 |
|---------|---------|---------|
| PENDING | authorize() | AUTHORIZED |
| PENDING | reject() | REJECTED |
| AUTHORIZED | execute() | EXECUTING |
| AUTHORIZED | timeout() | TIMEOUT |
| EXECUTING | complete() | SUCCESS/FAILURE |
| EXECUTING | timeout() | TIMEOUT |
| EXECUTING | cancel() | CANCELLED |
| * | retry() | PENDING（重试） |

### 11.3 数据存储

工具相关数据的存储策略。

| 数据类型 | 存储 | 保留期 | 说明 |
|---------|------|--------|------|
| 工具定义 | PostgreSQL | 永久 | 工具注册表 |
| 调用日志 | Event Store | 30天热 + 180天冷 | 调用记录 |
| 执行指标 | 时序数据库 | 90天 | Prometheus/InfluxDB |
| 工具缓存 | Redis | 24小时 | 热门工具 Schema |
| 审计日志 | WORM 存储 | 7年 | 合规要求 |
| 审批记录 | PostgreSQL | 3年 | 审批历史 |

---

## 十二、接口设计

### 12.1 工具注册接口

**接口描述**：注册新工具到工具注册表

**请求**：
- 工具定义（ToolDefinition）
- 注册来源（INTERNAL/MCP/LSP/PLUGIN）

**响应**：
- 注册结果（成功/失败）
- 工具 ID
- 注册状态

### 12.2 工具发现接口

**接口描述**：根据上下文发现可用工具

**请求**：
- 任务上下文（category、capabilities、risk_level）
- 用户权限
- 工作区信息

**响应**：
- 工具列表（ToolDefinition 列表）
- 排序结果

### 12.3 工具调用接口

**接口描述**：执行工具调用

**请求**：
- 调用请求（ToolCallRequest）
- 包含参数、幂等键、超时

**响应**：
- 调用响应（ToolCallResponse）
- 包含结果、错误、指标

### 12.4 工具审批接口

**接口描述**：审批工具调用

**请求**：
- 审批决策（批准/拒绝/修改）
- 审批意见

**响应**：
- 审批结果

### 12.5 上游依赖

| 依赖模块 | 依赖内容 | 接口 |
|----------|---------|------|
| REQ-RT-001 | Action、Evidence Schema | ToolCall → Action 关联 |
| REQ-RT-003 | 事件流 | 调用事件写入 |
| REQ-RT-006 | Trace 传播 | trace_id 注入 |
| REQ-RT-007 | 幂等键 | idempotency_key |
| REQ-SEC-002 | RBAC | 权限校验 |
| REQ-SEC-003 | Policy Gateway | 审批决策 |
| REQ-SEC-004 | 沙箱隔离 | 执行环境 |
| REQ-SEC-005 | 凭据代理 | 工具凭据 |
| REQ-REL-008 | 错误分类 | 错误分类复用 |

### 12.6 下游接口

| 接口 | 下游消费者 | 说明 |
|------|----------|------|
| ToolRegistry API | HAR-004、HAR-005 | 工具注册发现 |
| ToolExecutor API | Worker Runtime | 工具执行 |
| ToolAuditor API | OBS-001~007 | 审计观测 |

---

## 十三、验收标准

### 13.1 功能验收

| ID | 验收标准 | 验证方法 |
|----|---------|---------|
| HAR-003-F01 | 所有工具必须声明 input_schema 和 output_schema | Schema 校验测试 |
| HAR-003-F02 | 工具调用前必须通过权限校验 | 权限边界测试 |
| HAR-003-F03 | 高风险工具必须经过 Policy Gateway 审批 | 审批流程测试 |
| HAR-003-F04 | 工具执行必须携带幂等键 | 幂等性测试 |
| HAR-003-F05 | 工具错误必须分类并记录 | 错误分类测试 |
| HAR-003-F06 | 工具调用链路必须可追踪 | Trace 验证测试 |
| HAR-003-F07 | 工具发现延迟 < 50ms (p95) | 性能测试 |
| HAR-003-F08 | 支持异步工具调用 | 异步流程测试 |

### 13.2 隔离与安全验收

| ID | 验收标准 | 验证方法 |
|----|---------|---------|
| HAR-003-I01 | 危险工具必须在沙箱中执行 | 隔离验证测试 |
| HAR-003-I02 | 工具凭据必须遵循最小权限 | 凭据审计测试 |
| HAR-003-I03 | 敏感输出必须在返回前脱敏 | 安全测试 |
| HAR-003-I04 | 工具调用必须经过 Policy Gateway | 流程测试 |
| HAR-003-I05 | 未授权访问必须被拒绝 | 越权测试 |

### 13.3 版本与兼容验收

| ID | 验收标准 | 验证方法 |
|----|---------|---------|
| HAR-003-S01 | 工具 Schema 变更必须版本化 | 版本管理测试 |
| HAR-003-S02 | 废弃工具必须显示替代建议 | 降级测试 |
| HAR-003-S03 | 向后兼容性必须保证 | 兼容性测试 |

---

## 十四、与原设计对比

| 维度 | 原设计 | 修改后设计 | 改进点 | 对标依据 |
|------|-------|-----------|--------|---------|
| **Schema 完整性** | 仅输入、输出、错误、风险、超时 | 完整的 ToolDefinition（27+ 字段），含版本、依赖、能力、审批 | 覆盖完整生命周期 | MCP/LangChain |
| **注册机制** | 未定义 | 工具注册→校验→审核→发布 7 阶段流程 | 可治理 | MCP 注册表 |
| **安全机制** | 仅风险标注 | RBAC + Policy + 沙箱 + 审计 5 层防护 | 多层防护 | MCP/Cursor |
| **超时控制** | 笼统超时 | 工具声明超时 + 调用覆盖 + 自适应 | 可预测 | AutoGen |
| **错误处理** | 泛化错误 | 7 类错误 + 重试指导 + 降级策略 | 可操作 | LangChain/REL-008 |
| **幂等性** | 未提及 | 幂等键 + 版本化 | 可重试 | RT-007 |
| **观测性** | 未提及 | 8 指标 + 6 告警 + Trace + 审计 | 可追踪 | MCP/LangSmith |
| **版本化** | 未提及 | SemVer + 废弃流程 + 替代工具 | 可演进 | SemVer 标准 |
| **HITL** | 未提及 | 5 场景强制审批 + 可配置策略 | 可治理 | Cursor/Claude Code |

---

## 十五、设计理由总结

**为什么这样改更符合行业标杆**：

1. **MCP 兼容性**：采用 JSON Schema 格式，与 MCP 协议对齐，便于未来集成
2. **LangChain 类型安全**：使用结构化 Schema，支持输入输出验证
3. **AutoGen 隔离执行**：沙箱分级执行，防止危险操作
4. **Cursor 多协议融合**：支持工具注册、发现、版本化全流程
5. **Claude Code 安全实践**：HITL + 审批 + 沙箱多层防护

**解决了哪些问题**：

1. 工具定义不统一 → 标准化 Schema（27+ 字段）
2. 权限控制缺失 → RBAC + Policy Gateway（5 层校验）
3. 执行不安全 → 沙箱分级（5 个级别）
4. 错误处理混乱 → 分类 + 指导（7 类错误）
5. 不可观测 → 完整 Trace + 指标（8 核心指标）
6. 版本不兼容 → SemVer + 废弃策略
7. 人工介入缺失 → HITL 5 场景强制审批

**带来的收益**：

- **开发者**：统一的工具开发规范（27+ 字段标准 Schema），降低接入成本
- **安全**：多层防护（RBAC + Policy + 沙箱 + 审计），满足合规要求
- **运维**：完整的可观测性（8 指标 + 6 告警），快速定位问题
- **用户**：透明的执行（审批 + 通知），增强信任

---

## 十六、对其它待办的影响

**下游影响**：

| 模块 | 影响 | 同步要求 |
|------|------|---------|
| REQ-HAR-004 Hook Registry | Hook 需要挂钩到工具调用生命周期 | 接口对齐 |
| REQ-HAR-005 统一路由 | 工具发现依赖 ToolRegistry | 接口对齐 |
| REQ-HAR-006 契约测试 | 需要测试工具适配契约 | 测试规范 |

**上游依赖确认**：

| 模块 | 当前状态 | 影响 |
|------|---------|------|
| REQ-RT-001 | v0.2-designed | Action 与 ToolCall 关联已定义 |
| REQ-SEC-003 | v0.1-designed | Policy Gateway 可集成 |

**潜在风险与缓解**：

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| Schema 变更影响已有工具 | 中 | 版本化 + 兼容性检查 |
| 审批流影响执行延迟 | 中 | 异步审批 + 缓存决策 |
| 沙箱资源不足 | 高 | 资源预留 + 降级策略 |
| 工具注册泛滥 | 中 | 审批流程 + 配额限制 |

---

## 十七、版本与演进

### 17.1 v1.0 基线（MVP）

**功能范围**：
- 工具 Schema 标准化（ToolDefinition）
- 工具注册与发现机制
- 权限校验 + Policy Gateway 集成
- 基础沙箱执行（STANDARD 级别）
- 错误分类与重试
- 基础可观测性

**不包含**：
- 高级沙箱（STRICT/HARDENED）
- 流式执行
- 异步回调
- 工具市场

### 17.2 v1.1 增强

**新增功能**：
- 多级沙箱（STRICT/HARDENED）
- 流式执行支持
- 工具使用统计与推荐
- 工具组合编排

### 17.3 v2.0 高级

**新增功能**：
- 工具市场（Marketplace）
- AI 辅助工具发现
- 动态工具生成
- 跨平台工具同步

---

## 十八、实施计划

### Phase 1：核心机制（2 周）

- 工具 Schema 标准化
- 工具注册表实现
- 工具发现机制
- 基础权限校验

### Phase 2：安全集成（2 周）

- Policy Gateway 集成
- 沙箱执行实现
- 审批流程
- 凭据管理

### Phase 3：错误与观测（1 周）

- 错误分类
- 重试与降级
- 指标与告警
- 链路追踪

### Phase 4：验收与文档（1 周）

- 执行验收测试
- 性能基准测试
- 完善用户文档

---

## 十九、参考资料

以下为公开来源，访问日期均为 2026-09-30：

- **MCP**: [Model Context Protocol Specification](https://modelcontextprotocol.io/specification/2026-07-28)
- **LangChain**: [Tools Concepts](https://python.langchain.com/docs/concepts/tools/)
- **OpenAI**: [Function Calling Guide](https://platform.openai.com/docs/guides/function-calling)
- **AutoGen**: [AutoGen Documentation](https://microsoft.github.io/autogen/0.2/docs/Getting-Started/)
- **Cursor**: [Cursor Documentation](https://docs.cursor.com)
- **CrewAI**: [CrewAI Documentation](https://docs.crewai.com/)
- **Claude Code**: [Claude Code Security](https://docs.claude.com/claude-code-security)

---

## 二十、决策记录

| 决策项 | 决策 | 依据 |
|-------|------|------|
| Schema 格式 | JSON Schema | MCP/OpenAI 事实标准 |
| 安全分层 | RBAC + Policy + 沙箱 + 审计 | MCP/Cursor 最佳实践 |
| 沙箱级别 | 5 级（NONE/LIGHT/STANDARD/STRICT/HARDENED） | REQ-SEC-004 设计 |
| 错误分类 | 7 类（NETWORK/TIMEOUT/...） | REQ-REL-008 设计 |
| 版本管理 | SemVer | 行业标准 |
| HITL 触发 | 5 场景（CRITICAL/新工具/异常/跨项目/敏感） | Claude Code 实践 |

---

**文档创建时间**：2026-09-30  
**维护团队**：架构组  
**状态**：v0.1-designed，待跨模块评审与冻结
