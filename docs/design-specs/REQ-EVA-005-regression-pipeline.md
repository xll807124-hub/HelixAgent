# REQ-EVA-005: 回归流水线详细设计

> **需求编号**：REQ-EVA-005  
> **需求名称**：回归流水线（Regression Pipeline）  
> **优先级**：P0  
> **状态**：v0.1-designed  
> **设计完成日期**：2026-09-30  
> **前置依赖**：REQ-EVA-003（已完成）、REQ-EVA-004（已完成）  
> **后续依赖**：REQ-EVA-006 发布门禁

---

## 一、需求概述

### 1.1 设计目标

建立**自动化、可重复、成本感知**的回归评估管道，实现Agent行为变化的持续监控与质量门禁，支持：

1. **任务回放与轨迹分析**：完整记录并可重放任何评估执行
2. **测试套件管理**：组织、版本化和执行评估套件
3. **并行执行**：高效利用资源，缩短评估周期
4. **成本感知子集选择**：降低50-90%评估成本
5. **回归检测**：统计显著性检验，检出率≥90%
6. **CI/CD集成**：无缝集成到开发流程

### 1.2 核心问题

**问题陈述**：
- **全量评估成本不可控**：每次Agent变更需要重新评估所有任务，Token成本高昂
- **评估结果不可复现**：缺乏轨迹回放机制，失败案例难以诊断
- **缺乏回归检测**：依赖人工对比评估结果，容易遗漏回归问题
- **CI集成不完整**：缺少标准化CI集成方案，开发者体验差
- **并行执行低效**：资源利用不充分，评估周期长

### 1.3 业界对齐

本规范综合参考以下行业最佳实践：

| 来源 | 核心借鉴 | 访问日期 |
|------|---------|----------|
| **OpenAI Codex** | 三层评估管道（烟雾测试→确定性验证→LLM评分）、JSONL trace | 2026-09-30 |
| **Cursor @cursor/july** | 软/硬门禁分离、失败产物记录、CI集成 | 2026-09-30 |
| **DeepSeek** | 容器隔离评估、ATIF轨迹格式、Pier管道 | 2026-09-30 |
| **Kimi K3** | 多维度rubric评分、thinking history保留、成本效率测量 | 2026-09-30 |
| **SWE-bench** | 轨迹感知子集选择（节省90%成本）、IRT校准 | 2026-09-30 |
| **Manus AI** | 自愈调试、多Agent协调评估、概率性验证 | 2026-09-30 |

---

## 二、设计边界

### 2.1 本需求包含

- 评估套件管理（创建、编辑、删除、版本化）
- 评估执行引擎（全量/子集/增量三种模式）
- 轨迹记录与回放机制（ATIF格式）
- 子集选择算法（轨迹感知）
- 回归检测算法（统计显著性检验）
- 并行执行策略（静态/成本驱动/优先级）
- 报告生成与发布（通过率、评分分布、回归分析、成本报告）
- CI/CD集成（GitHub Action、通用Webhook）
- 评估仪表板（套件管理、进度监控、结果查看）

### 2.2 本需求不包含

| 内容 | 归属需求 |
|------|----------|
| Golden Dataset构建 | REQ-EVA-001 |
| 标注规范和rubric设计 | REQ-EVA-002 |
| 自动评分器实现 | REQ-EVA-003 |
| 失败归因分析 | REQ-EVA-004 |
| 发布门禁配置 | REQ-EVA-006 |

---

## 三、核心设计：三层评估管道

### 3.1 管道架构（对标OpenAI Codex）

