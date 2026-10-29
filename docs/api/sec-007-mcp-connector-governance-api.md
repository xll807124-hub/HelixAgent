# SEC-007 MCP 连接器治理 API 说明

包路径：`src.security.mcp_connector_governance`
状态：历史顶部 Task 2.4 的局部实现，正文归属 2.1 安全强化，并列为阶段 0 优先补缺。完整需求见 [REQ-SEC-007](../design-specs/REQ-SEC-007-mcp-connector-governance.md)。用户于 2026-10-28 回复“确认”，批准[生命周期发现/调用补缺方案](../review/sec007-lifecycle-discovery-design-2026-10-28.md)三项决策。下列契约已实现并通过功能验证；该切片及扫描扩展已于 2026-10-29 验收，见[验收记录](../delivery-reports/sec007-lifecycle-acceptance-2026-10-29.json)。

## 0. 本次已确认契约（2026-10-28）

- 新增 `ToolRegistry.get_tool_for_connector(connector_id: str, tool_name: str) -> ToolSchema | None`：只取该提供方登记的当前定义；未知关联返回 `None`。注册时更新提供方关联，注销时清理；全局版本查询保持兼容。
- `tools/list`：只使用存在且状态为 `ACTIVE` / `RESTRICTED` 的提供方，并继续应用既有黑名单和组织裁剪。孤立、停用或无可用提供方的工具不返回；同名可用定义不一致时隐藏并记录原因；停用方不能扩大参数范围或贡献描述/Schema。
- `tools/list` 的 `name` / `description` / `inputSchema` 及成功包络不变；没有可见工具返回 `result.tools: []`。未装配连接器注册表或查询异常返回 JSON-RPC `-32603`，不退化为返回全部工具。
- `tools/call` 保留 `connector_id:tool_name`；不可用或不存在的目标统一返回 `-32050`、`Tool unavailable`，不会调用执行器或扣配额。按提供方读取定义；保留输入校验、黑名单和组织限制。
- v2 `ToolExecutor` 准备凭据结束后、扣配额及传输前复核生命周期；拒绝返回 `success=False`、`metadata.blocked_by="lifecycle"`，使用既有审计入口。权限拒绝不自动重试。
- 协议入口提前拒绝仍写入既有 `log_policy_decision`，内部 `blocked_by="availability"`；外部统一错误保持不变。该路径审计入口抛异常时返回 `-32603` 并拒绝执行。此项不代表已修复其他组件的审计持久性缺口。
- 作用域为本进程尚未交给传输的调用；跨进程传播、代次识别、凭据吊销、Schema 审批仍待后续任务。本次没有新 HTTP 端点、配置项、前端或依赖。

兼容性变化：无注册表不再允许列工具，停用/歧义条目消失，非活动目标错误统一为 `-32050`。调用方与测试必须遵守此契约。

## 1. 组件总览

| 组件 | 位置 | 职责 |
|---|---|---|
| `ConnectorRegistry` | `registry/connector_registry.py` | 连接器登记、查询、状态与健康更新 |
| `ToolRegistry` | `registry/tool_registry.py` | 工具 Schema 摘要、版本、批准记录 |
| `PolicyEngine` | `policies/policy_engine.py` | 全局黑名单、组织白名单、能力裁剪、配额 |
| `LifecycleManager` | `lifecycle/lifecycle_manager.py` | 状态机、签名闸门、状态变更审计 |
| `AuthorizationManager` | `authorization/auth_manager.py` | 按认证模式准备凭据（OAuth2 PKCE / STDIO / API Key） |
| `SEC005CredentialProxyClient` | `authorization/credential_adapter.py` | 把 SEC-005 PDP/CDP 适配为凭据签发接口 |
| `ToolExecutor` | `execution/tool_executor_v2.py` | 签名闸门、策略、配额、传输层执行、退款、审计 |
| `MCPProtocolHandler` | `protocol/mcp_handler.py` | JSON-RPC 2.0 的 `tools/list`、`tools/call` |
| `AuditLogger` | `audit/audit_logger.py` | 审计事件记录与查询 |

## 2. LifecycleManager

```python
LifecycleManager(registry: ConnectorRegistry, audit_logger: Optional[AuditLogger] = None)
```

