# REQ-EVA-007 生产反馈、数据集更新和版本回滚详细设计

> 所属基线：`Evaluation and Release Gate Baseline v1.0`  
> 需求编号：`REQ-EVA-007`  
> 优先级：P0  
> 设计版本：`v1.0-designed`  
> 设计状态：详细设计已完成  
> 设计日期：2026-10-08  
> 依赖前置：`REQ-EVA-001`（已完成）、`REQ-EVA-005`（已完成）、`REQ-EVA-006`（已完成）、`REQ-OBS-002`（已完成）、`REQ-SEC-009`（已完成）、`REQ-REL-001`（已完成）  
> 依赖后置：持续改进、生产运维

---

## 1. 需求定义

### 1.1 核心职责（收窄后的范围）

补齐"评估模块主动发起、面向生产态漂移的回滚触发路径"，具体包括：

1. **漂移检测**：监控生产环境中Agent性能的统计显著性变化
2. **回滚触发**：当检测到漂移时，生成触发器并对接 REQ-EVA-006 发布门禁
3. **反馈闭环**：将生产失败案例反哺到 REQ-EVA-001 Golden Dataset
4. **版本协调**：管理模型版本、Prompt版本、Worker逻辑版本、评估集版本的回滚

### 1.2 设计边界明确

**本需求包含**：
- 漂移检测器（Drift Detector）
- 回滚决策引擎（Rollback Decision Engine）
- 生产反馈采集器（Production Feedback Collector）
- 版本回滚协调器（Version Rollback Coordinator）
- 与 REQ-EVA-006 的触发器集成

**本需求不包含**（已有其他 REQ 覆盖）：

| 内容 | 归属需求 |
|------|----------|
| 基础可观测性采集（Trace、Event、Metrics） | REQ-OBS-001/002/003 |
| Kill Switch 机制（M0-M5 六模式） | REQ-SEC-009 |
| 回归流水线基础设施 | REQ-EVA-005 |
| 发布门禁执行逻辑 | REQ-EVA-006 |
| Golden Dataset 构建 | REQ-EVA-001 |
| 失败分类体系 | REQ-REL-001 |

### 1.3 用户价值

| 使用方 | 价值 |
|-------|------|
| ML工程师 | 生产漂移自动检测，无需人工巡检 |
| 发布经理 | 数据驱动的回滚决策，减少主观判断 |
| 评估工程师 | 生产失败自动反哺评估集，持续改进 |
| SRE工程师 | 版本回滚协调，减少手工操作 |

---

## 2. 行业调研与标杆对齐

### 2.1 业界实践汇总

| 标杆产品 | 核心设计 | 可借鉴点 | 来源 |
|---------|---------|---------|------|
| **Anthropic** | Post-launch monitoring检测分布漂移；Capability eval毕业为Regression suite | 生产监控与预发布评估分离；评估集动态演进 | 《Demystifying evals for AI agents》2026-01-09 |
| **OpenAI Codex** | 生产Trace回放用于离线评估；失败案例自动入库 | 生产数据反哺评估 | Evals文档 |
| **MLflow** | Model Registry版本管理；Stage-based promotion | 版本Bundle管理；回滚前置条件 | MLflow Registry文档 |
| **SWE-bench** | 任务exposure_count管理；高通过率任务转为回归集 | 评估集老化检测 | REQ-EVA-001 §6.2 |
| **DeepSeek** | 生产环境容器化评估；ATIF轨迹标准 | 生产与评估环境对齐 | REQ-EVA-005 §8.1 |

### 2.2 关键设计原则

1. **时间窗口分层**：短期（发布后1h）由REQ-EVA-006覆盖，中长期（数周）由本需求覆盖
2. **非侵入式采集**：复用REQ-OBS-002审计事件，避免新增采集基础设施
3. **统计显著性检验**：避免随机波动导致的误报
4. **版本Bundle管理**：模型+评估集+评分器+Worker逻辑统一版本化

---

## 3. 设计边界

### 3.1 本需求与REQ-EVA-006的职责划分

**时间窗口划分**（关键边界）：

| 检测窗口 | 负责模块 | 触发器类型 | 典型场景 |
|---------|---------|-----------|---------|
| 发布后1小时内 | REQ-EVA-006 | 发布后回归检测 | 新版本引入的立即可见问题 |
| 发布后5分钟内 | REQ-EVA-006 | 告警聚合 | 配置错误、资源耗尽 |
| 连续3次健康检查 | REQ-EVA-006 | 健康检查失败 | 服务不可用 |
| 人工触发 | REQ-EVA-006 | Kill Switch | 紧急事件人工介入 |
| **数周~数月持续监控** | **REQ-EVA-007（本需求）** | **生产漂移检测** | **模型供应商静默更新、数据分布变化、评估集老化** |

**职责边界澄清**：
- REQ-EVA-006专注"发布质量门禁"（pre-release + immediate post-release）
- REQ-EVA-007专注"生产态持续监控"（long-term post-launch）
- 两者通过统一的触发器接口集成（扩展DriftTrigger）

### 3.2 本需求与REQ-OBS-*的集成方式

**复用原则**：
- 生产失败案例从 REQ-OBS-002 审计事件流中采集，不新增专用采集器
- 漂移检测指标从 REQ-OBS-003 指标字典中读取 `gen_ai.evaluation.result`
- 告警联动复用 REQ-OBS-005 告警-Kill Switch 映射机制

---

## 4. 核心架构：三层闭环

### 4.1 架构全景

```
┌─────────────────────────────────────────────────────────────────┐
│ Layer 1: 漂移检测层（Drift Detection Layer）                      │
│                                                                   │
│ 输入：生产Trace（REQ-OBS-002）+ Regression Eval结果（REQ-EVA-005）│
│ 检测维度：                                                         │
│   - 模型行为漂移（同Prompt不同输出分布）                          │
│   - Regression eval分数下降趋势（滚动窗口统计显著性）             │
│   - 任务成功率突降（对比基线）                                     │
│   - 评估集老化（exposure_count触顶）                              │
│ 输出：DriftEvent（严重度P0/P1/P2、影响面、疑似根因）              │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Layer 2: 回滚决策层（Rollback Decision Layer）                    │
│                                                                   │
│ 输入：DriftEvent + 当前发布状态 + Error Budget余额                │
│ 决策逻辑：                                                         │
│   - P0漂移（Regression下降>10% 或成功率<50%）→ 立即全量回滚      │
│   - P1漂移（Regression下降5-10%）→ 停止扩量+人工审批              │
│   - P2漂移（边缘指标异常）→ 告警+观察                             │
│ 输出：RollbackDecision + DriftTrigger（发送给REQ-EVA-006）       │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Layer 3: 反馈闭环层（Feedback Loop Layer）                        │
│                                                                   │
│ 输入：生产失败案例（REQ-OBS-002）+ 人工标记                       │
│ 采集流程：                                                         │
│   1. 失败根因分类（复用REQ-REL-001）                              │
│   2. 去重检查（与Golden Dataset现有案例相似度>85%跳过）           │
│   3. 入集审批（通过REQ-EVA-001闸门）                              │
│   4. Dataset版本更新（Capability→Regression转换）                │
│ 输出：候选评估案例 → Golden Dataset v(n+1)                        │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 三层协同关系

| 层级 | 触发条件 | 响应时间 | 人工介入 |
|------|---------|---------|---------|
| Layer 1 | 每日自动运行 | 15分钟内产出漂移报告 | 无（自动） |
| Layer 2 | Layer 1检测到P0/P1漂移 | 5分钟内发送触发器 | P1需人工审批 |
| Layer 3 | 任务失败或人工标记 | 24小时内完成入集审批 | 需人工审核 |

---

## 5. 漂移检测器（Drift Detector）设计

### 5.1 四维漂移检测

**检测维度**（按检测难度排序）：

| 维度 | 检测方法 | 数据源 | 检出延迟 | 误报率目标 |
|------|---------|-------|---------|-----------|
| **任务成功率突降** | 滚动窗口均值对比 | REQ-OBS-002事件流 | 1小时 | ≤5% |
| **Regression eval分数下降** | 统计显著性检验 | REQ-EVA-005回归报告 | 1天 | ≤10% |
| **模型行为漂移** | 轨迹embedding余弦相似度 | REQ-EVA-005 ATIF轨迹 | 3天 | ≤15% |
| **评估集老化** | exposure_count阈值检测 | REQ-EVA-001 Dataset元数据 | 7天 | 0%（确定性） |

### 5.2 检测算法详细设计

#### 5.2.1 任务成功率突降检测

```python
def detect_success_rate_drop(time_window_hours=24):
    """
    检测生产任务成功率相对基线的突降
    
    Returns:
        DriftSignal or None
    """
    # 步骤1：加载基线成功率（最近30天平均）
    baseline_success_rate = load_baseline_metric(
        metric_name="task.success_rate",
        time_window_days=30
    )
    
    # 步骤2：计算当前窗口成功率
    current_success_rate = compute_success_rate(
        time_window_hours=time_window_hours
    )
    
    # 步骤3：统计显著性检验（Chi-square）
    chi2_stat, p_value = chi_square_test(
        baseline_count=(baseline_success_rate * baseline_total),
        current_count=(current_success_rate * current_total)
    )
    
    # 步骤4：效应量计算
    absolute_drop = baseline_success_rate - current_success_rate
    relative_drop = absolute_drop / baseline_success_rate
    
    # 步骤5：判定逻辑
    if p_value < 0.05 and absolute_drop > 0.05:  # 统计显著且绝对下降>5%
        severity = "P0" if current_success_rate < 0.50 else "P1"
        return DriftSignal(
            drift_dimension="task_success_rate",
            severity=severity,
            baseline_value=baseline_success_rate,
            current_value=current_success_rate,
            degradation_pct=relative_drop * 100,
            p_value=p_value,
            evidence_trace_ids=sample_failed_trace_ids(limit=10)
        )
    
    return None
