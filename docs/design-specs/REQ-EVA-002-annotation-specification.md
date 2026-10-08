# REQ-EVA-002: 标注规范详细设计

> **需求编号**：REQ-EVA-002  
> **需求名称**：标注规范（Annotation Specification）  
> **优先级**：P0  
> **状态**：v0.1-designed  
> **设计完成日期**：2026-09-27  
> **前置依赖**：REQ-EVA-001 Golden Dataset  
> **后续依赖**：REQ-EVA-003 自动评分器、REQ-EVA-004 失败归因

---

## 一、需求概述

### 1.1 设计目标

建立**系统化、可复现、可校准**的任务标注规范，为 AI Agent 任务执行质量评估提供统一的标注框架，支持：

1. **Oracle 验证层**：定义任务预期结果的可验证性标准
2. **上下文需求层**：识别任务完成所需的必要上下文
3. **质量评估层**：多维度量化任务执行质量
4. **难度评估层**：IRT 校准任务难度参数
5. **失败归因层**：系统化分类失败原因
6. **一致性校验层**：确保标注者间一致性

### 1.2 核心问题

**问题陈述**：
- **无统一评分标准**：不同标注者对"任务成功"的判断不一致
- **Must-have 与 Nice-to-have 混淆**：硬性要求与软性偏好未分离
- **质量维度缺失**：功能正确但代码质量差，如何量化？
- **难度不可比**：简单任务与复杂任务使用相同阈值不合理
- **失败归因主观**：失败原因分类不明确，改进方向模糊
- **LLM-as-Judge 偏差**：位置偏差、verbose偏差、自我偏好偏差未校准
- **人工标注成本高**：缺乏结构化流程，重复劳动多

### 1.3 业界对齐

本规范综合参考以下行业最佳实践：

| 来源 | 核心借鉴 |
|------|---------|
| **OpenAI Trace Grading** | 分层Rubric、Must-have分离、可独立验证性 |
| **Claude Code Outcomes** | Outcomes框架、Must-have/Nice-to-have显式分离 |
| **CursorBench** | 功能正确性 + 验证质量 + 范围控制三维评分 |
| **Kimi K3 GRM** | 质量-难度-奖励三角模型、多维度加权 |
| **DeepSWE** | 代码质量子维度（可读性、可维护性、安全性） |
| **SPICE** | 工具使用评估、错误恢复能力 |
| **BACON / A-BB** | LLM-as-Judge偏差检测与校准框架 |

---

## 二、六层标注 Schema

### 2.1 整体架构

**标注数据结构**：

