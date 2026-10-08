# REQ-SEC-005：凭据代理

> 需求编号：`REQ-SEC-005`  
> 优先级：P0  
> 所属模块：安全（SEC）  
> 设计版本：`v0.1-designed`  
> 状态：详细设计已完成，待跨模块评审与冻结；未实现、未验证  
> 前置依赖：`REQ-SEC-002`、`REQ-SEC-003`  
> 下游依赖：`REQ-REL-005`、`REQ-SEC-009`、`REQ-HAR-003`  
> 设计日期：2026-09-23  
> 用户确认决策：Vault 单云优先云厂商托管（AWS/Azure/GCP），多云考虑 HashiCorp Vault；首批支持 GitHub App + AWS STS（OIDC）+ 通用 OAuth 2.0；Model C MVP 不实现仅留桩；OIDC 联合 MVP 必选；DPoP 预留渐进路线；CDP 多实例 active-active

---

## 1. 需求定义

### 1.1 目标

为 AI Agent 平台提供安全、可审计的凭据生命周期管理。核心原则：**Agent 不持有长期凭据**，通过 Capability Token 按需获取严格限定范围和有效期的短期凭据；在任务结束、权限撤销或 Kill Switch 触发时，通过标准化撤销协议实现即时分布式撤销。

### 1.2 问题与用户价值

原待办仅提出"Capability Token、短期凭据、撤销协议"三个关键词，无结构化描述，导致以下问题：缺少 PDP/CDP 架构导致与 Policy Gateway 无法对齐；撤销传播机制缺失导致 Kill Switch 后凭据无法全局撤销；Vault 存储未定义导致凭据静止时安全性无保障；按服务差异化策略缺失导致无法支持多类型外部服务；异常和降级策略未定义导致可靠性无法保证。

设计目标是让组织管理员获得可追溯的凭据使用记录和即时生效的撤销能力；让任务发起者在授权范围内自动获取所需凭据，无需感知凭据管理细节；让安全团队实现零长期凭据暴露、极小爆炸半径和完整审计链；让平台消除凭据散布风险并满足合规要求。

### 1.3 范围

包含：PDP/CDP 架构分离；Capability Token Schema（Request/Response）；三种代理模型及选择策略（Model A/B，不含 Model C）；按目标服务类型的差异化策略路由（GitHub App / AWS STS OIDC / 通用 OAuth 2.0）；短期令牌铸造与租约管理；分布式撤销传播协议；Vault 集成（单云云厂商托管优先）；OIDC 联合身份（AWS STS + GitHub OIDC）；CDP 多实例 active-active 高可用；审计事件；可观测指标；Fail-secure 语义。

不包含：Model C 凭据包装（遗留 API 支持），仅保留接口桩；DPoP 发送方约束（接口预留，渐进式启用）；多云 HashiCorp Vault 高级特性；行为基线与异常检测；细粒度 scope 协商。

### 1.4 设计不变量

1. Agent 进程从不持有根凭据或长期凭据，仅持有 CDP 签发的短期 Capability Token。
2. 每个 Capability Token 的 scope 精确限定到单资源、单操作，不得超出 Policy Gateway 审批范围。
3. 租约不可续期，TTL 到期必须重新请求，不能通过刷新延长有效期。
4. CDP 不可用时 fail-secure：拒绝所有新签发请求，不使用陈旧缓存放行。
5. 所有签发、拒绝、撤销事件必须写入不可变审计日志，审计记录不含 issued_token 内容。
6. 撤销事件在所有 Agent 实例间传播，传播延迟不超过 5 秒。
7. 审计事件仅记录 token_id、service、scope、task_id、user、timestamp，不记录凭据内容。
8. CDP 无状态设计，支持多实例 active-active 部署，单实例故障不导致全局阻断。

---

## 2. 共享概念与架构模型

### 2.1 PDP/CDP 分离原则

Credential Proxy 采用 Policy Decision Point（PDP）与 Credential Delivery Point（CDP）严格分离架构：

- **PDP**（Policy Decision Point）：无凭据材料访问权，仅负责授权决策。接收 Task Request Envelope，验证 agent_identity（通过 SPIRE SVID），校验请求是否在 RBAC 授权范围和 Policy Gateway 审批范围内，输出带签名的审批决策。PDP 不得访问 Vault 或持有任何凭据材料。
- **CDP**（Credential Delivery Point）：无策略制定权，仅负责凭据铸造和分发。接收 PDP 签发的审批决策，从 Vault 获取根凭据，铸造短期派生令牌，注册租约，返回 Capability Token 给 Agent。

