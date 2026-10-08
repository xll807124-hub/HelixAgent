# REQ-EVA-006 发布门禁详细设计

> 所属基线：`Evaluation and Release Gate Baseline v0.2`  
> 需求编号：`REQ-EVA-006`  
> 优先级：P0  
> 设计版本：`v0.1-designed`  
> 设计状态：详细设计已完成  
> 设计日期：2026-10-05  
> 依赖前置：`REQ-EVA-005`（已完成）、`REQ-SEC-001`（已完成）  
> 依赖后置：质量保证、持续改进

---

## 1. 需求定义

### 1.1 核心目标

建立分层发布门禁体系，实现：
1. 软硬门禁分离，支持告警和阻断的差异化处理
2. 血缘感知阈值，对不同评估层次和血缘类型差异化配置
3. 多维度回归检测，避免均值掩盖尾部问题
4. 例外机制和break-glass，确保紧急发布有合规通道
5. 自动回滚和人工审批联动，保障发布安全

### 1.2 设计目标

| 目标维度 | 具体目标 |
|---------|---------|
| **门禁准确性** | 误报率 ≤ 5%，漏报率 ≤ 1% |
| **门禁效率** | 总执行时间 < 30分钟 |
| **回归检出率** | ≥ 90% |
| **紧急发布支持** | Break-glass使用率 < 2% |
| **可观测性** | 所有决策可追溯、可审计 |

### 1.3 用户价值

| 使用方 | 价值 |
|-------|------|
| 发布经理 | 数据驱动的发布决策、例外申请和回滚支持 |
| ML工程师 | 多维度回归分析、定位模型/提示/工具退化 |
| 评估工程师 | 统一门禁执行入口、CI/CD自动化 |
| 安全工程师 | 安全门禁独立评估、与SEC模块联动 |
| SRE工程师 | 发布健康度全景视图、故障预警 |

---

## 2. 行业调研与标杆对齐

### 2.1 行业标杆汇总

| 标杆产品 | 核心设计 | 可借鉴点 | 来源 |
|---------|---------|---------|------|
| **Cursor** | 软/硬门禁分离、失败产物记录 | 软门禁告警不阻断，硬门禁必须通过 | REQ-EVA-005 §二.1 |
| **OpenAI Codex** | 三层管道分层阻断 | 确定性验证优先，分层门禁独立评估 | REQ-EVA-005 §二.1 |
| **SWE-bench** | 血缘感知阈值+统计显著性检验 | 不同血缘类型差异化阈值 | REQ-EVA-001 §二.2 |
| **DeepSeek** | 容器隔离评估+ATIF轨迹 | 评估一致性和可重复性 | REQ-EVA-005 §二.1 |
| **Kimi K3** | rubric维度独立评分+成本测量 | per-criterion评分便于定位问题 | REQ-EVA-005 §二.1 |

### 2.2 关键设计原则

1. **软硬门禁分离**：告警和阻断明确区分（对标Cursor）
2. **血缘感知阈值**：5类血缘差异化配置（对标SWE-bench）
3. **多维度回归检测**：通过率+评分+轨迹（对标SWE-bench统计检验）
4. **决策状态机**：ALLOW/DENY/CONDITIONAL/OVERRIDE清晰边界
5. **成本感知评估**：轨迹感知子集节省70-90%成本（对标SWE-bench）

---

## 3. 设计边界

### 3.1 本需求包含

- 四级门禁体系定义（冒烟/回归/性能/安全）
- 软硬门禁类型和触发条件
- 血缘感知阈值配置
- 多维度回归检测算法
- 例外申请和break-glass流程
- 自动回滚机制
- CI/CD集成方案
- 门禁可观测性和审计

### 3.2 本需求不包含

| 内容 | 归属需求 |
|------|----------|
| 回归测试流水线实现 | REQ-EVA-005 |
| 自动评分器实现 | REQ-EVA-003 |
| 失败归因分析 | REQ-EVA-004 |
| Golden Dataset构建 | REQ-EVA-001 |
| 安全扫描实现 | 安全扫描系统 |

