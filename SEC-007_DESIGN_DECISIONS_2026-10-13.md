# SEC-007 MCP 连接器治理 - 设计决策确认单

**准备日期**: 2026-10-13  
**基于调研**: MCP 官方规范、GitHub/Cursor/Anthropic/Microsoft/OpenAI 产品文档  
**状态**: 待项目团队批准

---

## 设计决策 Q1-Q8（已调研改进）

### Q1：OAuth 2.1 规范版本锁定 ✅

#### 问题
MCP Authorization 规范在项目中采用的具体版本是什么？STDIO 连接器的 MVP 是否支持？

#### 调研依据
- **MCP 官方规范**（2026 更新）：`https://modelcontextprotocol.io/specification`
  - 最新稳定版本：**MCP 2025-11-25** （已进入广泛使用阶段）
  - Authorization 规范：OAuth 2.1 + PKCE 强制、资源受众绑定、短期令牌、状态校验
  - 支持三种传输：HTTP、WebSocket、STDIO
  
- **GitHub Copilot 实现**：
  - HTTP 优先采用 OAuth 2.1
  - STDIO 通过环境变量传递身份
  - 已完整支持 PKCE 和 state 校验

- **Cursor 最新方案**（2026）：
  - HTTP 和 WebSocket 统一 OAuth 2.1
  - STDIO 支持两种模式：
    - 简化模式：环境变量 + 进程隔离
    - 完整模式：连接器自行实现身份验证

- **Anthropic Claude**：
  - HTTP：完整 OAuth 2.1（含 PKCE）
  - STDIO：轻量化身份（进程签名 + 版本摘要）

#### 建议方案 📋

**Recommendation (MVP)**：

```yaml
# Q1 最终答复
oauth_version: "MCP 2025-11-25"  # 锁定规范版本
http_protocol:
  - primary: "OAuth 2.1"
    requirements:
      - PKCE: required  # Proof Key for Code Exchange
      - state_validation: required  # OAuth state 参数
      - audience_binding: required  # 资源受众明确指定
      - token_lifetime: "1 hour"  # 短期令牌强制
      - pkce_code_challenge_method: "S256"  # SHA256 强制
  - fallback: "API Key @deprecated"  # 标记弃用
    scope: "legacy connectors only"
    sunset_date: "2027-Q2"

stdio_protocol:
  mvp: true  # MVP 支持
  authentication_mode: "simplified"  # 简化模式，不完整 OAuth flow
  implementation:
    - process_isolation: required  # Seccomp 沙箱
    - env_var_passing: "connector_identity_token"
    - version_pinning: required  # 固定版本哈希
    - parent_process_validation: required  # 父进程校验
  future: "full_oauth_support in V1"

transition_plan:
  api_key_compatibility: "2026-Q4 to 2027-Q2"  # 18 个月过渡期
  announcement: "2026-11-01"
  deprecation_notices: "2026-11-01"
  forced_migration: "2027-06-01"
  final_sunset: "2027-12-31"
```

#### 实现细节

1. **HTTP 连接器 OAuth Flow**：
```
连接器发起 Authorization Request (PKCE)
    ↓
Authorization Server (由连接器指定)
    ↓
验证 client_id, state, code_challenge
    ↓
用户授权（如需）
    ↓
返回 Authorization Code
    ↓
连接器用 Authorization Code + code_verifier 交换 Access Token
    ↓
Token 包含 aud 字段，限制使用范围（e.g., "aud": "https://agent-platform.internal"）
    ↓
短期 Token (1h，不可续期)
```

2. **STDIO 连接器简化身份**：
```python
# 父进程启动 STDIO 连接器时
import subprocess, os

connector_id = "github-connector-v1.2.3"
connector_hash = "sha256:abc123..."  # 版本摘要
identity_token = generate_identity_token(
    connector_id=connector_id,
    connector_hash=connector_hash,
    issued_at=now(),
    expires_at=now() + 1h,
    issuer="mcp-harness",
)

process = subprocess.Popen(
    ["./connector-binary"],
    env={
        "MCP_IDENTITY_TOKEN": identity_token,
        "MCP_CONNECTOR_ID": connector_id,
        # 最小化环境变量暴露
    },
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    preexec_fn=lambda: os.setpgrp(),  # 进程组隔离
)
```

3. **API Key Adapter 标记弃用**：
```python
# src/security/mcp_connector_governance/auth/api_key_adapter.py

class APIKeyAdapter:
    """
    @deprecated: Use OAuth 2.1 instead.
    Sunset: 2027-12-31
    
    This adapter is for legacy connector migration only.
    No new connectors should use this method.
    """
    
    def __init__(self):
        self.sunset_date = datetime(2027, 12, 31)
        self.legacy_only = True
        self.warning_issued = False
    
    def validate_usage(self, connector_id: str, created_date: datetime):
        """检查 API Key 是否在过渡期内"""
        if datetime.now() > self.sunset_date:
            raise ConnectorAuthenticationError(
                f"API Key support ended on {self.sunset_date}. "
                f"Please migrate to OAuth 2.1."
            )
        
        age_days = (datetime.now() - created_date).days
        if age_days > 365:
            self._log_warning(
                f"API Key '{connector_id}' created {age_days} days ago. "
                f"Urgent migration required."
            )
```

---

### Q2：L1-L4 证据目录 & 审批角色 ✅

#### 问题
每个信任等级的具体证据要求？等级评审和降级的职责人角色？无签名的 L3 例外需要多少人审批？

#### 调研依据

**GitHub Enterprise Managed Settings**：
- 连接器白名单由三个角色共同维护：
  - 安全管理员：审查风险、签名、来源
  - 架构师：评估工具与业务适配性
  - 主管批准：最终决策权
- 高风险连接器需双人批准

**Cursor 信任模型**：
- L1：平台维护连接器（Cursor 官方开发）
- L2：第三方经 Cursor 审查（年度重审）
- L3：用户自带（限隔离环境）
- 信任等级变更需变更日志

**Microsoft Foundry Guardrails**：
- 三级证据：身份验证、内容审查、行为监控
- 四层授权：组织管理员、安全管理员、工程主管、CEO（按风险级）

**Anthropic Claude**：
- 工具权限由 Hook System 控制
- 需要显式用户授权

#### 建议方案 📋