```

#### 5.2.2 Regression Eval分数下降检测

```python
def detect_regression_eval_degradation():
    """
    检测Regression eval分数相对上一版本的下降
    
    Returns:
        DriftSignal or None
    """
    # 步骤1：加载最近两次regression eval结果
    latest_eval = load_latest_regression_eval()
    previous_eval = load_previous_regression_eval()
    
    # 步骤2：按血缘类型分组对比
    drift_signals = []
    
    for lineage in [REAL_OWN_REPO, REAL_EXTERNAL, SYNTH_ADVERSARIAL]:
        latest_scores = latest_eval.scores_by_lineage[lineage]
        previous_scores = previous_eval.scores_by_lineage[lineage]
        
        # Wilcoxon rank-sum检验
        statistic, p_value = wilcoxon_ranksum(latest_scores, previous_scores)
        
        # 中位数变化
        median_drop = median(previous_scores) - median(latest_scores)
        relative_drop = median_drop / median(previous_scores)
        
        if p_value < 0.05 and median_drop > 0.05:
            severity = "P0" if relative_drop > 0.10 else "P1"
            drift_signals.append(DriftSignal(
                drift_dimension="regression_eval",
                severity=severity,
                affected_lineage=[lineage],
                baseline_value=median(previous_scores),
                current_value=median(latest_scores),
                degradation_pct=relative_drop * 100,
                p_value=p_value
            ))
    
    return drift_signals if drift_signals else None
```

#### 5.2.3 模型行为漂移检测

```python
def detect_model_behavior_drift():
    """
    检测模型在相同输入下的输出分布变化（轨迹级）
    
    Returns:
        DriftSignal or None
    """
    # 步骤1：选取锚定任务集（固定输入的代表性任务）
    anchor_tasks = load_anchor_task_set(size=50)
    
    # 步骤2：对比最近两周的轨迹
    baseline_trajectories = load_trajectories(
        task_ids=anchor_tasks,
        time_range=(-28, -14)  # 4周前到2周前
    )
    
    current_trajectories = load_trajectories(
        task_ids=anchor_tasks,
        time_range=(-14, 0)   # 最近2周
    )
    
    # 步骤3：轨迹embedding
    baseline_emb = embed_trajectories(baseline_trajectories)
    current_emb = embed_trajectories(current_trajectories)
    
    # 步骤4：余弦相似度
    similarity = cosine_similarity(
        aggregate_embedding(baseline_emb),
        aggregate_embedding(current_emb)
    )
    
    # 步骤5：判定逻辑
    if similarity < 0.85:
        severity = "P1" if similarity < 0.75 else "P2"
        return DriftSignal(
            drift_dimension="model_behavior",
            severity=severity,
            metric_name="trajectory_similarity",
            baseline_value=1.0,  # 完全相似基准
            current_value=similarity,
            degradation_pct=(1.0 - similarity) * 100,
            suspected_cause="model_provider_update"
        )
    
    return None
```

#### 5.2.4 评估集老化检测

```python
def detect_dataset_staleness():
    """
    检测Golden Dataset中任务的exposure_count过高（污染风险）
    
    Returns:
        DriftSignal or None
    """
    dataset = load_golden_dataset()
    
    # 按REQ-EVA-001 §6.2规则：exposure_count ≥ 3 自动降级
    stale_tasks = [
        task for task in dataset.tasks
        if task.exposure_count >= 3 and task.status == "ACTIVE"
    ]
    
    if len(stale_tasks) / len(dataset.tasks) > 0.20:  # 超过20%任务老化
        return DriftSignal(
            drift_dimension="eval_dataset_staleness",
            severity="P1",
            metric_name="stale_task_ratio",
            baseline_value=0.0,
            current_value=len(stale_tasks) / len(dataset.tasks),
            degradation_pct=(len(stale_tasks) / len(dataset.tasks)) * 100,
            suspected_cause="dataset_overexposure",
            recommended_action="refresh_golden_dataset"
        )
    
    return None
```

### 5.3 漂移报告Schema

```typescript
interface DriftSignal {
  // 基本信息
  signal_id: string;
  detected_at: timestamp;
  drift_dimension: "task_success_rate" | "regression_eval" | 
                   "model_behavior" | "eval_dataset_staleness";
  severity: "P0" | "P1" | "P2";
  
  // 度量值
  metric_name: string;
  baseline_value: number;
  current_value: number;
  degradation_pct: number;  // 劣化百分比
  
  // 统计显著性（如适用）
  p_value?: number;
  confidence_level?: number;
  
  // 影响面
  affected_task_types?: string[];
  affected_lineage?: LineageType[];
  
  // 诊断
  suspected_cause?: string;
  evidence_trace_ids?: string[];
  recommended_action?: string;
}

interface DriftReport {
  report_id: string;
  generated_at: timestamp;
  evaluation_window: {start: timestamp, end: timestamp};
  
  // 检测结果
  drift_signals: DriftSignal[];
  overall_verdict: "STABLE" | "DRIFTING" | "CRITICAL_DRIFT";
  
  // 汇总统计
  total_tasks_evaluated: number;
  success_rate_trend: number[];  // 最近30天趋势
  regression_score_trend: number[];
  