分离价值：任意一方被攻陷不直接泄漏凭据材料；策略评估与凭据操作独立扩展；满足 NIST SP 800-207 Zero Trust 架构中的 PDP/PEP 分离原则。

### 2.2 三种代理模型及选择策略

| 模型 | Agent 接触凭据 | 延迟 | 适用场景 | 选用状态 |
|------|--------------|------|---------|---------|
| **Model A：代理网关** | 从不接触真实凭据，CDP 代为转发请求 | 高（双跳） | DPoP 强制层、高安全隔离需求 | MVP 保留作为 AWS/GCP/Azure OIDC 联合身份的代理路径 |
| **Model B：短期令牌铸造** | 持有短期派生令牌（TTL 秒~分钟） | 低（一次性铸造） | GitHub App、AWS STS、通用 OAuth | **MVP 主要模式** |
| **Model C：凭据包装+定时撤销** | 持有真实凭据但定时撤销 | 无 | 遗留 API（无短期令牌支持） | MVP 不实现，仅保留接口桩（标记 @deprecated） |

### 2.3 Task Request Envelope

每次凭据请求，Agent 构造 Task Request Envelope 作为结构化证据信封：

```
{
  "envelope_version": "1.0",
  "agent_svid": "<SPIFFE SVID reference>",
  "request_id": "<UUID>",
  "timestamp": "<ISO-8601>",
  "target": {
    "service": "github|aws|slack|...",
    "action": "read|write|admin|...",
    "resource": "<resource identifier>",
    "scope": ["specific scope items"]
  },
  "justification": {
    "task_id": "<originating task reference>",
    "description": "<human-readable reason>"
  },
  "ttl_seconds": 60,
  "policy_approval_ref": "<SEC-003 approval reference>",
  "signature": "<SVID-signed envelope hash>"
}
```

关键约束：`justification.description` 字段**仅用于审计重建**，Policy 决策**不使用此字段**。Approval 基于：(1) agent_identity (SVID) 验证；(2) 目标服务/操作/scope 与策略匹配；(3) policy_approval_ref 有效性。

### 2.4 OIDC 联合身份

MVP 必选零密钥架构地基：

- **AWS STS**：通过 OIDC Workload Identity Federation，Agent 获取 AWS IAM 短期安全令牌，无需存储 AWS Access Key。CDP 使用 AWS STS AssumeRoleWithWebIdentity，Vault 持有 OIDC Provider 信任配置（Issuer URL + JWKS）。
- **GitHub OIDC**：通过 GitHub OIDC Provider，Agent 获取 GitHub Actions 风格的工作负载身份令牌，Vault 持有 GitHub App Private Key。
- **通用 OAuth 2.0**：支持 client credentials 流程，Vault 持有 client_secret，支持刷新令牌自动轮换。

---

## 3. Capability Token Schema

### 3.1 Capability Token Request

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `task_id` | UUID | 是 | 关联的任务唯一标识 |
| `target_service` | string | 是 | 目标服务类型：github / aws / gcp / azure / generic_oauth / postgres |
| `target_resource` | string | 是 | 目标资源标识（仓库名/ARN/数据库名） |
| `requested_action` | string | 是 | 操作类型：read / write / admin |
| `requested_scope` | string[] | 否 | 请求的作用域列表 |
| `justification` | object | 是 | 操作理由，仅用于审计 |
| `max_ttl_seconds` | integer | 否 | 请求的最大 TTL，默认值按服务类型配置 |
| `policy_approval_ref` | string | 是 | SEC-003 Policy Gateway 审批引用 |
| `dpop_public_key` | string | 否 | DPoP 公钥（PEM/SPKI），MVP 预留 |

### 3.2 Capability Token Response