```
┌──────────────────────────────────────────────────────────────┐
│ Layer 1: 确定性验证层（Deterministic Verification）            │
│ - Oracle验证（单元测试、集成测试、断言）                        │
│ - Schema验证（输出格式、必需字段）                              │
│ - 污染检查（exposure_count、holdout状态）                       │
│ ✅ 通过 → Layer 2  ❌ 失败 → 记录并跳过评分                     │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│ Layer 2: 自动评分层（Automated Scoring）                      │
│ - 调用REQ-EVA-003自动评分器                                    │
│ - 支持确定性检查、LLM-as-Judge、人工审核三种模式                │
│ - 生成JudgmentResult和证据链                                   │
│ ✅ 评分完成 → Layer 3  ❌ 评分失败 → 降级处理                   │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│ Layer 3: 失败归因层（Failure Attribution）                     │
│ - 调用REQ-EVA-004失败归因                                      │
│ - 生成AttributionResult和根因分析                              │
│ - 支持反事实验证和证据链构建                                    │
│ ✅ 归因完成 → 报告生成  ❌ 归因失败 → 标记INCONCLUSIVE          │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│ 报告生成与发布层（Report Generation & Publishing）             │
│ - 聚合通过率、评分分布、回归分析、成本统计                       │
│ - 生成CI友好报告（JUnit XML、JSON）                            │
│ - 发布到评估仪表板和CI系统                                      │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 三层管道优势

| 优势 | 说明 |
|------|------|
| **成本优化** | 确定性验证快速失败，减少不必要的LLM调用 |
| **质量保障** | 分层验证确保评估质量 |
| **可诊断性** | 每层生成独立证据，失败易追溯 |
| **灵活性** | 每层可独立配置和优化 |

---

## 四、评估执行模式

### 4.1 三种执行模式

| 模式 | 适用场景 | 成本 | 周期 |
|------|----------|------|------|
| **全量评估** | 主版本发布、基线建立 | 100% | 2小时 |
| **子集评估** | PR评审、快速回归 | 10-30% | 15分钟 |
| **增量评估** | 持续集成、日常开发 | 20-40% | 30分钟 |

### 4.2 模式切换策略

```
决策树：
IF 主版本发布 OR 基线缺失
  THEN 全量评估
ELSE IF PR评审 OR 快速验证
  THEN 子集评估
ELSE IF 持续集成 OR 日常开发
  THEN 增量评估
```

---

## 五、轨迹感知子集选择算法

### 5.1 算法目标（对标SWE-bench）

- **成本节省**：≥ 50%（目标90%）
- **估计精度**：中位估计误差 < 5%
- **代表性**：保持历史通过/失败率分布

### 5.2 算法流程

```
步骤1：分组阶段（Grouping）
  输入：全量任务集合T、历史评估结果H
  输出：分组G = {G_pass, G_fail}
  
  算法：
  FOR each task t in T:
    IF H[t].status == PASS:
      G_pass.add(t)
    ELSE:
      G_fail.add(t)
  
  验证：len(G_pass) + len(G_fail) == len(T)

步骤2：轨迹嵌入阶段（Embedding）
  输入：任务轨迹集合{Traj(t) | t in T}
  输出：嵌入向量集合{Emb(t) | t in T}
  
  算法：
  FOR each task t in T:
    trajectory = load_trajectory(t, H)
    sanitized = sanitize_trajectory(trajectory)  # 移除结果信号
    Emb(t) = embedding_model.encode(sanitized)
  
  说明：
  - sanitize_trajectory移除success/failure token
  - 使用预训练embedding model（如sentence-transformers）

步骤3：几何选择阶段（Geometric Selection）
  输入：分组G、嵌入集合Emb、子集比例p
  输出：选中子集S
  
  算法：
  FOR each group g in G:
    centroid_g = mean(Emb(t) for t in g)
    n_select = ceil(len(g) * p)
    
    # 选择最接近质心的n_select个任务
    distances = [euclidean_distance(Emb(t), centroid_g) for t in g]
    S_g = top_k_closest(g, distances, n_select)
    S.add(S_g)
  
  返回：S

步骤4：验证阶段（Validation）
  输入：选中子集S、评估结果R(S)
  输出：全量估计E、置信区间CI
  
  算法：
  pass_rate_subset = count(R(S)[t].status == PASS) / len(S)
  
  # 统计估计全量通过率
  E = estimate_full_pass_rate(pass_rate_subset, G, S)
  
  # Bootstrap计算置信区间
  CI = bootstrap_confidence_interval(R(S), G, alpha=0.05)
  
  返回：E, CI
```

### 5.3 轨迹清理规则

**需要移除的信号**：
- 显式结果token：`PASS`, `FAIL`, `SUCCESS`, `ERROR`
- 评分信息：`score=`, `verdict=`
- Oracle输出：测试通过/失败消息

**需要保留的信号**：
- 工具调用序列
- 推理步骤
- 上下文访问模式
- 错误恢复尝试

### 5.4 成本收益分析

| 子集比例 | 估计误差（中位） | Token节省 | 周期缩短 |
|----------|------------------|----------|----------|
| 100% | 0% | 0% | 0% |
| 30% | 3% | 70% | 70% |
| 10% | 5% | 90% | 90% |
| 5% | 8% | 95% | 95% |

**推荐配置**：
- PR评审：10%子集
- 主分支CI：30%子集
- 发布验证：100%全量

---

## 六、回归检测算法

### 6.1 设计原则

- **多维度比较**：通过率、评分分布、轨迹相似度
- **统计显著性检验**：避免随机波动误判
- **分层报告**：总体/血缘/根因类别

### 6.2 算法流程

```
步骤1：基线加载
  输入：历史评估ID baseline_id
  输出：基线指标B
  
  B.pass_rate = load_metric(baseline_id, "pass_rate")
  B.score_dist = load_metric(baseline_id, "score_distribution")
  B.trajectory_emb = load_metric(baseline_id, "trajectory_embeddings")