| 方法 | 签名 | 返回 |
|---|---|---|
| `transition_to` | `(connector_id, new_state, reason, triggered_by="system")` | `bool` |
| `activate` | `(connector_id, activated_by)` | `bool` |
| `pause` | `(connector_id, reason, paused_by)` | `bool` |
| `resume` | `(connector_id, resumed_by)` | `bool` |
| `revoke` | `(connector_id, reason, revoked_by)` | `bool` |
| `mark_for_review` | `(connector_id, reason)` | `bool` |
| `handle_health_anomaly` | `(connector_id, health_issue)` | `bool` |
| `check_expiry` | `(connector_id)` | `bool` |
| `get_transition_history` | `(connector_id=None)` | `List[Dict]` |

审计行为（传入 `audit_logger` 时生效）：

- 成功转换：`CONNECTOR_ACTIVATED` / `CONNECTOR_PAUSED` / `CONNECTOR_REVOKED`，其余目标状态为 `CONNECTOR_STATE_CHANGED`，`result="success"`。
- 非法转换、签名闸门拦截：统一记 `CONNECTOR_STATE_CHANGED`，`result="denied"`。被拒绝的尝试不会冒充"已激活/已撤销"。
- 审计写入异常只记日志，不改变转换结果。

## 3. AuthorizationManager

```python
AuthorizationManager(
    credential_proxy_client: Optional[CredentialProxyClient] = None,
    http_client: Optional[httpx.Client] = None,
    audit_logger: Optional[AuditLogger] = None,
)
prepare_credentials(connector, org_id, user_id) -> Optional[Dict[str, Any]]
```

返回 `None` 表示无法安全准备凭据，调用方必须拒绝调用。传入 `audit_logger` 后：

- 每次 `prepare_credentials` 记 `AUTH_GRANTED` 或 `AUTH_DENIED`，元数据含 `auth_mode`，不含令牌。
- OAuth 刷新记 `TOKEN_REFRESHED`，`result` 为 `success` 或 `failed`。
- API Key 模式标记为 `@deprecated`，使用时写 warning 日志。

## 4. SEC005CredentialProxyClient

```python
SEC005CredentialProxyClient(
    pdp: CredentialPDP,
    cdp: CredentialCDP,
    approval_provider: Callable[[str, str, str], ApprovalDecision],  # (key_ref, connector_id, org_id)
    *, agent_svid: str, worker_id: str,
    task_id: str = "mcp-connector-governance",
    target_service: str = "generic_oauth",
    requested_action: str = "invoke",
    requested_scope: list[str] | None = None,
    max_ttl_seconds: int = 900,
)
issue_short_lived_credential(*, key_ref, connector_id, org_id, ttl_seconds) -> {"token": str, "expires_at": datetime}
```

`ApprovalDecision(policy_gateway_approved, rbac_approved, rbac_scope=[], policy_approval_ref="")` 由调用方提供，适配器自身不放行任何请求。

所有失败抛 `CredentialIssuanceError`（消息不含凭据内容）：

- 参数缺失，或 `ttl_seconds <= 0`
- 审批方抛异常或返回非 `ApprovalDecision`
- `policy_approval_ref` 为空
- PDP 拒绝
- CDP 抛异常（如不健康）
- CDP 未返回令牌内容或过期时间无效。此时会先撤销已登记的租约，再抛异常。

TTL 取 `ttl_seconds` 与 `max_ttl_seconds` 的较小值，CDP 还会再按服务类型取上限。

## 5. ToolExecutor

```python
ToolExecutor(policy_engine, timeout_seconds=30,
             signature_verifier=None, audit_logger=None,
             authorization_manager=None, allow_private_networks=False)
await execute_tool(org_id, user_id, connector, tool, parameters) -> ToolExecutionResult
await verify_connector_signature(connector, signature_info) -> bool
```

执行顺序：签名闸门、策略检查（含生命周期闸门）、凭据准备、配额扣减、传输层执行、失败退款、审计。前置检查失败时不触达连接器，结果的 `metadata["blocked_by"]` 为 `signature` / `lifecycle` / `trust_level` / `credentials` / `quota` / `global_blacklist` / `org_policy` 等。

