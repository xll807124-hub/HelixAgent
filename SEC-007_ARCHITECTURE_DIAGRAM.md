# SEC-007 MCP 连接器治理 - 架构图

## 📐 系统架构总览

```
┌─────────────────────────────────────────────────────────────────────┐
│                    MCP Connector Governance                          │
│                         (SEC-007)                                    │
└─────────────────────────────────────────────────────────────────────┘
                                 │
                ┌────────────────┼────────────────┐
                │                │                │
        ┌───────▼────┐   ┌──────▼──────┐  ┌─────▼──────┐
        │  Registry  │   │  Policies   │  │ Lifecycle  │
        └────────────┘   └─────────────┘  └────────────┘
                │                │                │
        ┌───────▼────────────────▼────────────────▼───────┐
        │           8-Layer Defense Architecture          │
        └─────────────────────────────────────────────────┘
```

---

## 🏗️ 8 层纵深防御架构

```
┌─────────────────────────────────────────────────────────────────┐
│ Layer 1: Pre-Discovery Filter (发现前过滤)                      │
│ ├─ Global Blacklist Check                                       │
│ ├─ Namespace Validation                                         │
│ └─ Trust Level Classification                                   │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Layer 2: Tool Manifest Sync (工具清单同步)                      │
│ ├─ MCP tools/list Request                                       │
│ ├─ Schema Digest Computation (SHA256)                           │
│ └─ Breaking Change Detection                                    │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Layer 3: Capability Trimming (能力裁剪)                         │
│ ├─ Org-level Whitelist                                          │
│ ├─ Method/Parameter Restrictions                                │
│ └─ Rate Limiting                                                │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Layer 4: Policy Decision (策略决策)                             │
│ ├─ PolicyEngine Evaluation                                      │
│ ├─ Quota Check (Weighted)                                       │
│ └─ Risk Assessment                                              │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Layer 5: Credential Preparation (凭据准备)                       │
│ ├─ OAuth 2.1 PKCE Flow                                          │
│ ├─ Token Refresh                                                │
│ └─ SEC-005 Integration                                          │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Layer 6: Pre-Execution Review (执行前复核)                      │
│ ├─ Tool Schema Re-verification                                  │
│ ├─ Approval Check (schema_digest binding)                       │
│ └─ Final Policy Check                                           │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Layer 7: Tool Execution (工具执行)                              │
│ ├─ MCP tools/call Request                                       │
│ ├─ Timeout Control                                              │
│ └─ Error Handling & Quota Refund                                │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Layer 8: Audit (审计)                                           │
│ ├─ RT-008 Compliant Logging                                     │
│ ├─ Sensitive Data Sanitization                                  │
│ └─ Structured JSON Events                                       │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🔐 信任等级体系 (L1-L4)

```
┌────────────────────────────────────────────────────────────────────┐
│                     Trust Level Hierarchy                          │
├────────────────────────────────────────────────────────────────────┤
│  L1: Platform Managed                                              │
│      ├─ Quota Weight: 0.5x                                         │
│      ├─ Approval: 2-person                                         │
│      ├─ Signature: Required (SHA256/GPG/Sigstore)                  │
│      └─ Environment: Production ✓                                  │
├────────────────────────────────────────────────────────────────────┤
│  L2: Organization Verified                                         │
│      ├─ Quota Weight: 1.0x                                         │
│      ├─ Approval: Security Lead                                    │
│      ├─ Signature: Required                                        │
│      └─ Environment: Production ✓                                  │
├────────────────────────────────────────────────────────────────────┤
│  L3: Restricted Conditional                                        │
│      ├─ Quota Weight: 3.0x                                         │
│      ├─ Approval: Task-specific                                    │
│      ├─ Signature: Optional                                        │
│      ├─ Environment: Sandbox only                                  │
│      └─ Max TTL: 1 hour                                            │
├────────────────────────────────────────────────────────────────────┤
│  L4: Unverified / Untrusted                                        │
│      ├─ Quota Weight: 5.0x                                         │
│      ├─ Approval: None                                             │
│      ├─ Signature: Not required                                    │
│      ├─ Environment: Sandbox only                                  │
│      ├─ Max TTL: 10 minutes                                        │
│      └─ Isolation: VM                                              │
└────────────────────────────────────────────────────────────────────┘
```

---

## 📊 配额计算公式

```
┌──────────────────────────────────────────────────────────────┐
│              Weighted Quota Calculation                      │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  Cost = TrustWeight × ToolCount × RiskMult × NetMult × CM   │
│                                                              │
│  Where:                                                      │
│    TrustWeight  = 0.5x (L1) ~ 5.0x (L4)                     │
│    ToolCount    = Number of tools invoked                   │
│    RiskMult     = 0.5x (low) ~ 5.0x (critical)              │
│    NetMult      = 1.5x if network access                    │
│    CM           = 1.5x if credential access                 │
│                                                              │
└──────────────────────────────────────────────────────────────┘