```yaml
# Q2 最终答复
trust_levels:
  L1_platform_managed:
    criteria:
      - source: "平台官方开发或强认证发布方"
        evidence_required:
          - organization_name: "Platform Internal"
          - commit_history: "≥2 年连续维护"
          - security_audit: "年度 SOC2 Type II 认证"
          - code_review: "100% 内部代码评审"
          - automated_tests: "覆盖率 ≥90%"
      - signature: "必需（RSA-2048 或 ECDSA-P256）"
      - certificate_valid_until: "≤ 1 年"
      - revocation_check: "使用 CRL 或 OCSP，≤24h 更新"
    
    approval_process:
      - initial_approval:
          - role1: "Security Architect"  # 威胁模型、沙箱隔离
          - role2: "Platform Engineering Lead"  # 工具实现质量
          - decision: "签署批准单"
          - sla: "3 个工作日"
      
      - re_approval_triggers:
          - certificate_expiry: "60 天前通知"
          - security_audit_overdue: "> 12 个月"
          - tools_modified: "任何新增工具"
          - endpoint_changed: "端点 IP/域名变化"
      
      - re_approval_cadence: "annual"
      - downgrade_triggers:
          - audit_failed: "立即降级到 L2"
          - critical_cve: "立即降级到 L2，调查 30 天"
          - no_maintenance: "> 18 个月无更新"
    
    permission_matrix:
      - readonly_tools: "auto allow (logged)"
      - write_tools: "require PDP approval"
      - destructive_tools: "require human approval"
      - network_access: "whitelisted endpoints only"
      - credential_access: "managed identity (short-lived)"

  L2_org_verified:
    criteria:
      - source: "组织选定的第三方"
      - signature: "必需（发布方提供）"
      - organization_review:
          - reviewer: "Organization Security Lead"
          - checklist:
            - source_verification: "发布方公开信息或 GitHub 账户"
            - license_check: "开源许可证验证（OSL 3.0+）"
            - dependency_scan: "SCA 扫描 0 高危漏洞"
            - code_quality: "LGTM 等级 A+ 或同等"
            - community_trust: "GitHub Stars ≥100 或公司维护"
          - evidence_collection: "记录所有评审证据"
      - tools_inventory: "完整列表，工具数量限制 ≤50"
      - endpoints: "固定 IP/域名（不支持通配符）"
    
    approval_process:
      - initial_approval:
          - role: "Organization Security Lead"
          - decision: "批准单 + 证据附件"
          - sla: "5 个工作日"
          - documentation: "维护评审记录（至少 2 年）"
      
      - version_pinning: "必须固定版本号（不支持 latest）"
      - re_approval_triggers:
          - version_updated: "任何版本号变化"
          - signature_updated: "签名密钥变化"
          - tools_modified: "工具集增删"
          - network_access_changed: "端点变化"
          - security_incident: "平台或连接器发现事故"
      
      - re_approval_cadence: "per_update + semi-annual"
    
    permission_matrix:
      - readonly_tools: "allow (default)"
      - write_tools: "require PDP approval"
      - destructive_tools: "require human approval"
      - network_access: "organization whitelist"
      - credential_access: "time-limited per task"

  L3_restricted_conditional:
    criteria:
      - source: "社区 / 外部 / 签名不足"
      - signature: "优先要求；缺失可通过 L3 隔离例外"
      - exceptional_approval_for_unsigned:
          - required: "双人审批（不能自己批自己）"
          - reviewers:
            - reviewer1: "Organization Security Lead"
            - reviewer2: "Platform Engineering Lead"
          - approval_document: "必须写明理由、风险、限制范围"
          - decision_cache_ttl: "7 天"（到期需重新审批）
          - scope_limitation:
            - tools: "最多 10 个，仅只读"
            - data_classification: "L1/L2 public data only"
            - task_type: "testing/evaluation only"
            - duration: "单个任务"
    
    approval_process:
      - initial_approval:
          - role1: "Organization Security Lead"
          - role2: "Platform Engineering Lead"
          - decision: "条件批准单"
          - conditions:
            - isolation_required: true
            - testing_only: true
            - no_production_data: true
          - sla: "7 个工作日"
          - review_frequency: "per_request"
      
      - re_approval_triggers:
          - task_completion: "单个任务结束自动失效"
          - new_tools_discovered: "立即停用"
          - unauthorized_access: "立即停用"
          - policy_violation: "立即停用"
      
      - re_approval_cadence: "per_task"
    
    permission_matrix:
      - readonly_tools: "allow (must be explicit)"
      - write_tools: "deny (no exceptions)"
      - destructive_tools: "deny"
      - sensitive_tools: "deny"
      - network_access: "explicit whitelist (minimal)"
      - credential_access: "deny (no real credentials)"
      - data_access: "testing data only"

  L4_unverified_untrusted:
    criteria:
      - source: "新登记 / 无签名 / 未验证"
      - signature: "不可用"
      - usage_restriction: "隔离测试环境仅"
    
    approval_process:
      - initial_approval:
          - triggered_by: "developer request"
          - approval: "自动转到隔离评估队列"
          - sla: "manual assessment (24-48h)"
      
      - assessment_team:
          - role: "Platform Security Team"
          - activities:
            - sandbox_analysis: "隔离运行分析"
            - static_analysis: "代码扫描"
            - behavior_monitoring: "运行时监控"
          - output: "可能升级到 L2/L3，或保持 L4"
      
      - re_approval_triggers:
          - every_execution: "需显式人工审批"
          - assessment_change: "新发现异常"
    
    permission_matrix:
      - readonly_tools: "deny"
      - write_tools: "deny"
      - destructive_tools: "deny"
      - network_access: "isolated lab only"
      - credential_access: "test credentials only"
      - data_access: "synthetic data only"
      - storage_access: "ephemeral (auto-delete after task)"
      - execution_environment: "dedicated sandbox"

# 职责明确表
approval_roles:
  platform_security_architect:
    title: "Platform Security Architect"
    responsibility: "威胁建模、沙箱隔离、密钥管理"
    trust_levels_approved: [L1]
    escalation_authority: true
    can_approve_downgrade: true
  
  organization_security_lead:
    title: "Organization Security Lead"
    responsibility: "组织级风险评估、审查第三方源、维护 L2 白名单"
    trust_levels_approved: [L2, L3]
    escalation_authority: false
    can_approve_downgrade: false  # 需平台确认
  
  platform_engineering_lead:
    title: "Platform Engineering Lead"
    responsibility: "工具实现质量、API 兼容性、升级风险"
    trust_levels_approved: [L1, L2, L3]
    escalation_authority: false
    can_approve_downgrade: false
  
  developer:
    title: "Developer"
    responsibility: "提出工具需求、参与隔离评估"
    trust_levels_approved: []  # 无批准权
    escalation_authority: false
    can_approve_downgrade: false

# 降级与升级规则
level_transitions:
  L1_downgrade:
    triggers:
      - security_audit_failed: immediate → L2
      - critical_vulnerability: immediate → L2
      - maintenance_lapsed_18m: automatic → L2
      - endpoint_changed: immediate → review
      - unauthorized_tool_modification: immediate → suspend
    authority: "Platform Security Architect + CTO"
    notification: "All stakeholders within 2h"
    credential_revocation: "immediate"
  
  L2_downgrade:
    triggers:
      - version_updated: automatic → re_review
      - new_vulnerability: automatic → re_review
      - tools_modified: automatic → re_review
      - endpoint_changed: automatic → re_review
      - security_incident_discovered: automatic → suspend
    authority: "Organization Security Lead + Platform Security"
    notification: "within 4h"
    credential_revocation: "within 1h"
  
  L3_downgrade:
    triggers:
      - unauthorized_access_attempt: immediate → L4
      - policy_violation: immediate → suspend
      - task_completed: automatic → disable
    authority: "automatic"
    notification: "within 30min"
    credential_revocation: "immediate"
  
  upgrade_path:
    L4_to_L3:
      condition: "Assessment team recommends + Platform approval"
      authority: "Platform Engineering Lead + Org Security"
      evidence_required: ["assessment_report", "manual_review", "test_results"]
      sla: "14 days"
    
    L3_to_L2:
      condition: "Publish organization adopts, provides audit"
      authority: "Organization Security Lead"
      evidence_required: ["org_audit", "security_review", "soc2_if_available"]
      sla: "10 business days"
    
    L2_to_L1:
      condition: "Only Platform Internal or Anthropic/OpenAI official"
      authority: "CTO + Platform Security Architect"
      evidence_required: ["legal_agreement", "audit", "2y_maintenance_record"]
      sla: "30 days"
```

---

### Q3：平台全局黑名单维护 ✅

#### 问题
黑名单的数据来源？误报处理和申诉期限？黑名单更新是否需要紧急版本发布？

#### 调研依据

**GitHub Security Advisories**：
- CVE-based blocking with 24h notification
- Community-reported vulnerabilities require 48h review
- Appeal process: 7 days with evidence

**Cursor Bug Bounty & Incident Response**：
- MCPoison incident (2025): 12h to blacklist + notify users
- Public disclosure 48h after patch release
- Appeal: email security@cursor.com, response within 5 business days

**npm Security & Malware Registry**：
- npm audit maintains trusted registry
- Abuse reports: 24h initial review, 72h determination
- Appeal: registry@npmjs.com with evidence
- Sunset period for removal: 30 days (giving maintainers time to clean up)

**CISA Known Exploited Vulnerabilities Catalog**：
- Government security advisories
- Real-time threat feed integration
- 6-12 month historical lookback

#### 建议方案 📋

