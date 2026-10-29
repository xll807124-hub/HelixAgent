# REQ-SEC-007 对标分析：需求验收标准 vs 当前实现

> 2026-10-28 增量核验：生命周期发现/调用切片已实现，专项 46、全量 2047 通过 / 3 跳过；[测试报告](../test-reports/sec007-lifecycle-2026-10-28.md)。后续依赖与扫描配置已获用户批准，真实 SAST/SCA/Secret 门禁通过，见[增量报告](../test-reports/sec007-security-gate-2026-10-28.md)；✅ 本切片已于 2026-10-29 获用户验收完成；下述其他历史缺口继续开放。

对照基准：`docs/design-specs/REQ-SEC-007-mcp-connector-governance.md` 第 4.13 节 AC1-AC16。

> 2026-10-29 凭据失效增量：按用户批准的单进程切片，生命周期已联动缓存代次、SEC-005 已登记租约撤销与恢复闸门；详见[本轮测试报告](../test-reports/sec007-credential-invalidation-2026-10-29.md)。原有生产启动装配、真实外部签发/撤销、多进程传播和持久审计缺口继续开放。本轮失效审计失败会阻止恢复，其他审计路径仍按下述历史边界记录。
依据：读取当前源码，以及用临时脚本实测（脚本已删除）。"未核实"表示我没有检查或测试过。

## 1. 结论

16 项验收标准中，模块层面基本满足 4 项（AC2、AC3、AC5、AC9），部分满足 10 项（含 AC15 调用闸门、AC11 出口基线、AC16 环境闸门），未满足或基本未接入 2 项（AC14、AC8）。

当前交付可以说是"治理组件库已具备且单元测试通过"，但还不能说"治理闭环已在执行路径上生效"。最大的问题是各组件之间的接线缺失（见第 3 节）。

## 2. 逐项对照

| 编号 | 状态 | 依据 |
|---|---|---|
| AC1 稳定身份/版本 | 部分 | `connector_id` 稳定；工具批准 `ToolApproval` 绑定 `schema_digest`。但 `ToolRegistry.is_approved` 在 `src` 内没有调用点，执行路径不检查批准。 |
| AC2 OAuth 2.1 | 基本满足（模块层） | `OAuth21Handler` 含 PKCE(S256)、state 校验（5 分钟过期）、audience 校验；`test_mcp_oauth_audience.py` 20 例。资源元数据发现未核实。执行器已接入凭据注入，生产装配未做（见 3.1）。 |
| AC3 API Key 过渡 | 基本满足（模块层） | 枚举与配置标记 `@deprecated`（sunset 2027-12-31），使用时写 warning；`AuditLogger` 对敏感键名脱敏，测试确认令牌不入审计。 |
| AC4 工具级授权 | 部分 | `tools/list` 按全局黑名单和组织裁剪过滤；`tools/call` 只允许调用该连接器自己提供的工具并复核黑名单与裁剪。但"已批准工具"不是放行条件（`is_approved` 无调用点）。 |
| AC5 签名 | 基本满足 | `check_signature_gate` 要求 L1/L2 持有效签名，且签名摘要与当前配置一致，配置被改即拒绝；缺失、篡改均有测试。逐工具 Schema 摘要是否纳入签名负载未核实。 |
| AC6 变更使批准失效 | 部分 | 配置变更对 L1/L2 会被签名闸门拦截。L3/L4 的 `requires_signature=False`，配置变更无拦截。`ToolRegistry.detect_schema_change` 存在但无调用点，Schema 变更不会触发待复审。 |
| AC7 L1-L4 分级 | 部分 | `TrustLevelConfig` 定义了配额权重、`allowed_production`、`requires_signature`。L4 现在由策略引擎的环境闸门拒绝（见 AC16）。但 `allowed_production` 字段本身仍然没有读取点，闸门是对 L4 硬编码的。该字段对 L3 也是 `False`，而需求 4.4 允许 L3 在受限条件下使用（只要求"隔离运行"），两者不一致；我没有改动该字段，也没有让 L3 受环境闸门限制，需要你确认 L3 的预期。L3 的"逐工具显式批准""精确目的地白名单"等约束未实现。 |
| AC8 权限交集 | 未接入 | 黑名单、组织白名单、能力裁剪、配额有交集逻辑；SEC-002 用户授权和 SEC-003 决策未接入 `PolicyEngine`。 |
| AC9 黑名单优先/白名单 | 基本满足 | `evaluate_connector_access` 先黑名单后白名单；`MCPProtocolHandler` 对黑名单做纵深防御；`test_mcp_handler_blacklist.py` 11 例。 |
| AC10 配额 | 部分 | `quota_weight` 按信任等级计权，扣减/退款已测。重复登记绕过、并发边界未核实。 |
| AC11 SSRF | 部分满足 | `HTTPExecutor` 默认严格：仅 https，拒绝凭据段，拒绝非公网字面量 IP（回环、私网、链路本地含 169.254.169.254、CGNAT、多播、保留段，及 IPv4-mapped / 6to4 / NAT64 内嵌形式）；连接时的解析器逐条校验解析结果，任一条非公网即整体拒绝；不跟随重定向；校验先于凭据发送。拒绝非规范数字主机写法；测试 76 项（`test_mcp_egress_guard.py`）。未做：按连接器登记的目的地白名单（需求 4.4 要求"仅登记端点"）、受控出口代理、STDIO 子进程的网络限制，见 3.5。 |
| AC12 审计可追溯 | 部分 | 事件含 actor、org、connector、tool、结果。缺 Task、Worker、Action、Trace、policy 版本字段。 |
| AC13 依赖故障 fail-closed | 部分 | 凭据签发路径 fail-closed（PDP/CDP/审批方任一失败即无凭据）；签名闸门、策略失败 fail-closed。**审计写入失败则被设计为不阻断调用**，这与需求"安全关键调用必须可靠提交或受控暂挂"不一致，是我在本次实现中做的取舍（见 3.4）。 |
| AC14 Auto-review | 未实现 | 代码中没有相关组件。 |
| AC15 暂停/撤销传播 | **部分满足** | 发现过滤、入口拒绝和凭据等待后的状态复核已补并实测；凭据失效、代次识别、跨进程与 Kill Switch 仍开放，见 3.2。 |
| AC16 L4 不入生产 | 部分满足 | `PolicyEngine(environment=...)`，默认 `PRODUCTION`。L4（及无法识别的等级，按 L4 处理）在生产环境一律拒绝；在 `ISOLATED_EVALUATION` 下，数据分级不是 L1/L2 的工具（含无法解析的值）拒绝，任何认证模式非 `NONE` 的连接器拒绝。拒绝时 `blocked_by="trust_level"`，发生在凭据准备和扣配额之前。环境是引擎的部署属性，调用方无法按次声明。测试 27 项（`test_mcp_l4_environment_gate.py`）。未满足的部分：没有真实的隔离评估环境（这里只是一个标记，没有网络隔离、VM 隔离或任何运行面隔离）；没有"测试凭据"概念，所以评估环境里 L4 干脆不允许任何凭据，比需求"使用测试凭据"更严；数据敏感度取自工具自报的 `data_sensitivity`，没有校验其真实性，也没有对实际入参/出参做内容检测；需求里"工具调用需显式审批"在评估环境中也没有接入（执行器不处理 `requires_human_approval`，只产生 warning）。 |