| 字段 | 类型 | 说明 |
|------|------|------|
| `token_id` | UUID | 令牌唯一标识 |
| `issued_token` | string | 实际短期凭据（Token/JWT/Key） |
| `token_type` | enum | github_app_token / aws_sts_token / gcp_token / oauth_token / proxy_token |
| `scope` | string[] | 最终授予的精确作用域（可能窄于请求） |
| `expires_at` | ISO-8601 | 绝对过期时间 |
| `service_endpoint` | string | Model A 代理模式时的 CB4A 代理地址；Model B 时为空 |
| `audit_ref` | string | 本次签发的审计记录引用 |
| `dpop_fingerprint` | string | DPoP 公钥指纹（MVP 预留） |

---

## 4. 处理逻辑与流程

### 4.1 完整签发流程

**步骤 1：请求接收与基础校验**
- Credential Proxy 接收来自 Worker 的 Capability Token Request。
- 验证 `policy_approval_ref` 有效性（调用 SEC-003 验证接口），无效则拒绝。
- 验证 `task_id` 归属当前 Agent 上下文且未被撤销。
- 解析 `target_service`，选择对应的凭据策略处理器。

**步骤 2：Agent 身份验证**
- 通过 SPIRE SVID 验证 `agent_identity`，无效则拒绝。
- 验证 SVID 未过期且对应有效的 Agent 实例。

**步骤 3：RBAC 授权校验**
- 调用 SEC-002 授权服务，校验请求者是否在 `target_resource` 上具有 `requested_action` 权限。
- 授权结果作为 scope 上限约束。

**步骤 4：Scope 协商与 TTL 截断**
- 按 `target_service` 的凭据策略，确定最终 `scope`（可能自动窄于请求）。
- TTL 上限按服务类型配置并与 `max_ttl_seconds` 取较小值：
  - GitHub App Token ≤ 3600s（1h）
  - AWS STS Token ≤ 900s（15min）
  - GCP Token ≤ 3600s（1h）
  - 通用 OAuth Token ≤ 1800s（30min）
  - Model A 代理会话 ≤ 300s（5min）

**步骤 5：Vault 凭据获取**
- CDP 从云厂商托管 Vault（AWS Secrets Manager + KMS / Azure Key Vault / GCP Secret Manager）获取根凭据。
- Vault 连接使用 TLS 内部网络，根凭据在 Vault 中静态加密，CDP 进程内存中不解密缓存。

**步骤 6：短期令牌铸造（Model B）**
- **GitHub App**：调用 GitHub API `/app/installations/{id}/access_tokens`，scope 精确到 repo + permissions。
- **AWS STS**：调用 AssumeRoleWithWebIdentity，session policy 精确到角色 + 资源。
- **通用 OAuth 2.0**：调用 token endpoint，scope 精确到授权范围，支持刷新令牌自动轮换。

**步骤 7：租约注册**
- 生成 `token_id`（UUID v4）。
- 在 CDP 租约表中注册：`token_id`、`task_id`、`service`、`scope`、`expires_at`、`vault_lease_id`。
- 发布凭据签发事件（Event）供审计和缓存失效。

**步骤 8：DPoP 公钥绑定（MVP 预留）**
- 如请求包含 `dpop_public_key`，记录指纹并在响应中返回 `dpop_fingerprint`。
- Agent 每次 API 调用须附带 DPoP proof（渐进式启用）。

**步骤 9：响应返回**
- 返回 Capability Token Response（含 `issued_token` 或 `service_endpoint`）。
- 签发延迟目标：Model B p95 < 100ms（含 Vault 访问）。

### 4.2 OIDC 联合身份流程（AWS STS 为例）

```
Agent Worker
    ↓ Request Capability Token（target_service=aws）
CDP
    ↓ 验证 policy_approval_ref（SEC-003）
    ↓ 从 Vault 获取 AWS OIDC Provider 信任配置
    ↓ 调用 STS AssumeRoleWithWebIdentity
        ← AWS IAM
        ← 返回短期 AccessKeyId + SecretAccessKey + SessionToken（TTL ≤ 15min）
    ↓ 注册租约
    ↓ 返回 Capability Token（token_type=aws_sts_token）
Agent Worker
    ↓ 使用短期 STS Token 调用 AWS API
```

关键点：Agent 永不持有静态 AWS Access Key；每次请求通过 CDP 铸造新的 STS Token；AWS 审计日志直接归属到具体 Agent Session（通过 OIDC subject claim）。

### 4.3 撤销流程

**触发来源**：
- 任务取消或完成
- 用户主动撤销
- Kill Switch 触发（任意层级）
- SEC-002 授权失效
- SEC-003 Policy 审批过期