步骤2：当前评估执行
  输入：当前评估套件S
  输出：当前指标C
  
  C.pass_rate = execute_and_measure(S, "pass_rate")
  C.score_dist = execute_and_measure(S, "score_distribution")
  C.trajectory_emb = execute_and_measure(S, "trajectory_embeddings")

步骤3：差异计算与显著性检验
  
  # 3.1 通过率检验（Chi-square）
  chi2, p_value_pass = chi_square_test(B.pass_rate, C.pass_rate)
  
  # 3.2 评分分布检验（Wilcoxon rank-sum）
  statistic, p_value_score = wilcoxon_test(B.score_dist, C.score_dist)
  
  # 3.3 轨迹相似度（余弦相似度）
  trajectory_similarity = cosine_similarity(B.trajectory_emb, C.trajectory_emb)

步骤4：回归判定
  
  # 计算效应量
  effect_size_pass = abs(C.pass_rate - B.pass_rate)
  effect_size_score = cohen_d(B.score_dist, C.score_dist)
  
  # 判定逻辑
  IF p_value_pass < 0.05 AND effect_size_pass > 0.05:
    verdict_pass = "REGRESSION"
  ELIF p_value_pass < 0.05 AND effect_size_pass <= 0.05:
    verdict_pass = "DRIFT"
  ELSE:
    verdict_pass = "NO_CHANGE"
  
  IF p_value_score < 0.05 AND effect_size_score > 0.3:
    verdict_score = "REGRESSION"
  ELIF p_value_score < 0.05 AND effect_size_score <= 0.3:
    verdict_score = "DRIFT"
  ELSE:
    verdict_score = "NO_CHANGE"
  
  IF trajectory_similarity < 0.85:
    verdict_trajectory = "BEHAVIOR_CHANGE"
  ELSE:
    verdict_trajectory = "CONSISTENT"
  
  # 综合判定
  IF "REGRESSION" in [verdict_pass, verdict_score]:
    final_verdict = "REGRESSION"
  ELIF "DRIFT" in [verdict_pass, verdict_score]:
    final_verdict = "DRIFT"
  ELSE:
    final_verdict = "NO_CHANGE"

步骤5：分层报告生成
  
  # 5.1 总体报告
  report.overall = {
    "verdict": final_verdict,
    "pass_rate_change": C.pass_rate - B.pass_rate,
    "score_change": mean(C.score_dist) - mean(B.score_dist),
    "trajectory_similarity": trajectory_similarity
  }
  
  # 5.2 按血缘类型分解
  FOR lineage in [REAL_OWN_REPO, REAL_EXTERNAL, SYNTH_PROPERTY, 
                   SYNTH_ADVERSARIAL, SYNTH_STRESS]:
    report.by_lineage[lineage] = compute_regression(B, C, lineage)
  
  # 5.3 按根因类别分解（对于失败任务）
  FOR root_cause in [A1, A2, B1, C1, ...]:
    report.by_root_cause[root_cause] = compute_regression(B, C, root_cause)
  
  返回：report
```

### 6.3 判定阈值

| 指标 | 阈值 | 说明 |
|------|------|------|
| 显著性水平α | 0.05 | 95%置信度 |
| 通过率效应量 | 5% | 绝对差异 |
| 评分效应量（Cohen's d） | 0.3 | 小到中等效应 |
| 轨迹相似度 | 0.85 | 余弦相似度 |

---

## 七、并行执行策略

### 7.1 三种并行策略

**策略1：静态并行（Static Parallelism）**

```
配置：
  parallelism: 8  # 固定并发度
  
适用场景：
  - 资源充足
  - 任务数量稳定
  
实现：
  task_queue = Queue(all_tasks)
  workers = [Worker() for _ in range(parallelism)]
  
  FOR worker in workers:
    worker.start(task_queue)
  
  wait_all_workers_complete()
```

**策略2：成本驱动并行（Cost-Driven Parallelism）**

```
配置：
  token_budget: 1000000  # Token预算
  avg_token_per_task: 5000  # 平均每任务Token消耗
  
计算并行度：
  max_parallelism = token_budget / (avg_token_per_task * avg_duration_per_task)
  actual_parallelism = min(max_parallelism, cpu_cores)
  