## 3. 关键缺口

### 3.1 凭据接入执行路径（已接入，仍有缺口）
`ToolExecutor` 现在接受 `authorization_manager`，在策略检查之后、扣配额之前调用 `prepare_credentials`，把令牌注入 HTTP 的 `Authorization` 头或 STDIO 的 `MCP_CONNECTOR_TOKEN` 环境变量。需要认证但没有管理器、凭据不可用、抛异常、或凭据无法注入（mTLS）时一律拒绝。测试见 `TestCredentialInjection`（9 项）。

仍有缺口：
- 所有现有调用点（含 `MCPProtocolHandler` 的装配）默认不传 `authorization_manager`，所以需要认证的连接器在没配置时会被拒绝，而不是静默无认证调用。生产装配尚未写。
- mTLS 的客户端证书绑定未实现，目前直接拒绝。
- STDIO 用环境变量传令牌，同机其他有权限的进程可能读到子进程环境；是否改用管道或文件描述符传递需要决定。
- HTTP 注入测试用 monkeypatch 替换了 `HTTPExecutor.execute`，没有经过真实 `aiohttp` 请求；真实 HTTP 注入路径的测试在 `test_mcp_http_executor.py`（本机 Python 3.10 未装 `aiohttp`，3.13 下可运行）里还没有认证用例。
- 没有用真实 OAuth 服务器或真实 Vault 验证。

### 3.2 撤销/暂停的连接器仍可执行（AC15）— 调用闸门已修复
修复前实测：对 L3 STDIO 连接器，`REVOKED`、`PAUSED` 状态下 `ToolExecutor.execute_tool` 都返回 `success=True`。

已修复：`PolicyEngine.evaluate_connector_access` 在全局黑名单之后检查 `connector.status.is_callable()`，仅 `ACTIVE` / `RESTRICTED` 放行，其余状态返回 `blocked_by="lifecycle"`，且不消耗配额。`evaluate_tool_invocation` 复用该检查，`ToolExecutor` 和经它执行的 `MCPProtocolHandler.tools/call` 因此都被覆盖。测试见 `TestLifecycleGate`（13 项）。