  // 推荐动作
  recommended_actions: RecommendedAction[];
}
```

---

## 6. 回滚决策引擎（Rollback Decision Engine）设计

### 6.1 决策输入与输出

**输入**：
1. DriftReport（漂移检测结果）
2. 当前发布状态（金丝雀比例、已运行时长）
3. Error Budget余额（注意：REQ-EVA-006 当前未定义 Error Budget 机制，本需求暂行定义，待协同确认，见 §16.1）
4. 历史回滚记录（避免振荡）

**输出**：
1. RollbackDecision（ROLLBACK / HOLD / ALERT）
2. DriftTrigger（发送给REQ-EVA-006）

### 6.2 决策矩阵

| 漂移严重度 | Regression下降 | 成功率 | Error Budget | 决策 | 触发动作 |
|-----------|---------------|-------|-------------|------|---------|
| P0 | >10% | 任意 | 任意 | **ROLLBACK** | 立即全量回滚（先自动执行，事后补 VP 审批） |
| P1 | 5-10% | ≥80% | ≥50% | **HOLD** | 告警+观察7天 |
| P1 | 5-10% | ≥80% | <50% | **CONDITIONAL** | 停止扩量+人工审批 |
| P2 | <5% | ≥90% | 任意 | **ALERT** | 仅告警，不干预 |

### 6.3 决策算法

```python
def decide_rollback(drift_report: DriftReport, 
                   release_state: ReleaseState,
                   error_budget: ErrorBudget) -> RollbackDecision:
    """
    基于多维度评分做出回滚决策
    
    核心原则：P0 漂移立即自动回滚（先执行后补审批），P1/P2 分级处理
    
    Returns:
        RollbackDecision
    """
    # 步骤1：提取关键信号
    p0_signals = [s for s in drift_report.drift_signals if s.severity == "P0"]
    p1_signals = [s for s in drift_report.drift_signals if s.severity == "P1"]
    
    # 步骤2：P0 信号 → 立即回滚（无条件，先执行后补审批）
    if p0_signals:
        return RollbackDecision(
            decision="ROLLBACK",
            reason="P0_DRIFT_AUTO_ROLLBACK",
            rationale=f"检测到 {len(p0_signals)} 个 P0 漂移信号，自动触发回滚。事后需 VP 补审批。",
            drift_signals=p0_signals,
            target_version=release_state.previous_stable_version,
            urgency="IMMEDIATE",
            auto_approved=True,  # 自动执行
            requires_post_approval=True,  # 事后补审批
            approval_deadline=now() + timedelta(hours=4)  # 4小时内补审批
        )
    
    # 步骤3：P1 信号 → 根据 Error Budget 决策
    if p1_signals and error_budget.remaining_pct < 0.50:
        # P1漂移 + Error Budget紧张 → 停止扩量+人工审批
        return RollbackDecision(
            decision="CONDITIONAL",
            reason="moderate_drift_with_constrained_budget",
            drift_signals=p1_signals,
            required_approval="tech_lead",
            hold_duration_hours=24
        )
    
    if p1_signals:
        # P1漂移但Budget充足 → 告警+观察
        return RollbackDecision(
            decision="HOLD",
            reason="moderate_drift_monitor",
            drift_signals=p1_signals,
            observation_window_days=7
        )
    
    # 无严重漂移 → 仅告警
    return RollbackDecision(
        decision="ALERT",
        reason="minor_drift_or_stable",
        drift_signals=drift_report.drift_signals
    )


def compute_drift_score(drift_report: DriftReport) -> float:
    """
    计算综合漂移评分（0-100）
    
    评分维度：
    - 成功率下降：40%权重
    - Regression eval下降：30%权重
    - 轨迹相似度下降：20%权重
    - 评估集老化：10%权重
    """
    score = 0.0
    
    # 维度1：成功率
    if drift_report.success_rate_drop:
        score += 40 * drift_report.success_rate_drop.degradation_pct / 100
    
    # 维度2：Regression eval
    regression_signals = [s for s in drift_report.drift_signals 
                         if s.drift_dimension == "regression_eval"]
    if regression_signals:
        max_regression_drop = max([s.degradation_pct for s in regression_signals])
        score += 30 * max_regression_drop / 100
    
    # 维度3：轨迹相似度
    behavior_signals = [s for s in drift_report.drift_signals 
                       if s.drift_dimension == "model_behavior"]
    if behavior_signals:
        similarity = behavior_signals[0].current_value
        score += 20 * (1.0 - similarity)
    
    # 维度4：评估集老化
    staleness_signals = [s for s in drift_report.drift_signals 
                        if s.drift_dimension == "eval_dataset_staleness"]
    if staleness_signals:
        stale_ratio = staleness_signals[0].current_value
        score += 10 * stale_ratio
    
    return min(score, 100.0)
```

### 6.4 DriftTrigger Schema（对接REQ-EVA-006）

```typescript
// 扩展REQ-EVA-006的触发器类型
// 注：REQ-EVA-006 未定义统一的触发器基类型，其4类触发器仅以表格和伪代码描述，字段待协同确认
interface DriftTrigger {
  trigger_type: "drift_detected";  // 新增第5类触发器
  
  // 漂移特有字段
  drift_dimension: "model_behavior" | "regression_eval" | 
                   "task_success_rate" | "eval_dataset_staleness";
  severity: "P0" | "P1" | "P2";
  
  // 度量值（与REQ-EVA-006 §9.2兼容）
  metric_name: string;
  baseline_value: number;
  current_value: number;
  degradation_pct: number;
  
  // 影响面
  affected_task_types: string[];
  affected_lineage?: LineageType[];
  
  // 证据
  suspected_cause: string;
  evidence_trace_ids: string[];
  
  // 推荐动作
  recommended_action: "rollback" | "hold" | "alert";
  target_version?: string;  // 回滚目标版本
}
```

### 6.5 回滚决策Schema

```typescript
interface RollbackDecision {
  decision_id: string;
  timestamp: timestamp;
  
  // 决策结果
  decision: "ROLLBACK" | "CONDITIONAL" | "HOLD" | "ALERT";
  reason: string;
  urgency?: "IMMEDIATE" | "SCHEDULED";
  
  // 输入信号
  drift_signals: DriftSignal[];
  drift_score: number;  // 0-100综合评分
  
  // 回滚目标（如适用）
  target_version?: string;
  rollback_scope?: "model" | "prompt" | "worker_logic" | "eval_dataset" | "bundle";
  
  // 人工审批（如适用）
  required_approval?: "tech_lead" | "quality_committee" | "vp_engineering";
  hold_duration_hours?: number;
  observation_window_days?: number;
  
  // 审计
  triggered_by: "automated_drift_detection" | "manual_override";
  approved_by?: actor_id;
  approved_at?: timestamp;
}
```

---

## 7. 生产反馈采集器（Production Feedback Collector）设计

### 7.1 采集触发条件

**三类触发源**：

| 触发源 | 条件 | 数据来源 | 优先级 |
|-------|------|---------|-------|
| **任务失败事件** | Task状态迁移至FAILED（REQ-RT-002） | REQ-OBS-002审计事件流 | P0 |
| **人工标记** | 用户/审查者标记为"错误行为" | Web控制台/API | P1 |
| **审批拒绝** | Worker Action被Policy Gateway拒绝且理由为"业务逻辑错误" | REQ-SEC-003决策日志 | P2 |

### 7.2 入集闸门（四道门）

**对接REQ-EVA-001 §5入集闸门标准**，额外增加生产场景专属检查：

```python
def production_feedback_gate_check(failed_case: FailedTaskCase) -> GateCheckResult:
    """
    生产失败案例入集闸门（四道门）
    
    Returns:
        GateCheckResult (PASS / FAIL / NEEDS_REVIEW)
    """
    # 闸门1：新颖性检查
    novelty_check = check_novelty(failed_case)
    if not novelty_check.is_novel:
        return GateCheckResult(
            gate="novelty",
            status="FAIL",
            reason=f"与已有案例相似度{novelty_check.similarity:.2%} > 85%"
        )
    
    # 闸门2：可复现性检查
    reproducibility_check = check_reproducibility(failed_case)
    if not reproducibility_check.is_reproducible:
        return GateCheckResult(
            gate="reproducibility",
            status="FAIL",
            reason="轨迹回放失败，无法复现"
        )
    
    # 闸门3：Oracle可判定性检查
    oracle_check = check_oracle_validity(failed_case)
    if not oracle_check.has_valid_oracle:
        return GateCheckResult(
            gate="oracle_validity",
            status="NEEDS_REVIEW",
            reason="缺少自动化Oracle，需人工审核"
        )
    
    # 闸门4：污染检查
    contamination_check = check_contamination(failed_case)
    if contamination_check.is_contaminated:
        return GateCheckResult(
            gate="contamination",
            status="FAIL",
            reason=f"训练数据污染：{contamination_check.contamination_source}"
        )
    
    # 全部通过
    return GateCheckResult(
        gate="all",
        status="PASS",
        recommended_lineage=infer_lineage_type(failed_case)
    )