```
TaskAnnotation:
  # ========== 核心标识 ==========
  annotation_id: string              # 标注唯一标识
  task_id: string                   # 任务唯一标识（关联 REQ-EVA-001）
  annotation_version: string        # 标注规范版本（SemVer）
  annotator_id: string              # 标注者ID
  annotation_timestamp: ISO8601

  # ========== 第1层：Oracle 验证层 ==========
  oracle_verification:
    status: enum[PASS, FAIL, PARTIAL, INDETERMINATE]
    oracle_type: enum[UNIT_TEST, INTEGRATION_TEST, ASSERTION, HUMAN_REVIEW, COMPOSITE]
    oracle_details: OracleDetails
    contamination_check: ContaminationCheck
    independently_verifiable: boolean  # 是否可独立验证（无需原始上下文）

  # ========== 第2层：上下文需求层 ==========
  context_requirements:
    required_files: list[FilePath]         # 完成任务必需的文件
    required_symbols: list[SymbolRef]      # 必需的函数/类/变量
    required_dependencies: list[Dependency] # 必需的外部依赖
    context_sufficiency: enum[SUFFICIENT, INSUFFICIENT, EXCESSIVE]
    missing_context_impact: enum[BLOCKED, DEGRADED, NONE]

  # ========== 第3层：质量评估层（6维度加权） ==========
  quality_assessment:
    functional_correctness:      # 35%
      score: float[0,1]
      rubric: FunctionalCorrectnessRubric
      evidence: list[Evidence]
    
    verification_quality:        # 20%
      score: float[0,1]
      rubric: VerificationQualityRubric
      evidence: list[Evidence]
    
    scope_control:               # 15%
      score: float[0,1]
      rubric: ScopeControlRubric
      evidence: list[Evidence]
    
    tool_use_recovery:           # 15%
      score: float[0,1]
      rubric: ToolUseRecoveryRubric
      evidence: list[Evidence]
    
    code_quality:                # 10%
      score: float[0,1]
      rubric: CodeQualityRubric
      evidence: list[Evidence]
    
    efficiency:                  # 5%
      score: float[0,1]
      rubric: EfficiencyRubric
      evidence: list[Evidence]
    
    weighted_total: float[0,1]   # 加权总分

  # ========== 第4层：难度评估层（IRT校准） ==========
  difficulty_assessment:
    irt_difficulty: float        # θ 参数（-3 到 +3）
    irt_discrimination: float    # α 参数（0.5 到 2.5）
    confidence_interval_95: [float, float]
    
    complexity_dimensions:       # 五维难度分解
      code_complexity: int[1,5]          # 代码复杂度
      context_requirement: int[1,5]      # 上下文需求量
      reasoning_depth: int[1,5]          # 推理深度
      tool_diversity: int[1,5]           # 工具多样性
      error_recovery_need: int[1,5]      # 错误恢复需求

  # ========== 第5层：失败归因层 ==========
  failure_attribution:
    failure_category: FailureCategory    # 见 2.6 节
    root_cause: string                   # 根因描述
    evidence: list[Evidence]             # 支持证据
    preventability: enum[PREVENTABLE, SYSTEMIC, EXTERNAL]

  # ========== 第6层：一致性元数据层 ==========
  consistency_metadata:
    multi_annotator_agreement: float     # Krippendorff's alpha
    annotator_confidence: int[1,5]       # 标注者信心
    review_status: enum[PENDING, REVIEWED, DISPUTED, RESOLVED]
    reviewer_id: string | null
    resolution_notes: string | null
```

---

### 2.2 第1层：Oracle 验证层

**目标**：确保任务预期结果可验证、可复现。

#### 2.2.1 Oracle 类型定义

**UNIT_TEST**：单元测试通过
- `test_command`: 测试命令字符串
- `expected_exit_code`: 预期退出码（通常为0）
- `test_framework`: 测试框架名称

**INTEGRATION_TEST**：集成测试通过
- `test_suite`: 测试套件名称
- `coverage_threshold`: 覆盖率阈值

**ASSERTION**：断言验证
- `assertion_type`: FILE_EXISTS / CONTENT_MATCH / OUTPUT_MATCH / STATE_CHECK
- `assertion_script`: 断言脚本

**HUMAN_REVIEW**：人工审查
- `review_criteria`: 审查标准列表
- `reviewer_consensus_threshold`: 审查者共识阈值

**COMPOSITE**：组合验证
- `sub_oracles`: 子Oracle列表
- `combination_logic`: ALL / ANY / MAJORITY

#### 2.2.2 可独立验证性（Independently Verifiable）

**定义**：标注者无需访问原始对话历史或完整代码库，仅凭任务描述、提交的代码变更和 Oracle 即可验证结果。

**判断标准**：
- ✅ **可独立验证**：
  - 单元测试文件包含在提交中，可直接运行
  - 断言脚本明确，输入输出清晰
  - 集成测试环境可复现
  
- ❌ **不可独立验证**：
  - 需要原始issue描述才能理解预期
  - 依赖未版本化的外部状态
  - 人工审查标准模糊

**与 REQ-EVA-001 对齐**：
- `independently_verifiable: true` → 符合 Golden Dataset Oracle 入集闸门
- `independently_verifiable: false` → 需要补充 Oracle 或转为 `HUMAN_REVIEW`

#### 2.2.3 污染检查（关联 REQ-EVA-001）