环境闸门（`PolicyEngine(environment=ExecutionEnvironment.PRODUCTION)`，默认生产）：
- L4（及无法识别的信任等级）在 `PRODUCTION` 一律拒绝，`blocked_by="trust_level"`。
- `ISOLATED_EVALUATION` 下，L4 仍拒绝：`tool.risk_profile.data_sensitivity` 不是 `L1`/`L2`（含无法解析的值）的工具，以及认证模式非 `NONE` 的连接器。
- 环境在构造引擎时指定，调用方无法按次覆盖。当前只是策略标记，不提供运行面隔离。

出口校验（HTTP/SSE，`execution/egress_guard.py`）：
- 默认只允许 `https` 和公网地址；拒绝 URL 凭据段、非规范数字主机（`2130706433`、`127.1`、`0x7f.0.0.1` 等）、回环、私网、链路本地（含 169.254.169.254）、CGNAT、多播、保留段及其 IPv6 内嵌形式。
- 主机名在连接时由受控解析器校验，解析结果中任一地址非公网即拒绝；不跟随重定向。
- 拒绝时 `error` 以 `Egress blocked` 开头，`metadata["blocked_by"] == "egress"`，已扣配额会退款，且不发送凭据。
- `allow_private_networks=True` 仅用于本地开发和测试。

凭据注入规则：
- `auth.mode == NONE`：不调用 `authorization_manager`。
- 其他模式：必须配置 `authorization_manager`，否则拒绝（`blocked_by="credentials"`，不扣配额）。
- 取到的 `access_token` / `token` 只注入传输层：HTTP/SSE 放入 `Authorization: Bearer` 头，STDIO 放入子进程环境变量 `MCP_CONNECTOR_TOKEN`。不进入返回结果、元数据或审计。
- 凭据不可用、`prepare_credentials` 抛异常、或凭据里没有可注入的令牌（如 mTLS 只有证书指纹）时一律拒绝；异常信息不会回传给调用方。

## 6. 审计事件

`AuditLogger(log_file: Optional[str] = None)`：事件先存内存列表，传 `log_file` 时同时落文件。

| 方法 | 用途 |
|---|---|
| `log_event(event_type, actor, resource_type, resource_id, action, result, metadata=None, org_id=None)` | 通用入口 |
| `log_connector_registered` / `log_tool_invocation` / `log_policy_decision` / `log_quota_exceeded` / `log_schema_change` / `log_signature_verification` | 业务事件 |
| `log_lifecycle_transition` / `log_authorization` / `log_token_refresh` | 本次新增 |
| `get_events(event_type=None, actor=None, org_id=None, limit=100)` | 查询 |

`metadata` 中含 `token`、`private_key` 等敏感键名的值会被脱敏。

## 7. 已知限制

接入前请阅读 `docs/delivery-reports/REQ-SEC-007-compliance-analysis.md` 第 3 节。要点：

- v2 `ToolExecutor` 已调用所注入的 `AuthorizationManager` 并向传输层注入令牌；需要认证但未装配授权管理器时拒绝。缺口是生产装配与真实凭据签发/撤销闭环，不能误写成执行器完全没有接入。
- `HTTPExecutor` 只有黑名单式出口基线，没有按连接器登记的目的地白名单；STDIO 子进程不受出口限制。
- `allowed_production`、Schema 摘要复核（`is_approved` / `detect_schema_change`）没有调用点。
- `CredentialCDP` 的令牌生成仍是 SEC-005 的示例实现。


## 2026-10-29 已批准接口：凭据失效与撤销联动（实现前定稿）

用户已确认[三点设计](../review/sec007-credential-invalidation-design-2026-10-29.md)。本节是当前切片实施契约；未新增 HTTP 端点或 Runtime 共享字段。