---

## 4. 四级门禁体系架构

### 4.1 门禁分层

```
┌─────────────────────────────────────────────────────┐
│ Level 1: 冒烟测试门禁 (Smoke Tests)                  │
│ - 评估对象：10-20个最关键基础任务                    │
│ - 通过标准：100%通过                                 │
│ - 门禁类型：硬门禁（阻断发布）                       │
│ - 执行时间：< 5分钟                                  │
└─────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────┐
│ Level 2: 回归测试门禁 (Regression Tests)             │
│ - 评估对象：完整Golden Dataset（血缘感知）          │
│ - 通过标准：按血缘类型差异化阈值                     │
│ - 门禁类型：硬门禁（REAL_*/SYNTH_ADVERSARIAL）      │
│              软门禁（SYNTH_PROPERTY/SYNTH_STRESS）   │
│ - 执行时间：< 20分钟（子集评估）                     │
└─────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────┐
│ Level 3: 性能基准门禁 (Performance Benchmarks)       │
│ - 评估对象：延迟、吞吐量、Token使用、成本           │
│ - 通过标准：不退化超过20%                            │
│ - 门禁类型：软门禁（告警但不阻断）                   │
│ - 执行时间：< 2分钟                                  │
└─────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────┐
│ Level 4: 安全扫描门禁 (Security Scans)               │
│ - 评估对象：高危漏洞、凭据泄露、依赖漏洞            │
│ - 通过标准：CRITICAL=0，HIGH≤2                       │
│ - 门禁类型：硬门禁（CRITICAL/HIGH）                  │
│              软门禁（MEDIUM/LOW）                     │
│ - 执行时间：< 5分钟                                  │
└─────────────────────────────────────────────────────┘
           │
           ▼
      门禁决策聚合
           │
    ┌──────┴──────┐
    ▼             ▼
  ALLOW         DENY
  (发布)        (阻断)
```

### 4.2 软硬门禁分离

| 门禁类型 | 定义 | 触发动作 | 使用场景 |
|---------|------|---------|---------|
| **硬门禁** | 必须通过才能发布 | 阻断发布 + 通知 | 冒烟测试、真实任务回归、安全CRITICAL |
| **软门禁** | 未通过告警但不阻断 | 记录告警 + 通知 | 性能基准、合成任务回归、安全MEDIUM |

---

## 5. 血缘感知阈值配置

### 5.1 五类血缘差异化阈值

| 血缘类型 | 通过率阈值 | 平均分阈值 | 门禁类型 | 理由 |
|---------|-----------|-----------|---------|------|
| **REAL_OWN_REPO** | ≥ 95% | ≥ 0.90 | 硬门禁 | 真实生产任务，不容退化 |
| **REAL_EXTERNAL** | ≥ 90% | ≥ 0.85 | 硬门禁 | 公开基准，影响对外声誉 |
| **SYNTH_PROPERTY** | ≥ 85% | ≥ 0.80 | 软门禁 | 属性验证，告警即可 |
| **SYNTH_ADVERSARIAL** | ≥ 80% | ≥ 0.75 | 硬门禁 | 对抗鲁棒性，防注入/越狱 |
| **SYNTH_STRESS** | ≥ 75% | ≥ 0.70 | 软门禁 | 极限场景，探索性监控 |

### 5.2 阈值调整机制

| 调整触发条件 | 调整动作 | 审批要求 |
|------------|---------|---------|
| 新版本发布后3天内失败率>5% | 下调阈值5% | Tech Lead审批 |
| 连续10次发布无失败 | 上调阈值2% | 自动调整 |
| 季度业务需求变更 | 重新标定基线 | 质量委员会审批 |

---

## 6. 多维度回归检测算法

### 6.1 三维度检测

门禁系统对比**当前版本**与**基线版本**的三个维度：

