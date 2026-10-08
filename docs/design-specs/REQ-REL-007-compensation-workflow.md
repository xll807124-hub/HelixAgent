# REQ-REL-007 Compensation Workflow 详细设计

> 版本：v0.1-designed  
> 优先级：P0  
> 状态：详细设计已完成，待跨模块评审与冻结；未实现、未验证  
> 所属模块：可靠性（REL）  
> 前置依赖：REQ-REL-001、REQ-SEC-009  
> 协同依赖：REQ-RT-007、REQ-REL-005、REQ-REL-006、REQ-SEC-002、REQ-SEC-003、REQ-SEC-005

---

## 1. 目标与范围

当任务进入无法通过重试或检查点恢复的失败状态时，系统能够通过补偿工作流安全地撤销或中和已产生的外部副作用，或采用前向完成策略将系统收敛到一致状态。

**核心设计原则**：
- 补偿不是"正向执行的倒带"，而是独立状态机
- 补偿拥有独立的失败模式、超时语义和审批契约
- 补偿范围由依赖图驱动，而非简单 LIFO
- Pivot 后优先采用前向完成（forward recovery）
- ESCALATED 状态必须有硬 SLO 与强制回收机制

**本需求覆盖**：
- 三分支补偿决策（自动补偿、前向完成、升级人工）
- 依赖图驱动的补偿范围计算
- 决策谓词驱动的人工审批
- per-domain 超时配置与熔断
- ESCALATED 强制收敛机制

**非目标**：
- 不重新定义 Effect Log Schema（归属 REQ-REL-005）
- 不定义具体补偿器实现（归属各工具模块）
- 不定义 Pivot 声明协议（归属 REQ-REL-005）

---

## 2. 设计原则与术语

### 2.1 补偿的独立性

补偿工作流是独立于正向执行的状态机，具有：
- **独立失败模式**：补偿失败不等同于正向失败
- **独立超时语义**：补偿超时通常比正向更严格
- **独立审批契约**：补偿审批可能与正向审批不同
- **独立熔断器**：补偿流量不与正向流量共享配额
- **独立幂等键**：补偿幂等键带 `comp:` 前缀

### 2.2 三分支补偿决策

**分支一：自动补偿（Auto Compensation）**
- 适用于 Pivot 前的所有可补偿副作用
- 适用于 Pivot 后不涉及对外承诺的内部副作用
- 例如：分支创建、凭据签发、工作区分配、资源预留

**分支二：前向完成（Forward Recovery）**
- 适用于 Pivot 后已对外做出承诺的副作用
- 例如：已创建的 PR、已发送的通知、已触发的部署
- 策略：完成剩余必要步骤，使系统达到一致状态

**分支三：升级人工（Escalated）**
- 适用于无法自动补偿且无法前向完成的副作用
- 适用于补偿失败或对账结果为 IN_DOUBT 的情况
- 必须有硬 SLO 与强制回收机制

### 2.3 Pivot 声明与属性测试

**Pivot 声明要求**：
```yaml
action:
  pivot: true                    # 必须由动作自身声明
  external_visibility: true      # 是否对外可见
  pivot_reason: "PR已创建"       # Pivot 原因
  forward_recovery_defined: true # 是否定义了前向完成策略
```

**属性测试规则**：
- 任何将 `pivot: false` 改为 `pivot: true` 的 PR 必须触发 review
- 必须经过变更审批委员会批准
- 必须附带风险评估和前向完成策略
- 必须有回归测试验证 Pivot 边界

---

## 3. 补偿范围计算：依赖图驱动

### 3.1 Effect Log 依赖图

每条 Effect Log 记录必须声明依赖：

```json
{
  "effect_id": "effect_003",
  "effect_type": "BRANCH_PUSH",
  "depends_on": ["effect_001", "effect_002"],  // 依赖于分支创建和凭据签发
  "pivot": false,
  "external_visibility": false,
  "compensatable": true,
  "compensation_defined": true
}
```

### 3.2 补偿范围计算算法