适用场景：
  - Token预算有限
  - 需要优化成本-延迟权衡
```

**策略3：优先级调度（Priority Scheduling）**

```
优先级定义：
  P0: 发布门禁任务（立即执行）
  P1: 回归测试任务（高优先级队列）
  P2: 离线评估任务（低优先级队列）
  
调度算法：
  WHILE task_queue not empty:
    IF has_p0_task():
      execute_immediately(p0_task)
    ELIF has_p1_task():
      schedule_to_high_priority_worker(p1_task)
    ELSE:
      schedule_to_low_priority_worker(p2_task)
```

### 7.2 资源隔离机制（对标DeepSeek）

```
容器配置：
  cpu_limit: 2.0  # CPU核心数
  memory_limit: 8GB  # 内存限制
  disk_limit: 20GB  # 磁盘限制
  network: restricted  # 网络受限
  
隔离保证：
  - 每个任务在独立容器执行
  - 容器间无共享状态
  - 失败不影响其他任务
  - 资源耗尽自动终止
```

---

## 八、轨迹记录与回放

### 8.1 ATIF轨迹格式（对标DeepSeek）

```typescript
// Agent Trajectory Intermediate Format
interface ATIFTrajectory {
  // 元数据
  trajectory_id: string;
  task_id: string;
  agent_version: string;
  started_at: timestamp;
  completed_at: timestamp;
  
  // 执行环境
  environment: {
    runtime_version: string;
    sandbox_type: string;
    resource_limits: ResourceLimits;
  };
  
  // 步骤序列
  steps: ATIFStep[];
  
  // 最终状态
  final_state: {
    status: "SUCCESS" | "FAILURE" | "TIMEOUT" | "ERROR";
    artifacts: Artifact[];
    evidence: Evidence[];
  };
  
  // 资源使用
  resource_usage: {
    token_count: number;
    duration_ms: number;
    cpu_seconds: number;
    memory_peak_mb: number;
  };
}

interface ATIFStep {
  step_index: number;
  step_type: "ACTION" | "OBSERVATION" | "REASONING";
  timestamp: timestamp;
  
  // Action
  action?: {
    tool_name: string;
    tool_input: JSON;
    tool_output: JSON;
    tool_status: "SUCCESS" | "FAILURE" | "TIMEOUT";
  };
  
  // Observation
  observation?: {
    observation_type: string;
    observation_data: JSON;
  };
  
  // Reasoning
  reasoning?: {
    thinking: string;
    plan: string;
  };
}
```

### 8.2 轨迹回放流程

```
步骤1：接收回放请求
  输入：trajectory_id, replay_config
  输出：replay_report
  
  验证：
  - 轨迹存在且完整
  - 用户有回放权限
  - 回放环境可用

步骤2：轨迹加载
  trajectory = load_trajectory(trajectory_id)
  
  验证完整性：
  - 检查trajectory.steps完整性
  - 验证哈希签名
  - 确认依赖项存在

步骤3：环境重建
  environment = create_replay_environment(trajectory.environment)
  
  重建：
  - 沙箱类型
  - 资源限制
  - 初始上下文

步骤4：确定性重放执行
  FOR step in trajectory.steps:
    IF step.step_type == "ACTION":
      replay_result = replay_action(step.action, environment)
      compare_result(replay_result, step.action.tool_output)
    
    IF step.step_type == "OBSERVATION":
      # Observation通常是幂等的，直接记录
      record_observation(step.observation)
    
    IF step.step_type == "REASONING":
      # Reasoning可能不确定，记录差异
      replay_reasoning = regenerate_reasoning(environment)
      compare_reasoning(replay_reasoning, step.reasoning)

步骤5：差异分析
  differences = []
  
  FOR step_index, (original, replayed) in enumerate(zip(trajectory.steps, replay_steps)):
    IF not equal(original, replayed):
      differences.append({
        "step_index": step_index,
        "type": "OUTPUT_MISMATCH" | "REASONING_DIVERGENCE" | "ERROR",
        "original": original,
        "replayed": replayed
      })

步骤6：回放报告生成
  report = {
    "trajectory_id": trajectory_id,
    "reproducibility": len(differences) == 0,
    "differences": differences,
    "final_state_match": compare_final_state(trajectory, replay),
    "resource_usage_delta": compute_delta(trajectory.resource_usage, replay.resource_usage)
  }
  
  返回：report