Example:
  L2 connector with 3 tools (medium risk, network access):
  Cost = 1.0 × 3 × 1.0 × 1.5 × 1.0 = 4.5 quota units
```

---

## 🔄 连接器生命周期状态机

```
┌────────────────────────────────────────────────────────────────┐
│                  Connector Lifecycle States                    │
└────────────────────────────────────────────────────────────────┘

    [DRAFT]
       │
       ↓
  [PENDING_VERIFICATION]
       │
       ↓
  [PENDING_APPROVAL]
       │
       ↓
  [APPROVED_INACTIVE]
       │
       ↓
    [ACTIVE] ────────┬──────────────┬────────────────┐
       │             │              │                │
       ↓             ↓              ↓                ↓
 [PENDING_REVIEW] [RESTRICTED] [HEALTH_ANOMALY]  [PAUSED]
       │             │              │                │
       └─────────────┴──────────────┴────────────────┘
                     │
                     ↓
                 [REVOKED] (终态)
                     
    [EXPIRED] ───────┐
       │             │
       └─────────────┘
       (可重新验证)
```

---

## 🛡️ 策略决策流程

```
┌─────────────────────────────────────────────────────────────┐
│           Policy Decision Flow (3-Layer)                    │
└─────────────────────────────────────────────────────────────┘

  Request: Access connector "conn_001" for org "org_123"
     │
     ↓
  ┌────────────────────────────────────────┐
  │ Layer 1: Global Blacklist              │
  │ ├─ Check connector_id                  │
  │ ├─ Check namespace                     │
  │ └─ Check tool names                    │
  └────────────────────────────────────────┘
     │ (Not blocked)
     ↓
  ┌────────────────────────────────────────┐
  │ Layer 2: Org Whitelist (Optional)      │
  │ ├─ Check org policy                    │
  │ ├─ Apply capability trims              │
  │ └─ Check expiry                        │
  └────────────────────────────────────────┘
     │ (Allowed)
     ↓
  ┌────────────────────────────────────────┐
  │ Layer 3: Quota Check                   │
  │ ├─ Calculate weighted cost             │
  │ ├─ Check remaining quota               │
  │ └─ Consume quota                       │
  └────────────────────────────────────────┘
     │ (Sufficient quota)
     ↓
  [ALLOW] + PolicyDecision(allowed=True)
```

---

## 🔑 OAuth 2.1 PKCE 流程

```
┌──────────────────────────────────────────────────────────────┐
│              OAuth 2.1 PKCE Authorization Flow               │
└──────────────────────────────────────────────────────────────┘

1. Generate Authorization URL
   ├─ code_verifier = random(128 chars)
   ├─ code_challenge = SHA256(code_verifier)
   ├─ state = random(32 chars)
   └─ URL: /authorize?
           response_type=code&
           client_id=...&
           redirect_uri=...&
           code_challenge=...&
           code_challenge_method=S256&
           state=...&
           audience=...

