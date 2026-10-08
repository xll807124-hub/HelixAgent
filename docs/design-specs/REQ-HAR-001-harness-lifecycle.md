# REQ-HAR-001: Harness 生命周期管理

> **需求编号**: REQ-HAR-001  
> **需求名称**: Harness 生命周期  
> **优先级**: P0  
> **状态**: v0.1-designed（待跨模块评审与冻结）  
> **创建日期**: 2026-09-26  
> **依赖**: REQ-RT-001（核心实体 Schema）、REQ-SEC-003（Policy Gateway）  
> **被依赖**: REQ-HAR-002 至 REQ-HAR-006

---

## 一、设计目标

### 1.1 核心定位

**Harness 是可靠性验证的独立执行器**，而非 Agent 运行时包装器。它的职责是：
- 对被测系统（Task、Worker、Tool 等）进行故障注入和恢复验证
- 独立于被测系统的状态机，拥有自己的生命周期和判定逻辑
- 产出结构化的可审计判决（verdict）和证据包

**Harness 一次运行 = 一个可审计的实验**，必须具备独立的终态与回收义务。

### 1.2 设计原则

| 原则 | 说明 |
|------|------|
| **状态独立性** | Harness 不复用被测系统状态机，避免循环依赖 |
| **完整隔离** | 独立租户、独立凭据、独立观测，不污染生产环境 |
| **可审计性** | 每次运行产出结构化判决+证据包，支持事后审查 |
| **终态保证** | 所有 Harness 必须进入终态（REAPED），不允许悬置 |
| **自我验证** | Harness 必须是它验证契约的第一个客户 |

---

## 二、Harness 状态机设计

### 2.1 状态机全景

```
┌──────────────────────────────────────────────────────────────────┐
│                  Harness 独立状态机                                 │
│                                                                    │
│   ┌──────────┐                                                    │
│   │ CREATED  │ ← 测试计划创建                                      │
│   └────┬─────┘                                                    │
│        │ allocate_resources()                                     │
│        ▼                                                          │
│   ┌──────────┐                                                    │
│   │ ARMED    │ ← 资源就绪，可回退点已打点                          │
│   └────┬─────┘                                                    │
│        │ inject_fault()                                           │
│        ▼                                                          │
│   ┌──────────┐     ┌───────────────┐                             │
│   │ RUNNING  │ ──→ │ INCONCLUSIVE  │ ← 无法判定（如超时）         │
│   └────┬─────┘     └───────┬───────┘                             │
│        │                    │                                     │
│        │ collect_evidence() │                                     │
│        ▼                    │                                     │
│   ┌──────────┐              │                                     │
│   │ JUDGING  │ ← 评判阶段   │                                     │
│   └────┬─────┘              │                                     │
│        │                    │                                     │
│        ├─→ PASS ────────────┤                                     │
│        ├─→ FAIL ────────────┤                                     │
│        └─→ INCONCLUSIVE ────┘                                     │
│             │                                                      │
│             └───────→ reap_resources()                            │
│                       │                                            │
│                       ▼                                            │
│                  ┌──────────┐                                     │
│                  │ REAPED   │ ← 终态，资源已回收                  │
│                  └──────────┘                                     │
│                                                                    │
└──────────────────────────────────────────────────────────────────┘
```

### 2.2 状态定义

| 状态 | 说明 | 前置条件 | 后置保证 |
|------|------|---------|---------|
| **CREATED** | 测试计划已创建，等待资源分配 | 有效的测试计划 | - |
| **ARMED** | 资源已就绪，可回退点已打点 | 资源分配成功 + Checkpoint 已保存 | 可安全注入故障 |
| **RUNNING** | 故障注入中，收集观测数据 | ARMED 状态 | 产出观测数据 |
| **JUDGING** | 评判阶段，分析证据产出判决 | 观测数据完整 | 产出结构化判决 |
| **PASS** | 测试通过 | 满足所有断言 | 生成 PASS 证据包 |
| **FAIL** | 测试失败 | 违反至少一个断言 | 生成 FAIL 证据包 |
| **INCONCLUSIVE** | 无法判定（超时/数据不足） | 判定器无法得出结论 | 标记为待人工审查 |
| **REAPED** | 终态，所有资源已回收 | PASS/FAIL/INCONCLUSIVE | 资源完全释放 |

### 2.3 状态迁移规则

| 当前状态 | 触发事件 | 目标状态 | 前置条件 | 后置动作 |
|---------|---------|---------|---------|---------|
| CREATED | allocate_resources() | ARMED | 沙箱/租户/凭据分配成功 | 打 Checkpoint，记录回滚计划 |
| ARMED | inject_fault() | RUNNING | Checkpoint 已保存 | 执行故障注入，启动观测 |
| RUNNING | collect_evidence() | JUDGING | 观测窗口结束 | 停止注入，汇总证据 |
| RUNNING | timeout() | INCONCLUSIVE | 超时未收集到足够证据 | 记录超时原因 |
| JUDGING | analyze() | PASS/FAIL/INCONCLUSIVE | 判定器完成分析 | 产出结构化判决 |
| PASS/FAIL/INCONCLUSIVE | reap_resources() | REAPED | 判决已确认 | 释放沙箱、撤销凭据、清理租户 |

### 2.4 关键约束

#### 2.4.1 ARMED 前的可回退点

**必须完成的打点内容**：
1. **被测系统 Checkpoint**：保存被测系统的完整状态快照
2. **Harness 侧回滚计划**：
   - 已分配的沙箱 ID、租户 ID、凭据 ID
   - 已创建的测试数据标识
   - 已注册的故障注入点
3. **回滚验证**：执行一次 dry-run 回滚，验证可行性

**ARMED 门禁条件**：
```python
def can_enter_armed(harness: HarnessInstance) -> Tuple[bool, str]:
    """ARMED 状态门禁检查"""
    checks = [
        ("被测系统 checkpoint 已保存", harness.has_system_checkpoint()),
        ("回滚计划已生成", harness.has_rollback_plan()),
        ("回滚可行性已验证", harness.rollback_verified()),
        ("隔离资源已就绪", harness.all_resources_allocated()),
        ("观测点已插桩", harness.all_probes_armed())
    ]
    
    failed = [name for name, check in checks if not check]
    if failed:
        return False, f"ARMED 门禁失败: {', '.join(failed)}"
    return True, "ARMED 门禁通过"
```

#### 2.4.2 JUDGING 必须产出结构化判决

**禁止布尔值判决**，必须产出完整的 Verdict 对象：