| 维度 | 检测指标 | 检验方法 | 阈值 |
|------|---------|---------|------|
| **通过率** | Pass Rate (按血缘类型分组) | Chi-square检验 | p < 0.05 视为退化 |
| **评分分布** | Score分布 (0.0-1.0) | Wilcoxon rank-sum检验 | p < 0.05 且中位数下降>5% |
| **轨迹相似度** | 执行轨迹embedding余弦相似度 | Cosine Similarity | < 0.85 视为行为偏移 |

### 6.2 回归检测算法伪代码

```
function detect_regression(current_eval, baseline_eval):
    regression_signals = []
    
    # 维度1: 通过率检验（按血缘分组）
    for provenance_type in [REAL_OWN_REPO, REAL_EXTERNAL, ...]:
        current_pass_rate = calc_pass_rate(current_eval, provenance_type)
        baseline_pass_rate = calc_pass_rate(baseline_eval, provenance_type)
        p_value = chi_square_test(current_pass_rate, baseline_pass_rate)
        
        if p_value < 0.05 and current_pass_rate < baseline_pass_rate:
            regression_signals.append({
                dimension: "pass_rate",
                provenance: provenance_type,
                delta: current_pass_rate - baseline_pass_rate,
                p_value: p_value
            })
    
    # 维度2: 评分分布检验
    current_scores = extract_scores(current_eval)
    baseline_scores = extract_scores(baseline_eval)
    p_value = wilcoxon_ranksum(current_scores, baseline_scores)
    median_delta = median(current_scores) - median(baseline_scores)
    
    if p_value < 0.05 and median_delta < -0.05:
        regression_signals.append({
            dimension: "score_distribution",
            median_delta: median_delta,
            p_value: p_value
        })
    
    # 维度3: 轨迹相似度
    current_trajectories = extract_trajectories(current_eval)
    baseline_trajectories = extract_trajectories(baseline_eval)
    similarity = cosine_similarity(
        embed(current_trajectories),
        embed(baseline_trajectories)
    )
    
    if similarity < 0.85:
        regression_signals.append({
            dimension: "trajectory_similarity",
            similarity: similarity
        })
    
    return regression_signals
```

### 6.3 回归判定矩阵

| 通过率退化 | 评分退化 | 轨迹偏移 | 判定结果 |
|-----------|---------|---------|---------|
| ✓ | ✓ | ✓ | **DENY**（严重回归） |
| ✓ | ✓ | ✗ | **DENY**（统计显著） |
| ✓ | ✗ | ✓ | **CONDITIONAL**（需人工审查） |
| ✗ | ✓ | ✓ | **CONDITIONAL**（行为变化） |
| ✓ | ✗ | ✗ | **软门禁告警** |
| ✗ | ✗ | ✓ | **软门禁告警** |
| ✗ | ✗ | ✗ | **ALLOW** |

---

## 7. 决策状态机

### 7.1 四种决策状态

```
                    ┌──────────────┐
                    │  门禁评估     │
                    └──────┬───────┘
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
         ▼                 ▼                 ▼
    所有硬门禁通过      部分硬门禁失败    例外已审批
         │                 │                 │
         ▼                 ▼                 ▼
   ┌─────────┐      ┌─────────┐      ┌──────────────┐
   │ ALLOW   │      │  DENY   │      │ CONDITIONAL  │
   └─────────┘      └─────────┘      └──────────────┘
         │                              │
         └──────────┬──────────────────┘
                    │
             紧急发布通道?
                    │
                    ▼
           ┌─────────────────┐
           │   OVERRIDE      │
           │ (Break-Glass)   │
           └─────────────────┘
```

### 7.2 决策状态定义

| 状态 | 定义 | 前置条件 | 后置操作 |
|------|------|---------|---------|
| **ALLOW** | 所有硬门禁通过，允许发布 | Level 1-4硬门禁全部PASS | 自动发布、记录决策日志 |
| **DENY** | 至少一个硬门禁失败，阻断发布 | 任一硬门禁FAIL | 阻断发布、通知负责人、生成失败报告 |
| **CONDITIONAL** | 例外申请已审批，有条件通过 | DENY + 例外审批通过 | 限定范围发布、强化监控、定时复查 |
| **OVERRIDE** | Break-Glass紧急通道 | DENY + 紧急事件 + Quorum审批 | 立即发布、全链路审计、72h内强制修复 |