```
输入：失败的 Action ID、Effect Log、失败原因
输出：需要补偿的 Effect 列表

1. 构建 Effect 依赖图 G = (V, E)
   - V: 所有 Effect
   - E: depends_on 关系

2. 识别失败点 F（失败 Action 对应的 Effect）

3. 计算补偿范围 C
   For each effect E in reverse_topological_order(G):
     If E.timestamp > F.timestamp:
       Skip  // 未执行的副作用无需补偿
     
     If E.pivot == true AND E.external_visibility == true:
       If E has forward_recovery_strategy:
         Mark as FORWARD_RECOVERY
       Else:
         Mark as ESCALATED
       Continue  // Pivot 后对外可见效果不自动补偿
     
     If E.compensatable == false:
       Mark as NON_COMPENSATABLE
       Log warning
       Continue
     
     If E.compensation_defined == false:
       Mark as ESCALATED
       Log risk
       Continue
     
     If E has dependent AND dependent.status == IN_DOUBT:
       Mark as BLOCKED_ON_DEPENDENT
       Wait for reconciliation  // 绝不跳过
       Continue
     
     Add E to compensation_queue

4. 对 compensation_queue 进行拓扑排序（逆序）
   - 独立的 Effect 可并行补偿
   - 有依赖的 Effect 必须串行补偿

5. 返回补偿序列
```

### 3.3 依赖图阻塞语义

**铁律**：如果某个 Effect 的状态为 IN_DOUBT，其下游 Effect 的补偿必须阻塞等待对账结果，绝不能跳过。

**原因**：跳过 = 配额泄漏、孤儿资源

**处理流程**：
```
If effect.status == IN_DOUBT:
  Trigger reconciliation (REQ-REL-003 三值对账)
  Wait for reconciliation_result (timeout: 5min)
  
  If reconciliation_result == CONFIRMED_SUCCESS:
    Proceed with compensation
  Else If reconciliation_result == CONFIRMED_FAILURE:
    Skip compensation (副作用未发生)
  Else:  // STILL_IN_DOUBT
    Mark as ESCALATED
    Freeze related resources
    Notify on-call
```

---

## 4. 人工审批：决策谓词驱动

### 4.1 审批决策谓词

用决策谓词代替静态查表：

```python
def requires_human_approval(effect, context) -> bool:
    """
    决策谓词：判断是否需要人工审批
    
    Args:
        effect: Effect Log 条目
        context: 运行时上下文（包括当前状态、风险评分等）
    
    Returns:
        True 需要审批，False 自动执行
    """
    # 规则 1：Pivot 后的对外可见效果必须审批
    if effect.pivot and effect.external_visibility:
        return True
    
    # 规则 2：已提交 PR 的分支删除需要审批
    if effect.effect_type == "BRANCH_CREATED":
        if context.has_open_pr(effect.branch_name):
            return True
    
    # 规则 3：风险评分 ≥ 7 的补偿需要审批
    if context.risk_score(effect) >= 7:
        return True
    
    # 规则 4：涉及生产环境的补偿需要审批
    if context.environment == "production":
        return True
    
    # 规则 5：高价值资源（>$100）的释放需要审批
    if effect.effect_type == "RESOURCE_RESERVED":
        if context.resource_value(effect.resource_id) > 100:
            return True
    
    # 规则 6：批量补偿（>10个）需要审批
    if context.compensation_batch_size > 10:
        return True
    
    # 默认：低风险补偿自动执行
    return False
```

### 4.2 审批原则

**原则 1：审批对称性**
- 人批准过的动作，撤销也必须经过同一个人（或其委托）
- 实现：审批记录关联 `approved_by`，补偿审批路由到同一人

**原则 2：审批聚合**
- 同一 saga、同一根因、同一爆炸半径 → 合成一张审批单
- 避免工程师"一键全过"导致审批失效

审批单结构：
```json
{
  "approval_id": "approval_xxx",
  "compensation_id": "comp_xxx",
  "saga_id": "saga_xxx",
  "root_cause": "PIVOT_BEYOND_RECOVERY",
  "blast_radius": {
    "affected_branches": ["feature/login-fix"],
    "affected_workspaces": ["ws_abc123"],
    "affected_credentials": ["cred_xxx"],
    "estimated_cost": "$0.50"
  },
  "effects_to_compensate": [
    {
      "effect_id": "effect_001",
      "effect_type": "BRANCH_CREATED",
      "action": "删除分支 feature/login-fix",
      "risk_level": "LOW"
    },
    {
      "effect_id": "effect_002",
      "effect_type": "CREDENTIAL_ISSUED",
      "action": "撤销 GitHub App 凭据",
      "risk_level": "LOW"
    }
  ],
  "checkpoint_available": true,
  "checkpoint_id": "ckpt_xxx"
}
```

