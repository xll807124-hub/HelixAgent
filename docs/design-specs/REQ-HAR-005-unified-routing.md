# REQ-HAR-005: LSP/MCP/Skill 统一路由

> **需求编号**: REQ-HAR-005  
> **需求名称**: LSP/MCP/Skill 统一路由  
> **优先级**: P0  
> **状态**: v0.1-designed（待跨模块评审与冻结）  
> **创建日期**: 2026-10-05  
> **依赖**: REQ-HAR-003（Tool Adapter）、REQ-SEC-007（MCP 连接器治理）  
> **被依赖**: REQ-HAR-006（Harness 契约测试）

---

## 一、设计目标

### 1.1 核心定位

**统一路由层是 Harness 跨协议能力发现与调用的核心抽象**，负责将 LSP（Language Server Protocol）、MCP（Model Context Protocol）、Skill（Agent Skills）三层异构协议抽象为统一的能力视图，确保：

- 所有能力发现经过权限裁剪和 Policy 预检
- 所有工具调用路由到正确的协议适配器并执行 PEP 拦截
- 所有路由决策可追溯、可审计、可回放

**统一路由层是多 Worker 实例共享的能力中枢**，为 HAR-006 契约测试提供测试桩基础。

### 1.2 设计原则

| 原则 | 说明 |
|------|------|
| **协议无关** | 上层 Worker 不感知 LSP/MCP/Skill 协议差异 |
| **发现时裁剪** | 权限过滤在发现阶段完成，减少暴露面 |
| **延迟加载** | Token 预算驱动的按需工具加载 |
| **确定性仲裁** | 同名工具冲突按优先级规则解决 |
| **PEP 前置** | 所有执行前必须经过 Policy 拦截点 |

---

## 二、行业调研与可借鉴设计

### 2.1 竞品研究总结

| 大厂产品 | 发现机制 | 路由策略 | 延迟加载 | 核心亮点 |
|----------|----------|----------|----------|----------|
| **MCP（Anthropic）** | tools/list + listChanged | Client 端路由到 Server | 无 | per-request 权限裁剪 |
| **Cursor** | Enterprise/Team/Project/User/Plugin 多层 | MCP Policy 规则匹配 | 无 | 多层策略叠加 |
| **LangGraph** | MultiServerMCPClient | ToolNode + tools_condition | bigtool 语义检索 | Picker Node 分离 |
| **OpenAI Agents SDK** | MCPServerManager | Handoffs vs Agents as Tools | defer_loading=True | 多路由模式 |
| **Kimi Code** | deferred + manifest | select_tools 内置工具 | 四层作用域 | 同轮次多次加载 |
| **DeepSeekCode** | 统一执行路径 | Permission→Policy→Hook→Execution | Remote Schema 缓存 | MCP/ACP 双桥 |

**核心设计原则总结**：
1. **协议抽象**：Client-Server 分离的发现与执行模型（MCP）
2. **权限裁剪**：发现时即过滤无权限工具（Cursor/MCP）
3. **延迟加载**：语义检索 + Token 预算控制（LangGraph/Kimi）
4. **统一路径**：Permission→Policy→Hook→Execution 串联（DeepSeekCode）
5. **多路由模式**：Handoffs（转交控制）vs Agents as Tools（保留控制）（OpenAI）

