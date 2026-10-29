# 阶段 0：Runtime / Security 设计—代码对齐评审

> 评审日期：2026-10-28（Asia/Shanghai）
>
> 状态：✅ 评审文档于 2026-10-28 验收（交付后用户回复“继续”）。验证摘要：60 项需求、341 本地链接通过，2001 测试通过 / 3 跳过。以下缺口继续开放；未批准 Security 新冻结。
>
> 旧 v0.1 清单中的“凭据最长两小时”“M2 停用工具”“统一缓存五分钟”等推测已经撤回。本次只采用专项原文、源码与实际验证结果；不保留其作为当前决策依据。历史原文仍可由 Git 追溯。

## 1. 依据与判定方式

- 开发顺序：[执行手册正文](../../项目开发执行手册.md)。
- 设计状态：RT-001 v0.2-frozen、RT-002～008 v0.1-frozen，均保留 2026-10-07 冻结记录；SEC-001～010 为 designed，作为本轮评审目标，后续冻结仍需明确批准。
- 方案与完整功能清单：[阶段 0 评审记录](../review/roadmap-status-and-stage0-proposal-2026-10-28.md)。
- 本轮检查：[测试与扫描报告](../test-reports/stage0-alignment-2026-10-28.json)。
- “已对齐”仅限表中明确核查的字段/行为；“实现缺口”记录源码与设计差异；“验证不足”表示真实环境或完整验收证据缺失。已有单测通过不能覆盖未实现的条件。

## 2. 共享接口与调用边界矩阵