### 4.3 紧急通道（Break-Glass）

**场景**：凌晨遇到 Pivot 后悬置态，等待审批会造成业务损失

**机制**：
```yaml
break_glass:
  enabled: true
  conditions:
    - on_call_triggered: true
    - time_of_day: "00:00-06:00"
    - estimated_loss: "> $1000/hour"
  
  execution:
    - 允许先执行补偿，后补审批
    - 全程审计，自动建单
    - 24h 内必须补审
    - 逾期自动升级到 CISO
  
  monitoring:
    - 每月抽检 100% break-glass 使用记录
    - 滥用次数 > 3 次/月 → 触发调查
```

### 4.4 审批超时语义

**审批超时 ≠ 拒绝**

审批超时的正确处理：
```
If approval_timeout:
  Mark compensation as ESCALATED
  Freeze related resources (防止泄漏)
  Notify approval owner + manager
  Escalate to next level after 2h
  
  # 不能简单关单，因为副作用仍然存在
```

---

## 5. 超时配置：per-domain + 依赖图阻塞

### 5.1 超时配置模型

**per-domain 超时配置**：

```yaml
compensation_timeouts:
  # 默认配置
  default:
    max_duration: 30s
    retry_count: 2
    
  # 按 domain 覆盖
  domains:
    local_filesystem:
      max_duration: 5s
      retry_count: 1
      reason: "本地操作应该快速完成"
    
    git_operations:
      max_duration: 20s
      retry_count: 2
      reason: "Git 操作可能涉及网络"
    
    external_api:
      max_duration: 15s
      retry_count: 1
      reason: "外部 API 已退化，快速转对账"
    
    credential_revocation:
      max_duration: 10s
      retry_count: 2
      reason: "凭据撤销应快速完成"
    
    resource_cleanup:
      max_duration: 25s
      retry_count: 2
      reason: "资源清理可能涉及多个调用"
```

### 5.2 补偿超时原则

**补偿应比正向更"快进 IN_DOUBT"**：

```
# 正向动作配置
action_timeout: 60s
action_retry_count: 3

# 对应的补偿动作配置
compensation_timeout: 42s  # = 60s × 0.7
compensation_retry_count: 1  # = 3 / 2 向下取整
```

**理由**：
- 补偿通常在下游已退化时执行
- 在半死的下游上反复长超时重试 = 自我 DoS
- 快速转入对账与人工处理更安全

### 5.3 依赖图阻塞超时

**场景**：Effect B 依赖 Effect A，A 的补偿超时

**处理**：
```
If A.compensation_timeout:
  Trigger reconciliation for A
  
  If reconciliation_result == CONFIRMED_SUCCESS:
    Proceed with A's compensation
    Proceed with B's compensation
  
  Else If reconciliation_result == CONFIRMED_FAILURE:
    Skip A's compensation
    Skip B's compensation (因为 A 未发生)
  
  Else:  // STILL_IN_DOUBT
    Mark A as ESCALATED
    Block B's compensation
    Wait for manual intervention
```

### 5.4 总时限预算

**补偿工作流总时限**：
```yaml
compensation_workflow_budget:
  max_duration: 5min  # 整个补偿工作流的硬上限
  soft_limit: 3min    # 软限制，超过后告警
  
  escalation:
    at_soft_limit: "NOTIFY_ONCALL"
    at_hard_limit: "FORCE_ESCALATE"
```

### 5.5 组织级覆盖约束

**允许租户自定义超时，但有约束**：