```python
@dataclass
class HarnessVerdict:
    """Harness 判决结构"""
    verdict_id: UUID
    harness_run_id: UUID
    outcome: Literal["PASS", "FAIL", "INCONCLUSIVE"]
    
    # 结构化断言结果
    assertions: List[AssertionResult]  # 每个断言的详细结果
    
    # 证据包
    evidence: EvidenceBundle
    
    # 判定理由
    reasoning: str
    confidence: float  # 0.0-1.0
    
    # 可复现性
    reproducible: bool
    reproduction_seed: Optional[str]
    
    # 判定器元数据
    verifier_version: str
    verifier_config: Dict[str, Any]
    
    # 时间戳
    judged_at: datetime
```

**AssertionResult 定义**：

```python
@dataclass
class AssertionResult:
    """单个断言的结果"""
    assertion_id: str
    assertion_type: Literal["safety", "liveness", "performance"]
    description: str
    
    outcome: Literal["PASS", "FAIL", "INCONCLUSIVE"]
    
    # 实际观测值 vs 期望值
    observed: Any
    expected: Any
    
    # 违反证据（FAIL 时）
    violations: List[ViolationEvidence]
    
    # 超时/数据不足（INCONCLUSIVE 时）
    inconclusive_reason: Optional[str]
```

#### 2.4.3 INCONCLUSIVE 不等于 PASS

**INCONCLUSIVE 必须单独计数并设上限**：

```python
class Inconclusive Policy:
    """INCONCLUSIVE 治理策略"""
    
    MAX_INCONCLUSIVE_RATE = 0.05  # 5%
    
    def check_inconclusive_rate(self, test_suite: TestSuite) -> CheckResult:
        """检查 INCONCLUSIVE 比例"""
        total = test_suite.total_runs
        inconclusive = test_suite.inconclusive_count
        rate = inconclusive / total if total > 0 else 0.0
        
        if rate > self.MAX_INCONCLUSIVE_RATE:
            return CheckResult(
                passed=False,
                message=f"INCONCLUSIVE 率 {rate:.1%} 超过阈值 {self.MAX_INCONCLUSIVE_RATE:.1%}，"
                        f"阻断发布。需人工审查 {inconclusive} 个无法判定的用例。"
            )
        
        return CheckResult(passed=True, message=f"INCONCLUSIVE 率 {rate:.1%} 正常")
```

**INCONCLUSIVE 原因分类**：

| 原因类别 | 说明 | 处理策略 |
|---------|------|---------|
| `TIMEOUT` | 观测窗口不足 | 增加超时时间或优化判定器 |
| `INSUFFICIENT_DATA` | 证据数据不完整 | 检查观测点插桩 |
| `FLAKY_BEHAVIOR` | 行为不稳定 | 标记为 flaky，增加重跑次数 |
| `VERIFIER_BUG` | 判定器自身缺陷 | 修复判定器，重新评判 |
| `UNKNOWN` | 未知原因 | 人工审查 |

#### 2.4.4 REAPED 是终态且不可逆

**回收清单（必须覆盖所有 Harness 创建的资源）**：

```python
@dataclass
class ReapChecklist:
    """资源回收清单"""
    
    # 沙箱资源
    sandbox_terminated: bool
    sandbox_cleanup_verified: bool
    
    # 凭据资源
    credentials_revoked: bool
    credential_cache_cleared: bool
    
    # 测试租户
    test_tenant_deleted: bool
    tenant_data_purged: bool
    
    # 队列消息
    injected_messages_consumed: bool
    pending_events_cleared: bool
    
    # 观测插桩
    probes_uninstalled: bool
    monitors_deregistered: bool
    
    # 测试数据
    test_data_deleted: bool
    database_records_cleaned: bool
    
    # 网络资源
    test_endpoints_deregistered: bool
    firewall_rules_removed: bool
    
    # 审计证据
    evidence_bundle_archived: bool
    verdict_persisted: bool

def reap_resources(harness: HarnessInstance) -> ReapResult:
    """执行资源回收"""
    checklist = ReapChecklist()
    errors = []
    
    # 按依赖顺序回收
    try:
        checklist.probes_uninstalled = harness.uninstall_probes()
        checklist.credentials_revoked = harness.revoke_credentials()
        checklist.sandbox_terminated = harness.terminate_sandbox()
        checklist.test_tenant_deleted = harness.delete_test_tenant()
        # ... 其他回收步骤
    except Exception as e:
        errors.append(f"回收失败: {e}")
    
    # 验证完整性
    incomplete = [
        field for field, value in asdict(checklist).items()
        if not value
    ]
    
    if incomplete:
        return ReapResult(
            success=False,
            message=f"回收未完成: {', '.join(incomplete)}",
            checklist=checklist,
            errors=errors
        )
    
    return ReapResult(success=True, checklist=checklist)
```

**孤儿扫描例程**（每日执行）：

```python
class OrphanScanner:
    """孤儿资源扫描器"""
    
    def scan_orphans(self) -> OrphanReport:
        """扫描未回收的 Harness 资源"""
        orphans = OrphanReport()
        
        # 扫描悬置沙箱（创建超过 24h 且未关联活跃 Harness）
        orphans.sandboxes = self.find_orphan_sandboxes(max_age=timedelta(hours=24))
        
        # 扫描未撤销凭据（TTL 过期但未删除）
        orphans.credentials = self.find_orphan_credentials()
        
        # 扫描测试租户（Harness 已终止但租户仍存在）
        orphans.test_tenants = self.find_orphan_tenants()
        
        # 扫描未消费消息（Harness 注入但未清理）
        orphans.queue_messages = self.find_orphan_messages()
        
        return orphans
    
    def auto_reap_orphans(self, report: OrphanReport) -> ReapSummary:
        """自动回收孤儿资源"""
        summary = ReapSummary()
        
        for orphan in report.all_orphans():
            if self.is_safe_to_reap(orphan):
                try:
                    self.reap_orphan(orphan)
                    summary.reaped.append(orphan)
                except Exception as e:
                    summary.failed.append((orphan, str(e)))
            else:
                summary.requires_manual_review.append(orphan)
        
        return summary
```

---

## 三、隔离契约设计

### 3.1 核心原则

**Harness 绝不能与被测系统共用身份**，必须建立完整的隔离边界。

### 3.2 租户/命名空间隔离