**污染检查结构**：
- `contamination_status`: CLEAN / SUSPECTED / CONFIRMED
- `overlap_score`: n-gram 重叠分数（0-1）
- `repo_disjoint`: 仓库是否disjoint
- `exposure_count`: 该任务被模型见过的次数
- `contamination_evidence`: 污染证据

**阈值**（继承自 REQ-EVA-001）：
- `overlap_score > 0.3` → `SUSPECTED`
- `exposure_count > 0` → `CONFIRMED`（对于真实任务）
- `repo_disjoint: false` → `SUSPECTED`（对于外部真实任务）

---

### 2.3 第2层：上下文需求层

**目标**：识别任务完成所需的最小必要上下文。

#### 2.3.1 必需文件（Required Files）

**定义**：Agent 必须访问才能正确完成任务的文件。

**标注方法**：
1. 标注者模拟Agent视角，分析任务描述
2. 识别需要读取的源文件、配置文件、测试文件
3. 区分必需文件 vs 可选文件

**示例**：
```
任务：修复 src/utils/parser.py 中的解析错误
必需文件：
  - src/utils/parser.py（主修改目标）
  - tests/test_parser.py（验证修复）
  - src/utils/__init__.py（了解模块结构）
可选文件：
  - README.md（了解项目背景）
```

#### 2.3.2 必需符号（Required Symbols）

**定义**：Agent 必须理解的函数、类、变量。

**格式**：`<file_path>:<symbol_name>`

**示例**：
```
- src/utils/parser.py:parse_json
- src/utils/parser.py:Parser
- src/config.py:DEFAULT_ENCODING
```

#### 2.3.3 上下文充分性评估

**SUFFICIENT**：提供的上下文足以完成任务
**INSUFFICIENT**：上下文缺失导致任务无法完成或质量下降
**EXCESSIVE**：提供了不必要的上下文（可能干扰Agent）

---

### 2.4 第3层：质量评估层

**目标**：多维度量化任务执行质量，对齐Claude Outcomes和Kimi K3的设计。

#### 2.4.1 六维度评分体系

**维度1：功能正确性（Functional Correctness）- 权重35%**

**Must-have标准**（所有项必须通过）：
- Oracle验证通过（单元测试/集成测试/断言）
- 核心功能按任务描述实现
- 无功能性回归

**Nice-to-have标准**（加分项）：
- 边缘案例处理完善
- 错误提示友好
- 性能优于预期

**评分规则**：
- Must-have全部通过 → 基础分0.7
- Nice-to-have每项 → 加0.1（最高1.0）

---

**维度2：验证质量（Verification Quality）- 权重20%**

**Must-have标准**：
- 提供可执行的验证方法（测试/断言/示例）
- 验证覆盖核心功能路径
- 验证结果可复现

**Nice-to-have标准**：
- 测试覆盖率 ≥ 80%
- 包含边缘案例测试
- 提供性能基准测试

**评分规则**：
- 无验证 → 0分
- 基础验证 → 0.6分
- 完整验证 → 0.8-1.0分

---

**维度3：范围控制（Scope Control）- 权重15%**

**Must-have标准**：
- 变更范围符合任务描述
- 无不相关代码修改
- 无不必要的重构

**Nice-to-have标准**：
- 变更最小化原则
- 保持现有代码风格
- 修改位置精准

**评分规则**：
- 严重超范围 → 0-0.4分
- 轻微超范围 → 0.5-0.7分
- 范围精准 → 0.8-1.0分

---

**维度4：工具使用与恢复（Tool Use & Recovery）- 权重15%**

**Must-have标准**：
- 工具选择正确（文件读写/Git操作/测试执行）
- 错误后有恢复尝试
- 工具调用参数正确

**Nice-to-have标准**：
- 工具使用顺序合理
- 错误恢复策略有效
- 最小化工具调用次数

**评分规则**：
- 工具使用错误导致失败 → 0-0.3分
- 工具使用正确但低效 → 0.4-0.7分
- 工具使用优秀 → 0.8-1.0分