- `LifecycleManager(registry, audit_logger=None, authorization_manager=None)`：同一注册表绑定同一授权管理器，重复装配其他实例拒绝。无凭据连接器允许沿用无管理器装配；需认证且未装配时停用成功但撤销为 `unconfigured`，不允许恢复。
- `AuthorizationManager.invalidate_connector_credentials(connector_id, org_id, reason, actor)`：清空该作用域全部用户凭据并提升代次；重复调用可重试；返回下面的摘要。内部将同步本地失效和有界外部清理分开，不持锁进行网络等待。
- `LifecycleManager.get_credential_invalidation_status(connector_id, *, org_id)`：校验组织后返回副本；未知或不属于该组织返回 `None`。动态刷新迟到租约清理状态，不能通过新建 LifecycleManager 绕过未完成状态。
- `pause/revoke/transition_to`：原布尔值仍表示生命周期状态生效，不代表外部撤销成功。已停用状态重复请求可以重试清理；恢复或进入其他可调用状态必须确认撤销与失效审计已完成。
- `ConnectorStatus.credential_generation`：单进程单调递增的运行时字段；每次状态进入不可调用状态递增。执行器在凭据等待前后比较代次，防暂停→恢复竞态。`credential_invalidation` 保留不含秘密的状态摘要；不改变 RT 契约。
- 缓存键改为 `(org_id, user_id, connector_id)` 元组；不兼容测试直接写入旧私有字符串键。`get_credential_generation(connector_id, org_id)` 用于新授权开始时取代次。
- `store_oauth_token(..., *, expected_generation=None)`：初始代次 0 可兼容旧同步调用；失效后必须显式传入新授权开始时捕获的代次；停用或代次不符抛 `ValueError`，不写缓存。令牌内容不出现在异常中。
- `TokenManager` 增加组织绑定、失效及代次参数；注册到 AuthorizationManager 的管理器必须具有明确组织。独立旧用法仍支持本地 invalidate；不能作为跨组织的共享缓存。刷新完成后复核代次，拒绝停用期间的迟到响应。
- `SEC005CredentialProxyClient.revoke_connector_credentials(connector_id, org_id, reason)`：按签发句柄撤销，返回 `credential_revocation_status/pending_count/retryable`，不返回令牌。适配器保留迟到/失败租约；初次尝试后最多重试 3 次，超时仍在执行的同一句柄不启动重叠撤销。
- `SEC005CredentialProxyClient.get_revocation_status(...)` 和 `resume_connector_credentials(...)`：分别查询待处理数量及解除签发阻断。存在未完成签发、租约或撤销时不得解除。成功只代表已装配 CDP 返回，真实服务撤销仍需提供方实证。

摘要字段：`connector_id`, `org_id`, `generation`, `local_invalidated`, `cleared_count`, `credential_revocation_status`（`not_required/complete/partial/unsupported/unconfigured`）, `pending_count`, `retryable`, `audit_recorded`, `error_code`。查询不得暴露其他组织或原始异常。

直接 OAuth/Bearer 无远端撤销适配器时清除本地使用副本，返回 `unsupported` 并保持不可调用；受托管凭据经已有 SEC-005 接口处理。无凭据模式为 `not_required`。API Key 恢复后重新经 PDP/CDP 签发，不复用旧租约。普通任务暂停不受影响。

安全恢复：先本地阻断和清理，再外部撤销；外部失败不回滚状态。凭据失效审计故障保留错误，重试审计后才可恢复有凭据连接器。撤销回调异常只记录类别。新操作不得使用不支持撤销的旧认证状态绕过限制。

实施说明（2026-10-29）：

- 初始 `DRAFT → PENDING_VERIFICATION → PENDING_APPROVAL → APPROVED_INACTIVE` 是注册审批过程，不等同于停用；不创建外部凭据失效记录。已有可调用连接器进入不可调用状态，以及明确的暂停/撤销等入口，统一执行失效。
- 后补管理器不能证明此前未知租约已撤销，原 `unconfigured` 记录继续阻止恢复。更换管理器也不能清除同一注册表中的未完成状态。
- 适配器每个句柄每次请求最多 4 次尝试；默认每次等候 1 秒，重试退避 0.05/0.1/0.2 秒，最多 8 个尚未结束的撤销线程。超时不代表线程被终止，句柄继续保留；批量调用耗时与句柄数量有关。构造参数 `revoke_timeout_seconds`、`retry_delay_seconds` 可调整，必须是有限合法数值。
- `pending_count` 是待处理工作数量（含签发、授权准备和租约），不能当作唯一租约数。轮询不累加计数。查询和恢复不自动重发失败撤销；通过重复 `pause`/`revoke` 或直接失效请求重试。
- `get_revocation_status` / `resume_connector_credentials` 是提供方本地同步状态操作；提供方的网络撤销在 `revoke_connector_credentials` 内完成。装配其他提供方时须遵守这一约定。
- 协议预检已不可调用返回 `-32050`；通过预检后，在凭据等待期间失效，执行器失败沿用 `-32051`。二者都不会为被阻断调用发送传输请求或扣配额。