```python
class HarnessTenantStrategy:
    """Harness 租户策略"""
    
    TENANT_PREFIX = "harness-"
    
    def allocate_test_tenant(self, harness_id: UUID) -> TenantContext:
        """为 Harness 运行分配独立测试租户"""
        tenant_id = f"{self.TENANT_PREFIX}{harness_id}"
        
        # 创建隔离租户
        tenant = self.create_tenant(
            tenant_id=tenant_id,
            isolation_level="STRICT",
            allow_destructive_ops=True,  # 允许故障注入
            data_retention_policy="EPHEMERAL"  # 短期保留
        )
        
        # 标记为测试租户
        tenant.labels["purpose"] = "harness-testing"
        tenant.labels["expires_at"] = (datetime.now() + timedelta(hours=24)).isoformat()
        
        return TenantContext(tenant=tenant, namespace=tenant_id)
```

**禁止在真实客户租户上注入破坏性故障**：

```python
class DestructiveOpGuard:
    """破坏性操作防护"""
    
    PRODUCTION_TENANTS = {"customer-*", "prod-*"}
    
    def check_destructive_op(self, op: Operation, tenant_id: str) -> CheckResult:
        """检查破坏性操作是否允许"""
        if op.is_destructive:
            if self.is_production_tenant(tenant_id):
                return CheckResult(
                    allowed=False,
                    message=f"禁止在生产租户 {tenant_id} 上执行破坏性操作 {op.name}"
                )
            
            if not tenant_id.startswith("harness-"):
                return CheckResult(
                    allowed=False,
                    message=f"破坏性操作只允许在 harness-* 租户，当前: {tenant_id}"
                )
        
        return CheckResult(allowed=True)
```

### 3.3 独立凭据与速率桶

```python
class HarnessCredentialManager:
    """Harness 凭据管理"""
    
    def issue_harness_credentials(self, harness_id: UUID) -> HarnessCredentials:
        """为 Harness 签发独立凭据"""
        creds = HarnessCredentials(
            credential_id=f"harness-cred-{harness_id}",
            tenant_id=f"harness-{harness_id}",
            
            # 独立速率桶
            rate_limit=RateLimit(
                requests_per_minute=1000,
                quota_bucket=f"harness-{harness_id}",
                isolated_from_production=True  # 不共享生产配额
            ),
            
            # 短期有效
            expires_at=datetime.now() + timedelta(hours=4),
            
            # 权限受限
            permissions=[
                "harness:inject_fault",
                "harness:observe_metrics",
                "harness:read_audit_log"
            ],
            
            # 标记为测试凭据
            labels={"purpose": "harness-testing", "harness_id": str(harness_id)}
        )
        
        return creds
```

**注入流量不能挤占生产配额**：

```python
class RateLimitIsolation:
    """速率限制隔离"""
    
    def enforce_isolation(self, request: Request) -> Decision:
        """确保 Harness 流量不影响生产"""
        if request.is_from_harness():
            # 使用独立的 Harness 配额
            quota = self.get_harness_quota(request.harness_id)
            
            # Harness 流量与生产流量使用不同的熔断器
            circuit_breaker = self.get_harness_circuit_breaker()
            
            if circuit_breaker.is_open():
                return Decision.REJECT(reason="Harness 熔断器已打开")
            
            if not quota.allow():
                return Decision.REJECT(reason="Harness 配额耗尽")
            
            return Decision.ALLOW(quota_bucket="harness")
        else:
            # 生产流量使用生产配额
            return self.enforce_production_limit(request)
```

### 3.4 观测面只读

```python
class HarnessObservability:
    """Harness 观测策略"""
    
    ALLOWED_READ_SOURCES = [
        "audit_log",      # 审计日志
        "effect_log",     # Effect Log
        "metrics",        # 指标
        "checkpoint",     # 检查点
        "event_stream"    # 事件流
    ]
    
    FORBIDDEN_WRITE_TARGETS = [
        "business_tables",   # 业务表
        "customer_data",     # 客户数据
        "production_config"  # 生产配置
    ]
    
    def check_observation_access(self, op: ObservationOp) -> CheckResult:
        """检查观测操作权限"""
        if op.is_write():
            if op.target in self.FORBIDDEN_WRITE_TARGETS:
                return CheckResult(
                    allowed=False,
                    message=f"Harness 禁止写入 {op.target}，只允许读取观测数据"
                )
        
        if op.is_read() and op.source not in self.ALLOWED_READ_SOURCES:
            return CheckResult(
                allowed=False,
                message=f"Harness 只允许读取 {self.ALLOWED_READ_SOURCES}，"
                        f"当前尝试: {op.source}"
            )
        
        return CheckResult(allowed=True)
```

### 3.5 故障注入点在框架层插桩

**禁止通过修改业务代码模拟故障**，必须在框架层插桩：

```python
class FaultInjectionFramework:
    """框架层故障注入"""
    
    INJECTION_POINTS = {
        "worker_crash": "在 Worker 执行前注入进程崩溃",
        "checkpoint_write_fail": "在 Checkpoint 写入时注入 I/O 错误",
        "lock_loss": "在分布式锁持有期间注入租约丢失",
        "downstream_timeout": "在下游调用时注入超时",
        "probe_fail": "在对账探测时注入失败响应"
    }
    
    def inject_fault(self, fault_type: str, target: str) -> InjectionHandle:
        """在框架层注入故障"""
        if fault_type not in self.INJECTION_POINTS:
            raise ValueError(f"不支持的故障类型: {fault_type}")
        
        # 在框架层拦截点注入
        handle = self.framework.register_interceptor(
            intercept_point=self._get_intercept_point(fault_type),
            behavior=self._get_fault_behavior(fault_type),
            target=target
        )
        
        return handle
    
    def _get_intercept_point(self, fault_type: str) -> str:
        """获取框架拦截点"""
        mapping = {
            "worker_crash": "worker.before_execute",
            "checkpoint_write_fail": "checkpoint.on_write",
            "lock_loss": "lock.on_renew",
            "downstream_timeout": "http.before_request",
            "probe_fail": "probe.on_query"
        }
        return mapping[fault_type]
```

### 3.6 虚拟时钟驱动