---

**维度5：代码质量（Code Quality）- 权重10%**

**Must-have标准**：
- 代码可读性合格
- 无明显代码异味
- 符合项目约定

**Nice-to-have标准**：
- 命名清晰
- 注释适当
- 结构优雅

**评分规则**：
- 代码质量差 → 0-0.5分
- 代码质量一般 → 0.6-0.7分
- 代码质量优秀 → 0.8-1.0分

---

**维度6：效率（Efficiency）- 权重5%**

**Must-have标准**：
- 在合理时间内完成任务
- Token使用量在预期范围

**Nice-to-have标准**：
- Token使用量低于预期50%
- 完成时间快于预期50%

**评分规则**：
- 超时或Token耗尽 → 0分
- 在预算内完成 → 0.6-0.8分
- 高效完成 → 0.9-1.0分

---

#### 2.4.2 加权总分计算

```
weighted_total = 
  functional_correctness * 0.35 +
  verification_quality * 0.20 +
  scope_control * 0.15 +
  tool_use_recovery * 0.15 +
  code_quality * 0.10 +
  efficiency * 0.05
```

**通过标准**：
- `weighted_total >= 0.7` 且 所有Must-have项通过 → PASS
- 否则 → FAIL

---

### 2.5 第4层：难度评估层

**目标**：建立多维难度模型，支持IRT校准和难度分级。

#### 2.5.1 IRT参数（继承REQ-EVA-001）

**难度参数（θ）**：-3（极易）到 +3（极难）
**区分度参数（α）**：0.5（低区分度）到 2.5（高区分度）
**置信区间**：95%置信区间

**校准方法**：
1. 初始难度：专家标注
2. 实测校准：Agent舰队实测通过率
3. IRT拟合：最大似然估计θ和α
4. 置信区间：Bootstrap或Fisher信息矩阵

#### 2.5.2 五维复杂度（人工标注）

**维度1：代码复杂度（Code Complexity）**
- **LOW**：单文件修改，< 50行代码，圈复杂度 < 5
- **MEDIUM**：2-5文件修改，50-200行代码，圈复杂度5-15
- **HIGH**：> 5文件修改，> 200行代码，圈复杂度 > 15

**维度2：上下文需求（Context Demand）**
- **LOW**：1-3个必需文件，无外部依赖
- **MEDIUM**：4-10个必需文件，1-2个外部依赖
- **HIGH**：> 10个必需文件，> 2个外部依赖，需深度理解架构

**维度3：推理深度（Reasoning Depth）**
- **LOW**：直接修改，无需复杂推理
- **MEDIUM**：需要2-3步推理链
- **HIGH**：需要> 3步推理链，涉及多层依赖分析

**维度4：工具多样性（Tool Diversity）**
- **LOW**：使用1-2种工具（如文件读写）
- **MEDIUM**：使用3-4种工具（文件+Git+测试）
- **HIGH**：使用> 4种工具，需工具链协调

**维度5：错误恢复需求（Error Recovery Need）**
- **LOW**：预期无错误或单步可恢复
- **MEDIUM**：可能出现1-2次错误，需2-3步恢复
- **HIGH**：高错误风险，需复杂恢复策略

#### 2.5.3 综合难度档位

**档位判定规则**：
- **EASY**：至少4个维度为LOW，其余不高于MEDIUM
- **MEDIUM**：不满足EASY且不满足HARD
- **HARD**：至少3个维度为HIGH或所有维度为MEDIUM/HIGH

---

### 2.6 第5层：失败归因层

**目标**：系统化分类失败原因，对齐REQ-REL-001失败分类体系。

#### 2.6.1 失败分类（继承REQ-REL-001）

**4大类、14小类**：

**1. 规划与推理失败（PLANNING_REASONING）**
- `PLANNING_INCOMPLETE`：规划不完整
- `REASONING_ERROR`：推理错误
- `CONTEXT_MISUNDERSTANDING`：上下文理解错误

