# G06 评估数据集 — 下游消费接口参考

> 本文档从 `REQ-EVA-001` v0.1-designed 和 `REQ-EVA-002` v0.1-designed 提炼，供 EVA-003~006、REL-001、OBS、HAR-001 等下游专项在设计/实现阶段直接引用。
> 文档定位为"消费侧接口表"，不替代源设计；若冲突以源设计为准。
>
> 来源：
> - [REQ-EVA-001 Golden Dataset](REQ-EVA-001-golden-dataset.md)（v0.1-designed）
> - [REQ-EVA-002 Annotation Specification](REQ-EVA-002-annotation-specification.md)（v0.1-designed）

---

## 一、三条铁律速查（EVA-001 §1.1，下游专项不得违反）

```
铁律 1：Oracle 可判定性
每条任务必须有客观、可重复的完成判定标准。
无法判定的任务不得入集，不论其来源、难度或稀缺性。

铁律 2：血缘一等维度
数据来源是不可混淆的一等维度，永远分开报告，禁用混合总分。

铁律 3：污染控制等同安全事件
数据泄漏和任务污染不是"数据质量问题"，而是需要启动安全响应流程的安全事件。
```

---

## 二、五类血缘类型速查（EVA-001 §4.1，下游报告必须分开）

| 血缘类型 | 代码 | 定义 | 污染风险 | 下游使用规则 |
|---|---|---|---|---|
| **真实-自有仓库** | `REAL_OWN_REPO` | 从用户自有 GitHub 仓库衍生的任务，需验证未进入模型训练集 | 高：需检查训练数据收录情况 | 必须执行污染检查；命中则降级为 SYNTH_PROPERTY |
| **真实-外部仓库** | `REAL_EXTERNAL` | 从开源外部仓库衍生的任务 | 中：需验证仓库与训练集 disjoint | 必须验证仓库 disjoint；与 SWE-bench 训练集不重叠 |
| **合成-属性覆盖** | `SYNTH_PROPERTY` | 基于真实仓库结构生成的属性覆盖任务 | 低：天然与真实任务错开失败模式 | 可用于补充特征空间覆盖率 |
| **合成-对抗构造** | `SYNTH_ADVERSARIAL` | 专门设计的安全对抗任务 | 无：人工构造，不存在污染 | 必须由独立安全红队构建；保质期 6 个月 |
| **合成-压力测试** | `SYNTH_STRESS` | 边界条件、资源极限、异常流任务 | 无：不存在真实对应 | 可用于测试系统极限 |

### 混合报告的禁止规则

```
❌ 禁止：
- "整体通过率 85%" → 必须按五类分开报告
- "合成任务表现更好" → 必须说明是否因为 verifier 被摸透
- 跨血缘对比不说明假设前提

✅ 必须：
- 每条血缘曲线单独画，单独报告置信区间
- 任何跨血缘对比必须明确说明比较的假设前提
```

---

## 三、Oracle 入集闸门速查（EVA-001 §5，三道闸门）

### 闸门 1：Oracle 有效性

```
任务必须满足以下所有条件：
□ 存在至少一个 UNIT_TEST、INTEGRATION_TEST 或 ASSERTION 类型的 Oracle
□ Oracle 可在隔离环境中自动执行
□ Oracle 的通过/失败结果与任务描述的目标一致
□ Oracle 不依赖外部不可控状态（如网络、时间、随机数）

例外：MANUAL_REVIEW 类型的 Oracle 需要额外审批
```

### 闸门 2：污染检查

```
所有 REAL_* 类型任务必须通过以下检查：
□ 训练数据收录检查：验证任务/解决方案是否已进入被测模型训练集
  - 使用公开的模型卡片训练数据声明
  - 使用 n-gram 重叠检测（> 30% 重叠视为命中）
  - 命中则只能降级为 SYNTH_* 类型，不能进入 REAL_* 类型

□ 仓库 disjoint 检查（适用于 REAL_EXTERNAL）
  - 验证仓库与 SWE-bench 训练集 disjoint
  - 验证仓库与被测模型训练集 disjoint
```