def check_novelty(failed_case: FailedTaskCase) -> NoveltyCheckResult:
    """
    检查失败案例是否与Golden Dataset中已有案例重复
    """
    dataset = load_golden_dataset()
    
    # 特征提取
    case_features = extract_features(failed_case)
    
    # 与每个已有案例计算相似度
    similarities = []
    for existing_task in dataset.tasks:
        existing_features = extract_features(existing_task)
        sim = cosine_similarity(case_features, existing_features)
        similarities.append((existing_task.task_id, sim))
    
    # 最高相似度
    max_similarity = max([s[1] for s in similarities])
    
    return NoveltyCheckResult(
        is_novel=(max_similarity < 0.85),
        similarity=max_similarity,
        most_similar_task_id=similarities[0][0] if similarities else None
    )


def check_reproducibility(failed_case: FailedTaskCase) -> ReproducibilityCheckResult:
    """
    检查失败案例是否可复现
    """
    # 加载原始轨迹
    original_trajectory = load_trajectory(failed_case.trajectory_id)
    
    # 执行回放（REQ-EVA-005 §8.2轨迹回放流程）
    replay_result = replay_trajectory(original_trajectory)
    
    # 对比最终状态
    is_reproducible = (
        replay_result.final_state.status == original_trajectory.final_state.status
        and replay_result.reproducibility == True
    )
    
    return ReproducibilityCheckResult(
        is_reproducible=is_reproducible,
        replay_result=replay_result
    )
```

### 7.3 采集流程

```
生产失败事件
    │
    ▼
[触发源识别] 任务失败/人工标记/审批拒绝
    │
    ▼
[失败根因分类] 复用REQ-REL-001失败分类体系
    │  ├─ 模型能力不足 → 候选入集
    │  ├─ 工具调用失败 → 归档，不入集
    │  ├─ Policy拒绝 → 归档，不入集
    │  └─ 未知失败 → 人工审核
    │
    ▼
[去重检查] 与Golden Dataset相似度 < 85%
    │  ├─ 重复 → 归档，不入集
    │  └─ 新颖 → 继续
    │
    ▼
[四道闸门检查]
    │  ├─ 新颖性 FAIL → 归档
    │  ├─ 可复现性 FAIL → 归档
    │  ├─ Oracle可判定性 FAIL → 人工审核
    │  └─ 污染检查 FAIL → 归档
    │
    ▼
[入集审批] 人工审核（评估工程师）
    │  ├─ 批准 → PENDING_ANNOTATION
    │  └─ 拒绝 → 归档
    │
    ▼
[标注与验证] 按REQ-EVA-002标注规范
    │
    ▼
[版本更新] 进入Golden Dataset v(n+1)
```

### 7.4 PII脱敏与数据安全

**脱敏规则**（对齐REQ-OBS-004 §3）：

```python
def sanitize_failed_case(failed_case: FailedTaskCase) -> SanitizedCase:
    """
    对生产失败案例进行PII脱敏
    """
    sanitized = failed_case.copy()
    
    # 1. 移除直接PII
    sanitized.user_id = hash_with_salt(failed_case.user_id)
    sanitized.organization_id = hash_with_salt(failed_case.organization_id)
    
    # 2. 代码/文件内容脱敏
    sanitized.code_snapshot = redact_secrets(failed_case.code_snapshot)
    sanitized.code_snapshot = replace_proprietary_names(sanitized.code_snapshot)
    
    # 3. 轨迹脱敏
    sanitized.trajectory = sanitize_trajectory(
        failed_case.trajectory,
        redact_rules=[
            "email_addresses",
            "api_keys",
            "internal_hostnames",
            "proprietary_identifiers"
        ]
    )
    
    # 4. 添加脱敏审计记录
    sanitized.sanitization_log = {
        "sanitized_at": now(),
        "sanitized_by": "automated_pipeline",
        "redaction_count": count_redactions(sanitized)
    }
    
    return sanitized
```

---

## 8. 版本回滚协调器（Version Rollback Coordinator）设计

### 8.1 版本Bundle管理

**Bundle定义**：模型版本、评估集版本、评分器版本、Worker逻辑版本的统一快照。

```typescript
interface VersionBundle {
  bundle_id: string;
  bundle_version: string;  // semantic version: major.minor.patch
  created_at: timestamp;
  created_by: actor_id;
  
  // 组件版本
  components: {
    model_version: ModelVersion;
    eval_dataset_version: DatasetVersion;
    grader_version: GraderVersion;
    worker_logic_version: WorkerLogicVersion;
  };
  
  // 状态
  status: "ACTIVE" | "DEPRECATED" | "ARCHIVED";
  stability: "STABLE" | "CANARY" | "UNSTABLE";
  
  // 元数据
  baseline_metrics: BaselineMetrics;
  compatibility_matrix: CompatibilityMatrix;
  rollback_constraints: RollbackConstraints;
}

interface ModelVersion {
  provider: "openai" | "anthropic" | "deepseek";
  model_id: string;  // "gpt-4o-2024-08-06"
  snapshot_date: timestamp;
  capabilities: string[];
}

interface DatasetVersion {
  dataset_id: string;
  version: string;  // "v2.3.0"
  task_count: number;
  lineage_distribution: Map<LineageType, number>;
  frozen_at: timestamp;
}