**2. 工具使用失败（TOOL_USAGE）**
- `TOOL_SELECTION_ERROR`：工具选择错误
- `TOOL_PARAMETER_ERROR`：工具参数错误
- `TOOL_EXECUTION_TIMEOUT`：工具执行超时

**3. 代码生成失败（CODE_GENERATION）**
- `SYNTAX_ERROR`：语法错误
- `LOGIC_ERROR`：逻辑错误
- `INCOMPLETE_IMPLEMENTATION`：实现不完整

**4. 系统与环境失败（SYSTEM_ENVIRONMENT）**
- `DEPENDENCY_MISSING`：依赖缺失
- `PERMISSION_DENIED`：权限不足
- `RESOURCE_EXHAUSTED`：资源耗尽
- `NETWORK_ERROR`：网络错误
- `EXTERNAL_SERVICE_FAILURE`：外部服务失败

#### 2.6.2 根因分析

**根因描述**：简洁描述失败的直接原因（1-2句话）

**证据记录**：
- 错误日志片段
- 失败的工具调用
- 异常堆栈

**可预防性判定**：
- **PREVENTABLE**：Agent可通过更好的推理/工具使用避免
- **SYSTEMIC**：系统设计问题（如工具能力不足）
- **EXTERNAL**：外部因素（如网络故障）

---

### 2.7 第6层：一致性元数据层

**目标**：确保标注质量和一致性。

#### 2.7.1 多标注者一致性

**Krippendorff's alpha**：
- 范围：-1（完全不一致）到 +1（完全一致）
- 阈值：α ≥ 0.7 认为一致性可接受
- 计算：基于双标注样本的不一致度矩阵

**一致性等级**：
- **EXCELLENT**：α ≥ 0.9
- **GOOD**：0.7 ≤ α < 0.9
- **FAIR**：0.5 ≤ α < 0.7
- **POOR**：α < 0.5

#### 2.7.2 标注者置信度

**置信度评分**：1（极低）到 5（极高）

**判断依据**：
- 任务描述清晰度
- Oracle可验证性
- 标注经验
- 边缘案例复杂度

#### 2.7.3 复审状态

**状态枚举**：
- **PENDING**：待复审
- **REVIEWED**：已复审通过
- **DISPUTED**：标注争议中
- **RESOLVED**：争议已解决

---

## 三、标注流程设计

### 3.1 Oracle验证标注流程

**Step 1: 任务加载**
- 加载任务上下文（task_id、lineage_type、source_type）

**Step 2: Oracle类型识别**
- 分析任务是否有单元测试、集成测试、断言验证或复合Oracle
- 确定主Oracle类型

**Step 3: 验证执行**
- 在隔离环境执行Oracle验证
- 记录验证结果和输出

**Step 4: 污染检查（仅REAL_*类型）**
- 执行训练数据收录检查（n-gram重叠检测）
- 执行仓库disjoint检查
- 记录污染状态

**Step 5: 状态判定**
- 如果验证通过且无污染 → APPROVED
- 如果验证失败 → REJECTED，记录原因
- 如果验证存疑 → NEEDS_REVISION，标记需复审

**Step 6: 复审（可选）**
- 高级标注员复审NEEDS_REVISION状态的任务
- 最终确定状态

---

### 3.2 质量Rubric评分流程

**Step 1: Rubric加载**
- 加载针对任务类型的评分Rubric
- 确认Must-have和Nice-to-have分离

**Step 2: 产物分析**
- 阅读Agent输出产物（代码、测试、日志）
- 理解任务意图和Rubric要求

**Step 3: 逐项评估**
- 按Rubric逐项检查，每项给出PASS/FAIL
- 记录每项的具体证据和反馈

**Step 4: 分数计算**
- 计算每维度加权得分
- 计算总分

**Step 5: 置信度评估**
- 标注者自评置信度（HIGH/MEDIUM/LOW）
- 记录评估依据