---

## 8. 例外与Break-Glass机制

### 8.1 例外申请流程

```
发布被阻断 (DENY)
    │
    ▼
提交例外申请
    │
    ├─ 例外类型: 新功能测试覆盖不足
    ├─ 影响范围: 仅影响特定功能模块
    ├─ 缓解措施: 灰度发布10% + 24h监控
    └─ 补救计划: 48h内补齐测试用例
    │
    ▼
审批流程
    ├─ L1: Tech Lead审批（影响范围<5%）
    ├─ L2: 质量委员会审批（影响范围5-20%）
    └─ L3: VP Engineering审批（影响范围>20%）
    │
    ▼
决策: CONDITIONAL
    │
    ▼
限定范围发布 + 定时复查
```

### 8.2 Break-Glass紧急通道

**触发条件**：
- 生产严重故障（P0事件）
- 安全漏洞紧急修复
- 合规强制要求
- 用户承诺交付延误风险

**Quorum审批**：
- 至少3人审批通过
- 必须包含1位VP级别
- 审批时间窗口：2小时

**执行约束**：
```yaml
override:
  approval_quorum: 3
  min_vp_count: 1
  time_window: 2h
  scope:
    allowed_changes: [hotfix, security_patch, rollback]
    forbidden_changes: [new_feature, refactor, schema_migration]
  post_release:
    monitoring_duration: 72h
    mandatory_review: true
    remediation_deadline: 72h
```

### 8.3 审计追踪

所有例外和Override决策记录至审计日志：

| 字段 | 说明 |
|------|------|
| `decision_id` | 唯一决策ID |
| `decision_type` | CONDITIONAL / OVERRIDE |
| `triggered_by` | 触发人员 |
| `approved_by` | 审批人员列表 |
| `gate_failures` | 失败的门禁列表 |
| `exception_reason` | 例外理由 |
| `mitigation_plan` | 缓解措施 |
| `scope_limit` | 影响范围限制 |
| `timestamp` | 决策时间 |
| `audit_trail_url` | 审计链接 |

---

## 9. 自动回滚机制

### 9.1 回滚触发条件

| 触发器 | 条件 | 回滚动作 |
|-------|------|---------|
| **发布后回归检测** | 发布后1h内执行回归测试失败 | 自动回滚至上一稳定版本 |
| **告警聚合** | 5分钟内>10条CRITICAL告警 | 自动回滚 |
| **健康检查失败** | 健康检查连续3次失败 | 自动回滚 |
| **人工触发** | Kill Switch激活 | 立即回滚 |

### 9.2 回滚决策算法

```
function should_auto_rollback(release_version):
    # 1. 发布后回归测试
    post_release_eval = run_regression_tests(release_version)
    if post_release_eval.pass_rate < baseline_pass_rate * 0.90:
        return {action: "ROLLBACK", reason: "post_release_regression"}
    
    # 2. 告警聚合
    critical_alerts = get_alerts(severity="CRITICAL", time_window="5m")
    if len(critical_alerts) > 10:
        return {action: "ROLLBACK", reason: "alert_storm"}
    
    # 3. 健康检查
    health_checks = run_health_checks(release_version, attempts=3)
    if all([check.status == "FAIL" for check in health_checks]):
        return {action: "ROLLBACK", reason: "health_check_failure"}
    
    # 4. Kill Switch
    if kill_switch.is_activated():
        return {action: "ROLLBACK", reason: "kill_switch"}
    
    return {action: "HOLD", reason: "stable"}
```

### 9.3 CI/CD集成

**GitHub Actions集成示例**：