```python
class VirtualClock:
    """虚拟时钟（用于加速时间相关测试）"""
    
    def __init__(self, real_time: bool = False):
        self.real_time = real_time
        self.virtual_now = datetime.now()
        self.time_scale = 1.0  # 1.0 = 实时，10.0 = 10 倍速
    
    def now(self) -> datetime:
        """获取当前时间"""
        if self.real_time:
            return datetime.now()
        return self.virtual_now
    
    def advance(self, delta: timedelta) -> None:
        """推进虚拟时间"""
        if self.real_time:
            raise ValueError("实时模式下不能推进时间")
        self.virtual_now += delta
    
    def sleep(self, duration: timedelta) -> None:
        """虚拟睡眠"""
        if self.real_time:
            time.sleep(duration.total_seconds())
        else:
            self.advance(duration)

# 使用虚拟时钟测试退避、TTL、审批超时
def test_retry_backoff_with_virtual_clock():
    clock = VirtualClock(real_time=False)
    harness = Harness(clock=clock)
    
    # 注入故障触发重试
    harness.inject_fault("api_timeout", target="model_service")
    
    # 推进时间验证退避行为
    clock.advance(timedelta(seconds=1))  # 第 1 次重试（1s 退避）
    assert harness.retry_count == 1
    
    clock.advance(timedelta(seconds=2))  # 第 2 次重试（2s 退避）
    assert harness.retry_count == 2
    
    clock.advance(timedelta(seconds=4))  # 第 3 次重试（4s 退避）
    assert harness.retry_count == 3
```

---

## 四、三层断言体系

### 4.1 断言分层原则

**断言分三层，混在一起会互相掩盖**：

```python
class AssertionLayer(Enum):
    """断言层级"""
    SAFETY = "safety"      # 安全属性（never）
    LIVENESS = "liveness"  # 活性属性（eventually）
    PERFORMANCE = "performance"  # 性能属性（SLO）
```

### 4.2 安全属性（never）- 红线级

**任一命中即红，且进发布阻断清单**。

```python
@dataclass
class SafetyAssertion:
    """安全属性断言"""
    assertion_id: str
    description: str
    violation_severity: Literal["CRITICAL"]  # 永远是 CRITICAL
    
    def check(self, evidence: Evidence) -> AssertionResult:
        """检查安全属性"""
        pass

class SafetyAssertions:
    """安全属性断言集"""
    
    @safety_assertion
    def no_duplicate_side_effects(self, evidence: Evidence) -> AssertionResult:
        """断言：重复调用不产生重复副作用"""
        effects = evidence.get_effects()
        unique_effects = self._deduplicate_by_idempotency_key(effects)
        
        if len(effects) > len(unique_effects):
            duplicates = [e for e in effects if effects.count(e) > 1]
            return AssertionResult(
                outcome="FAIL",
                observed=len(effects),
                expected=len(unique_effects),
                violations=[
                    ViolationEvidence(
                        type="DUPLICATE_SIDE_EFFECT",
                        description=f"检测到重复副作用: {dup}",
                        evidence=dup
                    ) for dup in duplicates
                ]
            )
        
        return AssertionResult(outcome="PASS")
    
    @safety_assertion
    def no_orphan_resources(self, evidence: Evidence) -> AssertionResult:
        """断言：没有孤儿资源"""
        allocated = evidence.get_allocated_resources()
        released = evidence.get_released_resources()
        
        orphans = allocated - released
        
        if orphans:
            return AssertionResult(
                outcome="FAIL",
                violations=[
                    ViolationEvidence(
                        type="ORPHAN_RESOURCE",
                        description=f"资源未释放: {resource}",
                        evidence=resource
                    ) for resource in orphans
                ]
            )
        
        return AssertionResult(outcome="PASS")
    
    @safety_assertion
    def no_privilege_escalation(self, evidence: Evidence) -> AssertionResult:
        """断言：没有越权执行"""
        operations = evidence.get_operations()
        
        violations = []
        for op in operations:
            if op.executed_privilege > op.authorized_privilege:
                violations.append(
                    ViolationEvidence(
                        type="PRIVILEGE_ESCALATION",
                        description=f"操作 {op.name} 越权执行",
                        evidence={
                            "authorized": op.authorized_privilege,
                            "executed": op.executed_privilege
                        }
                    )
                )
        
        if violations:
            return AssertionResult(outcome="FAIL", violations=violations)
        
        return AssertionResult(outcome="PASS")
    
    @safety_assertion
    def no_silent_event_loss(self, evidence: Evidence) -> AssertionResult:
        """断言：事件不静默丢失"""
        emitted = evidence.get_emitted_events()
        persisted = evidence.get_persisted_events()
        
        lost = emitted - persisted
        
        if lost:
            return AssertionResult(
                outcome="FAIL",
                violations=[
                    ViolationEvidence(
                        type="SILENT_EVENT_LOSS",
                        description=f"事件 {event} 发出但未持久化",
                        evidence=event
                    ) for event in lost
                ]
            )
        
        return AssertionResult(outcome="PASS")
```

### 4.3 活性属性（eventually）- 带时限断言

```python
@dataclass
class LivenessAssertion:
    """活性属性断言"""
    assertion_id: str
    description: str
    timeout: timedelta  # 时限
    
    def check_with_timeout(self, evidence: Evidence) -> AssertionResult:
        """带超时的活性检查"""
        pass

class LivenessAssertions:
    """活性属性断言集"""
    
    @liveness_assertion(timeout=timedelta(minutes=30))
    def eventually_converges(self, evidence: Evidence) -> AssertionResult:
        """断言：最终收敛到一致状态"""
        states = evidence.get_state_snapshots()
        final_state = states[-1]
        
        if not self._is_consistent(final_state):
            return AssertionResult(
                outcome="FAIL",
                observed=final_state,
                expected="consistent_state",
                violations=[
                    ViolationEvidence(
                        type="CONVERGENCE_FAILURE",
                        description="系统未能收敛到一致状态",
                        evidence=final_state
                    )
                ]
            )
        
        return AssertionResult(outcome="PASS")
    
    @liveness_assertion(timeout=timedelta(hours=4))
    def escalated_resolved_within_slo(self, evidence: Evidence) -> AssertionResult:
        """断言：ESCALATED 状态在 SLO 内解决"""
        escalated_cases = evidence.get_escalated_cases()
        
        violations = []
        for case in escalated_cases:
            if case.resolution_time and case.resolution_time > timedelta(hours=4):
                violations.append(
                    ViolationEvidence(
                        type="SLO_VIOLATION",
                        description=f"ESCALATED 案例 {case.id} 解决时间 {case.resolution_time} 超过 SLO",
                        evidence=case
                    )
                )
        
        if violations:
            return AssertionResult(outcome="FAIL", violations=violations)
        
        return AssertionResult(outcome="PASS")
    
    @liveness_assertion(timeout=timedelta(minutes=10))
    def in_doubt_resolved(self, evidence: Evidence) -> AssertionResult:
        """断言：IN_DOUBT 状态被查明"""
        in_doubt_ops = evidence.get_in_doubt_operations()
        
        unresolved = [op for op in in_doubt_ops if not op.is_resolved()]
        
        if unresolved:
            return AssertionResult(
                outcome="FAIL",
                violations=[
                    ViolationEvidence(
                        type="UNRESOLVED_IN_DOUBT",
                        description=f"操作 {op.id} 在 IN_DOUBT 状态未被查明",
                        evidence=op
                    ) for op in unresolved
                ]
            )
        
        return AssertionResult(outcome="PASS")
```