### 闸门 3：难度可校准性

```
任务必须能够参与难度校准：
□ 任务足够具体，可被参考模型舰队重复执行
□ 任务不依赖于只有特定模型才有的知识
□ 任务有足够的挑战性（通过率 < 95% for 参考舰队）
```

---

## 四、污染控制机制速查（EVA-001 §6，作为安全事件管理）

### 4.1 污染分类

| 严重级别 | 定义 | 响应 |
|---|---|---|
| **P0-CRITICAL** | 确认数据泄漏，大量任务已污染 | 立即冻结受影响版本，启动根因分析，48h 内发布安全公告 |
| **P1-HIGH** | 疑似污染，部分任务可能泄漏 | 降级受影响任务为"调试可用、不计分"，启动调查 |
| **P2-MEDIUM** | 潜在风险，需要关注 | 记录并监控，不降级但增加检测频率 |
| **P3-LOW** | 极低风险，正常记录 | 仅记录，不触发响应 |

### 4.2 exposure_count 管理

```
规则：
- 每条任务被完整跑过一次，exposure_count += 1
- exposure_count ≥ 3 时，自动降级为 "训练/调试可用、不计分"
- 降级任务可继续用于调试，但不能计入正式评估结果
- 降级记录必须包含降级时间和降级原因

例外：
- 评估结果一致的稳定任务（连续 3 次相同结果）可申请豁免
- 豁免需要高级评估工程师审批
```

### 4.3 Per-Version Holdout

```
规则：
- 每个发布版本（v1.0.0、v1.1.0 等）有专属封存集
- 封存集在版本发布时一次性放出，跑完即冻结
- 封存集绝不在版本间复用
- 封存集的任务来自最新的候选池，确保与历史版本 disjoint

封存集大小：
- v0.1：≥ 10 条任务，每种血缘类型 ≥ 2 条
- v1.0：≥ 20 条任务，每种血缘类型 ≥ 4 条
```

---

## 五、多维难度校准速查（EVA-001 §7，IRT + 五维复杂度）

### 5.1 IRT 参数

| 参数 | 符号 | 范围 | 说明 |
|---|---|---|---|
| **难度参数** | θ | -3（极易）到 +3（极难） | 参考舰队平均正确率对应的能力值 |
| **区分度参数** | α | 0.5（低）到 2.5（高） | 高值表示能区分能力强弱 |
| **置信区间** | CI | 95% 置信区间 | Bootstrap 或 Fisher 信息矩阵 |

### 5.2 校准流程

```
1. 定义参考 agent 舰队（3-5 个不同能力级别的 agent）
2. 用舰队在候选任务上执行，记录通过率
3. 使用 IRT 模型拟合参数
4. 基于拟合参数将任务分档

分档标准（基于参考舰队 pass rate）：
- EASY: 参考舰队平均 pass rate > 70%
- MEDIUM: 参考舰队平均 pass rate 30%-70%
- HARD: 参考舰队平均 pass rate < 30%
```

### 5.3 五维复杂度（人工标注）

| 维度 | LOW (1-2 分) | MEDIUM (3 分) | HIGH (4-5 分) |
|---|---|---|---|
| **代码复杂度** | 单文件修改，< 50 行，圈复杂度 < 5 | 2-5 文件修改，50-200 行，圈复杂度 5-15 | > 5 文件修改，> 200 行，圈复杂度 > 15 |
| **上下文需求** | 1-3 个必需文件，无外部依赖 | 4-10 个必需文件，1-2 个外部依赖 | > 10 个必需文件，> 2 个外部依赖 |
| **推理深度** | 直接修改，无需复杂推理 | 需要 2-3 步推理链 | 需要 > 3 步推理链，多层依赖分析 |
| **工具多样性** | 使用 1-2 种工具（如文件读写） | 使用 3-4 种工具（文件+Git+测试） | 使用 > 4 种工具，需工具链协调 |
| **错误恢复需求** | 预期无错误或单步可恢复 | 可能出现 1-2 次错误，需 2-3 步恢复 | 高错误风险，需复杂恢复策略 |