```

### 8.3 轨迹存储与管理

**存储分层**：

| 层级 | 留存期 | 说明 |
|------|--------|------|
| 热存储 | 30天 | 最近评估，快速访问 |
| 冷存储 | 180天 | 历史评估，归档存储 |
| 封存档 | 永久 | 里程碑版本，WORM |

**索引结构**：

```
轨迹索引：
- trajectory_id（主键）
- task_id（外键，关联Golden Dataset）
- agent_version
- evaluation_run_id
- lineage_type
- final_status
- created_at
```

---

## 九、报告生成与发布

### 9.1 报告内容结构

```typescript
interface EvaluationReport {
  // 基本信息
  report_id: string;
  evaluation_run_id: string;
  generated_at: timestamp;
  evaluation_mode: "FULL" | "SUBSET" | "INCREMENTAL";
  
  // 通过率统计
  pass_rate_summary: {
    overall: PassRateMetric;
    by_lineage: Map<LineageType, PassRateMetric>;
    by_difficulty: Map<DifficultyLevel, PassRateMetric>;
  };
  
  // 评分分布
  score_distribution: {
    overall: ScoreDistribution;
    by_criterion: Map<CriterionType, ScoreDistribution>;
  };
  
  // 回归分析
  regression_analysis?: {
    verdict: "REGRESSION" | "DRIFT" | "NO_CHANGE";
    baseline_run_id: string;
    pass_rate_change: number;
    score_change: number;
    trajectory_similarity: number;
    failed_cases: FailedCase[];
  };
  
  // 成本报告
  cost_report: {
    token_usage: number;
    estimated_cost_usd: number;
    cost_per_task: number;
    cost_saving_pct?: number;  // 子集评估时
  };
  
  // 失败归因汇总
  failure_summary: {
    by_root_cause: Map<RootCauseCategory, number>;
    by_phase: Map<Phase, number>;
  };
}

interface PassRateMetric {
  total_tasks: number;
  passed_tasks: number;
  failed_tasks: number;
  pass_rate: number;
  confidence_interval_95?: [number, number];
}

interface ScoreDistribution {
  mean: number;
  median: number;
  std_dev: number;
  percentiles: {p25: number, p50: number, p75: number, p95: number};
  histogram: {bins: number[], counts: number[]};
}
```

### 9.2 CI友好报告格式

**JUnit XML格式**（对标Cursor）：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<testsuites name="Agent Evaluation" tests="100" failures="15" errors="2" time="7200">
  <testsuite name="REAL_OWN_REPO" tests="30" failures="5" errors="1" time="2400">
    <testcase classname="REAL_OWN_REPO" name="task-001" time="60">
      <failure message="Functional correctness score 0.65 below threshold 0.7">
        Score: 0.65
        Threshold: 0.7
        Evidence: Test case test_login failed
      </failure>
    </testcase>
    <testcase classname="REAL_OWN_REPO" name="task-002" time="45"/>
    <!-- ... -->
  </testsuite>
  <!-- ... -->
</testsuites>
```

**JSON格式**：

```json
{
  "evaluation_run_id": "eval-20260930-001",
  "summary": {
    "pass_rate": 0.85,
    "total_tasks": 100,
    "passed": 85,
    "failed": 15
  },
  "regression": {
    "verdict": "NO_CHANGE",
    "confidence": 0.95
  },
  "cost": {
    "token_usage": 500000,
    "estimated_cost_usd": 2.5
  }
}
```

### 9.3 发布渠道

| 渠道 | 目标受众 | 格式 |
|------|----------|------|
| 评估仪表板 | 评估工程师、ML工程师 | HTML |
| CI系统 | 开发者 | JUnit XML、JSON |
| 告警通知 | SRE工程师 | Email、Slack |
| 数据仓库 | 分析师 | Parquet、CSV |

---

## 十、CI/CD集成

### 10.1 GitHub Action集成

```yaml
# .github/workflows/agent-eval.yml
name: Agent Evaluation

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

jobs:
  eval:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Run Agent Evaluation
        uses: ai-agent-platform/eval-action@v1
        with:
          evaluation-suite: pr-eval-suite
          evaluation-mode: subset
          subset-ratio: 0.1
          fail-on-regression: true
          
      - name: Upload Results
        uses: actions/upload-artifact@v3
        with:
          name: evaluation-report
          path: reports/evaluation-report.json
          
      - name: Publish JUnit Report
        uses: dorny/test-reporter@v1
        with:
          name: Agent Evaluation Results
          path: reports/junit-report.xml
          reporter: java-junit
```

### 10.2 通用Webhook集成

