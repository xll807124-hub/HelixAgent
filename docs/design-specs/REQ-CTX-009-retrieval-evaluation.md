# REQ-CTX-009: 检索评测

> **需求编号**: REQ-CTX-009  
> **需求名称**: 检索评测  
> **优先级**: P1  
> **所属模块**: 上下文管理（CTX）  
> **状态**: v0.1-designed  
> **设计日期**: 2026-10-04  
> **前置依赖**: REQ-CTX-002（语言、仓库规模和基准集）、REQ-EVA-001（Golden Dataset）

---

## 一、需求目标

### 1.1 功能目标

建立多层次检索评测体系，支持离线指标评测、在线效果评测、端到端任务正确率关联分析，为检索算法优化和发布决策提供量化依据。

**核心交付**：
1. 离线检索指标评测（Recall@K、Precision@K、MRR@K、NDCG@K）
2. 延迟指标评测（p50/p95/p99、SLO 合规率）
3. 端到端任务正确率关联分析
4. 安全评测（敏感路径阻断率、权限过滤效果）
5. 自动化评测流水线（CI/CD 集成）
6. 可视化仪表板与告警机制

### 1.2 用户价值

| 价值维度 | 具体收益 |
|----------|----------|
| 算法优化 | 量化指标指导检索算法调优，避免盲目调参 |
| 发布质量 | CI/CD 集成阻断不合格发布，确保质量 |
| 用户体验 | 在线指标反映真实用户满意度 |
| 安全合规 | 验证权限过滤和敏感路径阻断效果 |
| 成本优化 | 评测频率和采样策略优化评测成本 |

### 1.3 行业对标

本设计参考以下行业标杆（未联网验证，基于已有知识）：

| 产品 | 核心架构 | 关键技术 | 可借鉴点 |
|------|----------|----------|----------|
| **Sourcegraph** | 两阶段评测（召回+重排） | BM25F、Cross-Encoder | 多层评测架构 |
| **GitHub Copilot** | 端到端评测 | HumanEval、延迟SLO | SLO定义与监控 |
| **DeepSeek** | 离线+成本评测 | RRF融合、Token消耗 | 成本效益框架 |
| **通义灵码** | 多维度评测 | Recall/Precision/F1 | 多语言差异化评测 |
| **SWE-bench** | 任务正确率评测 | Oracle判定、污染控制 | 端到端关联分析 |

---

## 二、设计范围

### 2.1 包含内容

1. ✅ 离线检索指标评测（Recall、Precision、MRR、NDCG）
2. ✅ 延迟指标评测（p50/p95/p99、SLO合规率）
3. ✅ 端到端任务正确率关联分析
4. ✅ 安全评测（敏感路径阻断率）
5. ✅ 评测基准集管理（复用Golden Dataset）
6. ✅ 自动化评测流水线
7. ✅ 可视化仪表板
8. ✅ CI/CD集成
9. ✅ 告警与优化建议

### 2.2 不包含内容（后续阶段）

1. ❌ 学习型评测（基于反馈自动优化）（Phase 3）
2. ❌ 检索-任务因果推断（Phase 3）
3. ❌ 多模态评测（代码+文档+图表）（Phase 3）
4. ❌ 企业级高级报表（Phase 2）

---

## 三、目标用户与使用场景

### 3.1 目标用户

| 用户类型 | 使用场景 |
|----------|----------|
| **算法工程师** | 发布前验证检索算法改动效果 |
| **数据科学家** | 分析检索质量与任务正确率的相关性 |
| **SRE** | 监控检索系统延迟SLO合规性 |
| **安全工程师** | 验证权限过滤和安全策略有效性 |
| **产品经理** | 查看检索系统质量报表 |
| **CI/CD系统** | 自动执行回归评测、阻断不合格发布 |

### 3.2 典型使用场景

**场景1：算法优化验证**

```
作为算法工程师
我需要在发布新检索算法前验证效果提升
以便决定是否上线新算法

流程：
1. 在Golden Dataset上执行旧配置评测
2. 在Golden Dataset上执行新配置评测
3. 对比Recall@20、MRR@10、延迟指标
4. 如果关键指标提升且无退化，则批准发布
```

**场景2：SLO合规监控**

```
作为SRE
我需要每日验证检索系统是否满足延迟SLO
以便及时发现性能退化

流程：
1. 抽取生产流量样本（1000条）
2. 执行检索评测，记录p50/p95/p99延迟
3. 对比SLO阈值（如p95<500ms）
4. 如果超标，触发告警并生成诊断报告
```