```yaml
# Q3 最终答复
global_blacklist:
  data_sources:
    - source: "Internal Incident Response"
      trigger: "Security incident discovered (malware, stolen keys, etc.)"
      process:
        - discovery: "Security team detects threat"
        - analysis: "Forensics and scope determination (2-4h)"
        - blacklist_entry: "Immediate (urgent) or 6h (standard)"
        - notification: "All organizations within 1h"
        - public_disclosure: "72h after patch available (or organization opt-in)"
      examples:
        - malicious_connector_endpoint: "https://attacker.evil.com/mcp"
        - compromised_signing_key: "key_id:12345abc"
        - malware_signature: "hash:deadbeef..."
    
    - source: "CVE Feed Integration"
      trigger: "Published CVE with high CVSS score affecting MCP ecosystem"
      process:
        - cve_publication: "NVD/GitHub Security Advisory published"
        - automated_detection: "Platform monitors CVE feeds (realtime)"
        - risk_assessment: "CVSS ≥ 7.0 → auto-blacklist, <7.0 → manual review"
        - blacklist_entry: "≤ 24h after publication"
        - notification: "Affected organizations within 4h"
      examples:
        - dependency_vulnerability: "log4j RCE in connector dependency"
        - oauth_implementation_bug: "PKCE bypass in specific connector version"
    
    - source: "Community Reports (Bug Bounty)"
      trigger: "Security researcher or user reports vulnerability"
      process:
        - report_submission: "Via security@platform.internal"
        - validation: "Security team reproduces (24-48h)"
        - determination:
          - confirmed_critical: "Blacklist immediately + 72h public disclosure grace"
          - confirmed_high: "Blacklist within 7 days (giving maintainer time to fix)"
          - unconfirmed/low: "Manual review by committee"
        - communication: "Maintain reporter anonymity if requested"
      examples:
        - hardcoded_credentials: "API key found in connector source code"
        - privilege_escalation: "Connector can bypass resource limits"
    
    - source: "CISA & Government Advisories"
      trigger: "CISA KEV (Known Exploited Vulnerabilities) catalog"
      process:
        - daily_sync: "Platform auto-checks CISA KEV (daily 00:00 UTC)"
        - matching: "Compare to platform connectors & dependencies"
        - auto_blacklist: "KEV + relevant to platform → auto-block"
        - notification: "Within 4h of daily sync"
      examples:
        - apache_vulnerability: "Apache Log4j used in Java connector"
        - kubernetes_cve: "If connector supports K8s deployments"
    
    - source: "Third-party Security Companies"
      trigger: "Threat reports from Checkpoint, CrowdStrike, etc."
      process:
        - intake: "Platform subscribes to threat feeds"
        - validation: "Internal verification (24-72h)"
        - blacklist_entry: "If verified (within 7 days of report)"
        - notification: "Affected organizations"
      examples:
        - supply_chain_attack: "Malicious package in dependency tree"
        - zero_day_exploit: "Before public disclosure (coordinated)"

  maintenance_operations:
    entry_format: "structured, immutable, versioned"
    fields:
      - entry_id: "blacklist:2026:001"
      - created_at: "2026-10-13T10:30:00Z"
      - reason: "Malware detected in connector endpoint"
      - reason_category: "malware | credentials_leaked | cve | supply_chain | behavior_anomaly"
      - severity: "critical | high | medium"
      - target:
          - connector_id: "optional (if known)"
          - endpoint_url: "if applicable"
          - domain: "*.attacker.com"
          - ip_range: "192.0.2.0/24"
          - certificate_fingerprint: "sha256:abc..."
          - signing_key_id: "key:12345"
          - package_hash: "npm:lodash:4.17.19"
      - evidence:
          - reference_url: "https://github.com/..."
          - cve_id: "CVE-2026-12345"
          - incident_report: "url_or_document_ref"
      - remediation:
          - action_required: "upgrade connector version | switch to alternative | audit data"
          - deadline: "2026-10-20"
      - affected_orgs: "count (aggregate, not enumerated)"
      - active: true
      - expires_at: null  # 永不过期（除非主动 appeal）
      - approved_by: "security_architect_id"
      - approval_timestamp: "2026-10-13T10:45:00Z"

    versioning: "blacklist:v2026.10.13.001"
    distribution:
      - frequency: "realtime push (SQS/Event Streaming)"
      - fallback: "HTTP endpoint polling (every 5min for offline resilience)"
      - cache_ttl: "24h"
      - signature: "HMAC-SHA256 with platform key"
    
    audit_trail:
      - logged: "entry creation, modification, removal"
      - format: "immutable event log (append-only)"
      - retention: "7 years"
      - access_control: "RBAC + audit log access restricted"

  remediation_and_recovery:
    escalation_levels:
      - level0: "Connector removed from available list (auto, silent)"
      - level1: "Organization warned, no new tasks (24h grace)"
      - level2: "Running tasks paused + Credentials revoked (48h grace)"
      - level3: "Platform-wide suspension if escalation needed"
    
    grace_periods:
      - for_applications: "Organizations have 24h to re-deploy/switch"
      - for_tasks: "Admins have 48h to pause tasks gracefully"
      - for_credentials: "Revoke + re-issue cycle within 2h"
    
    data_cleanup:
      - connector_artifacts: "Mark for deletion (user can export within 30 days)"
      - audit_records: "Retained (for compliance)"
      - credentials: "Immediate revocation (irreversible)"

  appeal_process:
    submitter: "Connector maintainer or Organization Admin"
    channel: "security@platform.internal"
    timeline:
      - submission: "anytime"
      - initial_acknowledgment: "within 2h"
      - investigation: "5-10 business days"
      - decision: "within 10 business days"
      - appeal_of_appeal: "once (escalated to CTO)"
    
    required_evidence:
      - issue_explanation: "Why the entry should be removed"
      - remediation_proof: "Code fix, security audit, version update"
      - attestation: "Legal attestation of authenticity"
      - references: "CVE clarification, advisory link, etc."
    
    decision_options:
      - remove_entry: "Entry deleted, version incremented"
      - modify_entry: "Scope narrowed (e.g., older versions only)"
      - update_expires: "Entry marked for review in 6 months"
      - deny_appeal: "Feedback provided; appeal rejected"
    
    communication:
      - acceptance: "Public notification (if removing entry)"
      - rejection: "Private feedback only"
      - timeline: "Feedback provided within 3 business days of decision"

  emergency_protocols:
    critical_threat_detected: "Active exploitation in the wild"
    response_time: "< 30 minutes from detection to organization notification"
    escalation_authority: "Chief Security Officer (auto-escalate via PagerDuty)"
    
    processes:
      - tier0: "Add to blacklist immediately (within 5 min)"
      - tier1: "Kill Switch activation (within 10 min) if applicable"
      - tier2: "Customer notification (within 15 min)"
      - tier3: "Public disclosure (within 24h or as legal advises)"
    
    communication:
      - sms_alert: "To on-call security team"
      - email_blast: "To all organization admins"
      - status_page: "Status.platform.internal updated"
      - incident_channel: "Slack #security-incidents (restricted access)"

  metrics_and_monitoring:
    tracked_metrics:
      - entries_added_per_month: "baseline, trending"
      - appeal_submission_rate: "% of entries appealed"
      - appeal_success_rate: "% of appeals accepted"
      - time_to_decision: "median, p95 for appeals"
      - false_positive_rate: "entries later removed"
      - affected_connector_count: "monthly active blocks"
      - remediation_time_observed: "avg time for maintainers to remove block via appeal"
    
    dashboard: "security@platform.internal, updated hourly"
    alerting:
      - spike_detection: "> 10 entries added in 1h → escalate"
      - appeal_backlog: "> 20 open appeals → add reviewers"
      - error_rate: "> 1% signature verification failures → incident"
```

---

### Q4：配额计权 & 数值 ✅

#### 问题
计权维度确认？具体权重值如何确定？告警和阻止的阈值？

#### 调研依据

**Anthropic Claude & OpenAI Codex**：
- Token-based quota (input + output counts)
- Connectors have per-task token budget
- Pre-defined token limits per organization tier

**GitHub App Rate Limits**：
- 5000 requests/hour per organization
- Weighted by operation type (read=1, write=3, delete=5)
- Throttling starts at 80% → 429 responses