```typescript
// Webhook接口
interface WebhookPayload {
  event_type: "evaluation_started" | "evaluation_completed" | "regression_detected";
  evaluation_run_id: string;
  timestamp: timestamp;
  
  // 针对evaluation_completed
  report?: EvaluationReport;
  
  // 针对regression_detected
  regression_details?: RegressionDetails;
}

// CI系统配置
{
  "webhook_url": "https://ci.example.com/hooks/agent-eval",
  "events": ["evaluation_completed", "regression_detected"],
  "auth": {
    "type": "bearer_token",
    "token": "{{WEBHOOK_SECRET}}"
  }
}
```

### 10.3 CI状态更新

```
评估状态映射到CI状态：
- RUNNING → pending
- COMPLETED + pass_rate >= threshold → success
- COMPLETED + pass_rate < threshold → failure
- FAILED → error
- REGRESSION_DETECTED → failure
```

---

## 十一、评估仪表板

### 11.1 核心功能

| 功能模块 | 功能 | 说明 |
|----------|------|------|
| **套件管理** | 创建、编辑、删除、克隆套件 | 支持版本化和权限控制 |
| **执行控制** | 启动、暂停、取消、重试评估 | 实时控制评估流程 |
| **进度监控** | 实时显示执行进度、资源使用 | WebSocket推送更新 |
| **结果查看** | 查看报告、轨迹回放、对比分析 | 多维度可视化 |
| **配置管理** | 管理评估策略、阈值、通知规则 | 配置即代码 |

### 11.2 关键视图

**视图1：套件列表**

```
┌────────────────────────────────────────────────────────┐
│ 评估套件                                                │
├────────────────────────────────────────────────────────┤
│ 名称             任务数  最后执行      通过率  操作     │
├────────────────────────────────────────────────────────┤
│ pr-eval-suite      10   2分钟前        90%   [执行]   │
│ main-eval-suite   100   1小时前        85%   [执行]   │
│ release-eval     100   昨天           88%   [执行]   │
└────────────────────────────────────────────────────────┘
```

**视图2：执行监控**

```
┌────────────────────────────────────────────────────────┐
│ 评估执行：eval-20260930-001                             │
├────────────────────────────────────────────────────────┤
│ 进度：45/100 (45%)  ████████░░░░░░░░░░░░               │
│ 状态：RUNNING       预计剩余时间：15分钟                │
│                                                        │
│ 通过：35  失败：10  运行中：5                          │
│ Token使用：250K / 500K                                 │
│                                                        │
│ 最近完成任务：                                          │
│ ✓ task-045  PASS  score=0.92  30s                    │
│ ✗ task-044  FAIL  score=0.58  45s                    │
└────────────────────────────────────────────────────────┘
```

**视图3：回归分析**

```
┌────────────────────────────────────────────────────────┐
│ 回归分析                                                │
├────────────────────────────────────────────────────────┤
│ 判定：NO_CHANGE  置信度：95%                           │
│                                                        │
│ 通过率变化：85% → 85% (0%)                             │
│ 评分变化：0.78 → 0.79 (+0.01)                          │
│ 轨迹相似度：0.92                                        │
│                                                        │
│ 按血缘类型：                                            │
│ REAL_OWN_REPO:    80% → 82% (+2%)                     │
│ REAL_EXTERNAL:    85% → 85% (0%)                      │
│ SYNTH_PROPERTY:   90% → 88% (-2%)                     │
└────────────────────────────────────────────────────────┘
```

---

## 十二、异常与失败处理

| 异常场景 | 检测条件 | 处理策略 | 降级方案 |
|----------|----------|----------|----------|
| 任务执行超时 | 执行时间 > timeout_threshold | 标记TIMEOUT，进入失败归因 | 记录超时证据，计入失败统计 |
| 评分器不可用 | 评分API返回503/504 | 切换备用评分器 | 降级为确定性检查 |
| 轨迹存储失败 | 写入返回错误 | 本地缓存+重试3次 | 告警+人工处理 |
| 子集选择失败 | 轨迹嵌入失败 | 回退到随机采样 | 记录并告警 |
| 资源耗尽 | CPU/内存/磁盘超限 | 暂停任务，等待资源 | 动态调整并行度 |
| CI连接失败 | Webhook超时 | 本地缓存结果+定时重试 | 最多重试3次 |
| 容器启动失败 | 容器创建超时 | 重试1次 | 标记ERROR |

---

## 十三、性能、成本、延迟考量

### 13.1 性能目标

| 指标 | 目标 | 说明 |
|------|------|------|
| 标准套件执行时间 | < 2小时 | 100任务，全量评估，8并发 |
| 子集评估执行时间 | < 15分钟 | 10%子集，8并发 |
| 增量评估执行时间 | < 30分钟 | 变更任务，8并发 |
| 单任务评估延迟P95 | < 60秒 | 不含Agent执行时间 |
| 并行吞吐量 | 50任务/分钟 | 理论最大值 |
| 轨迹回放延迟 | < 5秒 | 单次回放 |