**场景3：端到端效果分析**

```
作为数据科学家
我需要分析检索质量与任务正确率的关联
以便指导检索算法优化方向

流程：
1. 收集一批任务执行数据（检索日志+任务结果）
2. 按Recall@20分桶统计任务成功率
3. 计算Pearson相关系数
4. 如果相关性显著，则优先提升Recall
```

---

## 四、输入与输出定义

### 4.1 输入定义

```typescript
// 评测任务输入
interface EvaluationTask {
  task_id: string;
  task_type: EvaluationType;
  dataset_id: string;              // 基准数据集ID
  repository_scope: RepositoryScope;
  config: EvaluationConfig;
  schedule: ScheduleType;
  user_id: string;
  organization_id: string;
}

type EvaluationType = 
  | 'RETRIEVAL_OFFLINE'      // 离线检索指标评测
  | 'RETRIEVAL_ONLINE'       // 在线检索效果评测
  | 'RETRIEVAL_ENDTOEND'     // 端到端任务正确率评测
  | 'RETRIEVAL_SECURITY'     // 权限过滤安全评测
  | 'RETRIEVAL_REGRESSION';  // 回归评测

type RepositoryScope = 
  | 'ALL'                    // 所有支持仓库
  | 'TIER_1_LANGUAGES'       // TIER_1语言仓库
  | 'SPECIFIC_REPOS';        // 指定仓库列表

interface EvaluationConfig {
  metrics: MetricType[];           // 需要评测的指标列表
  k_values: number[];              // K值配置（如[5,10,20,50]）
  latency_slo: LatencySLO;         // 延迟SLO阈值
  sample_size?: number;            // 采样大小（在线评测用）
}

type MetricType =
  | 'RECALL_AT_K'
  | 'PRECISION_AT_K'
  | 'MRR_AT_K'
  | 'NDCG_AT_K'
  | 'LATENCY_P50'
  | 'LATENCY_P95'
  | 'LATENCY_P99'
  | 'SLO_COMPLIANCE'
  | 'TASK_SUCCESS_RATE'
  | 'RETRIEVAL_CONTRIBUTION'
  | 'SENSITIVE_BLOCK_RATE';

interface LatencySLO {
  p50_ms: number;
  p95_ms: number;
  p99_ms: number;
}

type ScheduleType =
  | 'MANUAL'           // 手动触发
  | 'PRE_RELEASE'      // 发布前自动执行
  | 'DAILY'            // 每日定时
  | 'WEEKLY';          // 每周定时
```

### 4.2 输出定义

```typescript
// 评测报告
interface EvaluationReport {
  report_id: string;
  task_id: string;
  timestamp: Timestamp;
  duration_ms: number;
  status: ExecutionStatus;
  results: EvaluationResults;
  comparison?: ComparisonResult;
  recommendations: Recommendation[];
  trace_id: string;
}

type ExecutionStatus =
  | 'SUCCESS'          // 成功完成
  | 'PARTIAL'          // 部分完成（有指标计算失败）
  | 'FAILED';          // 执行失败

interface EvaluationResults {
  offline_metrics?: OfflineMetrics;
  latency_metrics?: LatencyMetrics;
  endtoend_metrics?: EndToEndMetrics;
  security_metrics?: SecurityMetrics;
}

interface OfflineMetrics {
  recall_at_k: Map<number, number>;      // Recall@K
  precision_at_k: Map<number, number>;   // Precision@K
  mrr_at_k: Map<number, number>;         // MRR@K
  hit_rate_at_k: Map<number, number>;    // HitRate@K
  ndcg_at_k: Map<number, number>;        // NDCG@K
}

interface LatencyMetrics {
  p50_ms: number;
  p95_ms: number;
  p99_ms: number;
  avg_ms: number;
  slo_compliance_rate: number;
}

interface EndToEndMetrics {
  task_success_rate: number;
  retrieval_contribution_score: number;
  correlation_with_recall: number;
}

interface SecurityMetrics {
  sensitive_path_block_rate: number;
  unauthorized_access_attempt_rate: number;
}

interface ComparisonResult {
  baseline_report_id: string;
  metric_deltas: Map<string, number>;
  regression_detected: boolean;
  regression_details: RegressionDetail[];
}

interface Recommendation {
  priority: 'HIGH' | 'MEDIUM' | 'LOW';
  description: string;
  expected_impact: string;
}
```

---

## 五、处理逻辑与流程

### 5.1 总体流程