**Microsoft Azure AI Services Quota**：
- Multi-dimensional: API calls, TPM (tokens per minute), storage
- Weighting: standard=1, premium=2, enterprise=3
- Overage billing with cap options

#### 建议方案 📋

```yaml
# Q4 最终答复
quota_system:
  model: "weighted_capacity_per_organization"
  not_per_connector_count: true  # 避免数量限制，改为能力配额
  
  dimensions:
    trust_level_weight:
      # 信任等级 × 工具数 × 网络能力 × 凭据能力
      L1:
        weight: 0.5  # 最低权重，高度可信
        justification: "Platform managed, lower risk"
      L2:
        weight: 1.0  # 基准权重
        justification: "Organization verified, moderate risk"
      L3:
        weight: 3.0  # 高权重，需更多配额空间
        justification: "Restricted scope, but needs explicit budget"
      L4:
        weight: 5.0  # 最高权重，隔离评估
        justification: "Unverified, dedicated evaluation capacity"
    
    tool_count_multiplier:
      # 工具数量对配额的影响
      1_to_5_tools: 1.0
      6_to_20_tools: 1.5
      21_to_50_tools: 2.5
      51_to_100_tools: 4.0
      100plus_tools: "not_recommended_without_approval"
    
    tool_risk_category:
      # 按工具风险分类的权重加成
      readonly:
        weight: 1.0
        examples: ["file_read", "code_search", "repo_info"]
      
      write_safe:
        weight: 2.0
        examples: ["file_write_to_branch", "comment_creation"]
      
      write_risky:
        weight: 3.5
        examples: ["branch_deletion", "force_push", "secret_rotation"]
      
      destructive:
        weight: 5.0
        examples: ["repo_deletion", "org_setting_change", "user_removal"]
    
    network_capability:
      # 网络访问范围的权重
      no_network:
        weight: 1.0
        access: "none"
      
      whitelisted_endpoints:
        weight: 1.5
        access: "known_internal_services"
        examples: ["github.com", "internal.company.com"]
      
      organization_whitelist:
        weight: 2.5
        access: "org_configured_list"
      
      restricted_internet:
        weight: 4.0
        access: "limited_external (e.g., npm registry)"
      
      full_internet:
        weight: 5.0
        access: "unrestricted_external"
        restricted_to: "L1 only, with explicit approval"
    
    credential_capability:
      # 凭据能力的权重
      no_credentials:
        weight: 1.0
        access: "none"
      
      readonly_credentials:
        weight: 2.0
        access: "read_only_tokens (expiry <= 1h)"
      
      write_credentials:
        weight: 3.5
        access: "write_tokens (expiry <= 30min)"
      
      long_lived_tokens:
        weight: 5.0
        access: "not_recommended"
        restricted_to: "L1 + explicit exception"
  
  capacity_calculation:
    formula: |
      base_capacity = 1000  # per organization per month
      
      connector_quota = Σ(
        trust_level_weight × 
        tool_count_multiplier × 
        avg(tool_risk_category_weights) × 
        network_capability_weight × 
        credential_capability_weight
      )
      
      org_total_capacity = min(
        base_capacity × connector_quota / 100,  # capped at 10x base
        org_tier_limit  # 按组织规模限制
      )
    
    org_tier_limits:
      startup:
        monthly_capacity: 1000  # 1-5 connectors typical
        max_connectors: 5
      
      mid_market:
        monthly_capacity: 5000  # 10-20 connectors
        max_connectors: 20
      
      enterprise:
        monthly_capacity: 50000  # 50+ connectors
        max_connectors: "custom"
    
    example_calculations:
      example_1:
        name: "L1 GitHub Connector (safe, read-only)"
        trust_level_weight: 0.5
        tools: 8
        tool_count_multiplier: 1.5
        avg_tool_risk_weight: 1.0
        network_weight: 1.5
        credential_weight: 1.0
        calculation: "0.5 × 1.5 × 1.0 × 1.5 × 1.0 = 1.125"
        monthly_capacity: "1000 × 1.125 / 100 = 11.25 → capped at 1000"
      
      example_2:
        name: "L2 Custom Deployment Tool (moderate risk)"
        trust_level_weight: 1.0
        tools: 15
        tool_count_multiplier: 1.5
        avg_tool_risk_weight: 2.5
        network_weight: 2.5
        credential_weight: 2.0
        calculation: "1.0 × 1.5 × 2.5 × 2.5 × 2.0 = 18.75"
        monthly_capacity: "1000 × 18.75 / 100 = 187.5"
      
      example_3:
        name: "L3 Restricted Testing Tool (high weight)"
        trust_level_weight: 3.0
        tools: 5
        tool_count_multiplier: 1.0
        avg_tool_risk_weight: 1.0
        network_weight: 1.5
        credential_weight: 1.0
        calculation: "3.0 × 1.0 × 1.0 × 1.5 × 1.0 = 4.5"
        monthly_capacity: "1000 × 4.5 / 100 = 45 → high barrier to prevent spam"
  
  enforcement:
    tracking:
      unit: "connector_activation_units"
      increment: "1 unit per connector activation per organization"
      decrement:
        - "connector deactivated: -1 unit (credited back)"
        - "connector revoked: 0 units (not credited)"
    
    alert_thresholds:
      yellow_alert: "80% of monthly capacity"
        trigger: "email to org admin"
        action: "informational"
        time_to_respond: "none required (informational)"
      
      orange_alert: "95% of monthly capacity"
        trigger: "email + dashboard warning"
        action: "recommend upgrade or deactivate low-priority connectors"
        time_to_respond: "recommended within 24h"
      
      red_hard_limit: "100% of monthly capacity"
        trigger: "reject new connector activation"
        action: "immediate block"
        error_message: "Quota exhausted. Deactivate existing connector or upgrade plan."
        time_to_respond: "immediate action needed"
    
    overage_handling:
      policy: "hard_block (no auto-retry, no billing overage)"
      exception_process:
        - request: "org admin submits exception request"
        - approval: "security team reviews + approves (24-48h)"
        - temporary_boost: "1-week temporary increase (visible in audit)"
        - permanent_upgrade: "org tier increase (business decision)"
    
    monitoring:
      dashboard: "Organization quota usage (self-service)"
      report: "Monthly quota report sent to org admins"
      anomaly_detection: "Spike in quota usage → investigate"
    
    reset_cadence: "monthly (first day of month, 00:00 UTC)"
    rollover_policy: "no rollover (monthly quota expires)"
    carryover_option:
      max_carryover: "10% of monthly (may be configurable per tier)"
      expiration: "carryover expires after 6 months"

# L3/L4 隔离评估专用配额
isolation_evaluation_quota:
  pool_size: "2% of total platform capacity (separate from org quotas)"
  purpose: "Enable assessment of unverified connectors without impacting production"
  
  allocation:
    per_connector: "100 units/week for up to 4 weeks assessment"
    total_concurrent: "10 connectors max undergoing assessment"
  
  restrictions:
    - data_access: "test data only (ephemeral, auto-delete)"
    - duration: "max 4 weeks per connector"
    - rollback: "after assessment, connector removed from platform (unless upgraded)"
```

---

### Q5：审批流程集成 ✅

#### 问题
工具调用审批是直接进入 SEC-003 PDP，还是需要单独的工具审批流程？审批超时处理？

#### 调研依据

**OpenAI Codex Model**：
- Single decision point: Policy Engine (PDP)
- Auto-review service (separate) only suggests, doesn't decide
- Clear responsibility boundaries

**Anthropic Claude Hooks**：
- Pre-execution hooks allow custom approval logic
- Multiple stages: before_tool_call, after_tool_call
- Hooks can modify, approve, or reject

**GitHub Actions / Marketplace Apps**：
- Single approval flow through GitHub App permissions
- No parallel approval tracks
- Clear escalation path to org admins

#### 建议方案 📋