同一进程装配示例（复用既有注册表、策略引擎、PDP/CDP 和审批函数）：

```python
from src.security.mcp_connector_governance.authorization import (
    AuthorizationManager, SEC005CredentialProxyClient,
)
from src.security.mcp_connector_governance.execution import ToolExecutor
from src.security.mcp_connector_governance.lifecycle import LifecycleManager

proxy = SEC005CredentialProxyClient(
    pdp, cdp, approval_provider,
    agent_svid=agent_svid, worker_id=worker_id,
)
auth = AuthorizationManager(credential_proxy_client=proxy)
lifecycle = LifecycleManager(registry, authorization_manager=auth)
executor = ToolExecutor(policy_engine, authorization_manager=auth)

applied = lifecycle.pause(connector_id, "maintenance", "admin")
summary = lifecycle.get_credential_invalidation_status(connector_id, org_id=org_id)
# applied 只表示本地状态生效；检查 summary 的撤销状态及 audit_recorded。
resumed = lifecycle.resume(connector_id, "admin")
# resumed 为 True 后，新调用仍须重新经审批及 PDP/CDP 签发。
```

这不是新增 HTTP 管理 API 或生产启动装配；真实外部 OAuth/Vault、多进程传播、重启持久化仍不在本切片验收范围。

## 工具定义批准接口（2026-10-29 实施契约）

用户已确认 `sec007-tool-approval-schema-design-2026-10-29.md` 三点。本节先于生产实现定稿，仅增加单进程 Python 管理接口，不新增 HTTP 端点。

`ToolRegistry.bind_governance(connectors, *, authorizer=None, audit_logger=None, authorization_timeout=1.0)` 返回唯一 `ToolGovernance`；同一连接器注册表只能绑定同一工具注册表。授权回调是部署方注入的可信边界，缺失时不得签发批准。协议处理器自动连接注册表和 v2 执行器，但不会提供批准权限。

| 方法 | 契约 |
|---|---|
| `snapshot(org_id, connector_id)` | 返回不可变 `ManifestSnapshot`：组织、连接器、实际配置/签名身份修订、清单摘要、代次、是否完整、是否待复审、审计错误码；跨组织/未知目标统一抛 `GovernanceError("unavailable")` |
| `synchronize(org_id, connector_id, tools, *, expected_generation, actor, complete=True)` | 原子替换完整清单；首次登记待逐项批准；同一定义幂等；任何有效变化撤销整代批准并触发本地停止和凭据失效。部分/非法清单阻断旧缓存；迟到代次拒绝而不覆盖当前清单 |
| `mark_dirty(org_id, connector_id, *, expected_generation, actor)` | 接收可信发现适配层的已知变更/刷新失败信号；保留历史定义，但设为不完整、不可批准/执行，直到完整重同步 |
| `approve(snapshot, tool_name, definition_digest, *, actor, approval_ref, valid_until=None)` | 必须绑定当前修订/代次/摘要；可信回调接受不可变 `ApprovalRequest`，仅精确 `True` 批准。超时/异常/拒绝/缺失均不签发；关键审计成功且提交前快照仍相同才返回不可变 `ToolGrant` |
| `get_grant(org_id, connector_id, tool_name)` | 返回当前有效不可变批准或 `None`；缺少作用域的旧记录永不匹配；`now >= valid_until` 失效，naive 时间按 UTC 解释 |
| `revoke(org_id, connector_id, tool_name, *, actor)` | 本地立即撤销；即使审计失败也不恢复批准，快照暴露可重试错误。再次批准产生新 ID，旧在途调用不能复活 |
| `complete_review(snapshot, selected_tools, *, actor, approval_ref)` | 校验完整当前清单、选定工具有效批准及可信授权/关键审计；完成复审不自动激活。生命周期继续独立检查签名、凭据撤销等恢复条件；未选定工具保持隐藏 |
| `check_call(org_id, connector, tool)` / `revalidate(grant, connector, tool)` | 检查登记对象、组织、完整定义、当前批准、清单代次、连接器配置修订和状态；返回不可变批准或拒绝。不接受调用方的替换定义 |