```
评测请求
    │
    ▼
┌─────────────────┐
│ 评测任务解析     │
│ - 验证参数合法性 │
│ - 加载基准数据集 │
│ - 初始化评测环境 │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 数据准备         │
│ - 抽取评测查询集 │
│ - 准备ground truth│
│ - 权限上下文构造 │
└────────┬────────┘
         │
         ▼
┌─────────────────┬─────────────────┬─────────────────┐
│ 离线评测        │ 在线评测        │ 端到端评测      │
│ (并行执行)      │ (并行执行)      │ (并行执行)      │
└────────┬────────┴────────┬────────┴────────┬────────┘
         │                  │                  │
         ▼                  ▼                  ▼
┌─────────────────┬─────────────────┬─────────────────┐
│ Recall@K        │ 采纳率分析      │ 任务成功率      │
│ Precision@K     │ 用户满意度      │ 检索贡献度      │
│ MRR@K           │ 转化漏斗        │ 因果关联分析    │
└────────┬────────┴────────┬────────┴────────┬────────┘
         │                  │                  │
         └──────────────────┼──────────────────┘
                            ▼
                   ┌─────────────────┐
                   │ 结果聚合与报告   │
                   │ - 指标汇总       │
                   │ - 对比分析       │
                   │ - 建议生成       │
                   └────────┬────────┘
                            │
                            ▼
                   ┌─────────────────┐
                   │ 结果存储与告警   │
                   │ - 写入时序库    │
                   │ - 触发阈值告警  │
                   └─────────────────┘
```

### 5.2 离线检索评测流程

**步骤1：查询集准备**

```
操作：
1. 从Golden Dataset加载评测查询集
2. 构造检索查询（query_text, repository_id, source_revision）
3. 验证查询覆盖度（按语言、复杂度分层）

数据结构：
QuerySet {
  queries: Query[];
  coverage_report: CoverageReport;
}
```

**步骤2：Ground Truth构建**

```
操作：
1. 对每条查询，标注相关代码块
2. 标注方式：
   - 人工标注（高质量，成本高）
   - LLM辅助标注（效率高，需人工复审）
   - 任务执行轨迹挖掘（真实场景）
3. 记录相关性等级（完全相关/部分相关/不相关）

数据结构：
GroundTruth {
  query_id: string;
  relevant_chunks: RelevantChunk[];
}

RelevantChunk {
  chunk_id: string;
  relevance_level: 'FULLY_RELEVANT' | 'PARTIALLY_RELEVANT' | 'NOT_RELEVANT';
  annotation_source: 'HUMAN' | 'LLM_ASSISTED' | 'TRAJECTORY_MINING';
}
```

**步骤3：检索执行**

```
操作：
1. 调用检索接口（REQ-CTX-004）
2. 按配置执行多次（去除缓存影响）
3. 记录每次的返回结果和耗时

伪代码：
for i in 1..num_runs:
    start_time = now()
    results = retrieval_service.retrieve(query)
    end_time = now()
    record_result(results, end_time - start_time)
```

**步骤4：指标计算**

```
Recall@K计算：
  公式：Recall@K = |Relevant ∩ Retrieved@K| / |Relevant|
  - Relevant：Ground Truth中的相关文档集合
  - Retrieved@K：检索返回的Top-K结果

Precision@K计算：
  公式：Precision@K = |Relevant ∩ Retrieved@K| / K

MRR@K计算：
  公式：MRR = (1/N) × Σ(1/rank_i)
  - rank_i：第i个查询的首个相关文档排名
  - 如果无相关文档，rank_i=∞，贡献为0

NDCG@K计算：
  公式：NDCG@K = DCG@K / IDCG@K
  - DCG@K = Σ(rel_i / log2(i+1))
  - IDCG@K：理想DCG（按相关性排序）
```

**步骤5：结果聚合**

```
分组统计：
- 按语言分组（Python、TypeScript、Go等）
- 按仓库规模分组（SMALL、MEDIUM、LARGE）
- 按查询类型分组（精确符号、语义描述、结构导航）

输出格式：
GroupedMetrics {
  group_by: 'LANGUAGE' | 'REPOSITORY_SIZE' | 'QUERY_TYPE';
  metrics: Map<string, OfflineMetrics>;
}
```

### 5.3 端到端任务正确率关联分析流程

**步骤1：任务执行数据收集**

```
数据来源：
- 任务日志（Task execution logs）
- 检索日志（Retrieval logs）
- 任务结果（Task outcomes）

关联方式：
- 通过trace_id关联检索请求和任务执行
- 提取检索质量指标（Recall、相关性分数）
- 提取任务结果（成功/失败、完成质量）
```