```yaml
name: Release Gate Pipeline

on:
  push:
    branches: [main, release/*]

jobs:
  gate-evaluation:
    runs-on: ubuntu-latest
    steps:
      - name: Level 1 - Smoke Tests
        run: |
          python -m evaluation.gate --level=smoke --output=smoke_results.json
      
      - name: Level 2 - Regression Tests
        run: |
          python -m evaluation.gate --level=regression --subset=trajectory_aware
      
      - name: Level 3 - Performance Benchmarks
        run: |
          python -m evaluation.gate --level=performance
      
      - name: Level 4 - Security Scans
        run: |
          python -m evaluation.gate --level=security
      
      - name: Gate Decision
        id: decision
        run: |
          python -m evaluation.gate --aggregate --output=decision.json
          echo "::set-output name=decision::$(cat decision.json | jq -r '.decision')"
      
      - name: Block Release if DENY
        if: steps.decision.outputs.decision == 'DENY'
        run: |
          echo "Release blocked by gate"
          exit 1
      
      - name: Deploy
        if: steps.decision.outputs.decision == 'ALLOW'
        run: |
          ./deploy.sh
```

---

## 10. 数据模型与Schema定义

### 10.1 门禁配置Schema

```yaml
gate_config:
  version: "v1"
  levels:
    - name: "smoke"
      description: "冒烟测试门禁"
      type: "HARD"
      timeout: 300  # 5分钟
      dataset:
        source: "golden_dataset"
        filter: "smoke_critical == true"
        size: 15
      pass_criteria:
        pass_rate: 1.0  # 100%通过
        
    - name: "regression"
      description: "回归测试门禁"
      type: "MIXED"  # 软硬混合
      timeout: 1200  # 20分钟
      dataset:
        source: "golden_dataset"
        strategy: "trajectory_aware_subset"
        coverage_target: 0.95
      pass_criteria:
        by_provenance:
          REAL_OWN_REPO:
            pass_rate: 0.95
            avg_score: 0.90
            gate_type: "HARD"
          REAL_EXTERNAL:
            pass_rate: 0.90
            avg_score: 0.85
            gate_type: "HARD"
          SYNTH_PROPERTY:
            pass_rate: 0.85
            avg_score: 0.80
            gate_type: "SOFT"
          SYNTH_ADVERSARIAL:
            pass_rate: 0.80
            avg_score: 0.75
            gate_type: "HARD"
          SYNTH_STRESS:
            pass_rate: 0.75
            avg_score: 0.70
            gate_type: "SOFT"
            
    - name: "performance"
      description: "性能基准门禁"
      type: "SOFT"
      timeout: 120  # 2分钟
      metrics:
        - name: "latency_p95"
          threshold: 1.2  # 不退化超过20%
        - name: "token_usage"
          threshold: 1.2
        - name: "cost_per_request"
          threshold: 1.1  # 成本控制在10%以内
          
    - name: "security"
      description: "安全扫描门禁"
      type: "MIXED"
      timeout: 300  # 5分钟
      scanners:
        - name: "secret_scan"
          type: "HARD"
          allowed_critical: 0
          allowed_high: 0
        - name: "dependency_scan"
          type: "HARD"
          allowed_critical: 0
          allowed_high: 2
        - name: "code_quality"
          type: "SOFT"
          threshold: "B+"
```

### 10.2 门禁决策结果Schema

```json
{
  "decision_id": "dec_20261005_173042_a3f2e8",
  "timestamp": "2026-10-05T17:30:42Z",
  "release_version": "v2.3.5",
  "baseline_version": "v2.3.4",
  "decision": "ALLOW",
  "gate_results": [
    {
      "level": "smoke",
      "status": "PASS",
      "pass_rate": 1.0,
      "execution_time": 287
    },
    {
      "level": "regression",
      "status": "PASS",
      "pass_rate_by_provenance": {
        "REAL_OWN_REPO": 0.97,
        "REAL_EXTERNAL": 0.92,
        "SYNTH_PROPERTY": 0.88,
        "SYNTH_ADVERSARIAL": 0.83,
        "SYNTH_STRESS": 0.78
      },
      "regression_signals": [],
      "execution_time": 1134
    },
    {
      "level": "performance",
      "status": "PASS",
      "metrics": {
        "latency_p95": {"current": 450, "baseline": 420, "delta_pct": 7.1},
        "token_usage": {"current": 3200, "baseline": 3100, "delta_pct": 3.2},
        "cost_per_request": {"current": 0.012, "baseline": 0.011, "delta_pct": 9.1}
      },
      "execution_time": 98
    },
    {
      "level": "security",
      "status": "PASS",
      "findings": {
        "secret_scan": {"critical": 0, "high": 0, "medium": 1},
        "dependency_scan": {"critical": 0, "high": 1, "medium": 3}
      },
      "execution_time": 267
    }
  ],
  "total_execution_time": 1786,
  "approvals": [],
  "audit_url": "https://gate-audit.company.com/dec_20261005_173042_a3f2e8"
}
```