### 13.2 成本控制策略

| 策略 | 预期节省 | 实现方式 |
|------|----------|----------|
| 轨迹感知子集选择 | 50-90% | §五节算法 |
| 并行执行优化 | 30% | §七节策略 |
| 评分路由优化 | 40% | 确定性检查优先 |
| 增量评估 | 60% | 仅评估变更任务 |
| 评分缓存 | 20% | 相同任务避免重复评分 |

**成本预算示例**：

```
假设：
- 全量套件：100任务
- 平均每任务Token：5000
- Token单价：$0.005/1K

全量成本：
100 × 5000 × $0.005/1000 = $2.5

子集成本（10%）：
10 × 5000 × $0.005/1000 = $0.25
节省：90%

增量成本（20%变更）：
20 × 5000 × $0.005/1000 = $0.5
节省：80%
```

### 13.3 延迟优化

| 优化项 | 收益 | 说明 |
|--------|------|------|
| 并行执行 | 8倍加速 | 8并发 vs 串行 |
| 评分缓存 | 30%减少 | 避免重复评分 |
| 轨迹压缩 | 50%减少 | 存储和传输 |
| 懒加载 | 40%减少 | 按需加载轨迹 |

---

## 十四、权限、安全与合规

### 14.1 权限控制矩阵

| 角色 | 创建套件 | 执行评估 | 查看报告 | 管理配置 | 审核回归 | 回放轨迹 |
|------|----------|----------|----------|----------|----------|----------|
| 评估工程师 | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ |
| ML工程师 | ✗ | ✓ | ✓ | ✗ | ✗ | ✓ |
| 发布经理 | ✗ | ✗ | ✓ | ✗ | ✓ | ✗ |
| SRE工程师 | ✗ | ✗ | ✓ | ✗ | ✓ | ✓ |
| 审计员 | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ |

### 14.2 安全约束

**评估执行安全**：
- 评估在隔离容器中运行（§七.2）
- 容器间无共享状态
- 网络访问受限
- 文件系统隔离

**数据安全**：
- 轨迹数据按SEC-008脱敏
- 评估结果不可修改，仅追加
- 敏感任务（REAL_OWN_REPO）评估需要额外授权
- 轨迹数据按租户隔离

**审计追踪**：
- 所有评估操作关联actor_id
- 操作时间戳、IP地址记录
- 配置变更版本化
- 审计日志不可篡改

### 14.3 合规要求

**数据留存**（对齐RT-008）：

| 数据类型 | 留存期 | 存储类型 | 说明 |
|----------|--------|----------|------|
| 评估报告 | 2年 | 热存储30天+冷存储 | 合规最低要求 |
| 轨迹数据 | 180天 | 分层存储 | 可追溯窗口 |
| 封存评估 | 永久 | WORM | 里程碑版本 |
| 审计日志 | 5年 | WORM | 合规要求 |

**删除权限**：
- 仅合规团队有权申请删除
- 删除申请需数据治理委员会审批
- 删除操作记录完整审计日志

---

## 十五、与其他模块的接口

### 15.1 前置依赖

| 依赖 | 版本 | 接口 | 说明 |
|------|------|------|------|
| REQ-EVA-001 | v0.1-designed | Golden Dataset | 任务集合、血缘分类、Oracle |
| REQ-EVA-003 | v0.1-designed | JudgmentResult | 自动评分器 |
| REQ-EVA-004 | v0.1-designed | AttributionResult | 失败归因 |
| REQ-RT-003 | v0.1-designed | Event Schema | 轨迹记录格式 |
| REQ-RT-006 | v0.1-designed | Trace传播 | trace_id关联 |
| REQ-HAR-001 | v0.1-designed | Harness生命周期 | 执行接口 |

### 15.2 输出接口

| 接口 | 消费者 | 说明 |
|------|--------|------|
| `EvaluationReport` | REQ-EVA-006、发布经理、ML工程师 | 聚合报告 |
| `EvaluationRecord` | REQ-EVA-006 | 评估记录 |
| `ATIFTrajectory` | ML工程师、评估工程师 | 轨迹数据 |
| `RegressionAlert` | SRE工程师 | 回归告警 |
| `CIStatus` | CI/CD系统 | 执行状态 |
| `EvaluationMetrics` | REQ-OBS-003 | 可观测性指标 |

---

## 十六、验收标准