2026-10-28 增量：`tools/list` 只使用当前可调用提供方的定义和裁剪；同名歧义隐藏；`tools/call` 在入口拒绝不可用目标并记录审计；执行器凭据等待后复核状态。提供方定义快照避免同名串用，未知状态返回明确拒绝。真实 HTTP 联调验证暂停后零新增请求、恢复后可调用。

仍未解决（AC15 因此只算部分满足）：
- `LifecycleManager.revoke` 不撤销已签发凭据、不使缓存失效。
- 工具独立审批状态、连接器版本变化、跨进程传播及暂停后快速恢复的代次识别尚未闭环；本次只覆盖本进程尚未交给传输的调用。
- 组织禁用、Kill Switch 联动未接入。
- `RESTRICTED` 放行是沿用 `is_callable()` 既有语义，"受限"具体限制了什么尚未定义。

### 3.5 出口校验的边界（AC11）
实现位置：`execution/egress_guard.py`，由 `HTTPExecutor` 调用。`ToolExecutor(allow_private_networks=False)` 为默认值；设为 `True` 只放宽到 http 和私网地址，仍拒绝其他方案和凭据段，仅应用于本地开发和测试。现有 `test_mcp_http_executor.py` 因使用 127.0.0.1 测试服务器，已显式传 `True`。

这是黑名单式基线（拒绝已知危险地址），不是需求要求的"仅登记端点"白名单。边界：
- 公网主机名指向攻击者控制的公网服务时不会被拦截；这类风险要靠目的地白名单。
- 防重绑定依赖 aiohttp 在连接时调用解析器，且已关闭 DNS 缓存（`use_dns_cache=False`）；我没有对真实 DNS 做重绑定攻击测试，测试用的是注入的假解析器。
- 重定向一律不跟随，返回 `blocked_by="egress"`；合法连接器如果依赖重定向会失败。
- 环境代理变量（`HTTP_PROXY` 等）：aiohttp 默认不读取（`trust_env=False`），未改动；若日后启用代理，目的地校验会变成对代理地址的校验，需要重新设计。
- STDIO 子进程不受此校验约束，可自行联网。
- 实测发现的绕过已修复：aiohttp 3.11.10 的 `is_ip_address` 把"全数字加点"的主机（`2130706433`、`127.1`、`0177.0.0.1`）当 IP 直连，**跳过解析器**，所以只靠解析器校验会漏掉 `https://2130706433`（= 127.0.0.1）。现在 `validate_endpoint` 对所有非规范数字写法（十进制、八进制、十六进制、缺段、末尾点）一律拒绝。这条规则依赖 aiohttp 当前版本的行为；升级 aiohttp 后应重跑 `test_mcp_egress_guard.py`。
- IPv6 zone id（`%eth0`）只在 `is_blocked_address` 里测了，没有经 URL 端到端测试。

### 3.3 SEC-005 令牌为示例实现
`CredentialCDP._mint_token` 返回 `token_xxx` 形式的假令牌。适配器已按真实接口对接并有测试，但在 SEC-005 接入真实 Vault 前，签发出的凭据不可用于真实连接器。

### 3.4 审计失败不阻断调用
`LifecycleManager`、`AuthorizationManager`、`ToolExecutor` 在审计写入失败时只记日志。好处是审计故障不会拖垮业务；代价是可能出现"有副作用但无审计记录"。是否改成 fail-closed 需要产品决策。

## 4. 建议的后续任务（按优先级）

1. 生命周期调用闸门已有；2026-10-28 发现过滤和等待后复核已通过功能验证，本轮安全扫描已通过，✅ 本切片已于 2026-10-29 获用户验收（全量 2100 通过 / 3 Docker 跳过）。后续候选：撤销时使凭据/缓存失效。
2. 在 `ToolExecutor` 前置检查中加入 `ToolRegistry.is_approved` 与 Schema 摘要复核；`detect_schema_change` 命中时调用 `LifecycleManager.mark_for_review`。
3. （基线已完成）出口校验。后续：按连接器/组织登记目的地白名单，受控出口代理，STDIO 网络限制。
4. （环境闸门已完成）后续：真实隔离评估环境与测试凭据，确认 L3 的生产策略并让 `allowed_production` 真正生效。
5. （执行器已接入）在生产装配中提供 `authorization_manager`，并决定 mTLS 与 STDIO 令牌传递方式。
6. 补审计字段（Task、Worker、Action、Trace）并决定审计失败策略。
7. SEC-002 / SEC-003 接入 `PolicyEngine`；Auto-review 单独立项。

## 5. 竞品与规范参考的使用边界

需求文档第 3 节已说明，L1-L4 矩阵、配额计权属于本项目设计决策，不是竞品公开事实。本分析未重新核验竞品文档，竞品能力以需求文档第 3 节为准。
