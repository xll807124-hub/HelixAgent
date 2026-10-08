# REQ-OBS-005 告警和 Kill Switch 联动详细设计

> 所属基线：`Observability Baseline v0.1`  
> 需求编号：`REQ-OBS-005`  
> 优先级：P0  
> 设计版本：`v0.1-designed`  
> 设计状态：详细设计已完成，待跨模块冻结  
> 前置依赖：`REQ-SEC-009`（Kill Switch 状态机）、`REQ-OBS-003`（指标字典）  
> 关键决策：三维判定矩阵（严重度×置信度×爆破半径）；分层通知渠道；自动化联动三条铁律；告警有效性评估体系

---

## 1. 需求定义

### 1.1 目标

为 AI Agent 平台建立告警检测到 Kill Switch 控制的完整闭环，实现从异常监控到自动化止血的端到端能力。支持分层的触发阈值、自动化联动策略、多样化的通知渠道和升级机制，确保告警系统的可观测性和可评估性。

### 1.2 用户价值

- **SRE/运维**：快速响应系统异常，减少 MTTD（Mean Time To Detect）和 MTTR（Mean Time To Recover）
- **安全团队**：自动化止血能力，限制威胁扩散，遏制时间（MTTC）≤ 30s
- **平台运营**：成本和性能的可预测控制，避免意外超支
- **AI 研究员**：质量异常的早期预警，支持模型效果监控

### 1.3 范围

**包含**：
- 告警规则引擎（支持 PromQL 风格条件表达式）
- 与 SEC-009 Kill Switch 的深度集成（M0-M5 模式联动）
- 三维判定矩阵（严重度×置信度×爆破半径）
- 分层通知渠道（PagerDuty/Slack/Email/Webhook）
- 告警生命周期管理（触发、确认、解决、升级）
- 告警有效性评估（精确率、召回率、噪声比）
- 静默和抑制规则

**不包含**：
- 具体的指标定义（由 `REQ-OBS-003` 定义）
- Kill Switch State Machine 实现（由 `REQ-SEC-009` 定义）
- 审计查询 API（由 `REQ-OBS-006` 定义）
- 审计留存机制（由 `REQ-OBS-007` 定义）

---

## 2. 共享契约与术语

本设计复用 `REQ-OBS-003` 定义的指标字典、`REQ-SEC-009` 定义的 Kill Switch 状态机（M0-M5 模式枚举）、`REQ-RT-001` 定义的核心实体（组织、项目、任务标识）。

### 2.1 核心术语

| 术语 | 定义 |
|------|------|
| **Alert Rule** | 告警规则，定义触发条件、严重度、通知策略 |
| **Alert Event** | 告警事件，规则条件满足时生成的告警实例 |
| **三维判定矩阵** | 基于严重度×置信度×爆破半径的联动决策矩阵 |
| **Kill Switch Linkage** | 告警触发 Kill Switch 的自动化联动机制 |
| **Burn Rate** | 错误预算消耗速率，用于 SLO 告警 |
| **Blast Radius** | 爆破半径，告警影响的租户/任务范围 |
| **Notification Channel** | 通知渠道，告警消息的发送目标 |
| **Escalation** | 升级机制，告警无人响应时的自动升级 |
| **Suppression** | 抑制机制，在特定条件下阻止告警触发 |

---

## 3. 行业调研与可借鉴原则

### 3.1 OneUptime - AI Agent Circuit Breakers