**步骤2：分桶分析**

```
操作：
1. 按Recall@K分桶（如0-0.2, 0.2-0.4, ..., 0.8-1.0）
2. 统计每个桶的任务成功率
3. 绘制Recall-Success散点图

数据结构：
BucketAnalysis {
  buckets: Bucket[];
}

Bucket {
  recall_range: [number, number];
  task_count: number;
  success_rate: number;
}
```

**步骤3：相关性计算**

```
Pearson相关系数：
  公式：r = Cov(X,Y) / (σX × σY)
  - X：Recall@K
  - Y：任务成功率
  - 衡量线性相关

Spearman相关系数：
  - 衡量单调相关
  - 适用于非线性关系

统计显著性检验：
  - H0：Recall与任务成功率无关
  - p-value < 0.05：拒绝H0，相关性显著
```

**步骤4：因果推断**

```
回归分析：
  模型：TaskSuccess = β0 + β1×Recall + β2×TaskComplexity + ε
  - β1：检索质量对任务成功的影响系数
  - 控制混淆变量（任务复杂度、模型能力）

检索贡献度归因：
  使用Shapley值分解各因素贡献
  检索贡献 = Σ(边际贡献) / Σ(所有边际贡献)
```

---

## 六、算法设计分析

### 6.1 离线指标计算算法

**Recall@K算法实现**

```python
def calculate_recall_at_k(retrieved: List[str], relevant: Set[str], k: int) -> float:
    """
    计算Recall@K
    
    Args:
        retrieved: 检索返回的文档ID列表
        relevant: Ground Truth相关文档ID集合
        k: Top-K截断
    
    Returns:
        Recall@K值
    """
    if not relevant:
        return 0.0
    
    retrieved_at_k = set(retrieved[:k])
    intersection = retrieved_at_k & relevant
    
    return len(intersection) / len(relevant)
```

**MRR@K算法实现**

```python
def calculate_mrr_at_k(retrieved: List[str], relevant: Set[str], k: int) -> float:
    """
    计算MRR@K（Mean Reciprocal Rank）
    
    Args:
        retrieved: 检索返回的文档ID列表
        relevant: Ground Truth相关文档ID集合
        k: Top-K截断
    
    Returns:
        首个相关文档排名的倒数
    """
    for rank, doc_id in enumerate(retrieved[:k], start=1):
        if doc_id in relevant:
            return 1.0 / rank
    
    return 0.0  # 无相关文档
```

**NDCG@K算法实现**

```python
def calculate_ndcg_at_k(retrieved: List[str], relevance_scores: Dict[str, float], k: int) -> float:
    """
    计算NDCG@K（Normalized Discounted Cumulative Gain）
    
    Args:
        retrieved: 检索返回的文档ID列表
        relevance_scores: 文档相关性评分字典 {doc_id: score}
        k: Top-K截断
    
    Returns:
        NDCG@K值
    """
    # 计算DCG
    dcg = 0.0
    for rank, doc_id in enumerate(retrieved[:k], start=1):
        rel = relevance_scores.get(doc_id, 0.0)
        dcg += rel / math.log2(rank + 1)
    
    # 计算IDCG（理想DCG）
    ideal_scores = sorted(relevance_scores.values(), reverse=True)[:k]
    idcg = sum(rel / math.log2(rank + 1) for rank, rel in enumerate(ideal_scores, start=1))
    
    if idcg == 0:
        return 0.0
    
    return dcg / idcg
```

### 6.2 延迟指标计算算法

**分位数计算（T-Digest算法）**

```python
def calculate_percentiles(latencies: List[float]) -> LatencyMetrics:
    """
    使用T-Digest算法计算精确分位数
    
    Args:
        latencies: 延迟样本列表（毫秒）
    
    Returns:
        延迟指标
    """
    from tdigest import TDigest
    
    digest = TDigest()
    for latency in latencies:
        digest.update(latency)
    
    return LatencyMetrics(
        p50_ms=digest.percentile(50),
        p95_ms=digest.percentile(95),
        p99_ms=digest.percentile(99),
        avg_ms=sum(latencies) / len(latencies),
        slo_compliance_rate=calculate_slo_compliance(latencies, slo_threshold)
    )
```

**SLO合规率计算**