**撤销步骤**：
1. 接收撤销请求（携带 `revoke_reason`、`affected_token_ids` 或 `task_id`）。
2. CDP 根据 `token_id` 或 `task_id` 查找租约。
3. 调用各服务原生的撤销接口：
   - GitHub App Token：调用 `DELETE /applications/grants/{grant_id}` 或让 TTL 自然到期
   - AWS STS：让 TTL 自然到期（AWS STS 不支持主动撤销会话令牌，通过缩短 TTL 控制）
   - 通用 OAuth：调用 revoke endpoint
4. 发布分布式撤销事件（Redis Pub/Sub / 内部消息总线）。
5. 所有 Agent 实例收到事件，清除本地凭据缓存。
6. 写入不可变审计事件（revoke_reason、timestamp、triggered_by、affected_token_ids）。

**撤销传播目标**：从撤销 API 调用到所有 Agent 实例缓存清除完成，延迟 < 5s。

### 4.4 多实例 Active-Active 高可用

CDP 无状态设计确保多实例 active-active 部署：

- **无状态**：所有租约状态持久化到共享存储（Redis Cluster / PostgreSQL），每个 CDP 实例独立处理请求。
- **健康检查**：Kubernetes Liveness/Readiness 探针，实例故障自动剔除。
- **Vault 连接池**：每个实例维护独立的 Vault 连接池，连接池耗尽不阻塞其他实例。
- **请求路由**：Kubernetes Service + 负载均衡，请求分发到健康实例。
- **Fail-secure 语义**：CDP 不可用时，Agent 当前持有的有效凭据继续使用至 TTL 到期，新请求被拒绝。

---

## 5. Vault 集成

### 5.1 Vault 选型策略

| 部署环境 | 首选 Vault | 备选 |
|---------|-----------|------|
| AWS 单云 | AWS Secrets Manager + KMS | HashiCorp Vault（AWS 引擎） |
| Azure 单云 | Azure Key Vault | HashiCorp Vault（Azure 引擎） |
| GCP 单云 | GCP Secret Manager | HashiCorp Vault（GCP 引擎） |
| 多云/混合云 | HashiCorp Vault | — |

### 5.2 Vault 凭据存储结构

```
vault://secret/ai-agent/
  ├── github/
  │   ├── {org_id}/
  │   │   ├── private_key（PEM，GitHub App 私钥）
  │   │   └── app_id（整数）
  ├── aws/
  │   ├── {org_id}/
  │   │   ├── oidc_provider_arn
  │   │   └── role_arn
  ├── oauth/
  │   ├── {org_id}/
  │   │   ├── {service_id}/
  │   │   │   ├── client_id
  │   │   │   └── client_secret（加密）
  └── generic/
      ├── {org_id}/
          └── {service_id}/
              └── api_key（加密）
```

### 5.3 Vault 访问控制

- CDP 使用云厂商托管的 Vault 时，通过 IAM Role + Workload Identity（AWS/GCP）或 Managed Identity（Azure）认证，避免存储静态密钥。
- Vault 中的每个凭据路径绑定到 `organization_id`，确保多租户隔离。
- CDP 进程仅能读取其所在 organization 的凭据路径，无跨租户访问权。

---

## 6. 异常与失败处理

| 异常场景 | 处理策略 |
|---------|---------|
| CDP 不可用 | **Fail-secure**：拒绝所有新签发请求；Agent 当前持有的有效凭据继续使用至 TTL；监控告警 |
| Vault 不可达 | **Fail-secure**：拒绝签发新凭据；已签发凭据不受影响；重试指数退避（最大 3 次）后告警 |
| 外部服务撤销 API 超时 | 记录撤销失败事件；重试最多 3 次；触发安全告警；人工介入；写入 partial_revocation 标记 |
| Agent 请求超出授权范围 | 拒绝请求；返回拒绝原因；记录安全事件；不泄露其他租户信息 |
| TTL 过期但外部服务未感知 | CDP 在 TTL 精确时刻使令牌失效；Agent 后续请求被外部服务拒绝（401/403）；CDP 记录外部服务拒绝事件 |
| 任务暂停未撤销 | 暂停的任务持有的凭据继续有效至 TTL；恢复时如 TTL 未到则复用，否则重新请求 |
| DPoP 私钥泄露（Agent 侧） | MVP 阶段 DPoP 未启用；未来启用后：私钥在 Agent 内存中生成，不持久化，随进程销毁而销毁 |
| Vault 凭据路径不存在 | 拒绝请求；记录配置缺失事件；返回 organization 管理员可见的错误 |