### 4.4 性能属性（SLO）- 用 p95/p99 判定

```python
@dataclass
class PerformanceAssertion:
    """性能属性断言"""
    assertion_id: str
    description: str
    slo_p95: Optional[float] = None
    slo_p99: Optional[float] = None
    
    def check_slo(self, evidence: Evidence) -> AssertionResult:
        """检查 SLO"""
        pass

class PerformanceAssertions:
    """性能属性断言集"""
    
    @performance_assertion(slo_p99=100)  # 100ms
    def checkpoint_write_latency(self, evidence: Evidence) -> AssertionResult:
        """断言：Checkpoint 写入延迟 p99 < 100ms"""
        latencies = evidence.get_checkpoint_write_latencies()
        p99 = self._calculate_percentile(latencies, 99)
        
        if p99 > 100:
            return AssertionResult(
                outcome="FAIL",
                observed=f"p99={p99}ms",
                expected="p99<100ms",
                violations=[
                    ViolationEvidence(
                        type="SLO_VIOLATION",
                        description=f"Checkpoint 写入 p99 延迟 {p99}ms 超过 SLO 100ms",
                        evidence={"p99": p99, "p95": self._calculate_percentile(latencies, 95)}
                    )
                ]
            )
        
        return AssertionResult(outcome="PASS", observed=f"p99={p99}ms")
    
    @performance_assertion(slo_p95=5000)  # 5s
    def recovery_duration(self, evidence: Evidence) -> AssertionResult:
        """断言：恢复耗时 p95 < 5s"""
        durations = evidence.get_recovery_durations()
        p95 = self._calculate_percentile(durations, 95)
        
        if p95 > 5000:
            return AssertionResult(
                outcome="FAIL",
                observed=f"p95={p95}ms",
                expected="p95<5000ms"
            )
        
        return AssertionResult(outcome="PASS", observed=f"p95={p95}ms")
    
    @performance_assertion(slo_p95=1000)  # 1s
    def reconciliation_latency(self, evidence: Evidence) -> AssertionResult:
        """断言：对账耗时 p95 < 1s"""
        latencies = evidence.get_reconciliation_latencies()
        p95 = self._calculate_percentile(latencies, 95)
        
        if p95 > 1000:
            return AssertionResult(outcome="FAIL", observed=f"p95={p95}ms", expected="p95<1000ms")
        
        return AssertionResult(outcome="PASS", observed=f"p95={p95}ms")
    
    @performance_assertion(slo_p95=0.01)  # 1%
    def lock_contention_rate(self, evidence: Evidence) -> AssertionResult:
        """断言：锁冲突率 < 1%"""
        total_locks = evidence.get_total_lock_attempts()
        contentions = evidence.get_lock_contentions()
        rate = contentions / total_locks if total_locks > 0 else 0.0
        
        if rate > 0.01:
            return AssertionResult(
                outcome="FAIL",
                observed=f"{rate:.2%}",
                expected="<1%"
            )
        
        return AssertionResult(outcome="PASS", observed=f"{rate:.2%}")
```

---

## 五、Harness 评测治理

### 5.1 与安全对抗样本同源

```python
class HarnessTestRegistry:
    """Harness 测试注册表"""
    
    def register_test_case(self, test: HarnessTestCase) -> None:
        """注册测试用例"""
        # 种子版本化
        test.seed_version = self._compute_seed_version(test)
        
        # 血缘分类
        test.lineage = self._classify_lineage(test)
        
        # 注册到对应血缘组
        self.registry[test.lineage].append(test)
    
    def _classify_lineage(self, test: HarnessTestCase) -> str:
        """分类测试血缘"""
        lineages = {
            "fault_worker_crash": "Worker 进程崩溃注入",
            "fault_timeout": "超时故障注入",
            "fault_lock_loss": "分布式锁丢失注入",
            "fault_probe_fail": "对账探测失败注入",
            "real_incident_replay": "真实故障回放"
        }
        
        return test.fault_type if test.fault_type in lineages else "unknown"
```

### 5.2 血缘分开报告

**禁止混算一个总分**：

```python
class HarnessTestReport:
    """Harness 测试报告"""
    
    def generate_report(self, test_runs: List[HarnessRun]) -> Report:
        """生成分血缘报告"""
        report = Report()
        
        # 按血缘分组
        by_lineage = self._group_by_lineage(test_runs)
        
        for lineage, runs in by_lineage.items():
            lineage_report = LineageReport(
                lineage=lineage,
                total=len(runs),
                passed=sum(1 for r in runs if r.outcome == "PASS"),
                failed=sum(1 for r in runs if r.outcome == "FAIL"),
                inconclusive=sum(1 for r in runs if r.outcome == "INCONCLUSIVE"),
                pass_rate=self._calculate_pass_rate(runs)
            )
            
            report.lineages[lineage] = lineage_report
        
        # 禁止计算总体通过率
        report.overall_pass_rate = None  # 显式禁止
        report.note = "不同血缘的测试不可直接比较，禁止混算总分"
        
        return report
```

### 5.3 Exposure Count 治理

```python
class ExposurePolicy:
    """Exposure 治理策略"""
    
    EXPOSURE_THRESHOLD = 100  # 执行超过 100 次降级
    
    def check_exposure(self, test_case: HarnessTestCase) -> ExposureStatus:
        """检查 Exposure 状态"""
        execution_count = self.get_execution_count(test_case)
        
        if execution_count > self.EXPOSURE_THRESHOLD:
            return ExposureStatus(
                degraded=True,
                reason=f"执行 {execution_count} 次，超过阈值 {self.EXPOSURE_THRESHOLD}",
                action="降级为调试集，不计分",
                message="防止被测系统针对特定故障模式过拟合"
            )
        
        return ExposureStatus(degraded=False)
```

### 5.4 Per-version Holdout 封存故障集