### 5.4 置信区间要求

```
规则：
- 每个难度估计必须附带 95% 置信区间
- 置信区间宽度 > 30% 的任务需要更多实测数据
- 置信区间重叠严重的任务不强制分层
- 每半年用参考舰队重新校准难度参数
```

---

## 六、安全对抗样本设计速查（EVA-001 §8）

### 6.1 三层隔离架构

| 层级 | 职责 | 参与者 | 下游约束 |
|---|---|---|---|
| **Layer 1：基础样本构建** | 设计攻击向量、编写触发输入、定义成功判据 | 安全红队（独立于 Agent 开发团队） | Agent 开发团队不得参与 |
| **Layer 2：变体生成** | 基于基础样本生成多个变体、扩大覆盖 | 安全红队 + ML 工程师协作 | 生成器与被测模型必须不同族 |
| **Layer 3：质量验证** | 验证变体有效性、确保判据客观 | 安全审核委员会（独立于前两层） | 独立性记录必须可追溯 |

### 6.2 八种攻击类型覆盖

| 攻击类型 | 代码 | 基础样本数 | 下游测试覆盖 |
|---|---|---|---|
| **提示注入** | `PROMPT_INJECTION` | ≥ 5 | SEC-003 策略网关必须覆盖 |
| **恶意仓库** | `MALICIOUS_REPO` | ≥ 3 | SEC-001 威胁模型必须包含 |
| **权限绕过** | `PERMISSION_BYPASS` | ≥ 5 | SEC-002 授权必须测试 |
| **资源耗尽** | `RESOURCE_EXHAUSTION` | ≥ 3 | REL-002 熔断必须触发 |
| **数据外泄** | `DATA_EXFILTRATION` | ≥ 4 | SEC-008 租户隔离必须防御 |
| **凭据窃取** | `CREDENTIAL_THEFT` | ≥ 3 | SEC-005 凭据管理必须检测 |
| **沙箱逃逸** | `SANDBOX_ESCAPE` | ≥ 3 | SEC-009 沙箱隔离必须防御 |
| **依赖混淆** | `DEPENDENCY_CONFUSION` | ≥ 3 | HAR-001 工具治理必须检测 |

### 6.3 两条红线（不可违反）

```
红线 1：生成器与被测模型必须不同族
- 生成器使用 Model-A，被测 Agent 使用 Model-B
- 优先使用不同厂商的模型
- 禁止：同一模型生成攻击变体并测试同一模型
- 原因：测试的是自相似性，不是鲁棒性

红线 2：建防御的人不建、不评分攻击
- Agent 开发团队不能参与对抗样本构建
- 评分流程与开发流程完全隔离
- 审计要求：独立性记录必须可追溯
```

### 6.4 变体生成防塌缩机制

```
问题：LLM 生成的变体会塌缩到同一分布
后果：测试的是"检测器认不认得出生成器指纹"

解决方案：
1. 多生成器策略：使用 3+ 个不同模型族生成变体
2. 扰动注入：引入随机扰动（重述、翻译、风格变换）
3. 人工多样性审核：确保变体之间有足够的差异
4. 分布检测：定期检测变体分布，防止塌缩
```

### 6.5 保质期管理

```
规则：
- 每批对抗样本有"保质期"（shelf life）
- 默认保质期：6 个月
- 保质期届满前必须重新验证有效性
- 失效样本移入"历史对抗库"，不参与正式评估

失效判据：
- 攻击成功率 < 5%（防御已完全覆盖此类攻击）
- 攻击成功率 > 95%（攻击已完全失效，不再是测试用例）
- 检测器对同类攻击的识别率 > 99%
```