---

## 7. 权限、安全与合规

- Agent 进程内存中仅持有短期 Capability Token，进程退出后凭据随内存释放销毁。
- 每个凭据的 scope 精确限定到单资源、单操作，CDP scope 约束不得大于 Policy Gateway 审批范围。
- 凭据与 `task_id` 绑定，不可跨任务使用。
- 租约不可续期，TTL 到期必须重新请求。
- 撤销事件通过分布式消息总线传播，确保全局一致性。
- 根凭据存储在云厂商托管 Vault（HSM-backed），CDP 无法导出原始凭据，只能铸造派生令牌。
- 所有签发、拒绝、撤销事件必须写入不可变审计日志。
- CDP 不可用时 fail-secure，不使用陈旧缓存放行新请求。
- 审计日志仅记录 token_id、service、scope、task_id、user、timestamp，不记录 issued_token 内容。

---

## 8. 可观测性与评估指标

### 8.1 核心指标

| 指标类别 | 具体指标 | 告警阈值 |
|---------|---------|---------|
| 签发量 | 签发速率（tokens/min）、累计签发量、签发失败率 | 失败率 > 1% |
| TTL 分布 | 平均 TTL、中位数、p95 | TTL < 60s 或 TTL > 配置上限触发审查 |
| 撤销量 | 撤销速率、撤销成功率、撤销失败数 | 撤销失败率 > 5% |
| 外部服务分布 | 各目标服务的凭据请求量 | 新服务类型首次请求告警 |
| 延迟 | 签发延迟分布（p50/p95/p99） | p99 > 500ms |
| Vault 健康 | Vault 可用性、连接池使用率 | Vault 不可用触发 fail-secure |
| CDP 健康 | 各实例可用性、错误率 | 实例不可用数 > 总数 50% |
| OIDC 联合 | 联合身份签发成功率、各提供商延迟 | 失败率 > 0.5% |

### 8.2 Trace 关联

每次凭据签发和撤销生成对应的 Trace Span，携带 `token_id`、`task_id`、`service`、`scope`，通过 `REQ-RT-006` Trace 传播机制关联到完整的 Task Trace。Span 名称约定：`credential.issue`、`credential.revoke`。

---

## 9. 依赖与接口边界

### 9.1 上游依赖

- `REQ-SEC-002`（RBAC 授权）：提供主体、资源、操作授权结果和版本，作为 scope 上限约束。
- `REQ-SEC-003`（Policy Gateway）：提供 `policy_approval_ref`，作为凭据签发的必要前置条件。
- `REQ-RT-001`（核心实体）：提供 Task、Worker、organization_id 等共享实体定义。
- 云厂商托管 Vault：提供长期根凭据的安全存储和按需读取。
- SPIRE/Identity：提供 Agent 工作负载身份（SVID），用于验证 agent_identity。

### 9.2 下游接口

- `REQ-SEC-009`（Kill Switch）：消费凭据撤销 API，触发紧急撤销。
- `REQ-REL-005`（恢复决策）：消费凭据状态，用于判断恢复点有效性。
- `REQ-RT-006/008`（Trace/审计）：消费签发和撤销事件，写入不可变审计日志。
- `REQ-HAR-003`（Tool Adapter）：集成凭据获取逻辑，工具执行前通过 Credential Proxy 获取凭据。
- 外部服务 API：消费 CDP 签发的 Capability Token。

### 9.3 概念接口定义

- Agent → Credential Proxy：`CapabilityTokenRequest` → `CapabilityTokenResponse`（gRPC/HTTP2）
- Policy Gateway → CDP：签名审批决策消息（内部 mTLS 消息队列）
- CDP → Vault：各云厂商 Vault SDK API（TLS 内部网络）
- CDP → 外部服务：各服务原生 API（OAuth/GitHub App/STS/OIDC）
- Kill Switch → CDP：`RevocationRequest`（内部事件/API）

---

## 10. MVP 范围与演进

### 10.1 MVP