```python
def validate_org_timeout_override(org_config, platform_config):
    """
    验证组织级超时覆盖
    
    规则：
    1. 只能在自有连接器域内覆盖
    2. 只能收紧不能放宽（放宽会拖慢全局）
    3. 必须写入不可篡改日志
    4. 必须纳入变更管理
    """
    for domain, timeout in org_config.items():
        # 规则 1：检查域所有权
        if not org.owns_connector(domain):
            raise PermissionError(f"组织无权覆盖 {domain} 的超时配置")
        
        # 规则 2：只能收紧
        platform_timeout = platform_config.get(domain, {}).get("max_duration")
        if timeout > platform_timeout:
            raise ValueError(f"{domain} 超时只能收紧（<= {platform_timeout}）")
        
        # 规则 3：写入审计日志
        audit_log.write({
            "org_id": org.id,
            "domain": domain,
            "old_timeout": platform_timeout,
            "new_timeout": timeout,
            "approved_by": request.user,
            "timestamp": now()
        })
        
        # 规则 4：变更管理
        change_management.create_ticket({
            "type": "TIMEOUT_OVERRIDE",
            "org_id": org.id,
            "domain": domain,
            "config": timeout
        })
```

### 5.6 超时与保留期反向依赖

**第三次强调此依赖，因为它真的会咬人**：

```
对账探测需要的证据（执行日志、快照、Effect Log）的保留期必须满足：

expires_at >= compensation_max_duration + reconciliation_max_duration + postmortem_window

否则：
补偿超时 → 想对账 → 证据已被清理 → 只能升级人工（这会成为常态）
```

**推荐配置**：
```yaml
evidence_retention:
  compensation_max_duration: 5min
  reconciliation_max_duration: 10min
  postmortem_window: 7days
  
  # 计算结果
  min_retention: 7days + 15min  # 实际应配置为 14days 作为缓冲
```

---

## 6. ESCALATED 状态的硬 SLO 与强制回收

### 6.1 ESCALATED 硬 SLO

**问题**：没有硬 SLO 的 ESCALATED 状态会成为永久债务

**解决方案**：按副作用类型设置不同的 SLO

```yaml
escalated_slo:
  # 涉及计费/凭据的悬置态
  billing_or_credential:
    max_duration: 30min
    escalation_level: P0
    force_converge_after: 30min
  
  # Pivot 后的悬置态
  pivot_suspended:
    max_duration: 4h
    escalation_level: P1
    force_converge_after: 4h
  
  # 一般资源泄漏
  resource_leak:
    max_duration: 24h
    escalation_level: P2
    force_converge_after: 24h
```

### 6.2 强制收敛例程（Force-Converge）

**触发条件**：ESCALATED 状态超过硬 SLO

**执行策略**：以权威真相源为准做差异修补

```python
def force_converge(escalated_compensation):
    """
    强制收敛例程
    
    策略：查询权威真相源，根据实际状态决定补偿动作
    """
    effects = escalated_compensation.pending_effects
    
    for effect in effects:
        # 查询权威真相源
        actual_state = query_authoritative_source(effect)
        
        if actual_state == "EXISTS":
            # 副作用确实存在，执行补偿
            result = execute_compensation(effect, force=True)
            if result.success:
                log_success(effect, "force_converge")
            else:
                # 强制补偿仍失败，标记为永久债务
                mark_as_permanent_debt(effect)
                create_manual_cleanup_ticket(effect)
        
        elif actual_state == "NOT_EXISTS":
            # 副作用不存在，标记为已补偿
            mark_as_compensated(effect, reason="not_exists")
        
        else:  # UNKNOWN
            # 仍无法确定，标记为永久债务
            mark_as_permanent_debt(effect)
            create_escalation_ticket(effect, level="P0")
```

### 6.3 永久债务管理

**定义**：无法通过自动化或人工干预在合理时间内解决的补偿失败

**处理流程**：
```
1. 创建永久债务工单
   - 记录完整上下文
   - 附带失败证据
   - 指定责任团队

2. 纳入技术债务跟踪
   - 定期复盘
   - 优先级排序
   - 制定修复计划

3. 防止扩散
   - 冻结相关资源（如果可能）
   - 告警关联任务
   - 阻止类似操作

4. 定期清理
   - 每季度评审
   - 强制关闭超过 90 天的债务
   - 记录未解决原因
```

---