**Step 6: 偏差检测（LLM-as-Judge辅助）**
- 检查是否存在位置偏差（答案顺序影响）
- 检查是否存在verbose偏差（长度影响）
- 如有偏差，记录并在最终分数中调整

---

### 3.3 多标注者一致性校验流程

**Step 1: 样本抽取**
- 随机抽取10-20%任务进行双标注

**Step 2: 双标注执行**
- 两名标注者独立标注同一任务

**Step 3: 一致性计算**
- 计算Krippendorff's alpha
- 分析不一致项的原因

**Step 4: 偏差修正**
- 如果alpha < 0.7，启动标注规范复审
- 如果特定维度一致性问题，修订Rubric

**Step 5: 记录归档**
- 更新校准数据集
- 记录标注者表现评估

---

## 四、LLM-as-Judge校准机制

### 4.1 常见偏差与缓解

**偏差1：位置偏差（Position Bias）**
- **现象**：评分受答案顺序影响
- **检测**：交换答案顺序，观察评分变化
- **缓解**：随机化答案顺序、评估两个排列并平均

**偏差2：Verbose偏差（Verbosity Bias）**
- **现象**：长答案获得更高评分
- **检测**：分析评分与输出长度的相关性
- **缓解**：惩罚不必要长度、将正确性与风格分离

**偏差3：自我偏好偏差（Self-Preference Bias）**
- **现象**：Judge偏好自己生成的输出
- **检测**：比较同模型Judge与异模型Judge的评分
- **缓解**：交叉模型评判、集成评判

### 4.2 校准算法（分阶段）

**MVP阶段：启发式校准**

```
校准分数 = 原始分数 × 位置偏差因子 × Verbose惩罚 × 自我偏好因子
```

**V2阶段：Platt Scaling校准**

使用标注样本训练Platt Scaling模型：
- 输入：原始分数和人类标注的二分类标签
- 输出：校准后的概率分数

**V3阶段：BACON框架**

- 多Judge分数 + 不确定性统计 + 上下文嵌入作为辅助特征
- 小规模人类标注样本训练交叉拟合结果模型
- 两种下游模式：总体指标估计 vs 个体级代理评分

---

## 五、人机协同设计

### 5.1 标注角色定义

| 角色 | 职责 | 能力要求 |
|------|------|---------|
| **标注工程师** | 执行Oracle验证和质量评分 | 理解任务描述，能运行测试，基础代码阅读能力 |
| **高级标注员** | 复审标注结果，校验一致性 | 深度代码理解，Rubric设计经验 |
| **评估科学家** | 设计Rubric，定义评分标准，执行难度校准 | 统计学背景，熟悉IRT模型 |
| **安全红队** | 对抗样本专项标注 | 安全攻防经验，熟悉OWASP/ATLAS |
| **审计员** | 查看标注元数据和审计日志 | 合规背景 |

### 5.2 标注界面设计原则

- **明确的任务上下文**：标注者应能清晰看到任务描述、Agent输出和Rubric要求
- **逐项评分机制**：Must-have项必须全部通过才能进入Nice-to-have评分
- **即时反馈**：每项评分后显示当前加权得分，帮助标注者把握整体评分
- **置信度自评**：标注者需填写置信度和评分理由

### 5.3 人类在环触发机制

| 场景 | 触发条件 | 人类介入方式 |
|------|---------|------------|
| **Oracle验证** | 状态为NEEDS_REVISION | 高级标注员复审 |
| **质量评分** | 标注者置信度LOW | 人工复核 |
| **一致性校验** | Krippendorff's alpha < 0.7 | 启动标注规范复审 |
| **偏差检测** | 检测到系统性偏差 | 人工审查样本 |
| **对抗样本** | 任务类型为SYNTH_ADVERSARIAL | 安全红队专项标注 |

---

## 六、可观测性与评估指标

### 6.1 标注系统指标