```python
class HoldoutStrategy:
    """Holdout 封存策略"""
    
    def create_holdout_set(self, version: str, test_pool: List[HarnessTestCase]) -> HoldoutSet:
        """为版本创建封存集"""
        # 从测试池中随机抽取 20%
        holdout_size = int(len(test_pool) * 0.2)
        holdout_tests = random.sample(test_pool, holdout_size)
        
        # 封存
        holdout_set = HoldoutSet(
            version=version,
            tests=holdout_tests,
            created_at=datetime.now(),
            sealed=True  # 封存后不可见
        )
        
        # 存储到隔离存储
        self.store_sealed(holdout_set)
        
        return holdout_set
    
    def run_holdout_eval(self, version: str) -> HoldoutResult:
        """运行封存集评估（仅在发布前）"""
        holdout_set = self.load_sealed(version)
        
        if not self.is_release_gate():
            raise PermissionError("Holdout 评估只允许在发布门禁时执行")
        
        # 执行评估
        results = self.execute_tests(holdout_set.tests)
        
        return HoldoutResult(
            version=version,
            pass_rate=self._calculate_pass_rate(results),
            note="Holdout 集仅在发布前评分，平时不可见，防止 Goodhart 定律"
        )
```

### 5.5 Verifier 质量单独报告

```python
class VerifierQualityReport:
    """判定器质量报告"""
    
    def evaluate_verifier(self, verifier: Verifier) -> VerifierQuality:
        """评估判定器质量"""
        # 1. 使用金种子集（已知结果）
        gold_set = self.load_gold_standard_set()
        verifier_results = verifier.judge(gold_set)
        
        # 计算 Precision/Recall
        tp = sum(1 for r in verifier_results if r.correct and r.outcome == "FAIL")
        fp = sum(1 for r in verifier_results if not r.correct and r.outcome == "FAIL")
        fn = sum(1 for r in verifier_results if not r.correct and r.outcome == "PASS")
        
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        
        # 2. 双盲抽检
        blind_sample = self.sample_for_blind_review()
        human_judgments = self.collect_human_judgments(blind_sample)
        agreement = self._calculate_agreement(verifier_results, human_judgments)
        
        return VerifierQuality(
            verifier_version=verifier.version,
            precision=precision,
            recall=recall,
            human_agreement=agreement,
            gold_set_accuracy=tp / len(gold_set)
        )
    
    def track_verifier_changes(self, verifier: Verifier) -> ChangeLog:
        """判定器变更追踪"""
        return ChangeLog(
            version=verifier.version,
            code_hash=self._compute_code_hash(verifier),
            changes=self._get_code_diff(verifier),
            reviewed_by=self._get_reviewers(verifier),
            approved_at=self._get_approval_timestamp(verifier)
        )
```

**判定器失败的任务单独标记**：

```python
def mark_verifier_failure(self, harness_run: HarnessRun, error: Exception) -> None:
    """标记判定器失败"""
    harness_run.verdict = HarnessVerdict(
        outcome="INCONCLUSIVE",
        inconclusive_reason="VERIFIER_FAILURE",
        verifier_error=str(error),
        requires_manual_review=True
    )
    
    # 绝不静默丢弃
    self.alert_verifier_failure(harness_run, error)
    self.create_review_ticket(harness_run)
```

### 5.6 Flakiness 阈值

```python
class FlakinessDetector:
    """Flakiness 检测器"""
    
    CONSISTENCY_THRESHOLD = 0.95  # 95%
    RERUN_COUNT = 10
    
    def detect_flakiness(self, test_case: HarnessTestCase) -> FlakinessReport:
        """检测 Flakiness"""
        # 重跑 N 次
        results = []
        for _ in range(self.RERUN_COUNT):
            result = self.run_test(test_case)
            results.append(result.outcome)
        
        # 计算一致性
        most_common = Counter(results).most_common(1)[0]
        consistency = most_common[1] / len(results)
        
        if consistency < self.CONSISTENCY_THRESHOLD:
            return FlakinessReport(
                test_case=test_case,
                is_flaky=True,
                consistency=consistency,
                action="隔离，不进评分集",
                reason=f"重跑 {self.RERUN_COUNT} 次一致性 {consistency:.1%} < {self.CONSISTENCY_THRESHOLD:.1%}"
            )
        
        return FlakinessReport(
            test_case=test_case,
            is_flaky=False,
            consistency=consistency
        )
```

---

## 六、回收与保留期

### 6.1 Harness 产物分类

**Harness 运行产物拆成两半，挂靠已有策略**：

```python
class HarnessArtifactPolicy:
    """Harness 产物策略"""
    
    def classify_artifact(self, artifact: Artifact) -> ArtifactClass:
        """分类产物"""
        if artifact.type in ["verdict", "evidence_bundle", "assertion_results"]:
            # 判决类产物：挂靠审计日志策略
            return ArtifactClass(
                category="AUDIT",
                retention_policy=self.audit_log_policy,
                min_retention=timedelta(days=180)
            )
        elif artifact.type in ["sandbox_logs", "trace_data", "metrics_snapshot"]:
            # 观测类产物：挂靠可观测数据策略
            return ArtifactClass(
                category="OBSERVABILITY",
                retention_policy=self.observability_policy,
                min_retention=timedelta(days=30)
            )
        elif artifact.type in ["test_data", "temp_files", "cache"]:
            # 临时产物：短期保留
            return ArtifactClass(
                category="EPHEMERAL",
                retention_policy=self.ephemeral_policy,
                min_retention=timedelta(hours=24)
            )
```

### 6.2 GC 保护谓词

```python
class GCProtection:
    """GC 保护谓词"""
    
    def can_delete(self, artifact: HarnessArtifact) -> Tuple[bool, str]:
        """判断是否可以删除"""
        # 1. 存在 open case
        if self.has_open_case(artifact):
            return False, "关联的案例仍未关闭"
        
        # 2. Legal Hold
        if self.under_legal_hold(artifact):
            return False, "受 Legal Hold 保护"
        
        # 3. 未决 verdict 复评
        if self.pending_reverdict_review(artifact):
            return False, "存在未决的判决复评需求"
        
        # 4. 保留期未到
        if not self.retention_period_expired(artifact):
            return False, f"保留期未到（剩余 {self.remaining_retention(artifact)}）"
        
        return True, "可以删除"
```

### 6.3 孤儿扫描例程

**每日执行，Harness 是全平台唯一被授权制造故障的组件，其泄漏速度远快于业务**：