---

## 七、标注六层 Schema 速查（EVA-002 §2）

### 7.1 六层架构

```
TaskAnnotation:
  第 1 层：Oracle 验证层          # 可判定性、可独立验证性、污染检查
    ↓
  第 2 层：上下文需求层          # 必需文件/符号/依赖、上下文充分性
    ↓
  第 3 层：质量评估层（6 维）    # 功能正确性、验证质量、范围控制、工具使用、代码质量、效率
    ↓
  第 4 层：难度评估层            # IRT 参数、五维复杂度
    ↓
  第 5 层：失败归因层            # 14 小类失败分类、根因分析、可预防性
    ↓
  第 6 层：一致性元数据层        # Krippendorff's alpha、标注者置信度、复审状态
```

### 7.2 Oracle 验证层（第 1 层）

| Oracle 类型 | 代码 | 说明 | 下游消费 |
|---|---|---|---|
| **单元测试** | `UNIT_TEST` | 有明确的单元测试用例，运行后通过/失败 | EVA-003 自动评分器优先支持 |
| **集成测试** | `INTEGRATION_TEST` | 有明确的集成测试套件 | EVA-003 自动评分器优先支持 |
| **断言验证** | `ASSERTION` | 有可执行的断言验证脚本 | EVA-003 自动评分器优先支持 |
| **人工审查** | `MANUAL_REVIEW` | 必须人工判断完成质量（仅限特殊场景） | 需要额外审批，不作为 MVP 主力 |
| **复合验证** | `COMPOUND` | 上述类型的组合 | EVA-003 需支持多 Oracle 组合 |

**可独立验证性判断**：
```
✅ 可独立验证：
- 单元测试文件包含在提交中，可直接运行
- 断言脚本明确，输入输出清晰
- 集成测试环境可复现

❌ 不可独立验证：
- 需要原始 issue 描述才能理解预期
- 依赖未版本化的外部状态
- 人工审查标准模糊
```

### 7.3 质量评估层（第 3 层）— 六维度加权

| 维度 | 权重 | Must-have 标准 | 通过基础分 | 下游消费 |
|---|---|---|---|---|
| **功能正确性** | 35% | Oracle 验证通过、核心功能实现、无功能性回归 | 0.7 | EVA-003 自动评分器主力维度 |
| **验证质量** | 20% | 提供可执行的验证方法、覆盖核心功能、结果可复现 | 0.6 | EVA-003 验证质量评估 |
| **范围控制** | 15% | 变更范围符合任务、无不相关修改、无不必要重构 | 0.5-0.7 | EVA-004 失败归因需分析范围超范围 |
| **工具使用与恢复** | 15% | 工具选择正确、错误后有恢复尝试、参数正确 | 0.4-0.7 | HAR-001 工具治理需分析工具使用错误 |
| **代码质量** | 10% | 代码可读性合格、无明显异味、符合项目约定 | 0.6-0.7 | EVA-003 代码质量子评分器 |
| **效率** | 5% | 在合理时间内完成、Token 使用量在预期范围 | 0.6-0.8 | OBS-003 指标需分析 Token 消耗 |

**加权总分计算**：
```
weighted_total = 
  functional_correctness * 0.35 +
  verification_quality * 0.20 +
  scope_control * 0.15 +
  tool_use_recovery * 0.15 +
  code_quality * 0.10 +
  efficiency * 0.05

通过标准：
- weighted_total >= 0.7 且所有 Must-have 项通过 → PASS
- 否则 → FAIL
```

### 7.4 失败归因层（第 5 层）— 14 小类