| 指标 | 定义 | 目标 |
|------|------|------|
| `annotation_throughput` | 单位时间完成的标注数 | ≥ 10/小时/人 |
| `annotation_latency_p95` | 从任务入队到标注完成的延迟 | < 24小时 |
| `annotation_rejection_rate` | 被拒绝/需修订的标注比例 | < 20% |
| `krippendorffs_alpha` | 多标注者一致性 | ≥ 0.7 |
| `confidence_accuracy` | 标注者置信度与实际准确率的匹配度 | ≥ 80% |

### 6.2 评分器质量指标

| 指标 | 定义 | 目标 |
|------|------|------|
| `judge_human_agreement` | LLM Judge与人工判断一致率 | ≥ 85% |
| `judge_false_positive_rate` | 错误通过比例 | < 5% |
| `judge_false_negative_rate` | 错误拒绝比例 | < 5% |
| `position_bias_score` | 位置偏差程度 | < 0.05 |
| `verbosity_bias_score` | Verbose偏差程度 | < 0.05 |

### 6.3 数据质量指标

| 指标 | 定义 | 目标 |
|------|------|------|
| `oracle_verification_coverage` | 经过Oracle验证的任务比例 | 100% |
| `contamination_detection_rate` | 污染检测覆盖率 | 100% (REAL_*) |
| `annotation_completeness` | 完整填写所有必填字段的比例 | ≥ 95% |

---

## 七、权限、安全与合规

### 7.1 权限控制矩阵

| 角色 | Oracle验证 | 质量评分 | 难度评估 | 失败归因 | Rubric设计 | 查看审计日志 |
|------|----------|---------|---------|---------|-----------|-------------|
| 标注工程师 | ✓ | ✓ | ✗ | ✓ | ✗ | ✗ |
| 高级标注员 | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ |
| 评估科学家 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 安全红队 | ✓ (对抗) | ✓ (对抗) | ✗ | ✓ (对抗) | ✗ | ✗ |
| 审计员 | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ |

### 7.2 安全要求

**标注数据脱敏**：
- 移除用户身份信息（姓名、邮箱、手机号）
- 移除组织名称（公司名、项目名）
- 移除敏感代码（API密钥、凭据、私有算法）

**标注者身份追踪**：
- 所有标注操作必须关联`annotator_id`
- 记录标注时间戳和IP地址
- 支持标注者行为审计

**对抗样本隔离**：
- 对抗样本标注环境与常规标注环境分离
- 对抗样本仅安全红队可见
- 对抗样本标注结果加密存储

### 7.3 合规要求

**标注留存**：
- 标注数据按REQ-RT-008审计留存策略执行
- 最低留存期：2年
- 敏感标注数据留存期：5年

**删除权限**：
- 仅合规团队有权申请删除
- 删除申请需数据治理委员会审批
- 删除操作必须记录完整审计日志

**审计日志**：
- 记录所有标注创建、修改、删除操作
- 记录标注者ID、时间戳、操作类型、变更内容
- 审计日志不可修改，仅追加

---

## 八、验收标准

| 验收项 | 验收条件 | 验证方法 |
|--------|---------|---------|
| V1 | 标注Schema覆盖Oracle验证、上下文需求、质量评估、难度评估、失败归因、一致性元数据六大维度 | Schema审查 |
| V2 | 标注规范支持Must-have和Nice-to-have分离 | Rubric样本审查 |
| V3 | 标注规范与REQ-EVA-001的Golden Dataset Schema对齐 | 集成测试 |
| V4 | 支持人工标注和LLM辅助标注两种模式 | 功能测试 |
| V5 | 标注结果包含置信度和一致性元数据 | 数据审查 |
| V6 | 多标注者一致性Krippendorff's alpha ≥ 0.7 | 统计分析（双标注样本） |
| V7 | LLM-as-Judge与人工判断一致率 ≥ 85% | 对比测试（100样本） |
| V8 | 偏差检测机制可识别位置偏差和verbose偏差 | 偏差注入测试 |
| V9 | 标注数据脱敏符合SEC-008要求 | 安全审计 |
| V10 | 标注操作审计日志完整 | 审计追踪测试 |