```python
def calculate_slo_compliance(latencies: List[float], slo: LatencySLO) -> float:
    """
    计算SLO合规率
    
    Args:
        latencies: 延迟样本列表
        slo: SLO阈值定义
    
    Returns:
        合规率（0.0-1.0）
    """
    from tdigest import TDigest
    
    digest = TDigest()
    for latency in latencies:
        digest.update(latency)
    
    p95 = digest.percentile(95)
    
    # 判断p95是否满足SLO
    compliant = p95 <= slo.p95_ms
    
    return 1.0 if compliant else 0.0
```

### 6.3 相关性分析算法

**Pearson相关系数**

```python
def calculate_pearson_correlation(recall_values: List[float], success_rates: List[float]) -> float:
    """
    计算Pearson相关系数
    
    Args:
        recall_values: Recall值列表
        success_rates: 任务成功率列表
    
    Returns:
        Pearson相关系数 r
    """
    import numpy as np
    
    if len(recall_values) != len(success_rates):
        raise ValueError("输入列表长度必须相同")
    
    correlation_matrix = np.corrcoef(recall_values, success_rates)
    
    return correlation_matrix[0, 1]
```

**统计显著性检验**

```python
def test_correlation_significance(r: float, n: int, alpha: float = 0.05) -> bool:
    """
    检验相关性统计显著性
    
    Args:
        r: Pearson相关系数
        n: 样本量
        alpha: 显著性水平（默认0.05）
    
    Returns:
        是否显著（True/False）
    """
    import scipy.stats as stats
    
    # 计算t统计量
    t = r * math.sqrt(n - 2) / math.sqrt(1 - r**2)
    
    # 双尾检验
    p_value = 2 * (1 - stats.t.cdf(abs(t), n - 2))
    
    return p_value < alpha
```

---

## 七、异常与失败处理

### 7.1 异常分类与处理策略

| 异常类型 | 检测条件 | 处理策略 | 降级方案 |
|----------|----------|----------|----------|
| 基准数据集缺失 | dataset_id不存在 | 返回错误，终止评测 | 提示用户上传数据集 |
| 评测执行超时 | 执行时间 > 配置超时 | 标记为超时，返回部分结果 | 使用已计算完成的指标 |
| 检索服务不可用 | 检索接口返回错误 | 记录错误，返回失败状态 | 告警并记录日志 |
| 指标计算异常 | 除零、NaN | 跳过该指标，记录日志 | 标记为N/A |
| Ground Truth不完整 | 标注覆盖率 < 80% | 警告但继续执行 | 使用不完全标注 |
| SLO严重超标 | 合规率 < 90% | 立即告警 | 触发Kill Switch评估 |

### 7.2 错误码定义

| 错误码 | 含义 | HTTP状态码 | 处理建议 |
|--------|------|------------|----------|
| EVAL-001 | 评测任务配置错误 | 400 | 检查配置参数 |
| EVAL-002 | 基准数据集不存在 | 404 | 上传或指定正确数据集 |
| EVAL-003 | 检索服务不可用 | 503 | 稍后重试或联系运维 |
| EVAL-004 | 指标计算失败 | 500 | 检查Ground Truth数据 |
| EVAL-005 | 权限不足 | 403 | 申请相应权限 |
| EVAL-006 | 评测执行超时 | 504 | 减少查询数或优化检索 |

---

## 八、权限、安全与合规

### 8.1 评测数据权限

**访问控制规则**：

```
权限模型：
- 评测任务只能访问有权限的仓库
- Ground Truth数据按血缘类型隔离
  - SYNTH_ADVERSARIAL需特殊安全权限
  - REAL_*类型需相应仓库读权限
- 评测报告按组织隔离

数据隔离要求：
- 评测执行环境与生产环境隔离
- 评测数据不污染生产索引
- 敏感路径测试用例需脱敏后使用
```

### 8.2 安全约束

| 控制点 | 措施 |
|--------|------|
| 数据泄露防护 | 评测结果不包含敏感代码内容 |
| 污染控制 | 复用Golden Dataset的污染检测机制 |
| 审计追踪 | 所有评测操作记录审计日志 |
| 速率限制 | 每用户/每组织评测QPS限制 |
| 资源限制 | 评测任务资源配额（CPU/内存/时间） |

### 8.3 敏感路径测试

**测试用例构造**：

```
敏感路径示例：
- .env、.env.*
- secrets/、credentials/
- *.key、*.pem
- .aws/、.ssh/

测试流程：
1. 构造包含敏感路径的查询
2. 执行检索
3. 验证返回结果不包含敏感路径
4. 计算阻断率（目标：100%）
```

### 8.4 合规要求