| 大类 | 小类 | 代码 | 下游对齐 |
|---|---|---|---|
| **规划与推理失败** | 规划不完整 | `PLANNING_INCOMPLETE` | REL-001 症状：规划/推理阶段失败 |
| | 推理错误 | `REASONING_ERROR` | REL-001 症状：规划/推理阶段失败 |
| | 上下文理解错误 | `CONTEXT_MISUNDERSTANDING` | CTX-001 上下文管理需优化 |
| **工具使用失败** | 工具选择错误 | `TOOL_SELECTION_ERROR` | HAR-001 工具治理需改进 |
| | 工具参数错误 | `TOOL_PARAMETER_ERROR` | HAR-001 工具治理需改进 |
| | 工具执行超时 | `TOOL_EXECUTION_TIMEOUT` | REL-001 症状：OPERATION_TIMED_OUT |
| **代码生成失败** | 语法错误 | `SYNTAX_ERROR` | REL-001 症状：RESULT_INVALID |
| | 逻辑错误 | `LOGIC_ERROR` | EVA-003 自动评分器需检测 |
| | 实现不完整 | `INCOMPLETE_IMPLEMENTATION` | EVA-003 功能正确性维度检测 |
| **系统与环境失败** | 依赖缺失 | `DEPENDENCY_MISSING` | REL-001 症状：DEPENDENCY_UNAVAILABLE |
| | 权限不足 | `PERMISSION_DENIED` | REL-001 症状：REQUEST_REJECTED |
| | 资源耗尽 | `RESOURCE_EXHAUSTED` | REL-001 症状：RESOURCE_LIMIT_REACHED |
| | 网络错误 | `NETWORK_ERROR` | REL-001 症状：TRANSIENT_CONNECTIVITY |
| | 外部服务失败 | `EXTERNAL_SERVICE_FAILURE` | REL-001 症状：DEPENDENCY_UNAVAILABLE |

---

## 八、Verifier 质量控制速查（EVA-001 §9）

### 8.1 Verifier 独立测试原则

```
规则：
- Verifier 的准确性不能计入 Agent 评估结果
- Verifier 必须与被测 Agent 独立验证
- Verifier 的假阳性率和假阴性率必须可测量
```

### 8.2 Verifier 质量指标

| 指标 | 定义 | 目标 | 告警条件 |
|---|---|---|---|
| `verifier_accuracy` | Verifier 判定与人工判定一致的比例 | ≥ 95% | < 90% |
| `verifier_false_positive_rate` | 正确任务被错误拒绝的比例 | ≤ 2% | > 5% |
| `verifier_false_negative_rate` | 错误任务被错误通过的比例 | ≤ 3% | > 5% |
| `verifier_agreement` | 多个 Verifier 之间的一致性 | Krippendorff's alpha ≥ 0.8 | < 0.7 |

### 8.3 Verifier 校准数据集

```
规则：
- 维护独立的 Verifier 校准数据集（不参与 Agent 评估）
- 校准数据集包含已知正确和已知错误的样本
- 定期用校准数据集验证 Verifier 质量
- Verifier 质量下降时自动告警
```

---

## 九、LLM-as-Judge 偏差缓解速查（EVA-002 §4）

### 9.1 三种常见偏差

| 偏差类型 | 现象 | 检测方法 | 缓解策略 |
|---|---|---|---|
| **位置偏差** | 评分受答案顺序影响 | 交换答案顺序，观察评分变化 | 随机化答案顺序、评估两个排列并平均 |
| **Verbose 偏差** | 长答案获得更高评分 | 分析评分与输出长度的相关性 | 惩罚不必要长度、将正确性与风格分离 |
| **自我偏好偏差** | Judge 偏好自己生成的输出 | 比较同模型 Judge 与异模型 Judge 的评分 | 交叉模型评判、集成评判 |

### 9.2 校准算法（分阶段）

**MVP 阶段：启发式校准**
```
校准分数 = 原始分数 × 位置偏差因子 × Verbose 惩罚 × 自我偏好因子
```

**V2 阶段：Platt Scaling 校准**
```
使用标注样本训练 Platt Scaling 模型：
- 输入：原始分数和人类标注的二分类标签
- 输出：校准后的概率分数
```