interface WorkerLogicVersion {
  worker_type: "Explorer" | "Planner" | "Coder" | "Tester" | "Reviewer";
  git_commit_sha: string;
  deployed_at: timestamp;
}
```

### 8.2 回滚粒度层级

**五层回滚粒度**（从细到粗）：

| 层级 | 回滚范围 | 触发场景 | 回滚时间 | 风险 |
|------|---------|---------|---------|------|
| **L1: 配置回滚** | Prompt模板、Policy规则 | Prompt注入检出率下降 | <5分钟 | 低 |
| **L2: 模型版本回滚** | 模型供应商侧版本切换 | 模型行为漂移检测 | <15分钟 | 中 |
| **L3: Worker逻辑回滚** | 单个Worker类型代码版本 | 特定Worker成功率下降 | <30分钟 | 中 |
| **L4: 评估集回滚** | Golden Dataset版本切换 | 评估集老化严重 | <10分钟 | 低 |
| **L5: Bundle全量回滚** | 所有组件回退到上一稳定Bundle | P0严重漂移 | <60分钟 | 高 |

### 8.3 回滚前置条件检查

```python
def check_rollback_preconditions(
    target_bundle: VersionBundle,
    rollback_scope: RollbackScope
) -> PreconditionCheckResult:
    """
    回滚前置条件检查，确保回滚安全
    
    Returns:
        PreconditionCheckResult (SAFE / RISKY / BLOCKED)
    """
    checks = []
    
    # 检查1：目标Bundle状态
    if target_bundle.status != "ACTIVE":
        checks.append(Check(
            name="bundle_status",
            result="BLOCKED",
            reason=f"目标Bundle状态为{target_bundle.status}，不可回滚"
        ))
    
    # 检查2：兼容性矩阵
    compatibility = check_compatibility(
        current_infrastructure_version=get_current_infra_version(),
        target_bundle=target_bundle
    )
    if not compatibility.is_compatible:
        checks.append(Check(
            name="compatibility",
            result="BLOCKED",
            reason=f"基础设施不兼容：{compatibility.incompatible_components}"
        ))
    
    # 检查3：数据迁移需求
    migration_needed = check_migration_needed(
        current_bundle=get_current_bundle(),
        target_bundle=target_bundle
    )
    if migration_needed.has_breaking_changes:
        checks.append(Check(
            name="migration",
            result="RISKY",
            reason=f"需要数据迁移：{migration_needed.migration_scripts}"
        ))
    
    # 检查4：并发任务影响
    running_tasks = get_running_tasks()
    if len(running_tasks) > 10:
        checks.append(Check(
            name="concurrent_tasks",
            result="RISKY",
            reason=f"{len(running_tasks)}个任务运行中，回滚可能导致中断"
        ))
    
    # 检查5：回滚历史（避免振荡）
    recent_rollbacks = get_recent_rollbacks(time_window_hours=24)
    if len(recent_rollbacks) >= 3:
        checks.append(Check(
            name="rollback_frequency",
            result="BLOCKED",
            reason="24小时内已回滚3次，可能存在振荡，需人工介入"
        ))
    
    # 综合判定
    if any(c.result == "BLOCKED" for c in checks):
        return PreconditionCheckResult(
            verdict="BLOCKED",
            checks=checks,
            recommendation="修复阻塞项后重试"
        )
    elif any(c.result == "RISKY" for c in checks):
        return PreconditionCheckResult(
            verdict="RISKY",
            checks=checks,
            recommendation="建议人工审批后执行"
        )
    else:
        return PreconditionCheckResult(
            verdict="SAFE",
            checks=checks,
            recommendation="可自动执行"
        )
```

### 8.4 回滚执行流程

```
收到DriftTrigger（来自Layer 2决策引擎）
    │
    ▼
[决策层] 回滚决策 = ROLLBACK
    │
    ▼
[选择目标] 确定回滚目标Bundle/组件
    │  ├─ 模型漂移 → 回滚模型版本（L2）
    │  ├─ Worker失败 → 回滚Worker逻辑（L3）
    │  ├─ 评估集老化 → 切换评估集版本（L4）
    │  └─ P0严重漂移 → 全量回滚Bundle（L5）
    │
    ▼
[前置条件检查]
    │  ├─ BLOCKED → 中止，通知人工
    │  ├─ RISKY → 等待人工审批
    │  └─ SAFE → 继续
    │
    ▼
[执行回滚]
    │  ├─ 停止新任务分配
    │  ├─ 等待运行中任务完成（最多5分钟）
    │  ├─ 切换版本指针
    │  ├─ 重新加载配置
    │  └─ 验证回滚成功
    │
    ▼
[回滚后验证]
    │  ├─ 运行冒烟测试（REQ-EVA-006 Level 1）
    │  ├─ 监控关键指标（15分钟窗口）
    │  └─ 对比基线
    │
    ▼
[结果判定]
    │  ├─ 成功 → 标记当前Bundle为STABLE
    │  └─ 失败 → 按 REQ-SEC-009 模式切换规则逐级升级 Kill Switch（不得跳跃，具体档位待与 SEC-009 协同确认）
    │
    ▼
[审计记录] 写入回滚事件（REQ-OBS-007）
```

### 8.5 金丝雀回滚策略（EVA-007 自定义）

**设计说明**：EVA-006 仅在例外流程中提到"灰度发布 10% + 24h 监控"，未定义完整的金丝雀/回滚机制。本节由 EVA-007 自行定义，待与 EVA-006 协同确认。

**金丝雀回滚阶段定义**：

| 阶段 | 流量比例 | 持续时间 | 回滚条件 | 审批要求 |
|------|---------|---------|---------|---------|
| Canary-1 | 1% | 4h | 任何 P0 信号 | 自动 |
| Canary-2 | 5% | 8h | 任何 P0 信号 | 自动 |
| Canary-3 | 10% | 24h | P0 或 2+ P1 信号 | Tech Lead |
| Canary-4 | 25% | 48h | P0 或 3+ P1 信号 | Tech Lead |
| Full-rollout | 100% | - | P0 触发自动回滚 | VP 事后补审批 |

**回滚执行策略**：

```python
def execute_canary_rollback(canary_stage: str, drift_signals: List[DriftSignal]):
    """
    根据金丝雀阶段和漂移信号执行回滚
    """
    if any(s.severity == "P0" for s in drift_signals):
        # P0 信号：立即全量回滚到上一稳定版本（跳过金丝雀）
        return rollback_to_version(
            target=previous_stable_bundle,
            scope="FULL",
            urgency="IMMEDIATE"
        )
    
    if canary_stage in ["Canary-3", "Canary-4"]:
        p1_count = sum(1 for s in drift_signals if s.severity == "P1")
        if p1_count >= 2:
            # 多个 P1 信号：金丝雀回滚（5% → 观察15分钟 → 25% → 观察30分钟 → 100%）
            return rollback_to_version(
                target=previous_stable_bundle,
                scope="CANARY",
                stages=[0.05, 0.25, 1.0],
                observation_minutes=[15, 30]
            )
    
    # 否则仅告警，继续观察
    return alert_only(drift_signals)
```

**与 REQ-EVA-006 的集成点**：
- 本策略的触发器通过 `DriftTrigger` 接口发送给 EVA-006
- EVA-006 的回滚执行器负责实际的流量切换
- 具体字段映射待 EVA-006 补充触发器基类型后确认

### 8.6 回滚事件Schema

```typescript
interface RollbackEvent {
  event_id: string;
  event_type: "rollback_initiated" | "rollback_completed" | "rollback_failed";
  timestamp: timestamp;
  
  // 回滚触发
  triggered_by: DriftTrigger;
  rollback_decision: RollbackDecision;
  
  // 回滚执行
  rollback_scope: "model" | "worker_logic" | "eval_dataset" | "bundle";
  source_bundle: VersionBundle;
  target_bundle: VersionBundle;
  
  // 执行结果
  execution_result: "SUCCESS" | "FAILED" | "PARTIAL";
  affected_tasks: number;
  downtime_seconds: number;
  
  // 验证结果
  post_rollback_verification: {
    smoke_test_pass: boolean;
    success_rate_recovered: boolean;
    baseline_comparison: BaselineComparison;
  };
  
  // 审计
  executed_by: actor_id;
  approved_by?: actor_id;
  audit_trail_url: string;
}
```

---

## 9. Dataset动态更新机制

### 9.1 Capability → Regression转换规则

**对标Anthropic原文**：
> "After an agent is launched and optimized, capability evals with high pass rates can 'graduate' to become a regression suite that is run continuously to catch any drift."

**转换触发条件**：

| 条件 | 阈值 | 说明 |
|------|------|------|
| 连续通过率 | ≥95%，连续3次评估 | 任务已充分验证 |
| 稳定性 | 标准差 <2% | 性能稳定 |
| 覆盖率 | 该任务覆盖的代码路径/工具类型未被其他Regression任务覆盖 | 避免冗余 |

```python
def graduate_to_regression_suite(capability_task: TaskReference) -> bool:
    """
    判断Capability eval任务是否应转换为Regression suite
    
    Returns:
        bool: True if should graduate
    """
    # 检查1：连续通过率
    recent_evals = load_recent_evals(
        task_id=capability_task.task_id,
        count=3
    )
    
    if len(recent_evals) < 3:
        return False
    
    pass_rates = [eval.pass_rate for eval in recent_evals]
    if min(pass_rates) < 0.95:
        return False
    
    # 检查2：稳定性
    std_dev = statistics.stdev(pass_rates)
    if std_dev > 0.02:
        return False
    
    # 检查3：覆盖率去重
    existing_regression_tasks = load_regression_suite()
    coverage_overlap = compute_coverage_overlap(
        capability_task,
        existing_regression_tasks
    )
    
    if coverage_overlap > 0.80:
        return False  # 已有类似Regression任务覆盖
    
    return True