| 要求 | 实现 |
|------|------|
| 数据驻留 | 评测数据按组织配置存储区域 |
| 留存期 | 评测报告：热存储30天 + 冷存储180天 |
| 删除响应 | 用户删除仓库时，相关评测数据同步清理 |
| 审计日志 | 所有评测操作记录trace_id、user_id、timestamp |

---

## 九、性能、成本、延迟考量

### 9.1 评测执行性能目标

| 评测规模 | 查询数量 | 执行时间目标 | 资源消耗 |
|----------|----------|--------------|----------|
| 小型 | 100查询 | < 30s | < 1 CPU, 512MB RAM |
| 中型 | 1000查询 | < 5min | < 4 CPU, 2GB RAM |
| 大型 | 10000查询 | < 30min | < 16 CPU, 8GB RAM |
| 全量 | 50000查询 | < 2h | < 64 CPU, 32GB RAM |

### 9.2 评测频率与成本

| 评测类型 | 频率 | 单次成本估算 | 月度成本估算 |
|----------|------|--------------|--------------|
| 回归评测 | 每次发布（约4次/月） | $5-20 | $20-80 |
| 每日监控 | 每日 | $5-20/天 | $150-600 |
| 每周深度评测 | 每周（约4次/月） | $50-200 | $200-800 |
| 按需评测 | 按需（约10次/月） | $10-50 | $100-500 |
| **总计** | - | - | **$470-1980/月** |

### 9.3 延迟指标SLO定义

**SLO配置**：

```
离线评测延迟：
- 单次检索：p95 < 500ms
- 批量检索（100条）：p95 < 60s

在线评测延迟：
- 采样与处理：p95 < 2s

报告生成：
- 小型报告：p95 < 5s
- 大型报告：p95 < 30s
```

**告警阈值**：

```
Warning级别：
- 指标偏离基准 > 5%
- 延迟SLO违规率 > 1%

Critical级别：
- 指标偏离基准 > 10%
- 延迟SLO违规率 > 5%
- 敏感路径泄露（任何情况）
```

---

## 十、可观测性与评估指标

### 10.1 核心指标体系

| 指标类别 | 指标名称 | 定义 | SLO | 采集频率 |
|----------|----------|------|-----|----------|
| **离线-召回** | Recall@10 | Top-10召回率 | > 85% | 每次评测 |
| **离线-召回** | Recall@20 | Top-20召回率 | > 90% | 每次评测 |
| **离线-排序** | MRR@10 | 首个相关结果排名倒数均值 | > 0.70 | 每次评测 |
| **离线-排序** | NDCG@10 | 归一化折损累计增益 | > 0.75 | 每次评测 |
| **延迟** | Latency_p50 | 50%分位延迟 | < 200ms | 实时 |
| **延迟** | Latency_p95 | 95%分位延迟 | < 500ms | 实时 |
| **延迟** | Latency_p99 | 99%分位延迟 | < 1000ms | 实时 |
| **延迟** | SLO_Compliance | SLO合规率 | > 99% | 每日 |
| **端到端** | Task_Success_Rate | 任务成功率 | > 70% | 每周 |
| **端到端** | Retrieval_Contribution | 检索贡献度 | > 0.4 | 每周 |
| **安全** | Sensitive_Block_Rate | 敏感路径阻断率 | 100% | 每次评测 |
| **安全** | Unauthorized_Access_Rate | 未授权访问尝试率 | < 0.1% | 每次评测 |

### 10.2 链路追踪

**Trace传播**：

```
追踪链路：
evaluation_task (span) 
  └─ data_preparation (span)
  └─ retrieval_execution (span)
      └─ retrieval_request_1 (span)
      └─ retrieval_request_2 (span)
      └─ ...
  └─ metric_calculation (span)
  └─ report_generation (span)

关键字段：
- trace_id: 评测任务唯一标识
- evaluation_id: 评测实例ID
- dataset_id: 基准数据集ID
- user_id: 触发者ID
- latency_ms: 各阶段耗时
```

### 10.3 仪表盘与告警

**仪表盘视图**：