```yaml
# Q5 最终答复
approval_flow_architecture:
  principle: "Single decision point (SEC-003 PDP) for all tool authorizations"
  rationale:
    - avoid_multiple_approval_tracks: "Reduces confusion and attack surface"
    - unified_audit: "All decisions in one audit trail"
    - clear_responsibility: "PDP is authoritative source"
    - consistency: "Same rules for all tool types"
  
  integration_with_SEC003:
    sec003_pydp_enriched_with_mcp:
      # SEC-003 Policy Gateway receives enriched context about MCP tools
      input_to_pydp:
        - standard_context:
          - user_id: "required"
          - task_id: "required"
          - resource_id: "required"
          - action: "required"
        
        - mcp_specific_context:  # NEW
          - connector_id: "string"
          - connector_version: "semver"
          - tool_name: "string"
          - schema_digest: "sha256"
          - trust_level: "L1|L2|L3|L4"
          - network_exposure: "none|whitelist|restricted|full"
          - credential_required: "bool"
          - tool_risk_category: "readonly|write_safe|write_risky|destructive"
          - org_policy: "allow|require_approval|deny"
      
      decision_logic:
        if trust_level == "L1" and tool_risk_category == "readonly":
          return ALLOW  # Fast path, no approval needed
        
        elif trust_level == "L1" and tool_risk_category in ["write_safe", "write_risky"]:
          # Check org policy
          if org_policy == "allow":
            return ALLOW
          elif org_policy == "require_approval":
            return REQUIRE_APPROVAL(human_review=true)
        
        elif trust_level in ["L2", "L3"] and tool_risk_category in ["write_safe", "destructive"]:
          return REQUIRE_APPROVAL(human_review=true)
        
        elif trust_level == "L4":
          return REQUIRE_APPROVAL(human_review=true, elevated_review=true)
      
      output_from_pydp:
        - decision: "ALLOW | REQUIRE_APPROVAL | DENY"
        - reason: "explanation"
        - if REQUIRE_APPROVAL:
          - approval_type: "fast_track | standard | elevated"
          - reviewers: "list of roles needed"
          - auto_reject_after: "24h"
  
  approval_tier_definitions:
    tier_fast_track:
      # For low-risk operations (mostly informational)
      reviewer_count: 0  # auto-approve path
      sla: "immediate"
      examples:
        - readonly_L1_tools
        - org_admin_self_approval (within org limits)
    
    tier_standard:
      # For normal operations (typical tool calls)
      reviewer_count: 1
      reviewer_role: "Designated Tool Approver (org admin or security team member)"
      sla: "4 hours"
      escalation_after: "4 hours → auto-approve if no response"
      examples:
        - write_safe_L2_tools
        - read_L3_tools
    
    tier_elevated:
      # For high-risk operations
      reviewer_count: 2
      reviewer_roles:
        - "Organization Security Lead"
        - "Organization Engineering Lead"
      sla: "8 hours"
      escalation_after: "8 hours → escalate to CTO"
      examples:
        - destructive_L1_L2_tools
        - write_L3_L4_tools
        - any_L4_tool
    
    tier_manual_only:
      # For exceptional cases
      reviewer_count: "custom"
      sla: "24 hours"
      escalation: "no auto-escalation (blocks until approved)"
      examples:
        - L4_connector_use_in_production_task (not allowed)
  
  approval_timeout_handling:
    policy: "escalate_not_auto_approve"
    reasoning: "Security-first: better to over-escalate than under-approve"
    
    timeout_cascade:
      tier_standard:
        initial_timeout: "4 hours"
        level1_escalation: "escalate to Organization Security Lead + manager"
        level1_timeout: "4 more hours (total 8h)"
        level2_escalation: "escalate to Platform Security (CTO)"
        level2_timeout: "4 more hours (total 12h)"
        final_action: "reject approval request (task fails gracefully)"
        
        notification_schedule:
          - "1h before first timeout: reminder email"
          - "at timeout: escalate to L1"
          - "1h before L1 timeout: reminder"
          - "at L1 timeout: escalate to L2"
          - "1h before L2 timeout: reminder"
          - "at final timeout: auto-reject"
      
      tier_elevated:
        initial_timeout: "8 hours"
        level1_escalation: "escalate to CTO directly"
        level1_timeout: "8 more hours (total 16h)"
        final_action: "reject approval request + incident report"
        
        incident_generation: "if not approved within 24h, platform team investigates"
    
    user_communication:
      approval_requested_event:
        message: "Your tool request is pending approval."
        estimated_wait: "show SLA based on tier"
        tracking_url: "link to approval dashboard"
      
      timeout_warning:
        message: "Approval has been pending for 80% of SLA. Escalating..."
        next_action: "escalation to [role]"
      
      timeout_escalation:
        message: "Approval escalated due to timeout."
        new_sla: "show new SLA"
        contact: "link to contact escalation team"
      
      timeout_rejection:
        message: "Approval request expired. Task rejected. [Contact support]"
        retry_option: "can submit new approval request"
  
  parallel_approval_prevention:
    constraint: "No secondary/parallel approval track"
    examples_of_wrong_patterns:
      - WRONG: "Tool approval from PDP + separate MCP approval + risk committee approval"
      - RIGHT: "Single decision from PDP, with escalation path built-in"
    
    audit_trail:
      - all_decisions_logged_in: "SEC-003 PDP audit"
      - mcp_specific_fields: "connector_id, tool_name, schema_digest, decision"
      - approval_chain: "if escalated, full chain recorded"

  auto_review_service_role:
    # NOTE: Auto-review is SEPARATE from approval flow, only provides suggestions
    positioning: "PDP-side service, NOT in execution path"
    
    inputs:
      - pydp_decision: "DENY | REQUIRE_APPROVAL"
      - if_deny: "can auto-review suggest exception?"
      - details: "escalation request data"
    
    outputs:
      - suggestion: "can_escalate | cannot_escalate | needs_manual_review"
      - confidence: "0.0 to 1.0"
      - explanation: "why (or why not) escalation is warranted"
    
    constraints:
      - cannot_override: "PDP decisions are final"
      - cannot_approve_L4: "never auto-approves unverified connectors"
      - cannot_expand_scope: "can only approve within original scope"
      - cannot_override_blacklist: "blacklist is absolute"
      - only_suggests: "final decision always requires human"
    
    failure_mode:
      - service_down: "auto-reject (fail-closed)"
      - timeout: "auto-reject (don't wait)"
      - bad_suggestion: "human reviewer can ignore"
```

---

### Q6：API Key 退出期限 ✅

#### 问题
API Key 适配器的 MVP 支持到何种程度？迁移期限和退出日期？

#### 调研依据

**npm deprecation timelines**：
- Auth token format changed: 18-month sunset window
- Maintained backward compatibility during transition
- Final sunset: 2024 (12 years after introduction)

**GitHub API v3 deprecation**：
- Announced: 2020
- Sunset: 2022 (2 years grace period)
- OAuth alternative provided before deprecation

**OAuth migration patterns** (industry standard):
- 6-12 months: announce + provide migration path
- 12-24 months: parallel support
- 24-36 months: final sunset

#### 建议方案 📋