**V3 阶段：BACON 框架**
```
- 多 Judge 分数 + 不确定性统计 + 上下文嵌入作为辅助特征
- 小规模人类标注样本训练交叉拟合结果模型
- 两种下游模式：总体指标估计 vs 个体级代理评分
```

---

## 十、对下游各专项的具体接口契约

| 下游专项 | 必须复用的 G06 坐标 | 禁止事项 |
|---|---|---|
| **EVA-003** 自动评分器 | 六维质量评分体系、Oracle 类型枚举、LLM-as-Judge 偏差缓解 | 不得绕过 Oracle 验证；不得混合血缘类型训练 |
| **EVA-004** 失败归因 | 14 小类失败分类、根因维度、可预防性判定 | 失败归因必须与 REL-001 症状维度对齐 |
| **EVA-005** 回归测试 | exposure_count 管理、Per-Version Holdout、污染检查机制 | 回归测试不得使用 exposure_count ≥ 3 的任务 |
| **EVA-006** 发布门禁 | 五类血缘分开报告、IRT 难度分档、置信区间 | 门禁决策不得依赖混合总分 |
| **REL-001** 失败分类 | 失败归因层 14 小类与 REL-001 症状维度映射 | 失败分类不得脱离 Golden Dataset 验证 |
| **OBS-002** 事件 Schema | 标注事件（annotation.created/updated/approved）、污染事件 | 标注事件必须记录 annotator_id 和 annotation_version |
| **OBS-003** 指标 | verifier_accuracy、unknown_rate、krippendorffs_alpha | 指标不得缺失置信区间和校准质量信息 |
| **HAR-001** 工具治理 | 工具使用与恢复维度、工具失败分类（3 小类） | 工具适配器必须提供测试用例以验证 Oracle |
| **SEC-001** 威胁模型 | 八种攻击类型、对抗样本保质期、三层隔离架构 | 威胁模型必须覆盖所有攻击类型 |

---

## 十一、数据集 Schema 核心字段速查（EVA-001 §10）

### 11.1 GoldenDataset 顶层结构

```yaml
GoldenDataset:
  version: string                           # 版本号：major.minor.patch
  created_at: timestamp
  created_by: actor_id
  lineage_counts: map<LineageType, integer>  # 各血缘类型任务数
  holdout_set: boolean                      # 是否为封存集
  holdout_for_version: string?              # 封存版本
  provenance: ProvenanceRecord
  metadata: DatasetMetadata
  manifest_hash: string                     # 清单哈希（防篡改）
```

### 11.2 TaskReference（真实任务）核心字段

```yaml
TaskReference:
  task_id: string
  lineage_type: enum                       # REAL_OWN_REPO | REAL_EXTERNAL
  source_type: enum                        # GITHUB_ISSUE | PRODUCTION | MANUAL
  contamination_check: ContaminationCheck  # 污染检查记录
  exposure_count: integer                  # 被跑次数（≥ 3 自动降级）
  status: enum                            # ACTIVE | DEGRADED | RETIRED
  oracle: OracleSpec
  difficulty: DifficultySpec               # IRT 参数 + 五维复杂度
  annotation_status: enum                  # PENDING | APPROVED | REJECTED
```

### 11.3 AdversarialSample（对抗样本）核心字段

```yaml
AdversarialSample:
  sample_id: string
  lineage_type: const = SYNTH_ADVERSARIAL
  layer: enum                             # LAYER_1 | LAYER_2 | LAYER_3
  attack_type: AttackType                 # 8 种攻击类型之一
  generator_team: string                  # 构建团队（用于独立性审计）
  generator_model: string?                # 生成模型（需与被测 Agent 不同族）
  shelf_life: duration                    # 保质期（默认 6 个月）
  expires_at: timestamp?                  # 过期时间
  status: enum                           # ACTIVE | EXPIRED | RETIRED
```

### 11.4 ContaminationCheck 结构