2. User Authorization
   User → Authorization Server → Callback with code + state

3. Exchange Code for Token
   POST /token
   ├─ grant_type=authorization_code
   ├─ code=...
   ├─ code_verifier=...  (PKCE S256 验证)
   ├─ redirect_uri=...
   └─ client_id=...
   
   Response:
   ├─ access_token (1 hour TTL)
   ├─ refresh_token
   └─ expires_in=3600

4. Auto Token Refresh (5min buffer)
   POST /token
   ├─ grant_type=refresh_token
   └─ refresh_token=...
```

---

## 📦 模块依赖关系

```
┌────────────────────────────────────────────────────────────┐
│                  Module Dependencies                       │
└────────────────────────────────────────────────────────────┘

              ┌─────────────┐
              │   models    │  (Base Layer)
              └──────┬──────┘
                     │
        ┌────────────┼────────────┐
        │            │            │
   ┌────▼───┐  ┌────▼────┐  ┌────▼────┐
   │registry│  │policies │  │lifecycle│
   └────┬───┘  └────┬────┘  └────┬────┘
        │           │            │
        └───────┬───┴────────────┘
                │
        ┌───────▼────────┐
        │ authorization  │
        └───────┬────────┘
                │
        ┌───────▼────────┐
        │   execution    │
        └───────┬────────┘
                │
        ┌───────▼────────┐
        │     audit      │
        └────────────────┘

Dependency Rules:
- Lower layers do NOT depend on upper layers
- Cross-layer dependencies through interfaces
- Audit layer depends on ALL (observability)
```

---

## 📈 数据流图

```
┌──────────────────────────────────────────────────────────────┐
│                   Data Flow (Tool Invocation)                │
└──────────────────────────────────────────────────────────────┘

User Request: Invoke tool "get_weather" with {"city": "Beijing"}
     │
     ↓
┌────────────────────┐
│ 1. Tool Discovery  │
│    ToolRegistry    │
└─────────┬──────────┘
          │ tool_schema + schema_digest
          ↓
┌────────────────────┐
│ 2. Policy Check    │
│   PolicyEngine     │
└─────────┬──────────┘
          │ PolicyDecision(allowed=True, quota_cost=2.5)
          ↓
┌────────────────────┐
│ 3. Quota Consume   │
│   QuotaManager     │
└─────────┬──────────┘
          │ Success
          ↓
┌────────────────────┐
│ 4. Auth Prepare    │
│ AuthorizationMgr   │
└─────────┬──────────┘
          │ credentials (OAuth token)
          ↓
┌────────────────────┐
│ 5. Tool Execute    │
│   ToolExecutor     │
└─────────┬──────────┘
          │ ToolExecutionResult(success=True)
          ↓
┌────────────────────┐
│ 6. Audit Log       │
│   AuditLogger      │
└─────────┬──────────┘
          │
          ↓
      [Response to User]
```

---

## 🎯 关键接口

### ConnectorRegistry
```python
register(connector: Connector) -> None
get(connector_id: str) -> Optional[Connector]
list_by_trust_level(level: TrustLevel) -> List[Connector]
update_status(connector_id, new_state, reason) -> None
```

### PolicyEngine
```python
evaluate_connector_access(org_id, connector) -> PolicyDecision
evaluate_tool_invocation(org_id, connector, tool) -> PolicyDecision
consume_quota_for_invocation(org_id, connector, tool) -> bool
refund_quota_for_failed_invocation(...) -> None
```

### ToolExecutor
```python
async execute_tool(
    org_id, user_id, connector, tool, parameters
) -> ToolExecutionResult
```

### AuditLogger
```python
log_event(event_type, actor, resource_type, resource_id, 
          action, result, metadata) -> None
log_tool_invocation(...) -> None
log_policy_decision(...) -> None
```

---

生成时间: 2026-10-14 00:37 UTC+8
项目: SEC-007 MCP 连接器治理
状态: Day 1 完成