## 7. 补偿的独立熔断器与限流

### 7.1 独立熔断器

**原则**：补偿流量不能和正常流量抢同一个配额

```yaml
circuit_breaker:
  normal_traffic:
    failure_threshold: 50%
    timeout: 60s
    half_open_after: 30s
  
  compensation_traffic:
    failure_threshold: 30%  # 更严格
    timeout: 42s            # 0.7× 正常超时
    half_open_after: 60s    # 更长的恢复时间
    isolated: true          # 与正常流量隔离
```

### 7.2 独立限流桶

**实现**：
```python
class CompensationRateLimiter:
    def __init__(self):
        self.normal_bucket = TokenBucket(rate=100, capacity=200)
        self.compensation_bucket = TokenBucket(rate=50, capacity=100)
    
    def allow_compensation(self, effect):
        """
        补偿流量使用独立的限流桶
        """
        if not self.compensation_bucket.consume(1):
            # 补偿流量超限，延迟执行
            return False, "compensation_rate_limited"
        
        return True, None
```

---

## 8. 补偿幂等键：独立命名空间

### 8.1 幂等键生成规则

**补偿幂等键必须带 `comp:` 前缀与单调逆序编号**：

```python
def generate_compensation_idempotency_key(effect, attempt_number):
    """
    生成补偿幂等键
    
    格式: comp:{effect_id}:{reverse_seq}:{attempt}
    
    Args:
        effect: Effect Log 条目
        attempt_number: 补偿尝试次数（从 1 开始）
    
    Returns:
        补偿幂等键
    """
    # 计算逆序编号（基于 effect 在依赖图中的位置）
    reverse_seq = calculate_reverse_topological_index(effect)
    
    return f"comp:{effect.effect_id}:{reverse_seq}:{attempt_number}"
```

**示例**：
```
正向动作幂等键: action:branch_create:001
补偿动作幂等键: comp:effect_003:005:001
                ^    ^          ^   ^
                |    |          |   补偿尝试次数
                |    |          逆序编号
                |    Effect ID
                补偿前缀
```

### 8.2 补偿权限校验

**补偿必须重新经过 Policy Gateway 与权限校验**：

```python
def validate_compensation_permission(effect, executor):
    """
    校验补偿执行权限
    
    额外检查：
    1. 执行补偿的人/主体是否仍有权限做这件事
    2. 资源是否仍在授权范围内
    3. 补偿动作是否在允许的操作列表中
    """
    # 标准权限检查
    if not policy_gateway.check_permission(executor, effect.resource, "compensate"):
        return False, "permission_denied"
    
    # 额外检查：是否仍有权限访问原始资源
    if not policy_gateway.check_permission(executor, effect.resource, effect.original_action):
        return False, "original_permission_revoked"
    
    # 检查补偿是否在允许的时间窗口内
    if now() - effect.created_at > MAX_COMPENSATION_WINDOW:
        return False, "compensation_window_expired"
    
    return True, None
```

---

## 9. 可观测性：补偿成功率分解

### 9.1 一级指标：补偿成功率

**问题**：单一的"补偿成功率"指标会掩盖问题

**解决方案**：拆成"可补偿率"和"补偿执行成功率"

```yaml
metrics:
  # 指标 1：可补偿率
  compensatable_rate:
    definition: "需要补偿的副作用中，定义了补偿器的比例"
    formula: "effects_with_compensator / effects_requiring_compensation"
    target: "> 95%"
    
  # 指标 2：补偿执行成功率
  compensation_execution_success_rate:
    definition: "执行补偿动作的成功率"
    formula: "successful_compensations / attempted_compensations"
    target: "> 90%"
    
  # 指标 3：补偿完整成功率
  compensation_complete_success_rate:
    definition: "补偿工作流完全成功的比例"
    formula: "fully_compensated_workflows / triggered_workflows"
    target: "> 85%"
    
  # 指标 4：ESCALATED 解决时长
  escalated_resolution_time:
    definition: "ESCALATED 状态到解决的时长"
    percentiles: [p50, p90, p99]
    target_p90: "< 4h"
    target_p99: "< 24h"
```

### 9.2 追踪属性