```python
class OrphanScanScheduler:
    """孤儿扫描调度器"""
    
    def schedule_daily_scan(self):
        """调度每日扫描"""
        schedule.every().day.at("02:00").do(self.run_orphan_scan)
    
    def run_orphan_scan(self) -> OrphanScanReport:
        """执行孤儿扫描"""
        report = OrphanScanReport()
        
        # 1. 扫描无主沙箱
        orphan_sandboxes = self.find_orphan_sandboxes()
        report.sandboxes = orphan_sandboxes
        
        # 2. 扫描悬置租约
        orphan_leases = self.find_orphan_leases()
        report.leases = orphan_leases
        
        # 3. 扫描未回收测试租户
        orphan_tenants = self.find_orphan_test_tenants()
        report.tenants = orphan_tenants
        
        # 4. 扫描未清理凭据
        orphan_credentials = self.find_orphan_credentials()
        report.credentials = orphan_credentials
        
        # 自动回收
        reap_result = self.auto_reap_safe_orphans(report)
        
        # 告警
        if report.has_critical_orphans():
            self.alert_ops_team(report)
        
        return report
    
    def find_orphan_sandboxes(self) -> List[Sandbox]:
        """查找孤儿沙箱"""
        all_sandboxes = self.sandbox_manager.list_all()
        
        orphans = []
        for sandbox in all_sandboxes:
            # 创建超过 24h 且未关联活跃 Harness
            if sandbox.age > timedelta(hours=24):
                harness = self.find_harness_by_sandbox(sandbox)
                if not harness or harness.status == "REAPED":
                    orphans.append(sandbox)
        
        return orphans
```

---

## 七、CI 集成节奏

### 7.1 分层测试策略

```python
class HarnessCIStrategy:
    """Harness CI 集成策略"""
    
    LEVELS = {
        "L0": {"name": "确定性回归", "timeout": timedelta(minutes=5)},
        "L1": {"name": "属性/单元", "timeout": timedelta(minutes=15)},
        "L2": {"name": "单节点故障", "timeout": timedelta(minutes=30)},
        "L3": {"name": "全链路混沌", "timeout": timedelta(hours=2)},
        "L4": {"name": "封存集", "timeout": timedelta(hours=1)}
    }
    
    def run_level(self, level: str) -> LevelResult:
        """运行指定层级测试"""
        config = self.LEVELS[level]
        
        test_cases = self.get_test_cases_for_level(level)
        
        with timeout(config["timeout"]):
            results = self.execute_tests(test_cases)
        
        return LevelResult(
            level=level,
            total=len(test_cases),
            passed=sum(1 for r in results if r.outcome == "PASS"),
            failed=sum(1 for r in results if r.outcome == "FAIL"),
            duration=self._calculate_duration(results)
        )
```

### 7.2 L0/L1 快速稳定约束

**关键约束：L0/L1 必须快且稳定，否则会被开发者绕过**：

```python
class L0L1Quality:
    """L0/L1 质量门禁"""
    
    MAX_L0_DURATION = timedelta(minutes=5)
    MAX_L1_DURATION = timedelta(minutes=15)
    MIN_STABILITY = 0.99  # 99% 稳定性
    
    def validate_l0(self, result: LevelResult) -> ValidationResult:
        """验证 L0 质量"""
        if result.duration > self.MAX_L0_DURATION:
            return ValidationResult(
                passed=False,
                message=f"L0 耗时 {result.duration} 超过 {self.MAX_L0_DURATION}，"
                        f"开发者会绕过慢速测试"
            )
        
        stability = self._calculate_stability(result)
        if stability < self.MIN_STABILITY:
            return ValidationResult(
                passed=False,
                message=f"L0 稳定性 {stability:.1%} 低于 {self.MIN_STABILITY:.1%}，"
                        f"不稳定测试会被禁用"
            )
        
        return ValidationResult(passed=True)
```

### 7.3 L3 恢复期压力场景

**L3 必须包含恢复期压力场景（积压任务同时重试、补偿同时下发）**：

```python
class L3RecoveryPressureScenarios:
    """L3 恢复期压力场景"""
    
    def scenario_backlog_retry_storm(self) -> HarnessTestCase:
        """场景：积压任务同时重试"""
        return HarnessTestCase(
            name="积压任务重试风暴",
            description="""
            1. 注入长时间下游不可用（10min）
            2. 期间积压 1000+ 任务
            3. 下游恢复后，所有任务同时重试
            4. 验证：
               - 重试不触发新的熔断器
               - 幂等键正确防止重复副作用
               - 补偿工作流不互相干扰
               - 恢复期内完成 95% 积压
            """,
            fault_injection=[
                FaultInjection(type="downstream_unavailable", duration=timedelta(minutes=10)),
                FaultInjection(type="downstream_recovery", trigger="after_10min")
            ],
            assertions=[
                Assertion(type="safety", check="no_duplicate_side_effects"),
                Assertion(type="liveness", check="95%_backlog_cleared_within_30min"),
                Assertion(type="performance", check="no_new_circuit_breaker_trip")
            ]
        )
    
    def scenario_compensation_concurrency(self) -> HarnessTestCase:
        """场景：补偿工作流并发冲突"""
        return HarnessTestCase(
            name="补偿并发冲突",
            description="""
            1. 同时启动 50 个 Saga，每个包含 10 步
            2. 在第 5 步注入随机失败
            3. 触发补偿，所有 Saga 同时回滚
            4. 验证：
               - 补偿操作不产生锁冲突
               - Effect Log 正确记录补偿轨迹
               - ESCALATED 状态在 SLO 内解决
            """,
            fault_injection=[
                FaultInjection(type="random_step_failure", rate=0.2)
            ],
            assertions=[
                Assertion(type="safety", check="no_compensation_deadlock"),
                Assertion(type="liveness", check="all_escalated_resolved_within_4h"),
                Assertion(type="performance", check="lock_contention_rate_<1%")
            ]
        )
```

---

## 八、Harness 与被测系统的接口边界

### 8.1 Harness 对被测系统的每次写都走幂等键

```python
class HarnessWriteProtocol:
    """Harness 写操作协议"""
    
    NAMESPACE_PREFIX = "harness:"
    
    def write_to_system(self, op: WriteOperation) -> WriteResult:
        """Harness 对被测系统的写操作"""
        # 1. 生成幂等键（命名空间前缀 harness:）
        idempotency_key = f"{self.NAMESPACE_PREFIX}{op.harness_id}:{op.operation_id}"
        
        # 2. 写入 Effect Log
        effect = Effect(
            effect_id=uuid4(),
            idempotency_key=idempotency_key,
            operation=op,
            harness_id=op.harness_id,
            timestamp=datetime.now()
        )
        self.effect_log.append(effect)
        
        # 3. 通过被测系统的幂等闸门执行
        result = self.system_client.execute_with_idempotency(
            operation=op,
            idempotency_key=idempotency_key
        )
        
        return result
```