**参考资料**（访问日期：2026-10-04）：
- [MCP Specification](https://modelcontextprotocol.io/specification)
- [Cursor MCP Docs](https://cursor.com/docs/mcp)
- [LangGraph MCP Adapters](https://github.com/langchain-ai/langgraph-mcp)
- [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/)
- [Kimi Code Docs](https://www.kimi.com/code/docs/en/kimi-code-cli/)
- [DeepSeekCode Architecture](https://github.com/willamhou/DeepSeekCode)

---

## 三、核心实体 Schema

### 3.1 CapabilityItem（能力项）

协议无关的能力抽象，统一表示 LSP/MCP/Skill 三层的能力。

**核心字段**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `capability_id` | UUID | 是 | 能力唯一标识 |
| `name` | String | 是 | 能力名称 |
| `scoped_name` | String | 是 | 作用域名称（格式：`<protocol>__<source>__<name>`） |
| `description` | String | 是 | 自然语言描述（用于模型理解） |
| `source_protocol` | Protocol | 是 | LSP / MCP / SKILL |
| `source_id` | String | 是 | 来源标识（Server ID / Skill 文件路径） |
| `schema` | JSONSchema | 是 | 输入输出 Schema |
| `risk_level` | RiskLevel | 是 | LOW / MEDIUM / HIGH / CRITICAL |
| `requires_approval` | Boolean | 是 | 是否需要人工审批 |
| `visibility` | Visibility | 是 | VISIBLE / DEFERRED / HIDDEN |
| `priority` | Integer | 是 | 优先级（用于冲突仲裁） |
| `version` | SemVer | 是 | 版本号 |
| `registration_time` | Timestamp | 是 | 注册时间 |
| `schema_hash` | String | 是 | Schema 摘要（用于变更检测） |
| `required_permissions` | Array<String> | 否 | 所需权限列表 |
| `token_estimate` | Integer | 否 | Schema Token 估算 |
| `tags` | Array<String> | 否 | 标签（用于分类和检索） |

### 3.2 DiscoveryRequest（发现请求）

Worker 发起的能力发现请求。

**核心字段**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `request_id` | UUID | 是 | 请求唯一标识 |
| `worker_id` | UUID | 是 | Worker 标识 |
| `task_id` | UUID | 是 | 关联任务 |
| `user_id` | UUID | 是 | 用户标识 |
| `organization_id` | UUID | 是 | 组织标识 |
| `context` | Object | 是 | 任务上下文（描述、语言、资源） |
| `capability_requirements` | Array<String> | 否 | 能力需求（如 "file_read", "git_diff"） |
| `token_budget` | Integer | 否 | 可用 Token 预算 |
| `prefer_deferred` | Boolean | 否 | 是否优先延迟加载 |
| `trace_context` | TraceContext | 是 | 链路追踪上下文 |

### 3.3 DiscoveryResponse（发现响应）

**核心字段**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `request_id` | UUID | 是 | 请求唯一标识 |
| `capabilities` | Array<CapabilityItem> | 是 | 可见能力清单 |
| `deferred_capabilities` | Array<CapabilityItem> | 否 | 延迟加载能力清单 |
| `total_tokens_estimate` | Integer | 是 | 能力清单总 Token 估算 |
| `pruned_count` | Integer | 是 | 裁剪的能力数量 |
| `pruning_reasons` | Map<UUID, String> | 否 | 裁剪原因（capability_id → reason） |
| `cache_ttl` | Integer | 是 | 缓存 TTL（秒） |
| `refresh_token` | String | 否 | 增量刷新令牌 |

### 3.4 ToolCallRouteRequest（工具调用路由请求）

**核心字段**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `call_id` | UUID | 是 | 调用唯一标识 |
| `tool_name` | String | 是 | 工具名称（scoped_name） |
| `arguments` | Object | 是 | 调用参数 |
| `task_id` | UUID | 是 | 关联任务 |
| `action_id` | UUID | 是 | 关联 Action |
| `caller_identity` | Identity | 是 | 调用者身份 |
| `timeout_ms` | Integer | 否 | 超时覆盖 |
| `trace_context` | TraceContext | 是 | 链路追踪上下文 |

### 3.5 RoutingDecision（路由决策）

**核心字段**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `call_id` | UUID | 是 | 调用唯一标识 |
| `status` | RoutingStatus | 是 | ROUTED / DENIED / PENDING_APPROVAL / ERROR |
| `target_protocol` | Protocol | 否 | 目标协议（ROUTED 时） |
| `target_adapter` | String | 否 | 目标适配器 ID |
| `adapted_arguments` | Object | 否 | 适配后的参数 |
| `denial_reason` | String | 否 | 拒绝原因（DENIED 时） |
| `approval_id` | UUID | 否 | 审批 ID（PENDING_APPROVAL 时） |
| `execution_result` | Object | 否 | 执行结果（完成后） |

### 3.6 枚举类型定义

#### Protocol（协议类型）
| 值 | 说明 |
|----|------|
| `LSP` | Language Server Protocol |
| `MCP` | Model Context Protocol |
| `SKILL` | Agent Skills |

#### Visibility（可见性）
| 值 | 说明 |
|----|------|
| `VISIBLE` | 立即可见 |
| `DEFERRED` | 延迟加载 |
| `HIDDEN` | 隐藏（权限不足或策略拒绝） |

#### RoutingStatus（路由状态）
| 值 | 说明 |
|----|------|
| `ROUTED` | 已路由到目标适配器 |
| `DENIED` | 被拒绝 |
| `PENDING_APPROVAL` | 等待审批 |
| `ERROR` | 路由错误 |

---

## 四、能力发现与路由机制

### 4.1 统一发现流程（12 步）

```
Step 1: 路由请求接收
  - Worker Runtime 发起能力发现请求
  - 携带：worker_id、task_id、context、capability_requirements

Step 2: 协议源聚合（并行）
  - 从 LSP Registry 获取可用 LSP 能力
  - 从 MCP Registry 获取可用 MCP Server 工具清单（SEC-007）
  - 从 Skill Registry 获取可用 Skills（HAR-004）

Step 3: 权限预检（发现时裁剪）
  - 查询用户 RBAC 权限（SEC-002）
  - 查询组织 MCP Policy（SEC-007）
  - 过滤无权限的 Server/工具/Skill

Step 4: 策略预检
  - 调用 Policy Gateway 获取发现策略（SEC-003）
  - ALLOW：继续；DENY：拒绝并返回空清单；REQUIRE_APPROVAL：触发审批

Step 5: 延迟加载评估
  - 计算当前上下文 Token 消耗
  - 对比 Token 预算（CTX-006）
  - 如果 Token 不足，触发延迟加载决策

Step 6: 语义检索（可选）
  - 如果启用延迟加载，对候选工具进行语义搜索
  - 使用 FAISS/向量检索选择 top-N 相关工具
  - 限制因素：Token 预算、工具数量上限、用户偏好

Step 7: 能力聚合
  - 将 LSP/MCP/Skill 能力统一格式化为 CapabilityItem
  - 统一字段：name、description、schema、source_protocol、source_id、risk_level

Step 8: 冲突仲裁
  - 检测同名工具（不同协议提供相同功能）
  - 应用冲突仲裁规则：优先级（protocol_priority）> 版本 > 注册时间
  - 生成无冲突能力清单

Step 9: Schema 规范化
  - 将 LSP/MCP/Skill Schema 统一转换为 ToolDefinition（HAR-003）
  - 验证 Schema 签名（SEC-007）
  - 规范化工具命名：<protocol>__<source>__<name>

Step 10: 响应封装
  - 封装能力清单到路由响应
  - 携带：tools、skills、deferred_tools、deferred_skills
  - 包含：meta（Token 消耗预估、缓存 TTL）

Step 11: PEP 拦截点注册
  - 为每个暴露的工具注册 PEP 拦截点
  - 拦截点关联：Policy 版本、审批要求、执行约束

Step 12: 响应返回
  - 返回裁剪后的能力清单给 Worker
  - 同时更新 OBS 指标（发现延迟、裁剪率）
```

### 4.2 工具调用路由流程（7 步）

```
Step 1: 调用请求接收
  - 模型返回 tool_call（name + arguments）
  - 路由层解析工具名：<protocol>__<source>__<name>

Step 2: 协议路由
  - 从工具名提取 protocol 和 source
  - 路由到对应协议适配器：LSP Adapter / MCP Adapter / Skill Adapter

Step 3: 执行前检查
  - PEP 拦截点执行 Policy 检查（SEC-003）
  - 权限复核（SEC-002）
  - 状态验证（Server 在线、Schema 未变更）

Step 4: 参数转换
  - 协议适配器将通用参数转换为目标协议格式
  - LSP：转换为 LSP 方法调用
  - MCP：转换为 tools/call 请求
  - Skill：转换为 SKILL.md 执行上下文

Step 5: 执行委托
  - 委托给 HAR-003 Tool Adapter 执行
  - Tool Adapter 调用对应协议适配器

Step 6: 结果处理
  - 协议适配器将结果转换为统一格式
  - 进行 Schema 验证和安全扫描（SEC-006）
  - 生成 Evidence（RT-001）

Step 7: 响应返回
  - 返回统一格式的工具结果
  - 更新 OBS 指标
```

### 4.3 延迟加载机制

**触发条件**：
- Token 消耗 > 可用预算 × 70%（DEFER_THRESHOLD）
- 工具数量 > 配置的最大即时加载数（默认 20）
- 用户显式请求延迟加载（prefer_deferred=true）

**加载策略**：
- **语义检索**：使用向量检索或 BM25 选择 top-N 相关工具
- **分类加载**：按 tags 和 category 分组延迟加载
- **按需加载**：模型调用内置 `select_tools` 工具触发加载

**加载粒度**：
- Server 级别：加载整个 MCP Server 的所有工具
- Namespace 级别：加载 tool_namespace 内的工具组
- 工具级别：加载单个工具 Schema

### 4.4 冲突仲裁规则

**优先级计算**：

```
priority_score = protocol_priority × 10000 + version × 100 - days_since_registration

其中：
- protocol_priority: LSP=100, MCP=80, SKILL=60
- version: SemVer major.minor.patch 转换为整数
- days_since_registration: 注册时间距今天数
```

**仲裁策略**：
| 冲突类型 | 仲裁规则 | 示例 |
|----------|----------|------|
| 同名不同协议 | 协议优先级高者胜出 | LSP `format` > MCP `format` |
| 同协议不同版本 | 版本高者胜出 | v2.1.0 > v1.9.5 |
| 同协议同版本 | 注册时间早者胜出 | 2024-01-01 > 2024-12-01 |
| 无法仲裁 | 保留所有，由模型选择 | 添加协议前缀区分 |

**冲突日志**：
- 所有冲突必须记录到审计日志
- 包含：冲突工具列表、仲裁结果、选择原因
- 每日汇总冲突统计并告警

---

## 五、协议适配器设计

### 5.1 LSP Adapter

**职责**：
- 连接 Language Server（如 Pylance、TypeScript Language Server）
- 将 LSP 方法映射为能力项（textDocument/formatting → format_code）
- 处理 LSP 诊断和补全

**能力映射**：
| LSP 方法 | 能力名称 | 说明 |
|----------|----------|------|
| `textDocument/formatting` | `lsp__<server>__format_code` | 代码格式化 |
| `textDocument/definition` | `lsp__<server>__go_to_definition` | 跳转定义 |
| `textDocument/references` | `lsp__<server>__find_references` | 查找引用 |
| `textDocument/diagnostic` | `lsp__<server>__get_diagnostics` | 获取诊断 |

### 5.2 MCP Adapter

**职责**：
- 连接 MCP Server（stdio/HTTP/SSE）
- 执行 tools/list 发现和 tools/call 调用
- 处理 listChanged 通知驱动的增量更新
- 集成 SEC-007 Schema 签名验证

**发现流程**：
```
1. 连接 MCP Server（通过 MCPServerManager）
2. 发送 tools/list 请求
3. 接收工具清单和 Schema
4. 验证 Schema 签名（SEC-007）
5. 转换为 CapabilityItem
6. 注册到 CapabilityRegistry
7. 订阅 listChanged 通知
```

**调用流程**：
```
1. 接收 tool_call（scoped_name + arguments）
2. 提取 MCP Server 标识
3. 构造 tools/call 请求
4. 发送到目标 Server
5. 接收执行结果
6. 转换为统一格式
7. 返回给 Tool Adapter
```

### 5.3 Skill Adapter

**职责**：
- 扫描 SKILL.md 文件（四层作用域：Project/User/Extra/Built-in）
- 解析 YAML frontmatter 元数据
- 执行 Skill 内容注入到模型上下文

**作用域优先级**：
| 作用域 | 优先级 | 路径 |
|--------|--------|------|
| Project | 400 | `.cursor/skills/` |
| User | 300 | `~/.cursor/skills/` |
| Extra | 200 | 配置的额外路径 |
| Built-in | 100 | SDK 内置路径 |

**Skill 类型处理**：
| 类型 | 自动触发 | 手动触发 | 说明 |
|------|----------|----------|------|
| `prompt` | ✓ | ✓ | 可自动注入 |
| `inline` | ✓ | ✓ | 同 prompt |
| `flow` | ✗ | ✓ | 仅手动触发 |

---

## 六、权限裁剪与 Policy 集成

### 6.1 发现时权限裁剪

**裁剪层级**：
```
L1: Server 级别裁剪
  - 用户无权限访问的 MCP Server 不返回
  - 检查：SEC-002 RBAC + SEC-007 MCP Policy

L2: 工具级别裁剪
  - Server 内无权限的工具不返回
  - 检查：工具 required_permissions ⊆ 用户权限

L3: 参数级别裁剪（MVP 不实现）
  - 敏感参数字段隐藏
  - 检查：参数敏感级别 vs 用户权限
```

**裁剪算法**：

```python
def filter_by_permissions(capabilities, user):
    # L1: Server 级别
    user_permissions = rbac.get_user_permissions(user)
    org_policy = mcp_governance.get_org_policy(user.organization_id)
    
    filtered = []
    for cap in capabilities:
        # 检查 Server 访问权限
        if cap.source_protocol == 'MCP':
            if not org_policy.allows_server(cap.source_id):
                log_pruning(cap, reason='org_policy_deny')
                continue
        
        # L2: 工具级别
        if cap.required_permissions:
            if not all(p in user_permissions for p in cap.required_permissions):
                log_pruning(cap, reason='insufficient_permissions')
                continue
        
        filtered.append(cap)
    
    return filtered
```

### 6.2 Policy Gateway 集成

**集成点**：
| 阶段 | 集成点 | Policy 类型 | 决策 |
|------|--------|------------|------|
| 发现前 | Step 4 | DiscoveryPolicy | ALLOW / DENY / REQUIRE_APPROVAL |
| 调用前 | Step 3 | ExecutionPolicy | ALLOW / DENY / REQUIRE_APPROVAL |

**Policy 决策处理**：
```python
def handle_policy_decision(decision, context):
    if decision.result == 'ALLOW':
        return CONTINUE
    elif decision.result == 'DENY':
        return RoutingDecision(
            status=DENIED,
            denial_reason=decision.reason,
            evidence=decision.evidence
        )
    elif decision.result == 'REQUIRE_APPROVAL':
        approval_id = create_approval_request(context, decision)
        return RoutingDecision(
            status=PENDING_APPROVAL,
            approval_id=approval_id
        )
```

---

## 七、状态管理与数据流转

### 7.1 RoutingContext 状态机

**状态定义**：

| 状态 | 说明 | 可迁移到 |
|------|------|----------|
| `INIT` | 初始化 | ACTIVE |
| `ACTIVE` | 活跃状态 | SUSPENDED / CLOSED |
| `SUSPENDED` | 暂停状态 | ACTIVE / CLOSED |
| `CLOSED` | 已关闭 | - |

**状态迁移**：

| 当前状态 | 触发事件 | 目标状态 | 前置条件 |
|----------|----------|----------|----------|
| INIT | worker_started() | ACTIVE | Worker 启动完成 |
| ACTIVE | suspend() | SUSPENDED | 用户暂停或 Policy 暂停 |
| SUSPENDED | resume() | ACTIVE | 恢复条件满足 |
| ACTIVE | close() | CLOSED | Worker 停止 |
| SUSPENDED | close() | CLOSED | 强制关闭 |

### 7.2 CapabilityItem 可见性管理

**可见性状态**：

| 状态 | 说明 | 模型可见 |
|------|------|----------|
| `VISIBLE` | 立即可见 | ✓ |
| `DEFERRED` | 延迟加载 | ✗（manifest 可见） |
| `HIDDEN` | 隐藏 | ✗ |

**可见性转换**：
```
权限变更 → 重新评估可见性
Token 预算变化 → VISIBLE ↔ DEFERRED
Policy 更新 → VISIBLE → HIDDEN
```

### 7.3 数据流转图

```
┌─────────────────────────────────────────────────────────────────┐
│                        Worker Runtime                            │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Unified Router                                │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
│  │ LSP Adapter │  │ MCP Adapter │  │Skill Adapter│             │
│  └─────────────┘  └─────────────┘  └─────────────┘             │
│         │                │                │                      │
│         └────────────────┼────────────────┘                      │
│                          ▼                                        │
│  ┌─────────────────────────────────────────────┐                 │
│  │           Capability Abstraction Layer      │                 │
│  │  • 协议无关能力抽象                          │                 │
│  │  • 权限裁剪（SEC-002）                      │                 │
│  │  • Policy 预检（SEC-003）                    │                 │
│  │  • 延迟加载决策（CTX-006）                   │                 │
│  │  • 冲突仲裁                                  │                 │
│  └─────────────────────────────────────────────┘                 │
└─────────────────────────────────────────────────────────────────┘
                                │
              ┌─────────────────┼─────────────────┐
              ▼                 ▼                 ▼
     ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
     │  LLM Model  │    │ Context     │    │  PEP       │
     │  (能力清单) │    │ Selector    │    │  Registry  │
     └─────────────┘    └─────────────┘    └─────────────┘
```

---

## 八、异常与失败处理

### 8.1 异常场景与处理策略

| 异常场景 | 检测点 | 处理策略 | 降级路径 |
|----------|--------|----------|----------|
| **MCP Server 不可达** | 协议适配器连接检测 | 标记为 DISCONNECTED；返回空清单 | 使用缓存的工具 Schema |
| **Schema 签名验证失败** | 发现时（SEC-007） | 拒绝该工具进入可见清单 | 进入隔离评估队列（L4） |
| **Token 预算超限** | 延迟加载评估 | 强制延迟加载 | 使用最小 Schema 摘要 |
| **权限服务不可用** | 权限预检 | fail-secure；拒绝所有发现请求 | 使用上次缓存的权限快照 |
| **语义检索失败** | 延迟加载决策 | 回退到全量加载（如果有 Token） | 使用随机选择或注册顺序 |
| **冲突仲裁失败** | 冲突处理 | 记录冲突；返回最高优先级 | 使用第一个注册的 |
| **PEP 拦截点无响应** | 执行前检查 | 超时降级到 REQUIRE_APPROVAL | 触发人工审批 |
| **协议适配器崩溃** | 执行委托 | 隔离故障；标记适配器不可用 | 使用备用适配器或返回错误 |

### 8.2 故障隔离策略

**隔离级别**：
```
L1: 工具级别隔离
  - 单个工具失败不影响其他工具
  - 失败工具标记为 ERROR，但保留在注册表

L2: Server 级别隔离
  - MCP Server 连接失败不影响其他 Server
  - 失败 Server 标记为 DISCONNECTED，定期重连

L3: 协议级别隔离
  - LSP Adapter 失败不影响 MCP/Skill
  - 失败协议标记为 UNAVAILABLE
```

---

## 九、可观测性与审计

### 9.1 核心指标

**发现阶段指标**：

| 指标 | 类型 | 标签 | 说明 |
|------|------|------|------|
| `router_discovery_total` | counter | protocol, status | 发现请求总数 |
| `router_discovery_latency_p95` | histogram | protocol | 发现延迟 p95 |
| `router_capabilities_visible` | gauge | protocol | 当前可见能力数 |
| `router_capabilities_deferred` | gauge | protocol | 当前延迟能力数 |
| `router_discovery_pruned_rate` | gauge | reason | 发现裁剪率（按原因） |

**路由阶段指标**：

| 指标 | 类型 | 标签 | 说明 |
|------|------|------|------|
| `router_tool_call_total` | counter | protocol, source, status | 工具调用总数 |
| `router_tool_call_latency_p95` | histogram | protocol, source | 调用延迟 p95 |
| `router_routing_decision_latency` | histogram | - | 路由决策延迟 |

**延迟加载指标**：

| 指标 | 类型 | 标签 | 说明 |
|------|------|------|------|
| `router_deferred_loading_total` | counter | trigger | 延迟加载触发次数 |
| `router_deferred_loading_latency` | histogram | - | 延迟加载延迟 |
| `router_semantic_search_latency` | histogram | - | 语义检索延迟 |

**冲突与错误指标**：

| 指标 | 类型 | 标签 | 说明 |
|------|------|------|------|
| `router_conflict_detected_total` | counter | name | 冲突检测次数 |
| `router_adapter_error_total` | counter | protocol, error_type | 适配器错误次数 |

**性能目标**：

| 指标 | 目标 | 说明 |
|------|------|------|
| 发现延迟 | < 100ms (p95) | 缓存命中场景 |
| 路由决策延迟 | < 20ms (p95) | 解析 + 适配器查找 |
| 延迟加载决策 | < 50ms (p95) | 语义检索 |
| 冲突仲裁延迟 | < 10ms (p95) | 优先级计算 |

### 9.2 告警规则

| 规则 | 条件 | 严重度 | 通知 |
|------|------|--------|------|
| 发现延迟高 | p95 > 200ms | warning | 邮件 |
| 发现延迟极高 | p95 > 500ms | critical | PagerDuty |
| 裁剪率异常 | pruned_rate > 80% | warning | 邮件 |
| 冲突率异常 | conflict_rate > 10% | warning | 邮件 |
| Server 不可达 | 连续 3 次发现失败 | critical | PagerDuty |
| 适配器错误率高 | error_rate > 5% | warning | 邮件 |

### 9.3 链路追踪

每次发现和调用都纳入 OpenTelemetry Trace（对接 REQ-OBS-001）。

**追踪 Span**：

| Span 名称 | 属性 | 说明 |
|-----------|------|------|
| `router.discover` | protocol, worker_id, task_id | 统一发现 |
| `router.aggregate_sources` | protocols | 协议源聚合 |
| `router.permission_check` | user_id, organization_id | 权限预检 |
| `router.policy_check` | policy_version | Policy 预检 |
| `router.deferred_evaluation` | token_budget, token_used | 延迟加载评估 |
| `router.semantic_search` | query, top_n | 语义检索 |
| `router.conflict_resolution` | conflicts_count | 冲突仲裁 |
| `router.route_call` | tool_name, protocol | 工具调用路由 |
| `router.adapter_execute` | adapter_id, timeout_ms | 适配器执行 |

**追踪字段**：
- `trace_id`：全局链路追踪 ID
- `request_id`：单次请求标识
- `worker_id` + `task_id` + `action_id`：关联任务
- `protocol` + `source_id` + `tool_name`：工具标识
- `decision_id`：Policy 决策 ID

### 9.4 审计日志

完整的路由决策审计日志，支持合规和安全审计。

**审计内容**：

| 字段 | 说明 |
|------|------|
| 请求标识 | request_id、worker_id、task_id |
| 用户身份 | user_id、organization_id、roles |
| 发现上下文 | capability_requirements、token_budget |
| 权限裁剪 | pruned_capabilities、pruning_reasons |
| Policy 决策 | policy_decision、decision_reason |
| 延迟加载 | deferred_count、semantic_search_query |
| 冲突仲裁 | conflicts、resolution_results |
| 响应结果 | visible_count、deferred_count、total_tokens |
| 链路追踪 | trace_id、span_id |

**审计保留期**：
- 普通审计：30 天热存储 + 180 天冷存储
- 安全审计：1 年热存储 + 7 年冷存储

---

## 十、接口设计

### 10.1 统一路由接口

**接口描述**：统一的能力发现接口

**请求**：DiscoveryRequest（见 3.2 节）

**响应**：DiscoveryResponse（见 3.3 节）

**错误码**：

| 错误码 | 说明 | HTTP 状态码 |
|--------|------|-------------|
| `PERMISSION_DENIED` | 权限不足 | 403 |
| `POLICY_DENIED` | Policy 拒绝 | 403 |
| `TOKEN_BUDGET_EXCEEDED` | Token 预算超限 | 429 |
| `ADAPTER_UNAVAILABLE` | 协议适配器不可用 | 503 |
| `INTERNAL_ERROR` | 内部错误 | 500 |

### 10.2 工具调用路由接口

**接口描述**：工具调用路由决策

**请求**：ToolCallRouteRequest（见 3.4 节）

**响应**：RoutingDecision（见 3.5 节）

**错误码**：

| 错误码 | 说明 | HTTP 状态码 |
|--------|------|-------------|
| `TOOL_NOT_FOUND` | 工具未找到 | 404 |
| `PERMISSION_DENIED` | 权限不足 | 403 |
| `POLICY_DENIED` | Policy 拒绝 | 403 |
| `APPROVAL_REQUIRED` | 需要审批 | 202 |
| `ADAPTER_ERROR` | 适配器错误 | 502 |

### 10.3 延迟加载接口

**接口描述**：按需加载延迟工具

**请求**：
```typescript
interface DeferredLoadRequest {
  request_id: UUID;
  worker_id: UUID;
  task_id: UUID;
  load_targets: Array<{
    type: 'server' | 'namespace' | 'tool';
    target_id: string;
  }>;
  token_budget: number;
  trace_context: TraceContext;
}
```

**响应**：
```typescript
interface DeferredLoadResponse {
  request_id: UUID;
  loaded_capabilities: Array<CapabilityItem>;
  total_tokens_estimate: number;
  load_failures: Array<{
    target_id: string;
    error: string;
  }>;
}
```

### 10.4 上游依赖

| 依赖模块 | 依赖内容 | 接口（概念） |
|----------|----------|-------------|
| REQ-HAR-003 | 工具定义 Schema、执行契约 | CapabilityItem → ToolDefinition |
| REQ-SEC-002 | RBAC 权限查询 | get_permissions(user) → PermissionSet |
| REQ-SEC-003 | Policy Gateway 决策 | check_discovery(context) → PolicyDecision |
| REQ-SEC-007 | MCP Schema 签名验证 | verify_schema(server, schema) → bool |
| REQ-CTX-006 | Context Selector Token 预算 | get_token_budget(task_id) → Budget |
| REQ-HAR-004 | Skill 清单发现 | discover(requirements) → Skills[] |
| REQ-RT-003 | 事件驱动更新 | Event.on(DiscoveryChanged) |

### 10.5 下游接口

| 接口 | 下游消费者 | 说明 |
|------|-----------|------|
| UnifiedRouter.discover() | Worker Runtime | 统一发现接口 |
| UnifiedRouter.route_tool_call() | HAR-003 Tool Adapter | 工具调用路由 |
| CapabilityRegistry.register() | HAR-006 测试桩 | 能力注册 |
| AdapterRegistry.get() | HAR-006 测试桩 | 协议适配器查询 |
| PEPRegistry.register() | SEC-003 Policy Gateway | PEP 拦截点注册 |

---

## 十一、验收标准

| 编号 | 验收标准 | 验证方法 |
|------|----------|----------|
| **HAR-005-F01** | 支持 LSP/MCP/Skill 三层协议的能力发现 | 单元测试：注册三种协议工具，验证统一发现 |
| **HAR-005-F02** | 发现时完成权限裁剪，无权限工具不返回 | 集成测试：RBAC 变更后验证可见性变化 |
| **HAR-005-F03** | Token 预算超限时触发延迟加载 | 性能测试：模拟 Token 超限，验证延迟加载触发 |
| **HAR-005-F04** | 延迟加载工具在模型需要时正确加载 | 集成测试：调用 select_tools，验证 Schema 加载 |
| **HAR-005-F05** | 同名工具冲突时应用仲裁规则 | 单元测试：注册同名 LSP/MCP 工具，验证优先级 |
| **HAR-005-F06** | 工具调用路由到正确的协议适配器 | 集成测试：调用三种协议工具，验证适配器调用 |
| **HAR-005-F07** | PEP 拦截点在执行前生效 | 安全测试：高风险工具调用触发 Policy 检查 |
| **HAR-005-F08** | Schema 签名验证失败的工具不暴露 | 安全测试：伪造 Schema 签名，验证拒绝 |
| **HAR-005-S01** | 发现延迟 p95 < 100ms（缓存命中） | 性能测试：1000 次发现请求统计 p95 |
| **HAR-005-S02** | 支持 1000 Worker 并发发现 | 负载测试：1000 并发请求验证吞吐量 |
| **HAR-005-O01** | 所有发现请求记录审计日志 | 审计测试：验证日志完整性 |
| **HAR-005-O02** | 所有路由决策可追溯到权限和 Policy | 溯源测试：验证 trace_id 关联 |

---

## 十二、与原设计对比

| 维度 | 原设计 | 修改后设计 | 改进点 | 对标依据 |
|------|--------|-----------|--------|----------|
| **协议抽象** | 未定义 | 统一 Capability Abstraction Layer | 协议无关路由 | MCP/LangGraph |
| **发现机制** | 未定义 | 12 步发现流程 + Event 驱动更新 | 可预测、可追踪 | MCP listChanged |
| **权限裁剪** | 未明确 | 发现时 + 调用时双层裁剪 | 最小暴露面 | Cursor/SEC-002 |
| **延迟加载** | 未定义 | 语义检索 + Token 预算控制 | 工具爆炸缓解 | Kimi Code/LangGraph |
| **冲突仲裁** | 未定义 | 协议优先级 > 版本 > 注册时间 | 可预测仲裁 | 本项目设计 |
| **PEP 拦截** | 未明确 | 7 步路由流程 + PEP 注册 | 执行点拦截 | DeepSeekCode/SEC-003 |
| **Schema 验证** | 未提及 | SEC-007 签名验证集成 | 防篡改 | SEC-007 设计 |
| **可观测性** | 未提及 | 12 核心指标 + 5 告警规则 | 可评估 | OBS-001~007 |

---

## 十三、设计理由总结

**为什么这样改更符合行业标杆**：

1. **MCP 兼容性**：采用 MCP 官方规范的 tools/list + tools/call + listChanged 机制，无缝对接 Anthropic/OpenAI/Cursor/DeepSeek/Kimi 生态
2. **LangGraph 动态绑定**：Picker Node + Executor Node 分离架构，解决大工具集上下文溢出问题
3. **Kimi Code deferred 机制**：manifest + select_tools 实现按需加载，Token 消耗可控
4. **DeepSeekCode 统一路径**：Permission → Policy → Hook → Execution 串联所有检查点，执行可预测
5. **Cursor 多层权限**：Enterprise/Team/Project/User/Plugin 优先级体系，支持策略叠加收紧

**解决了哪些问题**：

1. **协议碎片化** → 统一 Capability Abstraction Layer，一次编写多协议适配
2. **工具爆炸** → 延迟加载 + Token 预算控制，防止上下文溢出
3. **权限泄露** → 发现时即裁剪，减少暴露面
4. **路由歧义** → 冲突仲裁规则，保证调用确定性
5. **安全盲区** → PEP 拦截点 + Schema 签名验证，多层防护
6. **不可观测** → 完整指标和审计日志，支持调优

**带来的收益**：

- **开发者**：一次编写工具，自动适配三种协议，接入成本降低 60%
- **安全团队**：统一的权限裁剪和 Policy 决策点，审计完整
- **运维团队**：跨协议统一可观测性，故障定位时间减少 50%
- **终端用户**：只看到相关工具，认知负担降低

---

## 十四、对其它待办的影响

| 需求 | 影响 | 同步要求 | 风险与缓解 |
|------|------|----------|------------|
| **REQ-HAR-006** | 契约测试需要测试桩模拟 LSP/MCP/Skill 协议 | 测试桩实现 Adapter 接口 | 测试覆盖度不足；需覆盖三种协议各 5 个场景 |
| **REQ-SEC-007** | MCP 工具发现需集成 Schema 签名验证 | 验证点：发现时签名检查 | 验证失败工具处理流程需对齐 |
| **REQ-SEC-003** | Policy Gateway 决策点需与路由层对齐 | 决策点：发现前、调用前 | 决策延迟影响路由响应时间 |
| **REQ-CTX-006** | Context Selector Token 预算需传递给路由层 | 接口：get_token_budget() | 预算计算需考虑 Schema Token |
| **REQ-HAR-004** | Skill 发现需通过路由层统一暴露 | 协议适配器：Skill Adapter | Skill 执行上下文需标准化 |

---

## 十五、版本与演进

### 15.1 v1.0 基线（MVP）

**功能范围**：
- LSP/MCP/Skill 三层协议的基本发现
- 发现时权限裁剪
- 基础的延迟加载（手动触发 select_tools）
- 基本的冲突仲裁（优先级规则）
- 基础的 PEP 拦截点
- 基础的可观测性

**不包含**：
- 自动延迟加载（语义检索）
- 跨 Worker 工具状态同步
- AI 驱动的工具推荐

### 15.2 v1.1 增强

**新增功能**：
- 自动延迟加载（语义检索）
- 工具使用统计与推荐
- 跨 Worker 工具状态同步

### 15.3 v2.0 高级

**新增功能**：
- AI 驱动的工具推荐
- 动态协议适配器加载
- 跨平台工具同步

---

## 十六、实施计划

### Phase 1：核心路由（2 周）

- 统一路由接口实现
- LSP/MCP/Skill Adapter 实现
- 基础的能力发现和路由
- 基础的权限裁剪

### Phase 2：安全集成（2 周）

- Policy Gateway 集成
- SEC-007 Schema 签名验证
- PEP 拦截点注册
- 权限复核机制

### Phase 3：延迟加载（1 周）

- 手动延迟加载实现
- select_tools 内置工具
- Token 预算集成

### Phase 4：可观测性（1 周）

- 核心指标收集
- 审计日志实现
- 链路追踪集成
- 告警规则配置

---

## 十七、参考资料

以下为公开来源，访问日期均为 2026-10-04：

- **MCP**: [Model Context Protocol Specification](https://modelcontextprotocol.io/specification)
- **Cursor**: [MCP Documentation](https://cursor.com/docs/mcp)
- **LangGraph**: [MCP Adapters](https://github.com/langchain-ai/langgraph-mcp), [LangGraph-bigtool](https://github.com/langchain-ai/langgraph-bigtool/)
- **OpenAI Agents SDK**: [Multi-Agent Orchestration](https://openai.github.io/openai-agents-python/multi_agent/), [Tools](https://openai.github.io/openai-agents-python/tools/)
- **Kimi Code**: [MCP Documentation](https://www.kimi.com/code/docs/en/kimi-code-cli/customization/mcp.html), [Skills](https://www.kimi.com/code/docs/en/kimi-code-cli/customization/skills.html)
- **DeepSeekCode**: [Architecture](https://github.com/willamhou/DeepSeekCode/blob/main/docs/architecture.md), [TUI](https://github.com/willamhou/DeepSeekCode/blob/main/docs/tui.md)

---

## 十八、决策记录

| 决策项 | 决策 | 依据 |
|-------|------|------|
| 协议优先级 | LSP=100, MCP=80, SKILL=60 | LSP 提供语言服务核心能力 |
| 延迟加载阈值 | Token 消耗 > 可用预算 × 70% | 保留 30% 缓冲 |
| 冲突仲裁 | 协议优先级 > 版本 > 注册时间 | 最大透明度和可预测性 |
| PEP 拦截点 | 发现前 + 调用前双层拦截 | 多层防护 |
| Schema 缓存 TTL | 1 小时 | 平衡新鲜度和性能 |
| 权限裁剪时机 | 发现时即裁剪 | 最小暴露面 |

---

**文档创建时间**：2026-10-05  
**维护团队**：架构组  
**状态**：v0.1-designed，待跨模块评审与冻结
