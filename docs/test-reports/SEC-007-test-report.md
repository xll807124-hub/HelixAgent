# SEC-007 MCP 连接器治理 测试报告

日期：2026-10-26
环境：Windows 11、Python 3.13.15、pytest（`-W ignore::DeprecationWarning`）

## 1. 结果

| 范围 | 通过 | 失败 | 跳过 |
|---|---|---|---|
| SEC-007 专项（14 个文件） | 348 | 0 | 0 |
| 全量 `pytest` | 1852 | 0 | 7 |

全量的 7 个跳过用例位于 `tests/unit/security/sandbox/test_docker_sandbox.py`，原因是需要 Docker 环境，与 SEC-007 无关。

## 2. 专项测试分布

| 文件 | 用例数 | 主要内容 |
|---|---|---|
| `test_mcp_audit_and_sec005_adapter.py` | 29 | 生命周期/授权/刷新审计；SEC-005 适配器各失败路径 |
| `test_mcp_auth_manager.py` | 28 | OAuth/STDIO/API Key 凭据准备 |
| `test_mcp_capability_trim.py` | 36 | 方法与参数级能力裁剪 |
| `test_mcp_governance_day1.py` | 13 | 模型与注册表 |
| `test_mcp_governance_day2.py` | 9 | 策略引擎与配额 |
| `test_mcp_governance_day3.py` | 16 | 协议处理与执行 |
| `test_mcp_handler_blacklist.py` | 11 | 黑名单在 `tools/list`、`tools/call` 的纵深防御 |
| `test_mcp_http_executor.py` | 5 | HTTP 执行器（本地服务器，`allow_private_networks=True`） |
| `test_mcp_egress_guard.py` | 76 | SSRF：地址分类（含 IPv6 内嵌形式）、endpoint 校验、解析器、重定向、经执行器的端到端 |
| `test_mcp_lifecycle_signature.py` | 21 | 生命周期状态机与签名闸门 |
| `test_mcp_oauth_audience.py` | 20 | PKCE、state、audience |
| `test_mcp_signature_verification.py` | 20 | 签名验证 |
| `test_mcp_tool_executor_v2.py` | 37 | 签名闸门、退款、审计、真实 STDIO、生命周期闸门（13）、凭据注入（9） |
| `test_mcp_l4_environment_gate.py` | 27 | AC16：L4 生产拒绝、未知等级按 L4、评估环境内敏感数据与凭据限制、经执行器不触达凭据与配额 |
| 合计 | 348 | |

## 3. 本次新增测试（29 例）

- 生命周期审计（7）：成功转换、激活/撤销事件类型、非法转换记 `denied`、签名闸门拦截记 `denied` 且不出现"已激活"事件、审计异常不阻断转换、无 `audit_logger` 仍可用。
- 授权审计（4）：授予/拒绝记录、审计异常不改变凭据结果、刷新审计且不含令牌值。
- SEC-005 适配器（16）：真实 `CredentialPDP/CDP` 签发；TTL 受适配器上限和服务类型上限约束；PDP 拒绝（Gateway/RBAC 各一）；作用域越界；缺审批引用；审批方异常不泄漏消息；审批方返回无效类型；CDP 不健康；CDP 无令牌内容时撤销租约；4 种非法参数；构造参数校验。
- 端到端（2）：适配器接入 `AuthorizationManager` 后签发与拒绝。

## 4. 覆盖率

命令：`pytest <12 个专项文件> --cov=src/security/mcp_connector_governance`。
这只统计专项测试，不含其他目录里可能覆盖到该包的测试。

整体 68%（2478 语句，未覆盖 789）。

| 模块 | 覆盖率 | 备注 |
|---|---|---|
| `authorization/credential_adapter.py` | 94% | 新增 |
| `policies/capability_trimmer.py` | 98% | |
| `registry/signature_verifier.py` | 95% | |
| `execution/tool_executor_v2.py` | 88% | |
| `protocol/mcp_handler.py` | 83% | |
| `lifecycle/lifecycle_manager.py` | 74% | |
| `authorization/auth_manager.py` | 74% | |
| `audit/audit_logger.py` | 77% | |
| `registry/tool_registry.py` | 54% | |
| `registry/connector_registry.py` | 57% | |
| `authorization/oauth_handler.py` | 45% | 令牌交换、`TokenManager` 缺测 |
| `protocol/transport.py` | 35% | |
| `persistence/repository.py` | 32% | 需要数据库 |
| `execution/tool_executor.py` | 0% | 旧版 v1，疑似被 v2 取代 |
| `models/base.py` | 0% | 未被任何测试导入 |

## 5. 未验证的内容

- 生命周期闸门已修复并有测试（`PolicyEngine` 仅放行 `ACTIVE` / `RESTRICTED`）。但"撤销时使凭据/缓存失效"、"工具级独立状态"、Kill Switch 联动仍未实现也未测试，AC15 只是部分满足。详见对标分析 3.2。
- SSRF 测试使用注入的假解析器和本地重定向服务器，没有对真实 DNS 做重绑定测试，也没有测试目的地白名单（未实现）。
- AC16 测试验证的是策略决策，没有真实的隔离评估环境可测（环境只是引擎上的一个标记）。
- 没有 Schema 变更触发复审、并发配额的测试，对应能力在代码中也不存在。
- 没有真实 Vault、真实 OAuth 服务器、真实 SPIRE 的集成测试；SEC-005 的令牌生成是示例实现。
- 没有运行 ruff、mypy 或其他静态检查。
- 没有性能或延迟测试。

## 6. 复现

```powershell
$files = (Get-ChildItem tests -Filter test_mcp_*.py | ForEach-Object { "tests/" + $_.Name })
python -m pytest $files -q -W ignore::DeprecationWarning
python -m pytest -q -W ignore::DeprecationWarning
```