**Harness 必须是它自己所验证的契约的第一个客户**：

```python
def validate_harness_self_compliance(harness: Harness) -> ComplianceReport:
    """验证 Harness 自身合规性"""
    violations = []
    
    # 1. 检查所有写操作是否携带幂等键
    writes_without_key = harness.find_writes_without_idempotency_key()
    if writes_without_key:
        violations.append(
            Violation(
                type="MISSING_IDEMPOTENCY_KEY",
                message="Harness 自身写操作未携带幂等键",
                evidence=writes_without_key
            )
        )
    
    # 2. 检查是否绕开幂等闸门
    bypassed_writes = harness.find_bypassed_idempotency_gate()
    if bypassed_writes:
        violations.append(
            Violation(
                type="BYPASSED_IDEMPOTENCY_GATE",
                message="Harness 绕开幂等闸门注入故障，导致 Q1/Q3 设计无真实负载验证",
                evidence=bypassed_writes
            )
        )
    
    if violations:
        return ComplianceReport(
            compliant=False,
            violations=violations,
            message="Harness 必须是它验证契约的第一个客户"
        )
    
    return ComplianceReport(compliant=True)
```

---

## 九、验收标准

### 9.1 功能验收

| ID | 验收标准 | 验证方法 |
|----|---------|---------|
| HAR-001-F01 | Harness 状态机符合定义，所有状态迁移合法 | 状态机单元测试 |
| HAR-001-F02 | ARMED 前必须完成可回退点打点 | 门禁检查测试 |
| HAR-001-F03 | JUDGING 产出结构化判决，禁止布尔值 | Verdict Schema 验证 |
| HAR-001-F04 | INCONCLUSIVE 率超过 5% 时阻断发布 | CI 集成测试 |
| HAR-001-F05 | REAPED 状态完整回收所有资源 | 资源泄漏检测测试 |
| HAR-001-F06 | Harness 所有写操作携带幂等键 | 自合规性测试 |

### 9.2 隔离契约验收

| ID | 验收标准 | 验证方法 |
|----|---------|---------|
| HAR-001-I01 | Harness 使用独立租户（harness-*） | 租户隔离测试 |
| HAR-001-I02 | 禁止在生产租户注入破坏性故障 | 安全防护测试 |
| HAR-001-I03 | Harness 使用独立凭据和速率桶 | 配额隔离测试 |
| HAR-001-I04 | Harness 观测面只读，不写业务表 | 权限边界测试 |
| HAR-001-I05 | 故障注入在框架层插桩，非业务代码 | 代码审查 |

### 9.3 断言体系验收

| ID | 验收标准 | 验证方法 |
|----|---------|---------|
| HAR-001-A01 | 安全属性违反触发发布阻断 | 门禁测试 |
| HAR-001-A02 | 活性属性带时限断言 | 超时测试 |
| HAR-001-A03 | 性能属性使用 p95/p99，非均值 | 统计算法验证 |

### 9.4 评测治理验收

| ID | 验收标准 | 验证方法 |
|----|---------|---------|
| HAR-001-G01 | 测试按血缘分开报告，禁止混算总分 | 报告格式验证 |
| HAR-001-G02 | Exposure 超过阈值降级为调试集 | Exposure 策略测试 |
| HAR-001-G03 | Holdout 集仅在发布前评分 | 访问控制测试 |
| HAR-001-G04 | Verifier 质量单独报告 | Precision/Recall 计算 |
| HAR-001-G05 | Flakiness 超过阈值隔离 | 一致性检测测试 |

### 9.5 CI 集成验收

| ID | 验收标准 | 验证方法 |
|----|---------|---------|
| HAR-001-C01 | L0 耗时 < 5min，稳定性 > 99% | 性能 + 稳定性测试 |
| HAR-001-C02 | L1 耗时 < 15min，稳定性 > 99% | 性能 + 稳定性测试 |
| HAR-001-C03 | L3 包含恢复期压力场景 | 场景覆盖检查 |

---

## 十、跨模块依赖与接口

### 10.1 依赖的上游模块

| 模块 | 依赖内容 | 接口 |
|------|---------|------|
| REQ-RT-001 | 核心实体定义 | Task、Worker、Action Schema |
| REQ-RT-005 | Checkpoint Protocol | 检查点读写接口 |
| REQ-SEC-003 | Policy Gateway | 故障注入授权检查 |
| REQ-REL-004 | 检查点保留策略 | 生命周期联动 |
| REQ-REL-007 | Compensation Workflow | Effect Log 读取 |

### 10.2 为下游提供的接口

| 接口 | 下游消费者 | 说明 |
|------|----------|------|
| HarnessLifecycleManager | HAR-002~006 | 生命周期管理入口 |
| HarnessVerdict | EVA-003 | 判决结构 |
| FaultInjectionFramework | REL-009 | 故障注入接口 |

---

## 十一、实施计划

### 11.1 MVP 范围

**Phase 1（2 周）**：
- 实现基础状态机（CREATED → ARMED → RUNNING → JUDGING → REAPED）
- 实现可回退点打点机制
- 实现基础资源回收

**Phase 2（2 周）**：
- 实现隔离契约（独立租户、独立凭据）
- 实现框架层故障注入点
- 实现虚拟时钟

**Phase 3（2 周）**：
- 实现三层断言体系
- 实现结构化判决
- 实现 INCONCLUSIVE 治理

**Phase 4（2 周）**：
- 实现评测治理（血缘报告、Holdout）
- 实现孤儿扫描
- CI 集成

### 11.2 后续演进

**v2.0**：
- 分布式 Harness 协调
- 更丰富的故障注入模式
- AI 辅助判定器

---

## 十二、参考资料

| 来源 | 内容 | 访问日期 |
|------|------|---------|
| Netflix Chaos Engineering | 混沌工程原则、隔离契约 | 行业标准 |
| Azure Chaos Studio | 故障注入框架设计 | 行业标准 |
| AWS Fault Injection Simulator | 独立租户、框架层插桩 | 行业标准 |
| Jepsen | 虚拟时钟、活性属性验证 | 行业标准 |
| TLA+ | 安全/活性/性能属性分类 | 形式化验证 |
| Google Testing Blog | 分层测试金字塔 | 行业最佳实践 |
| MLOps | Holdout 策略、Goodhart 定律防护 | 行业最佳实践 |

---

**文档版本**: v0.1-designed  
**创建日期**: 2026-09-26  
**作者**: 架构组  
**状态**: 待跨模块评审与冻结