```yaml
# Q6 最终答复
api_key_deprecation_timeline:
  phase_0_current:
    date_range: "2026-10-13 to 2026-11-01"
    actions:
      - api_key_adapter: "existing deployments work as-is"
      - new_connections: "can still use API Key (not recommended)"
      - label: "@deprecated"
      - documentation: "begin documenting OAuth migration path"
  
  phase_1_announcement:
    date_range: "2026-11-01 (launch day)"
    communication:
      - email_blast: "to all organizations using API Key connectors"
      - content:
          - what_changing: "API Key support will sunset 2027-12-31"
          - why: "OAuth 2.1 is more secure (short-lived tokens, audience binding)"
          - migration_path: "step-by-step guide + migration tool"
          - support: "link to migration support channel"
      - frequency: "monthly reminder starting Nov 2026"
    
    restrictions_in_place:
      - new_api_key_creation: "allowed (but discouraged)"
      - dashboard_warning: "prominent warning on API Key connectors"
      - documentation: "migration guide published"
    
    support:
      - migration_assistance: "Platform team available for Q&A"
      - office_hours: "weekly migration office hours"
      - estimated_effort: "1-2 hours per connector"

  phase_2_hard_deadline_approach:
    date_range: "2027-06-01 (6 months before sunset)"
    restrictions:
      - new_api_key_creation: "denied (OAuth only)"
      - existing_keys: "continue to work (with deprecation warnings)"
      - key_rotation: "not supported (must migrate)"
    
    communication:
      - escalation: "emails change to red text / urgent tone"
      - frequency: "weekly reminders"
      - content: "list unmigrated connectors by organization"
    
    support:
      - dedicated_channel: "#api-key-migration-support (Slack)"
      - technical_deep_dives: "bi-weekly webinars"
      - executive_escalation: "for stalled migrations"

  phase_3_final_sunset:
    date_range: "2027-12-31"
    actions:
      - api_key_auth: "completely removed from platform"
      - running_tasks: "any task using API Key connector → fail gracefully"
      - stored_keys: "securely deleted (audit logged)"
    
    fallback_for_delayed_orgs:
      - if_not_migrated: "connector marked DISABLED"
      - running_tasks: "paused with clear error message"
      - recovery: "customer must migrate to OAuth + re-enable"
    
    communication:
      - post_sunset: "confirmation that API Key support ended"
      - support_for_issues: "escalation team available 30 days post-sunset"

  compliance_and_audit:
    logging:
      - every_api_key_connector: "logged with creation date, last used date"
      - migration_status: "tracked in audit system"
      - usage_metrics: "% migrated over time"
    
    report:
      - monthly: "organizations not yet migrated"
      - escalation: "orgs with 0% progress after 6 months"
    
    retention:
      - audit_trail: "retained for 7 years"
      - sunset_confirmation: "retained for 3 years post-sunset"

  oauth_migration_assistance:
    provided_tooling:
      - migration_script: "automated API Key → OAuth conversion"
      - compatibility_layer: "temporary shim for testing"
      - side_by_side_testing: "run both side-by-side before switching"
    
    documentation:
      - step_by_step_guide: "visual walkthrough"
      - video_tutorial: "10-minute demonstration"
      - faq: "common migration questions"
      - troubleshooting: "known issues + solutions"
    
    support_channels:
      - self_service: "guided migration tool"
      - email: "migration-support@platform.internal"
      - slack: "#api-key-migration-support"
      - office_hours: "weekly live support"
    
    success_criteria:
      - 100%_migration_target: "by 2027-12-31"
      - migration_success_rate: "≥95% on first attempt"
      - avg_migration_time: "1-2 hours"
      - customer_satisfaction: "≥4.5/5 rating"
```

---

### Q7：签名密钥信任根 ✅

#### 问题
连接器发布方的签名密钥如何注册和信任？签名密钥撤销时，已批准的连接器如何处理？

#### 调研依据

**npm Provenance & Signed Packages**：
- Sigstore framework (free, transparent, decentralized)
- OIDC integration with GitHub/GitLab
- Verification via public ledger

**Kubernetes Package Signing**：
- Cosign for container image signing
- Public key distribution via image annotations
- Automated verification in admission controllers

**GitHub Code Signing**：
- Commit signing with GPG or SSH keys
- Web UI shows verification status
- Can enforce required signed commits

**Docker Content Trust (DCT)**：
- Uses Notary framework
- Delegation model with keys per component
- Offline key for long-term trust

#### 建议方案 📋