---

## 九、依赖与接口

### 9.1 上游依赖

| 依赖 | 版本 | 说明 |
|------|------|------|
| REQ-EVA-001 | v0.1-designed | Golden Dataset提供任务上下文和血缘分类 |
| REQ-RT-001 | v0.1-designed | 核心实体Schema（actor_id、timestamp） |
| REQ-REL-001 | v0.1-designed | 失败分类体系（FailureCategory） |
| REQ-SEC-008 | v0.1-designed | 多租户数据治理（标注权限控制） |

### 9.2 下游接口

| 接口 | 消费者 | 说明 |
|------|--------|------|
| `TaskAnnotation` Schema | REQ-EVA-003 | 自动评分器消费标注数据训练 |
| `AnnotationAuditLog` | REQ-RT-008 | 审计日志接口 |
| `CalibrationDataset` | REQ-EVA-002 | 校准数据集接口 |
| `AnnotationRubric` | 标注界面 | Rubric配置接口 |

---

## 十、演进路径

### 10.1 版本规划

| 版本 | 时间 | 目标 | 关键交付物 |
|------|------|------|-----------|
| **MVP (v0.1)** | Q1 | 基础标注Schema，支持Oracle验证和简单质量评分 | 六层Schema、基础Rubric模板 |
| **V1 (v1.0)** | Q2 | 完整五维度标注，支持LLM-as-Judge辅助 | 启发式校准、双标注流程 |
| **V2 (v2.0)** | Q3 | 引入Platt Scaling校准，支持多标注者协同 | Platt Scaling模型、一致性监控 |
| **V3 (v3.0)** | Q4 | 引入BACON框架，支持偏差有界评估 | BACON校准、置信区间报告 |

### 10.2 演进约束

**向后兼容性**：
- Schema字段只增不减（废弃字段标记`@deprecated`）
- Rubric版本化管理，历史版本可查询
- 标注数据迁移脚本

**扩展性**：
- 支持新增评分维度（权重可配置）
- 支持自定义Oracle类型
- 支持多语言标注（中文/英文）

---

## 十一、附录

### 11.1 术语表

| 术语 | 定义 |
|------|------|
| **Oracle** | 任务完成的客观判定标准（如单元测试、断言） |
| **Rubric** | 结构化评分标准，包含Must-have和Nice-to-have |
| **IRT** | Item Response Theory，项目反应理论，用于难度校准 |
| **Krippendorff's alpha** | 多标注者一致性统计量，范围[-1, +1] |
| **LLM-as-Judge** | 使用LLM作为评分器的评估模式 |
| **Position Bias** | 评分受答案顺序影响的偏差 |
| **Verbosity Bias** | 长答案获得更高评分的偏差 |

### 11.2 参考文献

1. OpenAI. (2026). *Agent Evals: Trace Grading Guide*. https://developers.openai.com/api/docs/guides/trace-grading
2. Anthropic. (2026). *Claude Code Outcomes Documentation*. https://platform.claude.com/docs/en/managed-agents/define-outcomes
3. Cursor. (2026). *CursorBench: Benchmarking Coding Agents*. https://cursor.com/blog/cursorbench
4. Moonshot AI. (2026). *Kimi K3 Agentic GRM Whitepaper*. arXiv:2607.24653
5. DeepSeek. (2026). *DeepSWE: Original Software Engineering Benchmark*. arXiv:2607.07946
6. SPICE. (2026). *SWE-bench Pipeline for Issue Clarity and Test Coverage*. arXiv:2507.09108
7. BACON. (2026). *Budgeted Human Calibration for LLM-as-Judge*. arXiv:2607.16239
8. A-BB. (2026). *Average Bias-Bounded Calibration Framework*. arXiv:2603.05485

---

**文档版本**：v0.1  
**文档状态**：designed  
**最后更新**：2026-09-27  
**维护团队**：评估工程组