管理操作错误使用不含原始定义、回调异常文本或凭据的 `GovernanceError.code`。业务错误包括 `unavailable`、`stale_snapshot`、`invalid_manifest`、`authorization_denied`、`audit_unavailable`、`invalid_approval`；绑定冲突及非法超时配置使用 `ValueError`。`review_required` 是快照状态字段。授权回调最长等待由有限正数超时控制，最多 8 个仍在运行的后台检查；迟到结果不得自行提交。

`definition_digest` 格式 `tool-v1:<sha256>`，覆盖完整 JSON 输入 Schema、原始附加定义字段、名称、描述、平台风险/能力和版本；严格 JSON 类型、有限数字、键排序规范化，数组顺序保留。旧 `schema_digest` 仅诊断。`register_tool/register_tools_batch/unregister_connector` 在装配治理后走相同变更门禁；旧无作用域 `approve_tool` 仅保留历史语义。

v2 `ToolExecutor(..., tool_registry=...)` 必须与协议使用同一工具注册表；签名/策略通过后、凭据等待前捕获批准，等待后在扣配额/交给传输前复核。未装配、过期、撤销、替换定义均拒绝。协议外部沿用 `-32050`（入口不可用）与 `-32051`（执行期拒绝）。发现先逐提供方检查批准，再裁剪及合并。

生命周期只在本地临界区更新状态和失效凭据，外部撤销在释放锁后完成；`RESTRICTED → PENDING_REVIEW` 合法。已暂停/撤销的连接器保留原状态及复审阻断。连接器配置更新/移除同样使现有工具批准失效，配置直接变异在下一次治理检查时被检测。部署方必须通过这些受控入口变更注册表。

恢复和回滚：现有工具需通过可信回调明确重批；本轮无数据库迁移。回滚代码会失去新增门禁，因此应先停止相应连接器；不能将恢复旧无作用域批准作为兼容开关。

普通暂停/恢复不改变已批准的工具定义；前项的凭据代次仍会拒绝旧在途调用。配置变更、工具变更或明确撤销后，则必须重新批准。审计失败恢复时，以相同完整清单和当前代次调用 `synchronize` 重试失效审计，再重新批准/完成复审；不能直接清除错误字段或改父状态。

### 装配与验证

以下为应用装配片段，`trusted_admin_review_check` 必须由宿主实现，核验真实审批主体、组织、操作和审批依据；它不是检查字符串标签后返回 True 的示例。先注入可信回调再创建处理器；若处理器先行绑定了空回调，可在同一注册表首次配置回调，之后不同回调对象重复绑定将拒绝。

```python
governance = tools.bind_governance(
    connectors, authorizer=trusted_admin_review_check,
    audit_logger=audit, authorization_timeout=1.0,
)
executor = ToolExecutor(policy_engine, authorization_manager=auth, tool_registry=tools)
handler = MCPProtocolHandler(tools, policy_engine, executor, connectors)

current = governance.snapshot(org_id, connector_id)
definition = tools.get_tool_for_connector(connector_id, tool_name)
grant = governance.approve(
    current, tool_name, definition.compute_definition_digest(),
    actor=verified_reviewer_id, approval_ref=verified_review_reference,
)
# 变更复审：先对本次选定工具逐项批准，再确认当前完整清单。
governance.complete_review(
    governance.snapshot(org_id, connector_id), selected_tool_names,
    actor=verified_reviewer_id, approval_ref=verified_review_reference,
)
# 恢复仍经过生命周期、签名和凭据撤销检查。
lifecycle.transition_to(connector_id, ConnectorLifecycleState.ACTIVE, "review complete")
```

本切片的可执行验证入口（项目根目录 PowerShell）：

```powershell
.venv/Scripts/python.exe -X utf8 -m pytest tests/test_mcp_tool_approval_schema.py -q
.venv/Scripts/python.exe -X utf8 -m nox -s lint typecheck
.venv/Scripts/python.exe -X utf8 -m nox -s security
$env:AI_AGENT_RUN_DOCKER_TESTS = '1'
.venv/Scripts/python.exe -X utf8 -m pytest -q
```

专项测试会自动启动并清理本机 HTTP 测试服务器；不要求外部密钥。本轮无新增环境变量、依赖或 HTTP 管理服务。既有主 API 启动方式见 [API README](./README.md)，它尚未装配本轮治理模块，不能把启动主 API 当作该功能已经对外发布。