```
┌─────────────────────────────────────────────────────────────┐
│                    检索评测仪表板                            │
├─────────────────────────────────────────────────────────────┤
│  指标概览                                                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐         │
│  │ Recall@20│ │ MRR@10   │ │ P95延迟  │ │ SLO合规率│         │
│  │  87.5%   │ │  0.72    │ │  342ms   │ │  99.2%   │         │
│  │  ▲ +2.1% │ │  ▲ +0.05 │ │  ▼ -12ms │ │  ▲ +0.3% │         │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘         │
├─────────────────────────────────────────────────────────────┤
│  趋势图                                                         │
│  [Recall@20趋势折线图]  [延迟分布直方图]                     │
├─────────────────────────────────────────────────────────────┤
│  分组分析                                                       │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ 语言      │ Recall@20 │ MRR@10 │ P95延迟 │ 任务成功率│    │
│  │ Python   │  89.2%   │  0.76  │  298ms  │   72.3%  │    │
│  │ TypeScript│  86.8%   │  0.71  │  356ms  │   68.9%  │    │
│  │ Go       │  85.1%   │  0.69  │  312ms  │   65.2%  │    │
│  └─────────────────────────────────────────────────────┘    │
├─────────────────────────────────────────────────────────────┤
│  告警与建议                                                     │
│  ⚠️ TypeScript MRR@10较上周下降3.2%，建议检查索引质量        │
│  💡 Python任务成功率显著高于其他语言，建议推广最佳实践          │
└─────────────────────────────────────────────────────────────┘
```

**告警规则**：

```yaml
alert_rules:
  - name: "Recall退化告警"
    condition: "recall_at_20 < baseline * 0.95"
    severity: WARNING
    notification: slack

  - name: "延迟SLO违规"
    condition: "slo_compliance_rate < 0.99"
    severity: CRITICAL
    notification: pagerduty

  - name: "敏感路径泄露"
    condition: "sensitive_block_rate < 1.0"
    severity: CRITICAL
    notification: security_channel
```

---

## 十一、验收标准

### 11.1 功能验收

| 编号 | 验收标准 | 验证方法 |
|------|----------|----------|
| CTX-009-F001 | 支持离线检索指标评测（Recall、Precision、MRR、NDCG） | 执行评测任务，验证各指标计算正确性 |
| CTX-009-F002 | 支持在线检索效果评测（采纳率、转化率） | 接入生产流量样本，执行在线评测 |
| CTX-009-F003 | 支持端到端任务正确率关联分析 | 分析历史任务数据，验证相关性计算 |
| CTX-009-F004 | 支持权限过滤安全评测 | 构造敏感路径测试用例，验证阻断率 |
| CTX-009-F005 | 支持评测任务状态追踪 | 创建评测任务，验证状态流转 |
| CTX-009-F006 | 支持历史基准对比 | 执行两次评测，验证对比报告生成 |
| CTX-009-F007 | 支持评测结果可视化仪表板 | 访问仪表板，验证数据展示 |
| CTX-009-F008 | 支持CI/CD集成 | 在CI中触发评测，验证阻断机制 |

### 11.2 性能验收

| 编号 | 验收标准 | 验证方法 |
|------|----------|----------|
| CTX-009-P001 | 离线评测p95延迟 < 500ms（单次检索） | 性能测试，1000次请求 |
| CTX-009-P002 | 评测任务执行完成率 > 99% | 长期监控，统计完成率 |
| CTX-009-P003 | 报告生成p95延迟 < 10s | 性能测试 |

### 11.3 质量验收

| 编号 | 验收标准 | 验证方法 |
|------|----------|----------|
| CTX-009-Q001 | Recall@20 > 85% | Golden Dataset评测 |
| CTX-009-Q002 | MRR@10 > 0.65 | Golden Dataset评测 |
| CTX-009-Q003 | SLO合规率 > 99% | 每日监控 |
| CTX-009-Q004 | 敏感路径阻断率 = 100% | 安全评测 |

---

## 十二、依赖与接口

### 12.1 前置依赖

| 依赖编号 | 依赖内容 | 接口要求 |
|----------|----------|----------|
| REQ-CTX-002 | 语言、仓库规模和基准集 | 基准数据集定义（语言分级、仓库规模） |
| REQ-EVA-001 | Golden Dataset | Golden Dataset接口（血缘分离、污染检测） |
| REQ-CTX-004 | 混合检索与排序 | 检索服务接口（retrieve） |
| REQ-RT-006 | Trace传播 | trace_id生成和传播 |
| REQ-SEC-002 | RBAC授权 | 权限检查接口 |
| REQ-OBS-001 | OpenTelemetry语义约定 | Span命名、属性定义 |

### 12.2 下游消费接口

| 消费需求 | 接口内容 |
|----------|----------|
| REQ-CTX-004 | 检索算法优化反馈 |
| REQ-CTX-006 | Context Selector优化反馈 |
| REQ-EVA-006 | 发布门禁数据输入 |
| REQ-OBS-003 | 指标字典数据输入 |

### 12.3 对外接口

**评测服务API**：