```yaml
ContaminationCheck:
  status: enum                         # PASS | SUSPECTED | CONFIRMED
  methods_used: string[]               # ["n-gram overlap", "repo disjoint"]
  result_details: JSON                 # 详细结果
  checked_at: timestamp
  checked_by: actor_id
```

### 11.5 DifficultySpec 结构

```yaml
DifficultySpec:
  irt_difficulty: number             # IRT θ 参数（-3 到 +3）
  irt_discrimination: number         # IRT α 参数（0.5 到 2.5）
  confidence_interval_95: [number, number]  # 95% 置信区间
  dimensions: map<string, number>   # 五维复杂度分数（1-5）
  calibrated_by: string             # 校准使用的舰队名称
  calibrated_at: timestamp
  reference_fleet_pass_rate: number  # 参考舰队通过率
```

---

## 十二、验收标准摘要（EVA-001 §13 + EVA-002 §8）

### 12.1 功能验收（EVA-001）

| 验收项 | 验收条件 |
|---|---|
| 血缘分离 | 五种血缘类型分开报告，禁用混合总分 |
| Oracle 入集闸门 | 每条任务有明确、可执行的 Oracle |
| 污染控制 | exposure_count 管理生效，holdout 机制可用 |
| 难度校准 | 多维难度参数可用，95% 置信区间已计算 |
| 对抗样本独立性 | 三层隔离架构已建立，两条红线已落实 |
| 版本化管理 | 清单哈希和签名防篡改机制已实现 |
| 保质期管理 | 对抗样本有保质期，过期自动告警 |

### 12.2 标注质量验收（EVA-002）

| 验收项 | 目标 | 验收方法 |
|---|---|---|
| 标注一致性（Krippendorff's alpha） | ≥ 0.7 | 双标注样本统计分析 |
| 污染检查覆盖率 | 100%（所有 REAL_* 任务） | 自动化检查验证 |
| Verifier 准确率 | ≥ 95% | 对比测试（100 样本） |
| Verifier 假阳性率 | ≤ 2% | 对比测试 |
| Verifier 假阴性率 | ≤ 3% | 对比测试 |
| LLM-as-Judge 与人工一致率 | ≥ 85% | 对比测试（100 样本） |
| 偏差检测 | 可识别位置/verbose 偏差 | 偏差注入测试 |

### 12.3 数量验收（EVA-001）

| 目标 | v0.1 | v1.0 |
|---|---|---|
| 真实任务总数 | ≥ 50 | ≥ 100 |
| 安全对抗样本总数 | ≥ 30 | ≥ 70 |
| 攻击类型覆盖 | ≥ 5 种 | 8 种全覆盖 |
| 每种血缘类型任务数 | ≥ 5 | ≥ 10 |
| 封存集大小 | ≥ 10 | ≥ 20 |

---

## 十三、版本化管理速查（EVA-001 §11）

### 13.1 版本号规则

```
major.minor.patch

- major：数据集结构重大变更（Schema 变更、血缘类型变更）
- minor：新增任务类别、新增攻击类型、难度重校准
- patch：任务更新、修正、新增样本
```

### 13.2 清单哈希与防篡改

```
规则：
- 每个版本生成清单（Manifest），包含所有任务 ID、版本哈希、来源信息
- 清单使用 SHA-256 计算整体哈希
- 使用平台私钥对清单签名
- 冻结后的清单不可修改
- 验证时检查签名完整性
```

### 13.3 版本发布流程

```
1. 构建版本：收集所有 APPROVED 状态的任务
2. 生成清单：计算清单哈希
3. 签名：对清单进行数字签名
4. 封存：如果当前版本是发布版本，创建封存子集
5. 发布：发布到数据集仓库，更新索引
6. 通知：通知相关团队版本发布
```

---

## 十四、变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.0 | 本次生成 | 首次从 EVA-001 和 EVA-002 提炼下游消费接口参考，不改变任何源设计内容 |