```json
{
  "compensation_id": "comp_xxx",
  "task_id": "task_xxx",
  "trigger_reason": "PIVOT_BEYOND_RECOVERY",
  "compensation_branch": "AUTO | FORWARD_RECOVERY | ESCALATED",
  "effects_total": 10,
  "effects_compensatable": 8,
  "effects_compensated_success": 7,
  "effects_compensated_failure": 1,
  "effects_skipped": 2,
  "started_at": "2026-09-25T10:00:00Z",
  "completed_at": "2026-09-25T10:02:30Z",
  "duration_ms": 150000,
  "approval_required": true,
  "approval_duration_ms": 45000,
  "break_glass_used": false
}
```

---

## 10. 验收标准

| 验收标准 | 验证方法 | 通过条件 |
|---------|---------|---------|
| V1: Pivot 后内部副作用可自动补偿 | 标记 pivot=true, external_visibility=false 的 Effect | 被自动补偿 |
| V2: Pivot 后对外副作用进入前向完成 | 标记 pivot=true, external_visibility=true 的 Effect | 触发 forward_recovery |
| V3: 依赖图驱动补偿范围 | Effect B 依赖 Effect A，A 失败 | B 的补偿阻塞等待 A 对账 |
| V4: 审批决策谓词生效 | 已提交 PR 的分支删除 | 需要人工审批 |
| V5: 审批聚合生效 | 同一 saga 的 8 个补偿动作 | 合成一张审批单 |
| V6: Break-glass 机制生效 | 凌晨触发补偿 | 先执行后审批，24h 内补审 |
| V7: per-domain 超时生效 | 本地文件操作超时 | 5s 超时（而非默认 30s） |
| V8: 补偿超时转对账 | 补偿动作超时 | 触发三值对账 |
| V9: ESCALATED 硬 SLO 生效 | 凭据悬置态超过 30min | 触发强制收敛 |
| V10: 补偿幂等键独立 | 重复执行同一补偿 | 使用 `comp:` 前缀的幂等键 |
| V11: 补偿独立熔断 | 补偿失败率 30% | 触发补偿熔断（不影响正常流量） |
| V12: 可补偿率指标 | 查询补偿指标 | 显示可补偿率和执行成功率 |

---

## 11. 依赖、影响与演进

**上游依赖**：
- `REQ-REL-005`：提供 Effect Log、Pivot 声明、污染半径
- `REQ-REL-001`：提供失败分类和根因分析
- `REQ-RT-007`：提供补偿幂等键机制
- `REQ-SEC-003`：提供 Policy Gateway 授权
- `REQ-SEC-005`：提供凭据撤销能力
- `REQ-SEC-009`：提供 Kill Switch 机制

**下游影响**：
- `REQ-REL-008`：需要区分可补偿的工具失败
- `REQ-REL-009`：需要测试补偿工作流的故障注入
- `REQ-HAR-001`：补偿是 Harness 生命周期的一部分
- `REQ-OBS-*`：需要增加补偿相关的可观测指标

**演进方向**：
- MVP：分支、凭据、工作区、资源四类副作用的补偿
- V1：PR 创建、通知发送的前向完成策略
- V2：跨租户补偿协调
- V3：补偿策略学习与优化

---

## 12. 修改前后对比

| 维度 | 原初始方案 | 修改后方案 | 改进点 | 对标依据 |
|------|-----------|-----------|--------|---------|
| **Pivot 后处理** | 二分法（自动补偿/升级） | 三分支（自动补偿/前向完成/升级） | 避免资源泄漏 | Azure SRE, Google SRE |
| **补偿范围** | 简单 LIFO | 依赖图驱动 + 阻塞语义 | 精确补偿，防止孤儿资源 | Temporal, LangGraph |
| **审批机制** | 静态查表 | 决策谓词 + 审批聚合 + break-glass | 工程化审批，避免审批失效 | AWS IAM, PagerDuty |
| **超时配置** | 单一默认 30s | per-domain + 0.7× 正向超时 | 快速转对账，避免自我 DoS | Temporal RetryPolicy |
| **ESCALATED** | 无 SLO | 硬 SLO + 强制收敛 | 防止永久债务 | SRE Incident Response |
| **幂等键** | 与正向共享 | 独立命名空间 `comp:` | 避免冲突 | CrewAI idempotent |
| **熔断器** | 共享 | 独立补偿熔断器 | 隔离故障影响 | Resilience4j |
| **可观测性** | 单一成功率 | 可补偿率 + 执行成功率 | 精确定位问题 | SRE Golden Signals |