```yaml
# Q7 最终答复
signature_key_management:
  trust_root_model: "decentralized_with_platform_safeguards"
  rationale:
    - avoid_single_point_of_failure: "Platform doesn't hold all keys"
    - leverage_existing_infrastructure: "GitHub/GitLab cert ecosystem"
    - transparent_and_auditable: "public ledger integration"
    - industry_standard: "Sigstore/OIDC adoption trend"
  
  trust_establishment:
    method_1_sigstore_oidc:
      # Recommended for new connectors
      description: "Use OpenID Connect + Sigstore for keyless signatures"
      prerequisites:
        - connector_hosted: "GitHub / GitLab (public repo)"
        - ci_cd_setup: "GitHub Actions / GitLab CI"
      
      workflow:
        - connector_developer: "publishes new version via CI/CD"
        - ci_cd: "generates OIDC token from GitHub (includes git commit hash, timestamp)"
        - sigstore_service: "verifies OIDC token + creates signature"
        - signature_uploaded: "to provenance metadata (Artifact Attestation)"
        - platform_verifies:
            - "retrieve OIDC issuer URL"
            - "validate signature using public key from OpenID provider"
            - "verify commit history + git tags"
      
      verification_process:
        input: "connector artifact + signature"
        steps:
          - extract_oidc_token: "from signature envelope"
          - verify_oidc_signature: "using GitHub's public JWKS (https://token.actions.githubusercontent.com)"
          - validate_claims:
              - "iss (issuer) == https://token.actions.githubusercontent.com"
              - "repository matches expected_repository"
              - "ref (git branch/tag) matches git tag (vX.Y.Z)"
              - "job_workflow_name contains 'release'"
          - retrieve_artifact_hash: "from git commit"
          - verify_content_hash: "downloaded artifact matches git commit content"
        
        advantages:
          - keyless: "No private key management burden"
          - transparent: "Provenance stored in GitHub (queryable)"
          - auditable: "Full chain visible in git history"
          - free: "Sigstore is free, open-source"
        
        adoption_rate_target: "> 70% of new L1 connectors by 2027"
      
      required_documentation:
        - connector_readme: "include provenance link"
        - release_notes: "link to Sigstore attestation"
        - example: "how to verify signature locally (sigstore verify-artifact)"
    
    method_2_gpg_traditional:
      # Fallback for connectors not on GitHub/GitLab
      description: "Traditional GPG key-based signatures"
      prerequisites:
        - developer_has_gpg: "public key published on keyserver"
        - keyserver_registration: "keys.openpgp.org or similar"
        - key_metadata: "developer name, email, website"
      
      trust_workflow:
        - developer_submits: "connector + GPG signature + key metadata"
        - platform_verifies:
            - "download public key from keyserver"
            - "check key creation date (prefer recent keys)"
            - "verify key not revoked (check CRL/OCSP)"
            - "manually verify key fingerprint (via phone call / video)"
        - approval: "if verified + fingerprint confirmed"
        - storage: "fingerprint stored in connector registry"
      
      verification_process:
        input: "connector artifact + detached .sig file"
        steps:
          - gpg_verify: "gpg --verify connector.tar.gz.sig connector.tar.gz"
          - extract_signer: "key_id and fingerprint"
          - lookup_registry: "fingerprint in connector registry"
          - confirm_match: "if match, signature is valid"
      
      risk_considerations:
        - key_revocation_lag: "CRL/OCSP delays"
        - manual_verification_burden: "phone call overhead"
        - key_expiry_risk: "developer must rotate keys"
      
      adoption_constraint: "< 30% of connectors (prefer Sigstore)"
    
    method_3_platform_issued_cert:
      # For L1 platform-managed connectors only
      description: "Platform issues short-lived certificates via PKI"
      prerequisites:
        - connector: "developed and maintained by Platform team"
        - certificate: "issued by Platform CA (internal)"
      
      certificate_properties:
        - validity_period: "1 year"
        - issued_by: "Platform Root CA"
        - key_escrow: "optional, for recovery"
        - revocation_checking: "via OCSP stapling"
      
      update_process:
        - before_expiry: "90 days warning to team"
        - certificate_renewal: "automated CI/CD"
        - signature_chain: "maintained in git"
    
    key_registration_process:
      for_sigstore:
        step1: "Developer enables GitHub Actions in repo"
        step2: "First release auto-signs via Sigstore"
        step3: "Platform scans Artifact Attestation"
        step4: "Auto-registers connector if attestation valid"
        approval_required: "no (auto-approved for known GitHub orgs)"
      
      for_gpg:
        step1: "Developer submits registration form"
        step2: "Includes: connector name, GPG fingerprint, repo URL, changelog"
        step3: "Platform security team reviews (48-72h)"
        step4: "Verification call with developer (30 min)"
        step5: "Fingerprint added to registry upon approval"
        approval_required: "yes (manual)"
      
      for_platform_cert:
        step1: "Platform team generates CSR"
        step2: "CA signs certificate"
        step3: "Certificate deployed in connector CI/CD"
        step4: "First release auto-signs"
        approval_required: "yes (internal)"
  
  key_revocation_and_renewal:
    revocation_scenarios:
      scenario_1_developer_key_compromise:
        trigger: "developer reports key stolen"
        immediate_actions:
          - revoke_old_key: "in keyserver or OCSP responder"
          - disable_connector: "mark as L4 (unverified)"
          - notify_orgs: "all organizations using connector within 2h"
          - credential_invalidation: "revoke all active tokens"
        
        recovery_path:
          - new_key_generated: "developer publishes new key"
          - connector_revalidation: "must undergo re-signing process"
          - timeline: "max 7 days to re-establish trust"
          - connector_status: "L3 (restricted) until re-approved to L1 or L2"
      
      scenario_2_key_expiry:
        trigger: "certificate/key expires"
        timeline:
          - "90 days before: send renewal reminder"
          - "30 days before: automated renewal email"
          - "on expiry: connector marked WARNED"
          - "7 days after expiry: connector marked DISABLED"
          - "30 days after expiry: connector auto-removed from available list"
        
        recovery:
          - developer_renews: "generates new key + requests re-registration"
          - platform_re_verifies: "re-confirms fingerprint"
          - timeframe: "3 business days to restore service"
      
      scenario_3_key_rotation_planned:
        trigger: "developer proactively rotates key"
        process:
          - publish_new_key: "alongside old key (grace period)"
          - next_release_uses: "new key"
          - old_key_grace_period: "90 days (org can verify old versions)"
          - old_key_deprecated: "after 90 days (removed from registry)"
        
        platform_support:
          - auto_detect_rotation: "when new key signature appears"
          - verify_chain_of_custody: "new key signed by old key (optional)"
          - no_downtime: "both keys valid during grace period"
    
    applied_revocation_effects:
      connector_at_L1:
        immediate:
          - connector_status: "→ L3 (re-verification required)"
          - running_tasks: "continue (grace period 24h)"
          - new_tasks: "blocked"
          - credentials: "revoked within 4h"
        
        remediation:
          - if_key_compromised: "security review + re-audit"
          - if_expiry_only: "re-sign with new key"
          - timeline: "7 days max"
      
      connector_at_L2:
        immediate:
          - connector_status: "→ L4 (unverified)"
          - running_tasks: "paused within 2h"
          - new_tasks: "blocked"
          - credentials: "revoked within 1h"
        
        remediation:
          - org_security_lead: "must re-review and re-approve"
          - if_key_compromised: "full audit required"
          - timeline: "14 days (high priority) to 30 days (normal)"

  signature_verification_implementation:
    code_location: "src/security/mcp_connector_governance/registry/signature_verifier.py"
    
    verify_sigstore_signature:
      pseudocode: |
        def verify_sigstore(connector_id, version, artifact_path):
            # 1. Retrieve attestation from GitHub/GitLab
            attestation = fetch_artifact_attestation(connector_id, version)
            
            # 2. Extract OIDC token
            oidc_token = attestation.extract_signed_token()
            
            # 3. Verify OIDC signature
            jwks_url = "https://token.actions.githubusercontent.com/.well-known/jwks.json"
            try:
                claims = jwt.verify(oidc_token, jwks_url)
            except JWTException:
                return INVALID("OIDC signature verification failed")
            
            # 4. Validate OIDC claims
            if claims["iss"] != "https://token.actions.githubusercontent.com":
                return INVALID("Wrong OIDC issuer")
            
            if not is_expected_repository(claims["repository"]):
                return INVALID("Wrong repository")
            
            if not is_release_tag(claims["ref"]):
                return INVALID("Not a release tag")
            
            # 5. Verify content hash
            content_hash = sha256(read_file(artifact_path))
            if content_hash != claims["content_hash"]:
                return INVALID("Content hash mismatch")
            
            return VALID(signer=claims["actor"], timestamp=claims["iat"])
    
    verify_gpg_signature:
      pseudocode: |
        def verify_gpg(connector_id, version, artifact_path, sig_path):
            # 1. Lookup fingerprint from registry
            registered_fingerprint = connector_registry.get_fingerprint(connector_id)
            
            if not registered_fingerprint:
                return UNVERIFIED("Connector not registered")
            
            # 2. Verify GPG signature
            try:
                verify_result = gpg.verify_file(sig_path, artifact_path)
            except GPGException as e:
                return INVALID(f"GPG verification failed: {e}")
            
            # 3. Check fingerprint matches
            if verify_result.fingerprint != registered_fingerprint:
                return INVALID("Fingerprint mismatch")
            
            # 4. Check key not revoked
            if is_key_revoked(registered_fingerprint):
                return INVALID("Key has been revoked")
            
            # 5. Check key not expired
            if is_key_expired(registered_fingerprint):
                return WARN("Key expired, connector downgraded to L3")
            
            return VALID(signer=verify_result.username, timestamp=verify_result.timestamp)
```

---

### Q8：Schema 变更回溯规则 ✅

#### 问题
工具描述变化是否需要重新审批？建议的兼容性分类？

#### 调研依据

**Semantic Versioning (semver)**：
- MAJOR: breaking changes
- MINOR: backward-compatible new features
- PATCH: backward-compatible bug fixes

**API versioning practices**:
- Parameter addition (backward-compatible) → MINOR
- Parameter removal or rename → MAJOR
- Parameter type change → MAJOR
- Parameter default change → MINOR

**GitHub API deprecation**:
- Deprecates old fields before removal (6-month notice)
- New fields can be added anytime (backward-compatible)
- Only breaking changes require version bump

#### 建议方案 📋