def update_dataset_with_graduated_tasks():
    """
    定期执行：将高通过率Capability任务转为Regression任务
    """
    capability_tasks = load_capability_eval_tasks()
    graduated_tasks = []
    
    for task in capability_tasks:
        if graduate_to_regression_suite(task):
            # 更新任务类型
            task.eval_type = "regression"
            task.graduated_at = now()
            task.previous_eval_type = "capability"
            
            graduated_tasks.append(task)
    
    if graduated_tasks:
        # 发布新Dataset版本
        new_version = create_dataset_version(
            base_version=get_current_dataset_version(),
            changes=[
                DatasetChange(
                    change_type="graduate_to_regression",
                    affected_tasks=[t.task_id for t in graduated_tasks],
                    rationale="High pass rate stability"
                )
            ]
        )
        
        publish_dataset_version(new_version)
        
        # 通知评估工程师
        notify_dataset_update(
            version=new_version,
            graduated_count=len(graduated_tasks)
        )
```

### 9.2 Dataset版本更新流程

```
触发条件（满足任一）：
  - 生产失败案例入集达到10个
  - Capability任务毕业为Regression
  - 评估集老化任务超过20%
    │
    ▼
[准备变更清单]
  - 新增任务列表
  - 毕业任务列表
  - 降级任务列表（exposure_count≥3）
  - 删除任务列表（冗余覆盖）
    │
    ▼
[版本号递增]
  - 新增任务 → minor版本+1
  - 毕业/降级 → minor版本+1
  - Schema变更 → major版本+1
    │
    ▼
[冻结与签名]
  - 生成清单哈希（REQ-EVA-001 §11.2）
  - 使用平台私钥签名
  - 标记为冻结状态
    │
    ▼
[发布通知]
  - 通知评估工程师
  - 更新CI配置（使用新版本）
  - 触发一次全量回归评估
    │
    ▼
[保留旧版本]
  - 旧版本标记为DEPRECATED
  - 保留至少2个主版本
```

### 9.3 Dataset版本兼容性

**向后兼容性规则**：

```typescript
interface DatasetVersionCompatibility {
  // 兼容性检查
  is_backward_compatible: boolean;
  breaking_changes: BreakingChange[];
  
  // 迁移指南
  migration_guide?: MigrationGuide;
  
  // 最低支持版本
  min_supported_grader_version: string;
  min_supported_runner_version: string;
}

// 破坏性变更示例
interface BreakingChange {
  change_type: "schema_change" | "oracle_signature_change" | "lineage_reclassification";
  affected_tasks: string[];
  mitigation: string;
}
```

---

## 10. 跨模块集成接口

### 10.1 依赖输入接口

| 模块 | 接口 | 数据流向 | 用途 |
|------|------|---------|------|
| **REQ-OBS-002** | 审计事件流 | OBS → EVA-007 | 生产失败案例采集 |
| **REQ-OBS-003** | 指标字典 `gen_ai.evaluation.result` | OBS → EVA-007 | 漂移检测数据源 |
| **REQ-EVA-001** | Golden Dataset | EVA-001 → EVA-007 | 去重检查、版本管理 |
| **REQ-EVA-005** | 回归报告、ATIF轨迹 | EVA-005 → EVA-007 | Regression分数、轨迹相似度 |
| **REQ-REL-001** | 失败分类体系 | REL → EVA-007 | 失败根因分类 |
| **REQ-SEC-009** | Kill Switch状态 | SEC → EVA-007 | 回滚后备机制 |

### 10.2 输出接口

| 模块 | 接口 | 数据流向 | 用途 |
|------|------|---------|------|
| **REQ-EVA-006** | DriftTrigger | EVA-007 → EVA-006 | 触发发布门禁回滚 |
| **REQ-EVA-001** | 候选评估案例 | EVA-007 → EVA-001 | 生产失败反哺Dataset |
| **REQ-OBS-005** | 漂移告警 | EVA-007 → OBS | 告警通知 |
| **监控仪表板** | DriftReport | EVA-007 → Dashboard | 可视化漂移趋势 |

### 10.3 接口Schema定义

**输入接口示例**（从OBS-002读取失败事件）：

```typescript
// 复用REQ-OBS-002的EventEnvelope
interface TaskFailedEvent extends EventEnvelope {
  event_type: "task.execution.failed";
  payload: {
    task_id: string;
    workflow_id: string;
    worker_id: string;
    failure_category: FailureCategory;  // 来自REQ-REL-001
    trace_id: string;
    evidence_artifacts: string[];
  };
}
```

**输出接口示例**（发送给EVA-006的触发器）：

```typescript
// 扩展REQ-EVA-006的触发器接口
// 注：REQ-EVA-006 未定义统一的触发器基类型，其4类触发器仅以表格和伪代码描述，字段待协同确认
interface DriftTrigger {
  trigger_type: "drift_detected";
  
  // REQ-EVA-006兼容字段
  severity: "P0" | "P1" | "P2";
  metric_name: string;
  baseline_value: number;
  current_value: number;
  
  // EVA-007扩展字段
  drift_dimension: string;
  degradation_pct: number;
  affected_task_types: string[];
  suspected_cause: string;
  evidence_trace_ids: string[];
  recommended_action: string;
}
```

---

## 11. 验收标准

### 11.1 功能验收

| 验收项 | 验收标准 | 验证方法 |
|--------|---------|---------|
| **漂移检测准确性** | 检出率 ≥85%，误报率 ≤10% | 注入已知漂移场景，验证检出率 |
| **回滚决策准确性** | 误报率 ≤10%（不应回滚却触发回滚） | 历史数据回测 |
| **失败案例入集率** | 新颖失败 ≥80% 在7天内通过四道闸门 | 统计生产失败案例处理时效 |
| **Dataset更新及时性** | 触发更新后7天内发布新版本 | 监控版本发布周期 |
| **门禁联动延迟** | DriftTrigger发送到EVA-006响应 <5分钟 | 端到端延迟测试 |
| **回滚执行时长** | L1配置回滚<5分钟、L5全量回滚<60分钟 | 实际回滚演练 |
| **回滚成功率** | ≥95%（回滚后成功率恢复到基线90%以上） | 回滚后验证指标 |

### 11.2 性能验收

| 指标 | 目标值 | 实际值 |
|------|--------|-------|
| 漂移检测延迟（从事件发生到报告产出） | ≤15分钟 | _待测试_ |
| 回滚决策延迟（从检测到触发器发送） | ≤5分钟 | _待测试_ |
| 失败案例去重查询延迟 | p95 <500ms | _待测试_ |
| Dataset版本发布耗时 | <10分钟 | _待测试_ |
| 回滚前置条件检查耗时 | <2分钟 | _待测试_ |

### 11.3 质量验收

| 指标 | 目标值 | 实际值 |
|------|--------|-------|
| 漂移检测误报率 | ≤10% | _待测试_ |
| 回滚振荡率（24h内回滚≥3次） | ≤2% | _待测试_ |
| 失败案例去重准确率 | ≥95% | _待测试_ |
| PII脱敏覆盖率 | 100%（无PII泄露） | 人工审计 |

### 11.4 合规验收

| 验收项 | 要求 | 验证方法 |
|--------|------|---------|
| 审计追踪完整性 | 所有漂移检测、回滚决策、Dataset更新记录可追溯 | 审计日志抽查 |
| PII脱敏合规 | 入集失败案例无明文PII | 自动化扫描+人工审查 |
| 数据留存策略 | 对齐REQ-OBS-007（漂移报告30天热+180天冷，回滚事件1年） | 留存策略文档评审 |
| 权限控制 | P0 漂移自动回滚（事后 VP 补审批），P1 漂移需 Tech Lead 审批 | 权限矩阵测试 |

---

## 12. 实施计划

### 12.1 里程碑

| 里程碑 | 交付物 | 时间 | 依赖 |
|--------|--------|------|------|
| **M1: 漂移检测** | 四维漂移检测算法、DriftReport Schema | 2周 | REQ-OBS-003, REQ-EVA-005 |
| **M2: 回滚决策** | 决策引擎、DriftTrigger集成 | 2周 | M1, REQ-EVA-006 |
| **M3: 反馈闭环** | 失败案例采集器、四道闸门 | 2周 | M1, REQ-EVA-001 |
| **M4: 版本协调** | Bundle管理、回滚执行流程 | 1周 | M2 |
| **M5: Dataset更新** | Capability→Regression转换、版本发布 | 1周 | M3 |
| **M6: 集成测试** | 端到端测试、回滚演练 | 1周 | M1-M5 |

**总计**：7周

### 12.2 开发顺序

```
Week 1-2: 漂移检测层
  - 任务成功率检测（优先，最简单）
  - Regression eval分数检测
  - 模型行为漂移检测
  - 评估集老化检测