---

## 11. 可观测性与监控

### 11.1 门禁执行仪表盘

| 监控指标 | 说明 | 告警阈值 |
|---------|------|---------|
| **门禁通过率** | 按Level统计通过率 | Level 1 < 95% |
| **执行时长** | 各Level执行耗时 | > SLA 1.5倍 |
| **误报率** | 阻断但人工判定无问题 | > 5% |
| **漏报率** | 通过但发布后发现问题 | > 1% |
| **Break-Glass使用率** | Override决策占比 | > 2% |
| **回滚触发率** | 自动回滚执行次数 | > 5%/周 |

### 11.2 决策可追溯性

每个决策生成详细报告，包含：
- 门禁执行时间线
- 各Level详细结果
- 回归信号分析
- 失败任务清单
- 审批链路（如适用）
- 回滚建议

### 11.3 质量趋势分析

跟踪长期趋势：
- 门禁通过率趋势图（按周/月）
- 回归检出率热力图（按血缘类型）
- 例外申请趋势
- Break-Glass使用频率

---

## 12. 验收标准

### 12.1 功能验收

| 验收项 | 标准 | 验证方法 |
|-------|------|---------|
| **四级门禁体系** | Level 1-4全部实现 | 执行完整门禁流水线 |
| **软硬门禁区分** | HARD阻断、SOFT告警 | 注入失败，验证阻断行为 |
| **血缘感知阈值** | 5类血缘差异化配置生效 | 检查配置文件和执行日志 |
| **回归检测** | 三维度检测（通过率+评分+轨迹） | 回归场景测试 |
| **例外机制** | 申请-审批-执行完整闭环 | 端到端测试 |
| **Break-Glass** | Quorum审批、审计追踪 | 模拟紧急发布 |
| **自动回滚** | 4类触发器生效 | 注入故障，验证回滚 |
| **CI/CD集成** | GitHub Actions集成 | 真实PR触发 |

### 12.2 性能验收

| 指标 | 目标 | 实际值 |
|------|------|-------|
| Level 1执行时长 | < 5分钟 | _待测试_ |
| Level 2执行时长 | < 20分钟 | _待测试_ |
| Level 3执行时长 | < 2分钟 | _待测试_ |
| Level 4执行时长 | < 5分钟 | _待测试_ |
| 总执行时长 | < 30分钟 | _待测试_ |

### 12.3 准确性验收

| 指标 | 目标 | 实际值 |
|------|------|-------|
| 回归检出率 | ≥ 90% | _待测试_ |
| 误报率 | ≤ 5% | _待测试_ |
| 漏报率 | ≤ 1% | _待测试_ |

---

## 13. 跨模块依赖

### 13.1 依赖输入

| 模块 | 需求编号 | 依赖内容 |
|------|---------|---------|
| Golden Dataset | REQ-EVA-001 | 血缘标注、分层数据集 |
| 自动评分器 | REQ-EVA-003 | 评分结果、置信度 |
| 失败归因 | REQ-EVA-004 | 失败根因分析 |
| 回归测试 | REQ-EVA-005 | 回归报告、轨迹感知子集 |
| 安全模块 | REQ-SEC-001 | Kill Switch状态 |
| 审计保留 | REQ-RT-008 | 审计日志写入接口 |