```typescript
interface EvaluationService {
  // 创建评测任务
  createTask(request: CreateTaskRequest): Promise<EvaluationTask>;
  
  // 执行评测
  executeTask(taskId: string): Promise<EvaluationReport>;
  
  // 查询评测结果
  getReport(reportId: string): Promise<EvaluationReport>;
  
  // 查询历史评测
  listReports(filter: ReportFilter): Promise<EvaluationReport[]>;
  
  // 对比两次评测
  compareReports(baselineId: string, currentId: string): Promise<ComparisonResult>;
}
```

---

## 十三、版本与演进计划

### 13.1 MVP版本（Phase 1）

**包含内容**：
- ✅ 离线检索指标评测（Recall、Precision、MRR、延迟）
- ✅ 基准数据集管理
- ✅ 基础仪表板
- ✅ CI/CD集成
- ✅ 权限过滤安全评测

**交付时间**：2周

### 13.2 Phase 2扩展

**包含内容**：
- 在线效果评测（采纳率分析）
- 端到端任务关联分析
- 高级仪表板（趋势、对比）
- 自动化告警
- 多语言差异化评测

**交付时间**：4周

### 13.3 Phase 3优化

**包含内容**：
- 检索-任务因果推断
- 学习型评测（基于反馈自动优化）
- 多模态评测（代码+文档+图表）
- 企业级报表
- 成本优化推荐

**交付时间**：6周

### 13.4 兼容性规则

**接口兼容性**：

```
变更类型与版本升级规则：
- 评测任务输入Schema变更：主版本升级
- 评测报告输出新增字段：次版本升级（可选字段）
- 指标定义变更：主版本升级 + 迁移期
- Bug修复：补丁版本升级
```

**数据兼容性**：

```
历史数据处理：
- 历史评测报告必须可查询
- 指标计算方法变更需要重新计算历史数据
- 提供数据迁移工具
```

---

## 十四、对其它需求的影响

### 14.1 被影响的待办

| 待办编号 | 待办名称 | 影响说明 | 影响程度 |
|----------|----------|----------|----------|
| REQ-CTX-004 | 混合检索与排序 | 评测结果反馈指导检索算法优化 | 中 |
| REQ-CTX-006 | Context Selector与预算 | 评测结果反馈指导Context Selector优化 | 中 |
| REQ-EVA-001 | Golden Dataset | 复用Golden Dataset的数据集管理机制 | 高 |
| REQ-EVA-006 | 发布门禁 | 评测结果作为发布门禁的输入 | 高 |
| REQ-OBS-003 | 指标字典 | 指标字典需要与评测指标对齐 | 中 |

### 14.2 需要同步修改

| 同步修改项 | 修改内容 |
|------------|----------|
| REQ-EVA-001 | 新增"检索评测"血缘类型到基准数据集 |
| REQ-OBS-001 | 新增评测相关的Trace语义约定 |
| REQ-OBS-003 | 新增评测指标到指标字典 |

### 14.3 潜在风险与缓解措施

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| 基准数据集不足 | 中 | 高 | 分阶段建设，初期使用有限数据集 |
| 离线-在线指标脱节 | 中 | 中 | 建立相关性校准机制 |
| 评测资源消耗过高 | 低 | 中 | 采样策略优化，优先执行关键指标 |
| 评测结果误判 | 低 | 中 | 人工审核节点，多维度验证 |

---

## 十五、参考资料

### 15.1 行业标杆文档（未联网验证）

1. **Sourcegraph Cody 检索评测**
   - 描述：两阶段检索架构（BM25F召回 → Cross-Encoder重排）
   - 关键内容：离线指标、在线指标、用户反馈闭环

2. **GitHub Copilot 延迟SLO**
   - 描述：代码补全与搜索延迟定义
   - 关键内容：p50 < 100ms, p95 < 500ms

3. **DeepSeek 检索评测**
   - 描述：三阶段流水线评测
   - 关键内容：离线指标、成本指标、任务指标

4. **SWE-bench / SWE-bench Verified**
   - 描述：软件工程任务评测基准
   - 关键内容：任务正确率、污染检测、Oracle判定

5. **Easy2Hard-Bench**
   - 描述：IRT模型难度校准
   - 关键内容：数值难度分数、多维难度参数

---

## 十六、变更记录

| 版本 | 日期 | 变更内容 | 作者 |
|------|------|----------|------|
| v0.1-designed | 2026-10-04 | 初始设计完成，定义三层评测体系、多维度指标、自动化流水线 | 架构团队 |

---

**文档结束**