Week 3-4: 回滚决策层
  - 决策矩阵实现
  - DriftTrigger Schema与EVA-006协同确认
  - Error Budget集成
  - 决策审批流程

Week 5-6: 反馈闭环层
  - 失败事件采集
  - 四道闸门检查
  - PII脱敏
  - 入集审批流程

Week 7: 版本协调器
  - Bundle管理
  - 回滚前置条件检查
  - 金丝雀回滚策略

Week 8: Dataset动态更新
  - Capability→Regression转换
  - 版本发布流程

Week 9: 集成与演练
  - 端到端测试
  - 回滚演练
  - 性能调优
```

### 12.3 风险与缓解

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|---------|
| 漂移检测误报率高 | 频繁误告警，降低可信度 | 中 | 7天缓冲期、人工复核、阈值动态调整 |
| EVA-006接口协同冲突 | 需修改已完成设计 | 中 | M1前与EVA-006作者确认Schema |
| 回滚失败导致服务中断 | 业务影响 | 低 | 回滚预演、前置条件检查、金丝雀回滚 |
| Dataset更新引入污染 | 评估集质量下降 | 低 | 严格四道闸门、人工审核 |
| 版本Bundle兼容性问题 | 回滚后系统不稳定 | 中 | 兼容性矩阵、冒烟测试 |

---

## 13. 运维与监控

### 13.1 关键指标仪表板

**漂移监控视图**：

```
┌──────────────────────────────────────────────────┐
│ 生产漂移监控 (Production Drift Monitoring)         │
├──────────────────────────────────────────────────┤
│ 综合状态：STABLE / DRIFTING / CRITICAL            │
│                                                  │
│ 任务成功率趋势（最近30天）                        │
│ ████████████████████░░░░ 85% → 83% (-2%)        │
│                                                  │
│ Regression Eval分数趋势                          │
│ REAL_OWN_REPO:    0.90 → 0.89 (-1%)            │
│ REAL_EXTERNAL:    0.85 → 0.86 (+1%)            │
│ SYNTH_ADVERSARIAL: 0.80 → 0.78 (-2%) ⚠️         │
│                                                  │
│ 模型行为相似度：0.92 (正常阈值: >0.85)            │
│ 评估集老化率：15% (警戒阈值: 20%)                 │
│                                                  │
│ 最近漂移信号：                                    │
│ • P1: Regression eval下降 (SYNTH_ADVERSARIAL)   │
│   检测时间：2小时前                              │
│   当前决策：HOLD (观察7天)                       │
└──────────────────────────────────────────────────┘
```

**回滚历史视图**：

```
┌──────────────────────────────────────────────────┐
│ 回滚历史 (Rollback History)                      │
├──────────────────────────────────────────────────┤
│ 时间           触发原因         范围      结果    │
├──────────────────────────────────────────────────┤
│ 2天前 14:23   P0严重漂移      Bundle   ✅成功    │
│ 7天前 09:15   Regression下降  模型版本  ✅成功    │
│ 15天前 16:42  评估集老化      Dataset   ✅成功    │
└──────────────────────────────────────────────────┘
```

### 13.2 告警规则

| 告警 | 条件 | 严重度 | 通知渠道 |
|------|------|--------|---------|
| 漂移检测异常 | 检测任务失败或超时>15分钟 | P2 | Slack |
| P0严重漂移 | 任务成功率<50% 或 Regression下降>10% | P0 | PagerDuty + Email |
| P1漂移 | Regression下降5-10% | P1 | Email |
| 回滚失败 | 回滚执行失败或验证不通过 | P0 | PagerDuty |
| 回滚振荡 | 24h内回滚≥3次 | P1 | Email + Slack |
| Dataset更新延迟 | 触发后>7天未发布新版本 | P2 | Slack |

### 13.3 Runbook

**场景1：收到P0严重漂移告警**

```
自动回滚流程已触发（<5分钟内完成）：
1. 系统自动执行全量回滚
2. PagerDuty 告警发送至 VP + 架构组
3. Dashboard 展示回滚进度

人工复核步骤：
1. 查看 DriftReport，确认漂移维度和影响面
2. 检查证据 Trace ID，定位失败案例
3. 评估回滚决策正确性：
   - 漂移信号是否准确？
   - 影响面评估是否合理？
4. VP 在 4 小时内完成补审批：
   - 确认回滚 → 记录审批日志
   - 判定误报 → 启动恢复流程（需 CISO + VP 双人确认）
5. 24 小时内完成 RCA 报告

4. 执行回滚（如需要）
   - 运行回滚前置条件检查
   - 执行金丝雀回滚或全量回滚
   - 运行回滚后验证

5. 根因分析
   - 检查模型供应商变更日志
   - 分析最近代码变更
   - 更新事故报告