- 支持 GitHub App（短期 Installation Token）、AWS STS（OIDC 联合）、通用 OAuth 2.0（client credentials + 刷新令牌轮换）。
- Model B 为主要模式；Model A 作为 AWS/GCP/Azure OIDC 联合身份的代理路径。
- 单云云厂商托管 Vault（AWS Secrets Manager + KMS / Azure Key Vault / GCP Secret Manager）。
- 按服务类型的 TTL 上限配置（GitHub ≤ 1h，AWS ≤ 15min，OAuth ≤ 30min）。
- 基本撤销传播（Redis Pub/Sub）。
- CDP 多实例 active-active（无状态 + Redis 共享租约）。
- OIDC 联合身份（AWS STS + GitHub OIDC）**必选**。
- DPoP 接口预留，**渐进式启用路线**。

### 10.2 后续版本候选

- DPoP 发送方约束（Model B 的安全增强）。
- 按模型供应商的完整差异化策略（GCP OIDC、Azure OIDC、MongoDB、PostgreSQL）。
- Model C 凭据包装（遗留 API 支持，标记 @deprecated + 严格约束）。
- 行为基线和异常检测。
- 细粒度 scope 协商（超出 MVP 粗粒度范围）。
- Vault HA 和跨区域复制。
- HashiCorp Vault 高级特性（多云场景）。

---

## 11. 验收标准

| 编号 | 可验证标准 | 验证方式 |
|------|----------|---------|
| SEC-005-AC1 | Agent 进程从不持有根凭据或长期凭据；仅持有 CDP 签发的短期 Capability Token | 代码审计 + 进程内存快照测试 |
| SEC-005-AC2 | 每个 Capability Token 的 scope 精确限定到单资源、单操作；不超过 Policy Gateway 审批范围 | 集成测试：请求宽泛 scope 验证自动截断 |
| SEC-005-AC3 | TTL 到期后凭据自动失效；CDP 租约表中该租约标记为 expired | TTL 过期测试：验证外部服务拒绝请求 |
| SEC-005-AC4 | 任务撤销、Kill Switch 触发、授权失效时，凭据通过撤销协议在 < 5s 内全局失效 | 撤销传播测试：触发撤销后验证所有实例缓存清除 |
| SEC-005-AC5 | CDP 不可用时 fail-secure：拒绝所有新签发请求，不使用陈旧缓存放行 | 故障注入测试：CDP 宕机后验证拒绝行为 |
| SEC-005-AC6 | 所有签发、拒绝、撤销事件产生不可变审计记录；审计记录不含 issued_token 内容 | 审计日志测试：查询审计 API 验证记录完整性 |
| SEC-005-AC7 | 按 `target_service` 选择正确的代理模型；GitHub → Model B，AWS/GCP/Azure OIDC → Model A | 集成测试：请求不同服务类型验证路由 |
| SEC-005-AC8 | 凭据签发与 SEC-002 授权结果绑定；无有效 policy_approval_ref 的请求被拒绝 | 安全测试：无审批引用时验证拒绝 |
| SEC-005-AC9 | OIDC 联合身份签发成功（AWS STS + GitHub OIDC）；Agent 不持有静态密钥 | 集成测试：OIDC 流程端到端验证 |
| SEC-005-AC10 | CDP 多实例 active-active：单实例故障不导致全局阻断；新请求路由到健康实例 | 故障注入测试：单实例宕机后验证请求路由 |
| SEC-005-AC11 | 撤销事件支持按 task_id 批量撤销；CDP 遍历所有受影响租约并执行撤销 | 批量撤销测试：验证 task_id 下所有 token 均被撤销 |
| SEC-005-AC12 | DPoP 接口预留完整；渐进式启用路线可执行 | 接口完整性测试：dpop_public_key 字段正确存储和响应 |

---

## 12. 竞品与公开依据

### 12.1 行业标准与最佳实践