| 验收项 | 验收条件 | 验证方法 |
|--------|----------|----------|
| V1 | 评估套件支持创建、编辑、删除、版本化 | 功能测试 |
| V2 | 支持全量/子集/增量三种评估模式 | 集成测试 |
| V3 | 子集评估节省≥50% Token成本 | 对比测试（历史基线） |
| V4 | 轨迹记录完整，ATIF格式符合规范 | Schema验证 |
| V5 | 轨迹回放成功率≥95% | 样本回放验证（N=50） |
| V6 | 回归检测检出率≥90%，误报率≤10% | holdout集验证（注入已知回归） |
| V7 | 评估报告包含通过率、评分分布、回归分析、成本报告 | 报告审查 |
| V8 | CI集成可用，GitHub Action和Webhook支持 | CI测试（实际PR） |
| V9 | 标准套件执行时间<2小时，子集<15分钟 | 性能测试 |
| V10 | 并行执行稳定，无资源泄漏 | 压力测试（连续运行24小时） |
| V11 | 评估数据治理符合RT-008要求 | 合规审计 |
| V12 | 评估仪表板可用，核心功能完整 | UAT测试 |

---

## 十七、版本与演进考虑

### 17.1 版本管理

```
评估流水线版本 = major.minor.patch
- major: 评估架构变更（如新增评估类型）
- minor: 子集选择算法改进、报告格式变更
- patch: bug修复、性能优化

示例：
v1.0.0 → 初始版本（全量评估+基础报告）
v1.1.0 → 新增轨迹感知子集选择
v1.2.0 → 新增回归检测
v1.2.1 → 修复轨迹回放bug
v2.0.0 → 新增多Agent协作评估
```

### 17.2 演进路线

| 阶段 | 内容 | 预期时间 | 关键交付物 |
|------|------|----------|-----------|
| **MVP (v1.0)** | 全量评估、基础报告、CI集成 | 当前版本 | 三层管道、GitHub Action |
| **V1.1** | 轨迹感知子集选择、回归检测 | +1个月 | 子集选择算法、回归检测报告 |
| **V1.2** | 增量评估、成本优化 | +2个月 | 增量模式、成本仪表板 |
| **V1.3** | 自适应并行、智能调度 | +3个月 | 动态并行度、优先级队列 |
| **V2.0** | 多Agent协作评估、持续学习 | +6个月 | 协作评估框架、学习反馈 |

### 17.3 向后兼容性

**数据兼容性**：
- 轨迹格式向后兼容（ATIF v1.x）
- 报告Schema字段只增不减
- 废弃字段标记`@deprecated`

**接口兼容性**：
- API版本化（/v1/eval、/v2/eval）
- Webhook payload版本字段
- CI Action向后兼容

---

## 十八、附录

### 18.1 术语表

| 术语 | 定义 |
|------|------|
| **ATIF** | Agent Trajectory Intermediate Format，Agent轨迹中间格式 |
| **轨迹感知** | Trajectory-Aware，基于执行轨迹的分析方法 |
| **几何选择** | Geometric Selection，在嵌入空间选择最接近质心的样本 |
| **回归检测** | Regression Detection，检测Agent行为相对基线的退化 |
| **子集评估** | Subset Evaluation，仅评估部分任务以节省成本 |
| **增量评估** | Incremental Evaluation，仅评估变更任务 |
| **效应量** | Effect Size，统计差异的实际意义大小（如Cohen's d） |

### 18.2 参考文献

1. OpenAI. (2026). *Testing Agent Skills Systematically with Evals*. https://developers.openai.com/blog/eval-skills. 访问日期：2026-09-30
2. Cursor. (2026). *Agent SDK Evals Documentation*. https://cdn.jsdelivr.net/npm/@cursor/july@0.2.1/dist/docs/evals.md. 访问日期：2026-09-30
3. DeepSeek. (2026). *DeepSeek-V4.1-Flash Evaluation*. https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash. 访问日期：2026-09-30
4. NxCode. (2026). *Kimi K3 Benchmarks Explained*. https://www.nxcode.io/resources/news/kimi-k3-benchmarks-coding-agent-evaluation-guide-2026. 访问日期：2026-09-30
5. arXiv. (2026). *Trajectory-Aware Benchmark Subset Selection*. https://arxiv.org/pdf/2609.24928v1. 访问日期：2026-09-30
6. Fast.io. (2026). *Manus AI Software Testing Workflow*. https://fast.io/resources/manus-ai-software-testing-workflow/. 访问日期：2026-09-30

---

**文档版本**：v0.1  
**文档状态**：designed  
**最后更新**：2026-09-30  
**维护团队**：评估工程组