### 13.2 依赖输出

| 下游模块 | 输出内容 |
|---------|---------|
| 发布系统 | 门禁决策（ALLOW/DENY/CONDITIONAL/OVERRIDE） |
| 监控告警 | 门禁失败通知、回滚事件 |
| 数据分析 | 门禁执行日志、决策审计 |
| 质量度量 | 发布质量指标、回归趋势 |

---

## 14. 实施计划

### 14.1 里程碑

| 阶段 | 交付物 | 时间 |
|------|--------|------|
| **M1: 基础门禁** | Level 1冒烟测试 + Level 2回归测试 | 2周 |
| **M2: 完整流水线** | Level 3性能 + Level 4安全 | 1周 |
| **M3: 例外机制** | 例外申请流程 + Break-Glass | 1周 |
| **M4: 自动回滚** | 回滚触发器 + CI/CD集成 | 1周 |
| **M5: 可观测性** | 仪表盘 + 审计追踪 | 1周 |

### 14.2 风险缓解

| 风险 | 缓解措施 |
|------|---------|
| 门禁执行超时 | 轨迹感知子集、并行执行 |
| 误报率高 | 2周缓冲期、逐步收紧阈值 |
| Break-Glass滥用 | 强审计、季度复盘 |
| 回滚失败 | 金丝雀发布、状态快照 |

---

## 15. 合规性与审计

### 15.1 合规要求

| 合规项 | 要求 | 实现 |
|-------|------|------|
| **决策可追溯** | 所有决策留存≥1年 | 审计日志持久化至REQ-RT-008 |
| **例外审批** | 权限分级、审批链完整 | Quorum审批、多级审批流 |
| **Break-Glass审计** | 72h内强制复盘 | 自动生成审计报告、定时提醒 |
| **数据隐私** | 评估数据脱敏 | PII自动检测、字段级加密 |

### 15.2 审计日志保留

| 日志类型 | 保留期 | 归档策略 |
|---------|-------|---------|
| 门禁决策日志 | 1年 | 冷存储归档 |
| 例外审批记录 | 3年 | 合规归档 |
| Break-Glass事件 | 5年 | 永久归档 |
| 回滚事件 | 1年 | 冷存储归档 |

---

## 16. 参考文献与标杆

1. **Cursor 评估系统设计**（`REQ-EVA-005 §二.1`）：软硬门禁分离、失败产物记录
2. **SWE-bench Verified**（`REQ-EVA-001 §二.2`）：血缘感知阈值、统计显著性检验
3. **OpenAI Codex Safety**（`REQ-EVA-005 §二.1`）：三层管道分层阻断
4. **DeepSeek 轨迹感知评估**（`REQ-EVA-005 §二.1`）：容器隔离、ATIF轨迹
5. **Kimi K3 Rubric评分**（`REQ-EVA-005 §二.1`）：per-criterion评分、成本测量

---

## 17. 附录：术语表

| 术语 | 定义 |
|------|------|
| **硬门禁** | 必须通过才能发布，失败阻断发布流程 |
| **软门禁** | 失败告警但不阻断发布，记录到审计日志 |
| **血缘感知阈值** | 根据评估样本血缘类型（真实/合成、内部/外部）差异化配置通过标准 |
| **回归检测** | 对比当前版本与基线版本，检测性能/准确性退化 |
| **Break-Glass** | 紧急发布通道，需Quorum审批、强审计追踪 |
| **Quorum审批** | 至少N人（含特定角色）共同审批 |
| **轨迹感知子集** | 根据执行轨迹相似度选择代表性子集，节省评估成本 |
| **CONDITIONAL决策** | 例外审批通过，有条件允许发布 |
| **OVERRIDE决策** | Break-Glass紧急通道，绕过门禁发布 |

---

**文档版本**: v0.1-designed  
**最后更新**: 2026-10-05  
**维护负责人**: 评估系统团队  
**审核状态**: 待技术评审