```

**场景2：回滚后验证失败**

```
1. 按 REQ-SEC-009 逐级升级 Kill Switch（项目级完全停止对应 M4，需双人审批）
2. 通知VP Engineering
3. 回滚到上上个稳定版本
4. 启动应急响应流程
5. 48小时内产出RCA报告
```

---

## 14. 安全与合规

### 14.1 权限控制矩阵

| 角色 | 查看漂移报告 | 触发人工回滚 | 审批P1回滚 | 补审批P0回滚 | 修改Dataset | 访问生产失败案例 |
|------|------------|------------|-----------|-------------|-----------|----------------|
| 评估工程师 | ✓ | ✗ | ✗ | ✗ | ✓ | ✓（脱敏后） |
| ML工程师 | ✓ | ✗ | ✗ | ✗ | ✗ | ✓（脱敏后） |
| Tech Lead | ✓ | ✓ | ✓ | ✗ | ✗ | ✓（脱敏后） |
| 发布经理 | ✓ | ✓ | ✓ | ✗ | ✗ | ✗ |
| VP Engineering | ✓ | ✓ | ✓ | ✓（必须，4h内） | ✗ | ✗ |
| SRE工程师 | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ |
| 审计员 | ✓（只读） | ✗ | ✗ | ✗ | ✗ | ✗ |

**注**：P0 漂移由系统自动回滚，VP 事后 4 小时内完成补审批。

### 14.2 数据隐私保护

**四层脱敏策略**：

| 敏感度 | 数据类型 | 脱敏方法 | 示例 |
|--------|---------|---------|------|
| L1公开 | 任务类型、失败分类 | 不脱敏 | "CODER_LOGIC_ERROR" |
| L2内部 | 仓库名、文件路径 | 哈希化 | "repo_a3f2e8" |
| L3敏感 | 代码片段、变量名 | 泛化+redact | `function foo() { /* redacted */ }` |
| L4机密 | API密钥、用户邮箱 | 完全移除 | 不保留 |

**PII检测规则**（复用REQ-OBS-004 §3）：

```python
PII_PATTERNS = {
    "email": r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
    "api_key": r'(sk|pk)_[a-zA-Z0-9]{32,}',
    "credit_card": r'\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b',
    "ssn": r'\b\d{3}-\d{2}-\d{4}\b',
    "phone": r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b',
    "ipv4": r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b',
}
```

### 14.3 审计日志留存（对齐REQ-OBS-007）

| 日志类型 | 热存储 | 冷存储 | 合规归档 |
|---------|--------|--------|---------|
| 漂移检测报告 | 30天 | 180天 | - |
| 回滚决策记录 | 30天 | 1年 | 3年 |
| 失败案例（脱敏后） | 30天 | 180天 | - |
| Dataset版本变更 | 永久 | - | 永久 |
| 审批记录 | 30天 | 3年 | 5年 |

### 14.4 合规要求

**SOC 2 Type II**：
- 所有回滚决策必须有审计追踪
- P0回滚需VP签字
- 审计日志不可篡改（WORM存储）

**GDPR**（如适用）：
- 生产失败案例脱敏后入集
- 支持"被遗忘权"（删除特定用户的失败案例）
- 数据驻留合规（EU数据不出境）

---

## 15. 成本估算

### 15.1 计算成本

| 组件 | 资源需求 | 月度成本估算 |
|------|---------|------------|
| 漂移检测（每日运行） | 2 vCPU, 8GB RAM, 1小时/天 | $50 |
| 失败案例采集（实时） | 1 vCPU, 4GB RAM, 常驻 | $70 |
| 回滚执行（按需） | 4 vCPU, 16GB RAM, 1次/月 | $5 |
| **总计** | - | **$125/月** |

### 15.2 存储成本

| 数据类型 | 日增量 | 留存期 | 月度成本估算 |
|---------|--------|--------|------------|
| 漂移报告 | 10MB | 180天 | $1 |
| 失败案例（脱敏） | 50MB | 180天 | $5 |
| 回滚事件 | 1MB | 1年 | $1 |
| Dataset版本 | 100MB | 永久 | $10 |
| **总计** | - | - | **$17/月** |

### 15.3 Token成本

| 场景 | Token消耗 | 频率 | 月度成本估算 |
|------|----------|------|------------|
| 轨迹embedding（漂移检测） | 50K tokens | 每日 | $7.5 |
| 失败案例相似度检查 | 10K tokens | 每失败1次 | $15（假设50失败/天） |
| **总计** | - | - | **$22.5/月** |

**总体月度成本**：约 $165/月（不含基础OBS采集成本）

---

## 16. 开放问题与待确认项

### 16.1 待跨模块协同确认（P0）

1. **EVA-006接口协同**：
   - DriftTrigger的字段Schema是否与现有4类触发器兼容？
   - REQ-EVA-006 §9.2回滚决策算法是否需要扩展以支持长时间窗口漂移？
   - 建议：M1前与EVA-006作者进行Schema评审

2. **OBS-003指标扩展**：
   - 当前`gen_ai.evaluation.result`指标是否已包含血缘类型维度？
   - 是否需要新增`gen_ai.drift.score`指标？
   - 建议：读取REQ-OBS-003完整指标定义确认

### 16.2 技术可行性待验证（P1）

1. **轨迹embedding性能**：
   - 每日对50+任务的轨迹进行embedding，延迟是否可控（<15分钟）？
   - 建议：M1阶段进行性能基准测试

2. **模型供应商变更检测**：
   - 如何检测模型供应商的静默更新（snapshot_date变化）？
   - 是否需要模型供应商提供版本变更webhook？
   - 建议：调研OpenAI/Anthropic的版本通知机制

3. **回滚振荡避免**：
   - 24h内回滚3次阻断是否足够？是否需要更智能的振荡检测？
   - 建议：M4阶段设计振荡检测算法

### 16.3 产品决策待确认（P2）

1. **Dataset更新频率**：
   - Capability→Regression转换是否应该立即触发版本发布，还是批量处理？
   - 建议：与评估工程师确认运维负担

2. **回滚人工审批阈值**：
   - P1漂移是否总是需要Tech Lead审批，还是允许自动化？
   - 建议：与发布经理确认风险承受度

---

## 17. 参考文献

1. **Anthropic**. (2026). *Demystifying evals for AI agents*. https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents. 发布日期：2026-01-09，访问日期：2026-10-08
   - 关键引用（§"How evals fit with other methods"）：Production monitoring检测分布漂移
   - 关键引用（§"Capability vs. regression evals"）：Capability eval毕业为Regression suite

2. **MLflow**. (2024). *MLflow Model Registry*. https://mlflow.org/docs/latest/model-registry.html. 访问日期：2026-10-08
   - 借鉴：版本Bundle管理、Stage-based promotion

3. **OpenAI**. (2026). *Evals Documentation*. https://github.com/openai/evals. 访问日期：2026-10-08
   - 借鉴：生产Trace回放、失败案例自动入库

4. **REQ-EVA-001**. *Golden Dataset详细设计*. v0.1-designed
   - §6.2：exposure_count管理、污染控制
   - §11.2：版本化管理协议

5. **REQ-EVA-005**. *回归流水线详细设计*. v0.1-designed
   - §6：回归检测算法（统计显著性检验）
   - §8：ATIF轨迹格式

6. **REQ-EVA-006**. *发布门禁详细设计*. v0.1-designed
   - §9：自动回滚机制（4类触发器）
   - 注：该文档未包含 Error Budget 机制，本文对其的引用为暂行定义，待协同确认

---

## 18. 变更记录

| 版本 | 日期 | 变更内容 | 作者 |
|------|------|---------|------|
| v1.0-designed | 2026-10-08 | 初始详细设计完成 | 架构组 |

---

## 19. 附录

### 附录A：术语表

| 术语 | 定义 |
|------|------|
| **漂移（Drift）** | 生产环境中Agent性能相对基线的统计显著性退化 |
| **Capability Eval** | 探索Agent能力上限的评估任务，初始通过率可能较低 |
| **Regression Eval** | 防止性能倒退的评估任务，预期持续高通过率（≥95%） |
| **Graduation** | Capability任务在高通过率稳定后转换为Regression任务 |
| **Version Bundle** | 模型版本、评估集版本、评分器版本、Worker逻辑版本的统一快照 |
| **exposure_count** | 任务被完整评估的累计次数（REQ-EVA-001污染控制指标） |
| **Error Budget** | 每月可用的SLO失误预算（本需求暂行定义，REQ-EVA-006 尚无对应机制，待协同确认） |
| **DriftTrigger** | 发送给REQ-EVA-006的漂移检测触发器 |

### 附录B：决策可逆性条件

根据红队复核报告（`红队复核整改报告-EVA-007.md`）要求，补充决策可逆性：

**降级回候选区触发条件**（满足任一即可）：
1. 详细设计阶段发现分布漂移判定逻辑的技术可行性不足（如依赖的时序分析基础设施未选型）
2. 与EVA-006的接口协同发现重大冲突，需修改已完成设计
3. 实施阶段成本超预算3倍以上（计算+存储+Token成本 >$500/月）

**降级审批**：需架构组批准，并需同步回退以下5份文档的计数修改：
- `00-integrated-design-baseline.md`
- `PENDING-REQUIREMENTS.md`
- `INDEX.md`
- `README.md`
- `05-evaluation-system.md`

---

**设计完成**：本需求范围内的详细设计已完成，可进入跨模块评审与冻结阶段。