| ID | 边界与设计依据 | 代码定位及观察 | 测试证据与判定 | 正文归属 |
|---|---|---|---|---|
| A01 | [RT-001 §5.4](./REQ-RT-001-core-runtime-entities.md)：Action 的父级、step、trace、版本坐标 | [Action:66](../../src/runtime/entities/action.py#L66) 含 task/workflow/worker/step/trace、tool_schema_version，实体层校验 ID 与 trace | 相关 Runtime 单测纳入本轮 2001 通过；字段形状已有，跨模块绑定继续见 A02/A04/A15 | 1.2 |
| A02 | [RT-003 验收条件](./REQ-RT-003-event-schema-versioning.md)：非法 ID/版本等拒绝 | [EventEnvelope:203](../../src/runtime/event_store/envelope.py#L203) 构造校验未检查 ID/trace 格式；离线构造传入 invalid-id/invalid-trace 被接受 | **实现缺口**；本次复现的是构造边界，不声称所有上游调用都会传入非法值；后续补拒绝用例 | 1.1/1.2 |
| A03 | [RT-003](./REQ-RT-003-event-schema-versioning.md)、手册 1.1：事件事实持久化 | [EventStore:94](../../src/runtime/event_store/store.py#L94) 有接口，[InMemoryEventStore:208](../../src/runtime/event_store/store.py#L208) 为现有实现；模块注释中的 PostgreSQL 名称不等于代码 | [存储测试](../../tests/unit/runtime/event_store/test_store.py)验证内存路径；**持久化实现/真实 DB 验证不足** | 1.1 |
| A04 | [RT-001 §5.4](./REQ-RT-001-core-runtime-entities.md)：执行前必须有 policy_decision_id；[SEC-003](./REQ-SEC-003-policy-gateway.md)：前后置决策 | [ActionExecutor:277](../../src/tools/executor.py#L277) 调用前置网关、后续调用后置网关；[基础 PolicyResult:22](../../src/security/policy_gateway/base.py#L22) 没有结构化决策 ID，执行器未绑定该 ID 即进入工具调用 | [执行器测试](../../tests/unit/tools/test_executor.py)覆盖拒绝/审批/成功；**决策引用与生产网关装配缺口**。V2 evaluate 接口不能视作基础 pre/post 接口已自动集成 | 1.2/1.3 |
| A05 | [SEC-003 决策语义](./REQ-SEC-003-policy-gateway.md)：ALLOW / REQUIRE_APPROVAL / DENY | [基础枚举:15](../../src/security/policy_gateway/base.py#L15) 使用 REQUIRES_APPROVAL，执行器依此分支 | **接口命名差异**；后续需明确适配/序列化映射与契约测试。本轮不改既有公共枚举或设计字段 | 1.3 |
| A06 | [SEC-003 §8、AC10](./REQ-SEC-003-policy-gateway.md)：风险差异 TTL，变更失效/直查 | [V2 Cache:147](../../src/security/policy_gateway/gateway_v2.py#L147) 默认 300s；[evaluate:264](../../src/security/policy_gateway/gateway_v2.py#L264)统一缓存结果。已包含授权快照、参数及有效期校验，但无按风险选择 TTL 的分支 | [V2 单测](../../tests/unit/security/policy_gateway/test_gateway_v2.py)及[已有回归](../../tests/unit/security/test_completed_function_regressions.py)通过；**差异化 TTL/完整失效路径待补**。设计原文低风险只读 5～15min，高风险/写 30～60s 或直查，不能概括为统一 5min | 1.3 |
| A07 | [SEC-009 §3/4](./REQ-SEC-009-kill-switch-incident-response.md)：M0～M5 与 NORMAL/DEGRADED/LOCKED | [state.py:19](../../src/security/kill_switch/state.py#L19)仅 IDLE/TRIGGERED/RECOVERING，作用域仅 GLOBAL/ORGANIZATION/PROJECT/REPOSITORY；没有完整设计模式 | [状态测试](../../tests/unit/security/kill_switch/test_state.py)和[集成测试](../../tests/unit/security/kill_switch/test_integration.py)验证的是简化模型；**设计模式、降级状态、传播与恢复演练待实现/验收** | 2.3 |
| A08 | [SEC-005 §2/4](./REQ-SEC-005-credential-proxy.md)：PDP 签名批准，CDP 执行签发 | [CDP:310](../../src/security/credential/pdp_cdp.py#L310)接受 tuple[bool, reason, scope]；[请求:47](../../src/security/credential/pdp_cdp.py#L47)带 policy_approval_ref | [PDP/CDP 单测](../../tests/unit/security/credential/test_pdp_cdp.py)覆盖本地控制；**跨进程身份/审批签名与可信引用验证待补**，不能把布尔结果等同完整生产授权证明 | 1.3 |
| A09 | [SEC-005 §4.1](./REQ-SEC-005-credential-proxy.md)：服务上限与 max_ttl_seconds 取小 | [CDP:338](../../src/security/credential/pdp_cdp.py#L338)只使用单独 requested_ttl_seconds 参数及服务默认值，未读取请求内 max_ttl_seconds | 离线请求 max_ttl_seconds=60、未传单独参数，观测租约 3600s；**实现缺口**。MCP [适配器:155](../../src/security/mcp_connector_governance/authorization/credential_adapter.py#L155)另传参数，不能据此声称该适配器路径也出现同一超限 | 1.3 |
| A10 | [SEC-005 §4](./REQ-SEC-005-credential-proxy.md)：通过实际服务代理铸造短期令牌 | [_mint_token:451](../../src/security/credential/pdp_cdp.py#L451)明确是示例字符串；单独 [GitHubCredentialProxy](../../src/security/credential/github_proxy.py)已具有 HTTP 实现 | [GitHub 契约测试](../../tests/unit/security/credential/test_github_contract.py)通过不能证明 CDP 已连接真实服务；**CDP 装配缺口**，不得生产冻结 | 1.3 |
| A11 | [SEC-004](./REQ-SEC-004-sandbox-isolation-baseline.md)：能力声明、风险路由及实际隔离 | [SandboxRouter:100](../../src/security/sandbox/router.py#L100)、[能力契约](../../src/security/sandbox/contracts.py)已有；[Docker:181](../../src/security/sandbox/docker_sandbox.py#L181)出口白名单抛未实现，[escape:268](../../src/security/sandbox/docker_sandbox.py#L268)同样未实现 | [路由测试](../../tests/unit/security/sandbox/test_router.py)、[SDK 回归](../../tests/unit/security/sandbox/test_docker_runtime_regressions.py)通过；3 个真实 Docker 用例跳过；**能力联合验证和真实隔离缺口** | 1.3 |
| A12 | [RT-008](./REQ-RT-008-event-query-retention-redaction-permission.md)：范围过滤、分页、脱敏 | [EventQueryService:98](../../src/runtime/query/event_query.py#L98)先权限检查，读取后核对 task/org/project/repository；序列快照分页；不含 payload 时返回空载荷 | [存储链路回归](../../tests/unit/runtime/query/test_store_integration.py)、[递归脱敏回归](../../tests/unit/runtime/query/test_redaction_regressions.py)通过；**该局部行为已对齐**，不外推为留存/归档完成 | 阶段 0 局部修复；1.2 |
| A13 | [RT-006](./REQ-RT-006-Trace-传播和审计关联.md)、[SEC-005](./REQ-SEC-005-credential-proxy.md)、[OBS-007](./REQ-OBS-007-audit-retention-integrity.md)：关联与不可变审计 | [V2 审计:374](../../src/security/policy_gateway/gateway_v2.py#L374)、[CDP:365](../../src/security/credential/pdp_cdp.py#L365)存内存列表；[MCP AuditLogger:49](../../src/security/mcp_connector_governance/audit/audit_logger.py#L49)为独立日志结构 | 局部日志测试存在；**统一 EventStore/trace 关联、持久性、完整性与留存待验收**。追加列表或 JSON 文件不能直接证明防篡改存储 | 2.2 |
| A14 | [SEC-007](./REQ-SEC-007-mcp-connector-governance.md)→[SEC-005](./REQ-SEC-005-credential-proxy.md)：审批与凭据 | [SEC005CredentialProxyClient:98](../../src/security/mcp_connector_governance/authorization/credential_adapter.py#L98)要求 approval_provider、审批引用、正 TTL；异常拒绝 | [适配器回归](../../tests/test_mcp_audit_and_sec005_adapter.py)通过；**局部拒绝边界已有**。生产 provider、真实 CDP、撤销传播、Schema 复审见[合规清单](../delivery-reports/REQ-SEC-007-compliance-analysis.md) | 阶段 0 优先补缺 / 2.1 |
| A15 | [RT-001 身份坐标](./REQ-RT-001-core-runtime-entities.md)、[SEC-008](./REQ-SEC-008-multi-tenant-data-governance.md)：资源作用域不得混同 | [ActionExecutor:229](../../src/tools/executor.py#L229)向 Kill Switch 传 repository_id=context.task_id | **实现缺口**：task_id 不能代替 repository_id；需在后续任务补同项目不同仓库及任务场景测试，不能由 org/project 查询测试推出全部隔离完成 | 1.3/2.3/2.4 |
| A16 | [RT-005](./REQ-RT-005-checkpoint-protocol.md)、[RT-007](./REQ-RT-007-idempotency-key.md)：恢复及副作用去重 | [InMemoryCheckpointStorage:103](../../src/runtime/checkpoint/manager.py#L103)、[InMemoryIdempotencyStorage:111](../../src/runtime/idempotency/storage.py#L111)已有；Worker 另有 JSON checkpoint | 内存单测及本地恢复不等于跨进程权威账本、事务恢复；**持久化与故障注入验证不足** | 1.2 |

以上来源行号对应 2026-10-28 工作区。源码在本轮保持不变；复核时优先按符号定位，避免以后行号漂移。

## 3. 本轮离线最小复核记录

这些复核只构造进程内对象，无外部服务调用，未输出令牌内容。结果用于确认缺口，不是生产安全验收通过。

| 复核 | 输入/操作 | 实际观察 | 后续修复目标 |
|---|---|---|---|
| EventEnvelope 构造校验 | event_type=ReviewProbe，payload_schema=review.v1，event_id/task_id=invalid-id，trace_id=invalid-trace | 构造成功 | 根据 RT-003 拒绝非法标识，并核验写入边界 |
| CDP TTL 上限 | github 请求 max_ttl_seconds=60，PDP 本地允许，未另传 requested_ttl_seconds | 租约约 3600s | 服务上限、请求上限及调用参数共同取小，补边界测试 |
| Kill Switch 模型 | 枚举 KillSwitchState 与 KillSwitchScope | 三个简化状态、四个作用域 | 实现设计中的模式/运行状态/作用域并提供迁移兼容方案 |
| Policy 缓存 | 构造默认 PolicyDecisionCache | ttl_seconds=300 | 按风险区分且校验撤销/版本失效；不擅自把 300s 写成设计统一要求 |

## 4. Security 条件冻结建议（未批准）

本轮只有 RT 既有冻结记录被确认保留。下列是待后续决议的建议，不能据此把 SEC 页改为 frozen。

| 范围 | 建议 | 必须先关闭/明确的条件 |
|---|---|---|
| SEC-001 威胁模型 | 待评审 | 统一风险词表与各网关/检测器映射、实际控制证据 |
| SEC-002 RBAC | 可提交已测授权模型作限定范围评审 | 持久授权、资源坐标绑定、撤销与租户边界 |
| SEC-003 Policy Gateway | 暂缓生产冻结 | 决策 ID、审批枚举映射、网关装配、差异化缓存与审计 |
| SEC-004 Sandbox | 暂缓生产冻结 | 真实环境测试、出口白名单、逃逸验证和能力声明一致性 |
| SEC-005 Credential Proxy | 暂缓生产冻结 | 实际服务铸造、可信审批证明、TTL 上限、撤销传播与审计持久化 |
| SEC-006 Prompt 防护 | 保留历史验收，完整设计冻结另评审 | 历史交付范围之外的恶意仓库/红队/端到端验收不能自动视作完成 |
| SEC-007 MCP 治理 | 暂缓生产冻结 | 生产授权 provider、真实凭据、Schema 重审、撤销失效与隔离环境 |
| SEC-008 多租户 | 待评审 | 资源坐标、数据/计算/密钥隔离与完整泄露测试 |
| SEC-009 Kill Switch | 暂缓生产冻结 | 完整模式、降级状态、范围语义、Break-Glass 与传播演练 |
| SEC-010 安全控制验证 | 待评审 | 真实扫描、红队场景和门禁；本轮 SCA 漏洞记录处理 |

条件冻结必须明确具体版本、允许实现的范围、阻塞项、验证方式和用户决议日期；不会用“若干单测通过”代替这些条件。

## 5. 质量门槛与现状

用户已于 2026-10-28 确认：总体行覆盖 ≥70%、核心 ≥90%、分支 ≥60%；鉴权/授权、Policy Gateway、幂等键、Checkpoint、审计写入指定关键路径 100% 行覆盖。实际扫描缺失不算通过。

本轮全量回归 2001 通过、0 失败、3 跳过；行覆盖 85.56%、分支 73.80%。Ruff 0 诊断，mypy 196 个源文件 0 错误。总体指标不能替代逐关键路径门槛；对应路径尚未全部达标/验收。

SCA 实际扫描报告 6 包共 68 条已知漏洞记录；未据此推断全部为高危，分级和修复仍开放。项目可编辑分发包按约定跳过，其已安装依赖仍被扫描。SAST/Secret 工具缺失，记未验收；3 个 Docker 用例亦未验收。证据与命令见[测试报告](../test-reports/stage0-alignment-2026-10-28.json)。

## 6. 交付与后续

本清单交付的是已核查的接口事实、实现缺口、条件冻结建议与证据。生产代码缺口仍保留在各正文任务下，不标为已修复。

阶段 0 / 步骤 1 在用户验收前保持进行中。验收后重新读取手册，核定阶段 0 剩余优先缺口中的下一项，并为该单项提交设计确认。CTX-008 原文恢复和 Web 控制台任务归属均作为开放事项保留。