**来源**：[OneUptime AI Agent Circuit Breakers](https://oneuptime.com/docs/en/telemetry/ai-agent-circuit-breaker)  
**访问日期**：2026-10-05

**关键发现**：
- 触发信号：LLM 成本预算监控（基于 `gen_ai.*` 指标）或循环检测（Span 计数异常）
- 工作流触发：告警创建 → 触发 Workflow → 调用 Kill 端点
- 端点设计：提供 `agent_kill_endpoint`，支持多种 blast-radius 选择
- 检测延迟：监控间隔 1 分钟，检测滞后 1-3 分钟

**借鉴点**：per-agent 预算监控粒度；Kill 端点的 blast-radius 分级；通知标题包含 runner 名称便于路由。

**证据等级**：A（官方文档）

---

### 3.2 AgentGazer - Kill Switch 与 Alert 集成

**来源**：[AgentGazer Kill Switch](https://agentgazer.com/en/guide/kill-switch.html)、[AgentGazer Alerts](https://agentgazer.com/en/guide/alerts.html)  
**访问日期**：2026-10-05

**关键发现**：
- Kill Switch 触发：SimHash 算法检测重复模式，综合评分超过阈值自动停用
- Alert 类型：agent_down、error_rate、budget、kill_switch（自动生成）
- 通知渠道：Webhook、Email、Telegram
- 评分权重：相同工具调用 ×1.5，其他重复 ×2

**借鉴点**：Alert 与 Kill Switch 的自动联动；多通知渠道统一配置；Dashboard Badge 实时展示停用状态。

**证据等级**：A（官方文档）

---

### 3.3 Agent Sentinel - 置信度门控设计

**来源**：[Agent Sentinel](https://docs.agentsentinel.dev/)  
**访问日期**：2026-10-05

**关键发现**：
- 置信度门控：BurnRateMonitor 检测失败率异常，自动降级为 propose_only 模式
- 自动操作菜单：reroute、pause、rollback（可逆操作优先）
- AutoActThreshold：置信度 ≥ 0.8 时自动执行；其余升级人工

**借鉴点**：置信度门控理念（止血 vs 治病分离）；渐进式降级策略；自动操作与人工审批的分级机制。

**证据等级**：A（官方文档）

---

### 3.4 Guardplane - 控制平面设计

**来源**：[Guardplane GitHub](https://github.com/mkadri85/guardplane/)  
**访问日期**：2026-10-05

**关键发现**：
- 信号平面：每决策一条可重放事件
- 推理层：检测器判断是否真正故障（循环、成本失控、错误率飙升、质量漂移）
- 动作层：可逆修复操作菜单（reroute、rollback、pause）
- Burn Rate 监控：当前失败率与历史基线对比，2× 阈值触发降级

**借鉴点**：框架无关的最小化设计；检测器可插拔架构；轻量止血 + 人工兜底的分级策略。

**证据等级**：A（开源代码和文档）

---

### 3.5 Grafana - SLO 与 Burn Rate Alert

**来源**：[Grafana SLO Best Practices](https://grafana.com/docs/grafana-cloud/observe-and-act/alert-and-measure-reliability/slo/best-practices/)  
**访问日期**：2026-10-05

**关键发现**：
- SLI 定义：成功率比率（如 successful_requests / total_requests）
- SLO 窗口：7-28 天滚动窗口
- 双层告警：Fast-burn（快速消耗错误预算）和 Slow-burn（缓慢消耗错误预算）
- Burn Rate 计算：(当前窗口错误率 / SLO 目标错误率) × 时间因子

**借鉴点**：SLO 驱动的告警设计；Fast/Slow burn 分层减少告警疲劳；Alert labels 支持路由到不同团队。

**证据等级**：A（官方文档）

---

### 3.6 PagerDuty - 自动化响应集成

**来源**：[PagerDuty Automation Actions](https://docs.pagerduty.com/ai-automation/automation/automation-actions)  
**访问日期**：2026-10-05

**关键发现**：
- Automation Actions：触发 Runbook Automation 或脚本执行
- Webhook 订阅：V3 webhook 支持事件过滤和路由
- 事件编排：Enrich 诊断信息或执行修复操作
- 上下文变量：将告警数据作为 PD-CEF 标准化格式传递

**借鉴点**：告警到自动化的标准化集成模式；Event Orchestration 实现条件化响应；幂等性设计确保安全执行。

**证据等级**：A（官方文档）

---

## 4. 告警规则引擎设计

### 4.1 告警规则 DSL

**规则配置格式**（YAML）：

```yaml
# 告警规则示例
alert: high_error_rate
  severity: HIGH
  metrics:
    - gen_ai.task.failed.total
    - gen_ai.task.completed.total
  condition: |
    error_rate = sum(rate(gen_ai.task.failed.total[5m])) / 
                 sum(rate(gen_ai.task.completed.total[5m])) > 0.1
  for: 5m
  labels:
    team: sre
    severity: p2
  annotations:
    summary: "Task error rate exceeds 10%"
    runbook: "https://wiki.example.com/runbooks/high-error-rate"
  kill_switch_linkage:
    enabled: true
    trigger_condition:
      severity: HIGH
      confidence: MEDIUM
      blast_radius: LIMITED
    linkage_action: M1  # 触发 SEC-009 M1 模式（只读）
    auto_release: true
    release_window: 15m
    observation_period: 24h
```

### 4.2 告警规则类型

| 规则类型 | 触发条件 | 适用场景 | 示例 |
|---------|---------|---------|------|
| **阈值告警** | 指标值超过静态阈值 | 成本、延迟、错误率监控 | `gen_ai.cost.usage.total > 100` |
| **Burn Rate 告警** | 错误预算消耗速率异常 | SLO 监控 | `burn_rate_1h > 14.4` |
| **异常检测告警** | 指标值偏离历史基线 | 质量漂移、流量异常 | `deviation(error_rate, 7d) > 2σ` |
| **复合告警** | 多个条件同时满足 | 复杂故障场景 | `error_rate > 0.1 AND latency > 5s` |

### 4.3 告警严重度定义

| 严重度 | 定义 | 响应时效 | 通知渠道 | 示例 |
|--------|------|---------|---------|------|
| **CRITICAL** | 平台级故障，影响所有租户 | < 5 分钟 | PagerDuty | 全局 Kill Switch 触发 |
| **HIGH** | 组织级异常，影响单个组织 | < 15 分钟 | PagerDuty + Slack | 成本失控、安全事件 |
| **MEDIUM** | 项目级异常，影响单个项目 | < 30 分钟 | Slack | 错误率超标、延迟增加 |
| **LOW** | 信息性告警，需关注但非紧急 | 24 小时内 | Email | 使用趋势、容量预警 |

### 4.4 告警规则评估流程

```
1. 指标采集与预处理
   ├─ 从 OTel Collector 接收指标数据流
   ├─ 按组织、项目、Agent 维度聚合
   ├─ 计算衍生指标（如 Burn Rate、错误率、成本速率）
   └─ 检测指标异常（超出基线或阈值）

2. 告警规则匹配
   ├─ 按告警规则优先级排序（CRITICAL > HIGH > MEDIUM > LOW）
   ├─ 评估告警条件表达式（支持 PromQL 风格语法）
   ├─ 检查静默规则（时间窗口、节假日、Maintenance Window）
   └─ 评估 for 持续时间（避免抖动）

3. 告警事件生成
   ├─ 生成 AlertEvent（包含上下文、指标快照、关联 Trace）
   ├─ 记录到告警历史
   └─ 更新告警状态机（INACTIVE → PENDING → FIRING）

4. 三维判定与联动决策
   ├─ 评估严重度（基于告警类型和指标偏离度）
   ├─ 评估置信度（基于历史准确率和信号一致性）
   ├─ 评估爆破半径（预计影响的租户/任务数）
   └─ 根据判定矩阵决定联动动作

5. 执行通知与联动
   ├─ 根据告警级别和通知策略路由到对应渠道
   ├─ 若满足联动条件，发送 Kill Switch 联动请求
   ├─ 记录通知发送状态（成功/失败/重试中）
   └─ 启动升级计时器（无人响应时自动升级）

6. 告警生命周期管理
   ├─ 等待告警条件消失（自动解决）或人工确认
   ├─ 记录告警解决时间（MTTR）
   ├─ 生成告警复盘报告（触发原因、响应过程、根因）
   └─ 更新告警规则有效性评分
```

---

## 5. 三维判定矩阵与 Kill Switch 联动

### 5.1 三维判定矩阵

**维度定义**：

| 维度 | 含义 | 取值范围 |
|------|------|---------|
| **严重度（Severity）** | 事件对业务的影响程度 | LOW / MEDIUM / HIGH / CRITICAL |
| **置信度（Confidence）** | 检测系统的判断确定性 | LOW / MEDIUM / HIGH |
| **爆破半径（Blast Radius）** | 预计影响的范围 | MINIMAL / LIMITED / SIGNIFICANT / MASSIVE |

**判定矩阵到 Kill Switch 模式的映射**：

| 严重度 \ 置信度 \ 爆破半径 | LOW 置信度 | MEDIUM 置信度 | HIGH 置信度 |
|--------------------------|-----------|--------------|------------|
| **LOW / MINIMAL** | 无联动 | 记录告警 | 记录告警 |
| **LOW / LIMITED** | 记录告警 | 记录告警 | M1（观察） |
| **MEDIUM / MINIMAL** | 记录告警 | 记录告警 | M1（5min 解除） |
| **MEDIUM / LIMITED** | 记录告警 | M1（5min 解除） | M1（15min 解除） |
| **HIGH / SIGNIFICANT** | M1（15min 解除） | M2（需审批） | ⚠️ M3（人工） |
| **CRITICAL / MASSIVE** | ⚠️ M3（人工） | ⚠️ M4（人工双人） | ⚠️ M4（人工双人） |

### 5.2 自动化联动三条铁律

**铁律 1：爆破半径上限**
- 自动触发必须有爆破半径上限：单次最多影响 ≤5% 租户 或 ≤1 个连接器
- 超限即降级为"高优告警 + 人工决策"
- 这是防止误触雪崩的唯一闸门

**铁律 2：自动解除分档**
- M1 自动解除：5 分钟（限流类天然短生命周期）
- M2 自动解除：15 分钟
- M3 自动解除：30 分钟
- M4/M5：永不自动解除
- 每次自动解除都必须生成"是否复发"的回检

**铁律 3：观察期**
- 自动解除 ≠ 风险消除
- 解除后进入**观察期**（建议 24h）
- 观察期内同一信号再次命中则直接升级一级
- 避免"振荡式开合"（Kill Switch 开开关关）

### 5.3 Kill Switch 联动路由算法

```
输入：AlertEvent {type, severity, confidence, blast_radius, organization_id, project_id}
输出：KillSwitchAction {mode, scope, ttl, auto_release}

1. 读取 KillSwitchConfig[organization_id]
2. 评估三维判定：severity × confidence × blast_radius
3. 确定联动模式：
   - 命中 M1 区域 → mode = M1, scope = project, auto_release = true
   - 命中 M2 区域 → mode = M2, scope = project, auto_release = true
   - 命中 M3 区域 → mode = M3, scope = connector, auto_release = false
   - 命中 M4 区域 → mode = M4, scope = org, auto_release = false
4. 验证爆破半径上限：
   - if blast_radius > MAX_BLAST_RADIUS:
       return ESCALATE_TO_HUMAN  # 降级为人工决策
5. 验证 Kill Switch 当前状态：
   - if current_mode >= target_mode:
       return NO_OP  # 不降级已有保护
6. 计算 TTL 和自动解除时间
7. 生成 KillSwitchAction 并发送到 SEC-009 Kill Switch State Machine
```

---

## 6. 通知渠道与升级机制

### 6.1 通知渠道分层

| 渠道 | 适用场景 | 响应时效要求 | 配置示例 |
|------|---------|------------|---------|
| **PagerDuty** | P1/P2 紧急告警，需要立即响应 | < 5 分钟 | routing_key + integration_url |
| **Slack/Teams** | P3/P4 常规告警，团队协作响应 | < 30 分钟 | webhook_url + channel |
| **Email** | P5 信息性告警，每日汇总 | 24 小时内 | smtp_server + recipients |
| **Webhook** | 系统集成，触发自动化工作流 | 即时 | endpoint_url + auth_header |

### 6.2 通知路由策略

```yaml
# 通知路由配置示例
notification_policy:
  default:
    channels:
      - type: slack
        webhook_url: "https://hooks.slack.com/services/XXX"
        channel: "#alerts"
  
  routes:
    - match:
        severity: CRITICAL
      channels:
        - type: pagerduty
          integration_key: "${PAGERDUTY_KEY}"
          urgency: high
        - type: slack
          webhook_url: "https://hooks.slack.com/services/XXX"
          channel: "#incidents"
    
    - match:
        severity: HIGH
        team: sre
      channels:
        - type: pagerduty
          integration_key: "${PAGERDUTY_KEY}"
          urgency: low
        - type: slack
          webhook_url: "https://hooks.slack.com/services/XXX"
          channel: "#sre-alerts"
    
    - match:
        severity: MEDIUM
      channels:
        - type: slack
          webhook_url: "https://hooks.slack.com/services/XXX"
          channel: "#alerts"
      group_wait: 30s
      group_interval: 5m
    
    - match:
        severity: LOW
      channels:
        - type: email
          recipients: ["team@example.com"]
      group_wait: 1h
      group_interval: 24h
```

### 6.3 升级机制

**升级策略**：

| 告警严重度 | 初始通知渠道 | 升级条件 | 升级目标 | 升级时间 |
|-----------|------------|---------|---------|---------|
| **CRITICAL** | PagerDuty（高优先级） | 无人确认 | 安全团队 Lead | 5 分钟 |
| **HIGH** | PagerDuty（低优先级） | 无人确认 | 安全团队 | 15 分钟 |
| **MEDIUM** | Slack | 无人响应 | SRE Team Lead | 30 分钟 |
| **LOW** | Email | 24h 无人查看 | 不升级 | N/A |

**升级流程**：
```
1. 告警触发 → 发送初始通知
2. 启动升级计时器
3. 检查告警确认状态
4. 若超时未确认 → 发送升级通知到更高优先级渠道
5. 记录升级事件到审计日志
6. 若再次超时 → 继续升级或触发事故响应流程
```

---

## 7. 告警生命周期管理

### 7.1 告警状态机

```
INACTIVE → PENDING → FIRING → ACKNOWLEDGED → RESOLVED
              ↓           ↓            ↓
          SUPPRESSED   ESCALATED   AUTO_RESOLVED

状态说明：
- INACTIVE：告警规则存在但条件不满足
- PENDING：条件满足，等待 for 持续时间
- FIRING：持续满足条件，触发通知
- ACKNOWLEDGED：人工确认告警
- SUPPRESSED：被静默规则抑制
- ESCALATED：升级到更高优先级或人工
- RESOLVED：告警条件消失，人工解决
- AUTO_RESOLVED：告警条件自动消失
```

### 7.2 静默与抑制规则

**静默（Silence）**：
- 时间窗口静默：在特定时间段内不触发告警
- 维护窗口：计划维护期间自动静默相关告警
- 手动静默：人工临时静默特定告警

**抑制（Inhibit）**：
- 级联抑制：高优先级告警触发时，抑制相关低优先级告警
- 依赖抑制：依赖服务故障时，抑制上游告警

```yaml
# 静默规则示例
silences:
  - name: maintenance_window
    matchers:
      - service: "agent-platform"
    start_time: "2026-10-06T02:00:00Z"
    end_time: "2026-10-06T04:00:00Z"
    creator: "sre-team"
    comment: "Database maintenance"
  
  - name: manual_silence
    matchers:
      - alertname: "high_error_rate"
      - organization_id: "org_123"
    duration: "2h"
    creator: "alice@example.com"
    comment: "Known issue, investigating"

# 抑制规则示例
inhibit_rules:
  - source_match:
      severity: CRITICAL
    target_match:
      severity: MEDIUM
    equal:
      - organization_id
      - project_id
  
  - source_match:
      alertname: "database_down"
    target_match:
      service: "agent-platform"
    equal:
      - organization_id
```

### 7.3 告警去重与聚合

**去重策略**：
- 5 分钟内同一告警规则的重复触发合并为一条
- 通过 `fingerprint` 字段识别唯一告警

**聚合策略**：
- 同类告警聚合为一条通知（如多个 Agent 错误率超标）
- 聚合配置：`group_by` 字段定义聚合维度

```yaml
# 聚合配置示例
grouping:
  - group_by: ['alertname', 'organization_id']
    group_wait: 30s        # 等待 30s 收集同组告警
    group_interval: 5m     # 5 分钟后发送新的同组告警
    repeat_interval: 4h    # 4 小时后重复发送未解决告警
```

---

## 8. 告警有效性评估

### 8.1 评估指标

| 指标名称 | 定义 | 计算方式 | 目标 |
|---------|------|---------|------|
| **精确率（Precision）** | 告警中真实问题的比例 | `true_positive / (true_positive + false_positive)` | ≥ 80% |
| **召回率（Recall）** | 问题被正确告警的比例 | `true_positive / (true_positive + false_negative)` | ≥ 90% |
| **噪声比（Noise Ratio）** | 无意义告警的比例 | `false_positive / all_alerts` | ≤ 20% |
| **响应率（Response Rate）** | 被响应的告警比例 | `acknowledged / fired` | ≥ 95% |
| **解决率（Resolution Rate）** | 被解决的告警比例 | `resolved / fired` | ≥ 90% |
| **平均确认时间（MTTA）** | 从触发到确认的平均时间 | `avg(acknowledge_time - trigger_time)` | < 5min（P1） |
| **平均解决时间（MTTR）** | 从触发到解决的平均时间 | `avg(resolve_time - trigger_time)` | < 30min |

### 8.2 评估周期与流程

**评估周期**：
- 每周离线分析：计算告警有效性指标
- 每月策略评审：调整告警规则和阈值
- 每季度复盘：全面优化告警策略

**评估流程**：
```
1. 数据采集
   ├─ 提取告警历史数据（触发、确认、解决记录）
   ├─ 提取人工标注数据（true_positive / false_positive）
   └─ 提取系统事故记录（missed_alerts）

2. 指标计算
   ├─ 计算精确率、召回率、噪声比
   ├─ 计算响应率、解决率
   └─ 计算 MTTA、MTTR

3. 问题识别
   ├─ 识别高噪声告警规则（噪声比 > 30%）
   ├─ 识别漏报场景（召回率 < 80%）
   └─ 识别响应不及时告警（MTTA > 目标）

4. 策略优化
   ├─ 调整告警阈值（减少噪声或提高召回）
   ├─ 优化通知路由（改善响应时间）
   └─ 新增缺失告警规则

5. 效果验证
   ├─ A/B 测试新规则
   ├─ 监控优化后效果
   └─ 持续迭代
```

### 8.3 告警质量改进建议

| 问题场景 | 症状 | 改进建议 |
|---------|------|---------|
| **高噪声告警** | 噪声比 > 30% | 提高告警阈值、增加 for 持续时间、使用 Burn Rate 替代静态阈值 |
| **漏报** | 召回率 < 80% | 降低告警阈值、新增监控指标、使用异常检测 |
| **响应不及时** | MTTA > 5min | 优化通知渠道、增加升级机制、改善 On-Call 流程 |
| **告警疲劳** | 响应率 < 80% | 合并同类告警、增加静默规则、分级路由 |

---

## 9. 异常与失败处理

### 9.1 告警系统自身故障

| 场景 | 症状 | 处理策略 |
|------|------|---------|
| **告警系统不可用** | 无法接收指标或触发告警 | 降级到本地日志记录，不阻塞 Agent 执行 |
| **规则评估超时** | PromQL 查询超过 5s | 跳过该规则本次评估，记录 `rule_evaluation_timeout` |
| **指标数据缺失** | 关键指标无数据 | 标记为 `telemetry_blind_spot`，触发 P2 告警 |
| **存储不可用** | 告警历史写入失败 | 本地缓冲队列保存，异步重试 |

### 9.2 Kill Switch 联动失败

| 场景 | 症状 | 处理策略 |
|------|------|---------|
| **Kill Switch 服务不可用** | 无法执行联动 | 使用 SEC-009 定义的三态 Fail-Closed 机制 |
| **联动请求被拒绝** | Kill Switch 返回 403 | 记录拒绝原因，升级人工审批 |
| **联动冲突** | 新告警请求 M1，但当前已是 M3 | 不降级已有保护，忽略低级别联动请求 |
| **联动超时** | Kill Switch 30s 未响应 | 重试 1 次，失败则升级人工 |

### 9.3 通知发送失败

| 场景 | 症状 | 处理策略 |
|------|------|---------|
| **Webhook 返回 5xx** | 通知发送失败 | 指数退避重试（1s, 2s, 4s, 8s, 16s），最多 5 次 |
| **PagerDuty 服务故障** | 无法创建事件 | 降级到 Slack + Email，记录发送失败 |
| **Slack 限流（429）** | 触发速率限制 | 等待 `Retry-After` 后重试，临时降级到 Email |
| **Email 发送失败** | SMTP 连接超时 | 重试 3 次，失败记录到 `notification_failure` |

### 9.4 告警风暴

| 场景 | 症状 | 处理策略 |
|------|------|---------|
| **短时间大量告警** | 1 分钟内触发 > 100 条告警 | 启动聚合模式，5 分钟发送一次汇总通知 |
| **级联故障** | 下游服务故障引发上游大量告警 | 应用抑制规则，只保留根因告警 |
| **循环触发** | 告警自动解决后立即再次触发 | 标记为 `flapping`，增加 for 持续时间到 10 分钟 |

---

## 10. 性能、成本与延迟

### 10.1 性能目标

| 指标 | 目标 | 说明 |
|------|------|------|
| 告警触发延迟 | < 10s（从指标异常到告警触发） | 依赖 OTel 导出延迟 + 规则评估延迟 |
| 规则评估延迟 | < 500ms（p95） | PromQL 查询性能 |
| 通知发送延迟 | < 1s（p95） | Webhook 调用性能 |
| Kill Switch 联动延迟 | < 30s（p99） | MTTC-p99 目标（对齐 SEC-009） |
| 告警查询延迟 | < 100ms（p95） | Dashboard 加载性能 |
| 规则评估吞吐 | > 1000 规则/分钟 | 支持大规模部署 |

### 10.2 成本控制

**计算成本**：
- 规则评估频率：每分钟一次（MVP），可配置为 15s
- 规则数量限制：单组织最多 100 条告警规则
- 查询超时：PromQL 查询最多 5s，超时跳过

**存储成本**：
- 告警历史保留：热存储 30 天，温存储 180 天，冷存储 7 年
- 告警状态存储：使用 Redis 缓存，TTL 7 天
- 通知历史：仅保留最近 90 天

**通知成本**：
- 通知去重窗口：5 分钟内同类告警合并为一条
- 聚合发送：MEDIUM/LOW 告警批量发送，减少 API 调用
- PagerDuty 成本：按事件数计费，优化触发频率

### 10.3 延迟预算分配

```
端到端延迟分解（目标 < 60s）：

指标采集 → OTel 导出（< 100ms）
    ↓
指标预处理 → 聚合计算（< 1s）
    ↓
规则评估 → PromQL 执行（< 500ms）
    ↓
告警触发 → 通知发送（< 1s）
    ↓
Kill Switch 联动 → 状态同步（< 30s）
    ↓
总延迟：< 35s（p95）、< 60s（p99）
```

---

## 11. 可观测性指标

### 11.1 告警系统自身指标

| 指标名 | 类型 | 定义 | 目标 | 告警条件 |
|--------|------|------|------|---------|
| `obs.alert.triggered.total` | Counter | 触发告警总数 | 基准指标 | N/A |
| `obs.alert.fire_rate` | Gauge | 告警触发率（per min） | 趋势监控 | 同比 > 200% |
| `obs.alert.mtta` | Histogram | 平均告警响应时间 | < 5min（P1） | p95 > 15min |
| `obs.alert.mttr` | Histogram | 平均告警解决时间 | < 30min | p95 > 2h |
| `obs.alert.suppression_rate` | Gauge | 静默/抑制率 | < 10% | > 30% |
| `obs.alert.noise_ratio` | Gauge | 噪声比（false_positive 占比） | < 20% | > 40% |
| `obs.alert.precision` | Gauge | 告警精确率 | ≥ 80% | < 70% |
| `obs.alert.recall` | Gauge | 告警召回率 | ≥ 90% | < 80% |
| `obs.alert.response_rate` | Gauge | 告警响应率 | ≥ 95% | < 85% |

### 11.2 Kill Switch 联动指标

| 指标名 | 类型 | 定义 | 目标 | 告警条件 |
|--------|------|------|------|---------|
| `obs.killswitch_linkage.requested` | Counter | Kill Switch 联动请求数 | 基准指标 | N/A |
| `obs.killswitch_linkage.approved` | Counter | 人工审批通过数 | 基准指标 | N/A |
| `obs.killswitch_linkage.rejected` | Counter | 联动被拒绝数 | < 5% | > 20% |
| `obs.killswitch_linkage.latency` | Histogram | 联动延迟分布 | p99 < 30s | p99 > 60s |
| `obs.killswitch_linkage.auto_release` | Counter | 自动解除次数 | 基准指标 | N/A |
| `obs.killswitch_linkage.escalated` | Counter | 升级人工次数 | 基准指标 | N/A |

### 11.3 通知渠道指标

| 指标名 | 类型 | 定义 | 目标 | 告警条件 |
|--------|------|------|------|---------|
| `obs.notification.sent.total` | Counter | 通知发送总数 | 基准指标 | N/A |
| `obs.notification.delivery_rate` | Gauge | 通知送达率 | ≥ 99% | < 95% |
| `obs.notification.latency.p95` | Histogram | 通知发送延迟 p95 | < 1s | > 5s |
| `obs.notification.retry.total` | Counter | 通知重试次数 | < 5% | > 15% |
| `obs.notification.failed.total` | Counter | 通知失败次数 | < 1% | > 5% |

---

## 12. 安全与合规

### 12.1 权限控制

| 操作 | 权限要求 | RBAC 角色 |
|------|---------|----------|
| 创建/修改告警规则 | `alert:write` | 组织管理员、项目管理员 |
| 删除告警规则 | `alert:admin` | 平台管理员 |
| 触发 Kill Switch M1/M2 | `killswitch:trigger` | 项目管理员、安全团队 |
| 触发 Kill Switch M3/M4 | `killswitch:admin` | 安全团队 Lead、CISO |
| 审批 Kill Switch 恢复 | `killswitch:approve` | 与触发同级或更高 |
| 查看告警历史 | `alert:read` | 项目成员 |
| 导出告警报告 | `alert:export` | 合规团队 |
| 配置通知渠道 | `notification:write` | 组织管理员 |
| 静默告警 | `alert:silence` | 项目管理员、SRE |

### 12.2 审计要求

**审计记录字段**：
```json
{
  "event_type": "alert.rule.created",
  "timestamp": "2026-10-05T12:34:56Z",
  "actor": {
    "user_id": "user_123",
    "role": "org_admin",
    "ip_address": "192.168.1.100"
  },
  "resource": {
    "rule_id": "rule_456",
    "rule_name": "high_error_rate",
    "organization_id": "org_789"
  },
  "changes": {
    "condition": "error_rate > 0.1",
    "severity": "HIGH",
    "kill_switch_linkage": true
  },
  "result": "success"
}
```

**审计事件类型**：
- `alert.rule.created`：告警规则创建
- `alert.rule.updated`：告警规则更新
- `alert.rule.deleted`：告警规则删除
- `alert.acknowledged`：告警确认
- `alert.resolved`：告警解决
- `alert.silenced`：告警静默
- `killswitch_linkage.requested`：Kill Switch 联动请求
- `killswitch_linkage.approved`：Kill Switch 联动审批
- `notification.sent`：通知发送

### 12.3 数据保护

**敏感数据处理**：
- 通知消息不得包含凭据、PII、完整 Prompt
- 告警历史脱敏：移除敏感字段（对齐 REQ-OBS-004）
- Webhook 回调必须验证签名（HMAC-SHA256）

**数据保留策略**：
- 告警记录保留 7 年（对齐 REQ-RT-008）
- Kill Switch 操作记录视为安全事件（对齐 REQ-SEC-009）
- 通知历史保留 90 天

---

## 13. API 端点设计

### 13.1 告警规则管理 API

```
# 列表告警规则
GET /api/v1/alerts/rules
Query Parameters:
  - organization_id: string (required)
  - project_id: string (optional)
  - severity: enum (optional)
  - enabled: boolean (optional)
Response: 200 OK
  {
    "rules": [
      {
        "rule_id": "rule_123",
        "name": "high_error_rate",
        "severity": "HIGH",
        "enabled": true,
        "created_at": "2026-10-01T10:00:00Z",
        "updated_at": "2026-10-05T12:00:00Z"
      }
    ],
    "total": 10
  }

# 创建告警规则
POST /api/v1/alerts/rules
Request Body:
  {
    "name": "high_error_rate",
    "organization_id": "org_123",
    "project_id": "proj_456",
    "severity": "HIGH",
    "metrics": ["gen_ai.task.failed.total", "gen_ai.task.completed.total"],
    "condition": "error_rate = sum(rate(gen_ai.task.failed.total[5m])) / sum(rate(gen_ai.task.completed.total[5m])) > 0.1",
    "for": "5m",
    "labels": {"team": "sre"},
    "annotations": {"summary": "Task error rate exceeds 10%"},
    "kill_switch_linkage": {
      "enabled": true,
      "trigger_condition": {
        "severity": "HIGH",
        "confidence": "MEDIUM",
        "blast_radius": "LIMITED"
      },
      "linkage_action": "M1"
    }
  }
Response: 201 Created
  {
    "rule_id": "rule_789",
    "name": "high_error_rate",
    "created_at": "2026-10-05T12:34:56Z"
  }

# 获取规则详情
GET /api/v1/alerts/rules/{rule_id}
Response: 200 OK

# 更新规则
PUT /api/v1/alerts/rules/{rule_id}
Request Body: (same as create)
Response: 200 OK

# 删除规则
DELETE /api/v1/alerts/rules/{rule_id}
Response: 204 No Content
```

### 13.2 告警实例管理 API

```
# 列表告警
GET /api/v1/alerts
Query Parameters:
  - organization_id: string (required)
  - project_id: string (optional)
  - severity: enum (optional)
  - status: enum (optional, FIRING/ACKNOWLEDGED/RESOLVED)
  - start_time: datetime (optional)
  - end_time: datetime (optional)
Response: 200 OK
  {
    "alerts": [
      {
        "alert_id": "alert_123",
        "rule_id": "rule_456",
        "rule_name": "high_error_rate",
        "severity": "HIGH",
        "status": "FIRING",
        "triggered_at": "2026-10-05T12:30:00Z",
        "fingerprint": "abc123",
        "labels": {"team": "sre", "organization_id": "org_123"},
        "annotations": {"summary": "Task error rate exceeds 10%"}
      }
    ],
    "total": 5
  }

# 获取告警详情
GET /api/v1/alerts/{alert_id}
Response: 200 OK
  {
    "alert_id": "alert_123",
    "rule_id": "rule_456",
    "severity": "HIGH",
    "status": "FIRING",
    "triggered_at": "2026-10-05T12:30:00Z",
    "acknowledged_at": null,
    "resolved_at": null,
    "metric_snapshot": {
      "error_rate": 0.15,
      "failed_tasks": 150,
      "total_tasks": 1000
    },
    "related_traces": ["trace_789"],
    "kill_switch_linkage": {
      "requested": true,
      "mode": "M1",
      "applied_at": "2026-10-05T12:30:25Z"
    }
  }

# 确认告警
POST /api/v1/alerts/{alert_id}/acknowledge
Request Body:
  {
    "comment": "Investigating the issue"
  }
Response: 200 OK
  {
    "alert_id": "alert_123",
    "status": "ACKNOWLEDGED",
    "acknowledged_at": "2026-10-05T12:35:00Z",
    "acknowledged_by": "user_456"
  }

# 解决告警
POST /api/v1/alerts/{alert_id}/resolve
Request Body:
  {
    "comment": "Issue resolved by restarting service"
  }
Response: 200 OK
  {
    "alert_id": "alert_123",
    "status": "RESOLVED",
    "resolved_at": "2026-10-05T12:45:00Z",
    "resolved_by": "user_456"
  }

# 静默告警
POST /api/v1/alerts/{alert_id}/silence
Request Body:
  {
    "duration": "2h",
    "comment": "Known issue, will fix later"
  }
Response: 200 OK
  {
    "silence_id": "silence_789",
    "alert_id": "alert_123",
    "start_time": "2026-10-05T12:50:00Z",
    "end_time": "2026-10-05T14:50:00Z"
  }
```

### 13.3 Kill Switch 联动 API

```
# 请求 Kill Switch 联动（幂等）
POST /api/v1/kill-switch/linkage
Request Body:
  {
    "alert_id": "alert_123",
    "organization_id": "org_123",
    "project_id": "proj_456",
    "mode": "M1",
    "scope": "project",
    "reason": "high_error_rate alert triggered",
    "idempotency_key": "idem_789"
  }
Response: 200 OK
  {
    "linkage_id": "linkage_abc",
    "status": "APPLIED",
    "applied_at": "2026-10-05T12:30:25Z",
    "auto_release": true,
    "release_at": "2026-10-05T12:45:25Z"
  }

# 查询联动状态
GET /api/v1/kill-switch/linkage/{linkage_id}
Response: 200 OK
  {
    "linkage_id": "linkage_abc",
    "alert_id": "alert_123",
    "mode": "M1",
    "status": "ACTIVE",
    "applied_at": "2026-10-05T12:30:25Z",
    "auto_release": true,
    "release_at": "2026-10-05T12:45:25Z"
  }

# 查询组织当前 Kill Switch 状态
GET /api/v1/kill-switch/status
Query Parameters:
  - organization_id: string (required)
Response: 200 OK
  {
    "organization_id": "org_123",
    "current_mode": "M1",
    "applied_at": "2026-10-05T12:30:25Z",
    "linkage_id": "linkage_abc",
    "alert_id": "alert_123",
    "auto_release": true,
    "release_at": "2026-10-05T12:45:25Z"
  }
```

### 13.4 通知渠道管理 API

```
# 列表通知渠道
GET /api/v1/notifications/channels
Query Parameters:
  - organization_id: string (required)
Response: 200 OK
  {
    "channels": [
      {
        "channel_id": "channel_123",
        "type": "slack",
        "name": "SRE Team Slack",
        "enabled": true,
        "config": {"webhook_url": "https://...", "channel": "#alerts"}
      }
    ]
  }

# 创建通知渠道
POST /api/v1/notifications/channels
Request Body:
  {
    "organization_id": "org_123",
    "type": "slack",
    "name": "SRE Team Slack",
    "config": {
      "webhook_url": "https://hooks.slack.com/services/XXX",
      "channel": "#alerts"
    }
  }
Response: 201 Created

# 更新通知渠道
PUT /api/v1/notifications/channels/{channel_id}
Response: 200 OK

# 删除通知渠道
DELETE /api/v1/notifications/channels/{channel_id}
Response: 204 No Content

# 测试通知渠道
POST /api/v1/notifications/channels/{channel_id}/test
Response: 200 OK
  {
    "status": "success",
    "message": "Test notification sent"
  }
```

---

## 14. 依赖与跨模块边界

### 14.1 前置依赖

| 需求 | 依赖内容 | 边界 |
|------|---------|------|
| `REQ-OBS-003`（指标字典） | 指标名称、类型、维度定义 | 告警规则引用的指标必须在 OBS-003 中定义 |
| `REQ-SEC-009`（Kill Switch） | Kill Switch State Machine API、M0-M5 模式枚举 | OBS-005 调用 SEC-009 的联动接口 |
| `REQ-RT-001`（核心实体） | 组织、项目、任务标识 | 告警规则和事件的关联字段 |
| `REQ-RT-007`（幂等键） | 幂等性保障机制 | Kill Switch 联动请求携带幂等键 |
| `REQ-OBS-001`（语义约定） | Span 属性定义 | 告警上下文关联 Trace/Span |

### 14.2 下游依赖

| 需求 | 本设计提供的内容 | 边界 |
|------|---------------|------|
| `REQ-OBS-006`（审计查询 API） | 告警事件和 Kill Switch 联动记录 | OBS-006 查询 OBS-005 产生的审计事件 |
| `REQ-OBS-007`（审计留存） | 告警历史数据 | OBS-007 实现 7 年留存策略 |
| `REQ-EVA-003`（自动评分器） | 告警有效性指标 | EVA-003 可使用告警精确率/召回率作为评分输入 |

---

## 15. 验收标准

### 15.1 功能性验收

| 编号 | 验收项 | 验收方法 |
|------|--------|---------|
| OBS-005-AC1 | 告警规则支持 PromQL 风格条件表达式 | 编写测试规则，验证评估结果 |
| OBS-005-AC2 | 告警触发后 Kill Switch 联动在 ≤ 30s 内生效（p99） | 注入告警 + 测量 Kill Switch 状态变更延迟 |
| OBS-005-AC3 | 爆破半径超限（> 5% 租户）时自动降级为人工审批 | 模拟超限告警，验证升级流程 |
| OBS-005-AC4 | 通知渠道支持 PagerDuty/Slack/Email/Webhook | 配置各渠道并发送测试通知 |
| OBS-005-AC5 | 告警 Dashboard 展示实时告警列表和状态 | UI 测试 + 性能测试（< 100ms p95） |
| OBS-005-AC6 | 告警历史保留 7 年（合规） | 数据治理测试 |
| OBS-005-AC7 | 告警规则变更必须审计记录 | 创建/修改/删除规则，验证审计日志 |
| OBS-005-AC8 | Kill Switch 联动操作幂等性 | 重复发送同一联动请求，验证只执行一次 |
| OBS-005-AC9 | 告警静默规则在指定时间窗口生效 | 配置静默规则并触发告警，验证被抑制 |
| OBS-005-AC10 | 告警有效性指标可计算（精确率、召回率） | 离线分析 + 报表验证 |
| OBS-005-AC11 | 告警与 Kill Switch 冲突时有明确优先级 | 模拟冲突场景（M1 请求但当前 M3），验证不降级 |
| OBS-005-AC12 | 三维判定矩阵按预期映射到 Kill Switch 模式 | 覆盖所有矩阵单元格的集成测试 |
| OBS-005-AC13 | 告警升级在超时后自动触发 | 配置升级规则，不响应告警，验证自动升级 |
| OBS-005-AC14 | 告警去重和聚合正确执行 | 短时间触发多条同类告警，验证合并为一条 |
| OBS-005-AC15 | 告警抑制规则正确应用 | 触发高优先级告警，验证低优先级告警被抑制 |

### 15.2 性能验收

| 指标 | 目标 | 验证方法 |
|------|------|---------|
| 告警触发延迟 | < 10s（从指标异常到告警触发） | 端到端测量 |
| 规则评估延迟 | < 500ms（p95） | 微基准测试 |
| 通知发送延迟 | < 1s（p95） | Webhook 性能测试 |
| Kill Switch 联动延迟 | < 30s（p99） | 集成测试 |
| 告警查询延迟 | < 100ms（p95） | Dashboard 性能测试 |
| 规则评估吞吐 | > 1000 规则/分钟 | 压力测试 |

### 15.3 质量验收

| 指标 | 目标 | 验证方法 |
|------|------|---------|
| 告警精确率 | ≥ 80% | 离线分析历史数据 |
| 告警召回率 | ≥ 90% | 对比系统事故记录 |
| 告警噪声比 | ≤ 20% | 人工标注 + 离线分析 |
| 通知送达率 | ≥ 99% | 监控通知发送成功率 |
| Kill Switch 联动成功率 | ≥ 99.9% | 监控联动请求成功率 |

---

## 16. 实现指导

### 16.1 推荐技术栈

**告警规则引擎**：
- Prometheus Alertmanager（推荐）
- Grafana Alerting
- 自研引擎（基于 PromQL 解析器）

**指标存储与查询**：
- Prometheus（推荐）
- VictoriaMetrics
- Grafana Mimir

**通知服务**：
- Alertmanager Receiver（Webhook/Email/Slack）
- PagerDuty API
- 自研通知服务

**状态存储**：
- Redis（告警状态缓存）
- PostgreSQL（告警历史）

### 16.2 实现检查清单

- [ ] 实现告警规则 DSL 解析器
- [ ] 实现 PromQL 条件评估引擎
- [ ] 实现三维判定矩阵逻辑
- [ ] 实现 Kill Switch 联动客户端（调用 SEC-009 API）
- [ ] 实现通知路由器（支持多渠道）
- [ ] 实现告警状态机
- [ ] 实现静默和抑制规则引擎
- [ ] 实现告警去重和聚合
- [ ] 实现升级机制
- [ ] 实现告警 Dashboard UI
- [ ] 实现告警管理 API
- [ ] 实现审计日志记录
- [ ] 编写单元测试和集成测试
- [ ] 配置监控告警（告警系统自身）
- [ ] 编写运维文档和 Runbook

### 16.3 分阶段实施计划

**Phase 1：MVP（4 周）**
- 基础告警规则引擎（静态阈值）
- 与 SEC-009 Kill Switch 的基础联动（M1/M2）
- 三层通知渠道（Webhook/Slack/PagerDuty）
- 告警 Dashboard（实时列表、确认、解决）
- 基础审计日志

**Phase 2：增强功能（3 周）**
- Burn Rate 告警支持
- M3/M4 联动支持
- Email 通知渠道
- 静默和抑制规则
- 告警去重和聚合
- 升级机制

**Phase 3：优化与评估（2 周）**
- 告警有效性评估系统
- 异常检测告警
- 告警模板系统
- 性能优化
- 文档完善

---

## 17. MVP 范围

**MVP 包含**：
- 基础告警规则引擎（支持 PromQL 静态阈值条件）
- 与 SEC-009 Kill Switch 的基础联动（M1/M2 模式）
- 三维判定矩阵（简化版，仅支持 HIGH/MEDIUM/LOW 三级严重度）
- 三层通知渠道（Webhook/Slack/PagerDuty）
- 告警 Dashboard（实时列表、确认、解决、详情查看）
- 告警管理 API（CRUD + 确认/解决）
- 基础审计日志（规则变更、告警触发、联动请求）
- 告警自身监控指标（触发数、延迟、送达率）

**MVP 不包含**：
- Burn Rate 告警（留待 Phase 2）
- M3/M4 联动（留待 Phase 2）
- Email 通知渠道（留待 Phase 2）
- 静默和抑制规则（留待 Phase 2）
- 告警去重和聚合（留待 Phase 2）
- 升级机制（留待 Phase 2）
- 告警有效性评估（留待 Phase 3）
- 异常检测告警（留待 Phase 3）

---

## 18. 设计决策记录

```text
需求编号：REQ-OBS-005
功能点：告警和 Kill Switch 联动
当前状态：详细设计已完成，待跨模块评审与冻结
前置依赖：REQ-SEC-009、REQ-OBS-003
候选方案：
  A. 静态告警 + 人工触发 Kill Switch
  B. 静态告警 + 简单联动规则
  C. 三维判定矩阵 + 自动化联动 + 分层通知 + 告警评估体系（推荐）
公开证据等级：A（基于 OneUptime、AgentGazer、Agent Sentinel、Guardplane、
             Grafana、PagerDuty、DeepSeek 等产品文档和最佳实践）
推荐基线：方案 C
选择理由：
  1. 三维判定矩阵（严重度×置信度×爆破半径）提供精确的自动化决策依据
  2. 与 SEC-009 Kill Switch 的深度集成实现异常检测到自动止血的闭环
  3. 分层通知渠道和升级机制减少告警疲劳，提高响应效率
  4. 告警有效性评估体系确保告警策略可持续优化
  5. 借鉴行业标杆（Grafana SLO、PagerDuty Automation、Agent Sentinel 置信度门控）
  6. 自动化联动三条铁律防止误触雪崩
适用边界：
  MVP 先行静态阈值告警 + M1/M2 联动，Burn Rate 和 M3/M4 联动后续扩展
替代方案：
  完全人工触发（不推荐）：无法满足 MTTC ≤ 30s 的快速止血要求
安全约束：
  告警规则变更必须审计；Kill Switch 联动请求幂等；通知消息脱敏；
  爆破半径上限防止误触；M3/M4 联动需人工审批
失败与恢复：
  告警系统不可用 → 降级到本地日志；Kill Switch 不可用 → 三态 Fail-Closed；
  通知失败 → 指数退避重试；联动冲突 → 不降级已有保护
验收指标：
  告警触发延迟 < 10s，联动延迟 p99 < 30s，通知送达率 ≥ 99%，
  告警精确率 ≥ 80%，召回率 ≥ 90%
目标版本：REQ-OBS-005 v0.1-designed
```

---

## 19. 参考资料

### 19.1 行业标杆产品

- OneUptime AI Agent Circuit Breakers: https://oneuptime.com/docs/en/telemetry/ai-agent-circuit-breaker (访问日期: 2026-10-05)
- AgentGazer Kill Switch: https://agentgazer.com/en/guide/kill-switch.html (访问日期: 2026-10-05)
- AgentGazer Alerts: https://agentgazer.com/en/guide/alerts.html (访问日期: 2026-10-05)
- Agent Sentinel: https://docs.agentsentinel.dev/ (访问日期: 2026-10-05)
- Guardplane GitHub: https://github.com/mkadri85/guardplane/ (访问日期: 2026-10-05)
- Grafana SLO Best Practices: https://grafana.com/docs/grafana-cloud/observe-and-act/alert-and-measure-reliability/slo/best-practices/ (访问日期: 2026-10-05)
- PagerDuty Automation Actions: https://docs.pagerduty.com/ai-automation/automation/automation-actions (访问日期: 2026-10-05)
- PagerDuty Webhooks: https://docs.pagerduty.com/developer/webhooks-overview (访问日期: 2026-10-05)
- DeepSeek Observability: https://chat-deep.ai/docs/deepseek-observability/ (访问日期: 2026-10-05)
- DeepSeek Prometheus Exporter: https://github.com/xxiaoxiong/dsh-prometheus (访问日期: 2026-10-05)

### 19.2 技术标准与最佳实践

- Google SRE Workbook - Burn Rate Alerting
- Prometheus Alerting Best Practices
- OpenTelemetry GenAI Semantic Conventions
- NIST SP 800-61r3 Computer Security Incident Handling Guide

---

## 20. 变更记录

| 版本 | 日期 | 变更 | 作者 |
|------|------|------|------|
| `v0.1-designed` | 2026-10-05 | 基于行业标杆（OneUptime、AgentGazer、Agent Sentinel、Guardplane、Grafana、PagerDuty、DeepSeek）完成详细设计：告警规则引擎、三维判定矩阵、Kill Switch 联动、分层通知、升级机制、告警评估体系 | 架构组 |

---

**文档维护**：架构组  
**最后更新**：2026-10-05