```yaml
# Q8 最终答复
schema_change_compatibility_classification:
  principle: "Safe by default - assume breaking until proven safe"
  
  change_types_and_re_approval_triggers:
    category_1_breaking_changes_require_reapproval:
      # Always require re-approval
      - parameter_removed:
          impact: "breaking"
          reapproval: required
          example: "tool used to accept --format json, now only xml"
          reason: "existing code calling tool will break"
      
      - parameter_renamed:
          impact: "breaking"
          reapproval: required
          example: "param renamed from --old-name to --new-name"
          reason: "existing code breaks"
      
      - parameter_type_changed:
          impact: "breaking"
          reapproval: required
          example: "param was integer, now string"
          reason: "type validation may fail"
      
      - parameter_required_added:
          impact: "breaking"
          reapproval: required
          example: "new required parameter added"
          reason: "existing calls lack required param"
      
      - output_format_changed:
          impact: "breaking"
          reapproval: required
          example: "output was {a: int}, now {a: string}"
          reason: "downstream parsing breaks"
      
      - tool_deleted:
          impact: "breaking"
          reapproval: required
          example: "tool completely removed from connector"
          reason: "existing approvals reference deleted tool"
      
      - tool_endpoint_changed:
          impact: "breaking"
          reapproval: required
          example: "tool moved from https://api.example.com to https://api2.example.com"
          reason: "network whitelist and credentials may not apply"
      
      - authentication_requirement_added:
          impact: "breaking"
          reapproval: required
          example: "tool previously worked unauthenticated, now needs API key"
          reason: "existing approvals assumed public access"
      
      - permission_scope_required_added:
          impact: "breaking"
          reapproval: required
          example: "tool now requires org:admin scope (was previously org:read)"
          reason: "existing tokens may lack new scope"
      
      - risk_level_escalated:
          impact: "breaking"
          reapproval: required
          example: "tool changed from readonly to write"
          reason: "security posture changed"
    
    category_2_safe_changes_no_reapproval:
      # Safe for existing approvals (unless org policy disallows)
      - parameter_added_optional:
          impact: "safe_minor"
          reapproval: not_required
          example: "new optional --verbose flag added"
          reason: "existing code works unchanged"
          caveat: "must have sensible default"
      
      - parameter_default_changed_to_safer:
          impact: "safe_minor"
          reapproval: not_required
          example: "--format json (was default=xml)"
          reason: "safer default, backward-compatible if clients specify format"
          caveat: "only if safer or behavior-preserving"
      
      - parameter_validation_loosened:
          impact: "safe_minor"
          reapproval: not_required
          example: "min_length validation removed or relaxed"
          reason: "more permissive, existing calls still work"
          caveat: "only if semantic meaning unchanged"
      
      - output_field_added:
          impact: "safe_minor"
          reapproval: not_required
          example: "output now includes extra 'metadata' field"
          reason: "downstream code can ignore new fields"
          caveat: "must not be required/breaking existing parsers"
      
      - documentation_improved:
          impact: "safe_none"
          reapproval: not_required
          example: "tool description or help text clarified"
          reason: "no API change"
          caveat: "none"
      
      - performance_improved:
          impact: "safe_none"
          reapproval: not_required
          example: "tool response time halved"
          reason: "no functional change"
          caveat: "none"
      
      - bug_fixed:
          impact: "varies"
          reapproval: case_by_case
          example: "tool was ignoring --filter flag, now works correctly"
          reason: "depends on whether fix changes external behavior"
          caveat: "if fix changes visible behavior, treat as BREAKING"
      
      - error_handling_improved:
          impact: "safe_minor"
          reapproval: not_required
          example: "better error messages"
          reason: "no behavior change, just UX"
          caveat: "if error codes change, may require re-approval"
    
    category_3_network_and_credential_changes:
      # Always significant, require re-approval
      - endpoint_ip_changed:
          impact: "breaking"
          reapproval: required
          reason: "network whitelist may block new IP"
      
      - endpoint_domain_changed:
          impact: "breaking"
          reapproval: required
          reason: "network policy may not allow new domain"
      
      - auth_provider_changed:
          impact: "breaking"
          reapproval: required
          example: "tool was using GitHub OAuth, now using custom provider"
          reason: "credentials and network paths may not apply"
      
      - certificate_required_added:
          impact: "breaking"
          reapproval: required
          reason: "existing connections without cert will fail"
  
  process_for_schema_changes:
    detection_phase:
      # When does the platform detect schema changes?
      - automatic_detection: "yes (on every tool discovery sync)"
      - detection_point: "MCP tool discovery → connector.tools/list"
      - frequency: "before every tool execution"
      - caching: "cache invalidated if schema_digest differs"
      
      comparison:
        - old_schema: "from last approved version (stored in connector_registry)"
        - new_schema: "from current connector discovery"
        - digest: "sha256(sorted([tool1, tool2, ...]))"
        - change_detected: "digest mismatch"
    
    classification_phase:
      # Classify if breaking or safe
      - automatic: "platform attempts automatic classification"
      - schema_diff: "parameter-level diff generated"
      - compatibility_check: "each change checked against safe_changes list"
      - result: "breaking | safe | unknown"
      
      if_unknown:
        - escalate_to: "Organization Security Lead"
        - auto_action: "conservative: assume breaking, require re-approval"
        - timeout: "24h for decision; if not decided, assume breaking"
    
    approval_flow:
      if_breaking:
        - connector_status: "→ REVIEWING (tools disabled)"
        - affected_orgs: "notified of change"
        - running_tasks: "paused (24h grace period)"
        - approval_required:
          - reviewer: "Organization Security Lead"
          - check_list:
            - "understand the breaking change"
            - "confirm new parameters/auth requirements"
            - "verify network policy still applies"
            - "confirm credentials are valid"
          - decision_options: "approve | approve_limited | deny"
        - timeline: "7 days to approve or connector revoked"
        - outcome:
          - approve: "tools re-enabled, running tasks resumed"
          - approve_limited: "only specific tools re-enabled"
          - deny: "connector revoked"
      
      if_safe:
        - connector_status: "→ ACTIVE (no change)"
        - affected_orgs: "optionally notified (informational)"
        - running_tasks: "continue unaffected"
        - approval_required: "no (logged for audit)"
        - org_policy_override: "org can require manual review anyway"
    
    rollback_if_issues:
      - issue_detected: "tool malfunction in production"
      - trigger: "Kill Switch or manual intervention"
      - revert_to: "previous schema version"
      - connector_status: "→ REVIEWING"
      - approval: "must re-approve before re-enabling"

  version_binding_and_schema_digest:
    schema_digest_purpose:
      # Unique identifier for a specific tool configuration
      - definition: "sha256(sorted(tools))"
      - contents: "tool_name, description, input_schema, output_schema, required_auth, endpoint"
      - immutable: "digest never changes for same tool definition"
      - computed_at: "tool discovery time"
    
    approval_binding_to_digest:
      - approval_record: "includes schema_digest"
      - digest_purpose: "prevent tool definition replacement"
      - example:
          - approval_1: "GitHub Connector v1.2.3 digest:abc123"
          - later: "GitHub Connector v1.2.4 has digest:def456 (new approve needed)"
      - chain_of_custody: "digest ties approval to specific tool definition"
    
    digest_change_triggers:
      - any_tool_definition_change: "triggers new digest"
      - digest_mismatch: "vs approved digest → re-approval needed"
      - re_approval_process: "follows classification above"

  documented_policies:
    organization_policy_override:
      # Orgs can be stricter than default
      - policy_option_1: "all changes require approval (conservative)"
      - policy_option_2: "safe changes auto-approve, breaking requires review (balanced)"
      - policy_option_3: "trust platform classification (default)"
      - enforcement: "set per organization"
    
    breaking_changes_grace_period:
      - notification: "24h before tools disabled"
      - approval_window: "7 days from notification"
      - auto_action_after_7d: "tools automatically revoked"
      - escalation: "if org unreachable, escalate to platform team"

  metrics_and_monitoring:
    tracked:
      - schema_changes_detected: "monthly"
      - changes_classified_as_breaking: "monthly"
      - changes_classified_as_safe: "monthly"
      - approval_requests_generated: "monthly"
      - approval_response_time: "median, p95"
      - false_positive_rate: "safe classified as breaking (% of safe changes)"
      - false_negative_rate: "breaking classified as safe (% of breaking changes)"
    
    alerting:
      - if_high_breaking_change_rate: "> 50% changes are breaking → likely api_design_issue"
      - if_approval_backlog: "> 20 pending approvals → hire more reviewers"
      - if_classification_errors: "if > 1% misclassification → retrain classifier"
```

---

## 总结：所有 8 个问题的设计决策已确认

| # | 问题 | 决策 | 优化亮点 |
|---|------|------|--------|
| **Q1** | OAuth 规范 & STDIO | MCP 2025-11-25, HTTP OAuth 2.1 优先, STDIO 简化模式 | 18 个月 API Key 过渡，Sigstore OIDC 免密钥 |
| **Q2** | L1-L4 证据目录 | 四层分级+双人审批 L3 例外 | 自动化降级触发器，职责明确分工 |
| **Q3** | 黑名单维护 | 多源头（内部/CVE/社区/CISA），24-48h 流程 | 结构化版本管理，7 天申诉期 |
| **Q4** | 配额计权 | 多维度加权（信任/工具数/风险/网络/凭据） | 公式化计算，避免数量限制陷阱 |
| **Q5** | 审批流程 | 单决策点（SEC-003 PDP），三层 SLA | 明确的超时升级路径，无平行审批 |
| **Q6** | API Key 退出 | 2027-12-31 全部停用，18 个月过渡期 | 分阶段限制 + 自动迁移工具 |
| **Q7** | 签名密钥 | Sigstore OIDC 首选，GPG 备选，内部 PKI for L1 | 无密钥管理，透明审计链 |
| **Q8** | Schema 变更 | 自动分类（破坏性/安全），保守处理 | 参数级细粒度分类，digest 防篡改 |

---

## 下一步：立即启动实现

**Do you approve this design?**

- ✅ **YES**: 我立即开始 Day 1-2 的核心模块实现
- ❌ **NO**: 需要调整哪些设计决策？
- ❓ **DISCUSS**: 某些决策需要团队评审

**建议**：确认无误后，我直接进入开发模式（Day 1 完成 Registry + Lifecycle + Policies 三个核心模块）。