---

## 13. 公开事实与设计推断

**公开事实**：
- Temporal Saga Pattern 支持依赖图驱动的补偿序列
- LangGraph 的补偿节点检查 `state["completed"]` 决定补偿范围
- Azure SRE Agent 提出"forward recovery 优先于 rollback"
- AWS IAM 的 break-glass 机制允许先执行后审计
- Google SRE 强调"故障恢复期应降低负载而非增加"
- CrewAI 发现 Checkpoint 恢复导致工具重复执行
- ACRFence 研究指出 12 个主流框架均存在副作用重复执行问题

**设计推断**：
- Pivot 三分支策略结合了 Temporal 的 Saga Pattern 和 Azure 的 forward recovery
- per-domain 超时配置是对 Temporal RetryPolicy 的扩展应用
- 决策谓词驱动的审批机制借鉴了 AWS IAM 的 policy evaluation
- ESCALATED 硬 SLO 借鉴了 SRE incident response 的 SLO 管理
- 补偿独立熔断器是对 REQ-REL-003 恢复期保护的同源应用

---

## 14. 参考资料

以下为公开来源，访问日期均为 2026-09-25：

- Temporal Saga Pattern：[https://docs.temporal.io/guides/saga-pattern](https://docs.temporal.io/guides/saga-pattern)
- LangGraph Fault Tolerance：[https://docs.langchain.com/oss/python/langgraph/fault-tolerance](https://docs.langchain.com/oss/python/langgraph/fault-tolerance)
- Devin Dynamic Workflows：[https://docs.devin.ai/work-with-devin/dynamic-workflows](https://docs.devin.ai/work-with-devin/dynamic-workflows)
- DeepSeek Agent Lifecycle：[https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/agent-lifecycle.md](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/agent-lifecycle.md)
- CrewAI Issue #5802：[https://github.com/crewAIInc/crewAI/issues/5802](https://github.com/crewAIInc/crewAI/issues/5802)
- ACRFence Paper：[https://arxiv.org/pdf/2603.20625](https://arxiv.org/pdf/2603.20625)
- AI Agent Compensation：[https://digitalthoughtdisruption.com/2026/09/19/ai-agent-compensation-why-rollback-is-not-undo/](https://digitalthoughtdisruption.com/2026/09/19/ai-agent-compensation-why-rollback-is-not-undo/)
- AWS IAM Break-Glass：[AWS Security Best Practices](https://aws.amazon.com/security/security-best-practices/)
- Google SRE Incident Response：[Site Reliability Engineering Book](https://sre.google/books/)

---

## 15. 决策记录与待冻结事项

**已确认决策**：
- 采用三分支补偿决策（自动补偿/前向完成/升级）
- 采用依赖图驱动的补偿范围计算
- 采用决策谓词驱动的人工审批
- 采用 per-domain 超时配置 + 0.7× 正向超时
- 采用 ESCALATED 硬 SLO + 强制收敛机制
- 采用独立补偿幂等键（`comp:` 前缀）
- 采用独立补偿熔断器与限流桶
- 采用分解的可观测指标（可补偿率 + 执行成功率）

**待跨模块评审冻结**：
- Pivot 声明协议的具体字段与 REQ-REL-005 的对齐
- Effect Log `depends_on` 字段与 REQ-RT-005 的兼容性
- 补偿幂等键生成规则与 REQ-RT-007 的整合
- 决策谓词的风险评分算法与 REQ-SEC-001 的对齐
- per-domain 超时配置的默认值（需要基准测试）
- ESCALATED SLO 的具体数值（需要运营数据）
- 强制收敛例程的权威真相源定义
- 补偿可观测指标的告警阈值

---

**文档创建时间**：2026-09-25  
**最后更新时间**：2026-09-25  
**维护团队**：架构组