- **IETF CB4A**：draft-hartman-credential-broker-4-agents-00（2026-03-29）提供了凭据代理的权威架构框架，包含 PDP/CDP 分离、三种代理模型、Tiered Approval、租约不可续期设计。本设计直接对齐 CB4A 框架，来源：https://datatracker.ietf.org/doc/html/draft-hartman-credential-broker-4-agents-00（访问日期：2026-09-23）。**事实**。
- **GitHub Copilot Cloud Agent**：Agents Secrets 隔离、MCP 凭据前缀（`COPILOT_MCP_`）、优先使用临时 GITHUB_TOKEN。来源：https://docs.github.com/en/copilot/tutorials/cloud-agent/give-access-to-resources（访问日期：2026-09-23）。**事实**。
- **Claude Code**：云端安全代理协议翻译、Workload Identity Federation 免静态密钥。来源：https://platform.claude.com/docs/en/manage-claude/authentication（访问日期：2026-09-23）。**事实**。
- **Cursor Cloud Agent**：本地 socket minting OIDC JWT（5min TTL）、MicroVM 隔离、Vault 集成。来源：https://cursor.com/docs/cloud-agent/identity（访问日期：2026-09-23）。**事实**。
- **Devin**：OIDC 联合身份联邦、会话级作用域。来源：https://docs.devin.ai/product-guides/oidc（访问日期：2026-09-23）。**事实**。
- **Azure AI Foundry**：三层令牌链、托管标识联邦、Data Proxy。来源：https://github.com/MicrosoftDocs/azure-ai-docs/blob/main/articles/foundry/agents/concepts/agent-identity.md（访问日期：2026-09-23）。**事实**。

### 12.2 项目内部设计输入

- `REQ-SEC-001` 威胁模型：明确凭据散布为关键威胁，凭据代理是核心缓解措施。
- `REQ-SEC-002` RBAC 与资源授权：提供凭据代理所需的主体、资源、操作授权语义。
- `REQ-SEC-003` Policy Gateway：提供凭据签发的 policy_approval_ref 前置条件。
- `02-security-threat-model.md` §八：凭据代理 PDP/CDP 架构初步设计，本设计为该架构的完整细化。
- `00-integrated-design-baseline.md` §5.2：明确凭据代理依赖 SEC-002 授权范围与版本。

---

## 13. 关键设计决策记录

| 决策 | 选定基线 | 理由/边界 |
|------|---------|---------|
| PDP/CDP 架构 | 严格分离，PDP 无凭据材料 | 任意一方被攻陷不直接泄漏凭据；对齐 CB4A 和 NIST SP 800-207 |
| 代理模型选择 | Model B 为主（GitHub/OAuth），Model A 为 OIDC 联合代理路径 | 安全与性能最佳平衡；Model C MVP 不实现仅留桩 |
| Vault 选型 | 单云优先云厂商托管（AWS SM+KMS / Azure KV / GCP SM），多云考虑 HashiCorp Vault | 简化运维，利用云厂商原生 HSM 保护 |
| OIDC 联合身份 | MVP 必选（AWS STS + GitHub OIDC） | 零密钥架构地基，多个大厂已验证 |
| DPoP | MVP 接口预留，渐进式启用 | 当前 Agent 内存凭据窃取风险通过 TTL 短周期控制 |
| 高可用 | CDP 多实例 active-active，无状态设计 | fail-secure 语义下单点故障等同全局阻断；Redis 共享租约 |
| 撤销传播 | Redis Pub/Sub，传播延迟 < 5s | 满足 Kill Switch 即时性要求；可升级为 Kafka/事件总线 |
| Fail-secure | CDP 不可用拒绝新签发请求，不使用陈旧缓存放行 | 避免凭据撤销后仍被使用；与 SEC-002 fail-secure 语义一致 |
| Model C | MVP 不实现，仅保留 @deprecated 接口桩 | 无明确遗留 API 需求；Model C 安全风险最高 |
| 审计数据 | 仅记录 token_id/service/scope/task_id/user/timestamp，不含凭据内容 | 数据最小化；合规要求；issued_token 泄漏风险 |

---

## 14. 变更记录

| 版本 | 日期 | 变更 |
|------|------|------|
| `v0.1-designed` | 2026-09-23 | 完成凭据代理详细设计；基于 CB4A 框架、6 大厂竞品研究和用户确认决策；覆盖 PDP/CDP 架构、三代理模型选择策略（Model B 为主、Model A 用于 OIDC 联合）、Capability Token Schema、OIDC 联合身份（AWS STS + GitHub OIDC）、Vault 集成（单云云厂商托管）、CDP 多实例 active-active、撤销传播协议、Fail-secure 语义、审计事件和可观测指标 |
