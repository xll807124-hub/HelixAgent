# REQ-REL-008 测试失败与工具异常分类详细设计（工具治理与上线策略）

> 版本：v0.1-designed  
> 优先级：P0  
> 状态：详细设计已完成，待跨模块评审与冻结；未实现、未验证  
> 所属模块：可靠性（REL）  
> 子需求：REQ-REL-008A（分类引擎的决策树、解析器与信号处理细节，见 [REQ-REL-008A](./REQ-REL-008A-test-failure-tool-exception-classification.md)）  
> 前置依赖：REQ-REL-001（失败分类）、REQ-REL-003（重试决策引擎）、REQ-RT-007（幂等键）  
> 下游依赖：REQ-REL-009（故障注入验证）、REQ-EVA-004（失败归因）、REQ-HAR-003（Tool Adapter）

---

## 1. 目标与范围

### 1.1 核心目标

建立测试失败（业务反馈）与工具异常（系统故障）的明确区分规则，使分类结果能够：
1. 正确驱动重试决策引擎（REL-003）的路由逻辑
2. 保留足够的执行上下文用于失败归因（EVA-004）
3. 为工具波次上线提供分类基础（按"能否为下一类工具提供安全装置"）

### 1.2 设计边界

**包含**：
- 测试失败与工具异常的信号解析规则
- 工具类型分层上线顺序（W1/W2/W3）
- 工具注册表 Schema（包含 Effect Log 必填字段）
- 分类器输出规范（校准分数 + 证据，不含裁决阈值）
- 版本化配置契约

**不包含**：
- 裁决阈值设定（归全局决策表，本需求不定义）
- 具体工具实现（归 REQ-HAR-003）
- 补偿工作流实现（归 REQ-REL-007）

### 1.3 关键设计原则

| 原则 | 说明 | 来源 |
|------|------|------|
| **分类与裁决分离** | 分类器只产出校准分数与证据，不持有阈值 | 用户需求 Q2 + 机器学习 SRE 实践 |
| **工具分波上线** | 按安全装置就绪度分波，而非功能编号 | 用户需求 Q1 + Kubernetes API 演进 |
| **Effect Log 优先** | 工具注册时同步 7 件必填事项 | 用户需求 Q1 + Temporal Activity 契约 |
| **配置外部化** | 策略（reversible/pivot）不写死代码 | 用户需求 Q3 + 云原生配置管理 |

---

## 2. 工具分波上线策略

### 2.1 波次划分原则

**不按能力编号，按安全装置就绪度**：每一波工具上线必须为下一波提供可靠的验证、回滚或可观测能力。

### 2.2 W1（第一波）：只读观测 + 可逆写入 + 验证闭环

**目标**：建立「观测 → 写入 → 验证 → 回退」最小闭环

| 工具类型 | 示例工具 | 风险级别 | 为下一波提供的安全装置 |
|---------|---------|---------|---------------------|
| **只读观测** | `read_file`、`grep`、`git_log`、`ls` | 最低 | 为写入提供前置状态快照 |
| **可逆写入** | `write_file`（+ tombstone）、`git_commit`（+ revert） | 低 | 为测试提供代码输入 |
| **测试执行器** | `run_test`、`lint`、`typecheck` | 低 | 为下一波提供验证能力 |
| **检查点** | `save_checkpoint`、`restore_checkpoint` | 低 | 为下一波提供回滚能力 |

**上线条件**：
- 所有工具完成 7 件必填事项（见 § 2.4）
- 测试执行器能输出结构化结果（JUnit XML/JSON）
- Tombstone 回收站能保留删除文件 48 小时

**串行风险解除**：测试执行器与文件操作工具并行开发，避免卡死。

### 2.3 W2（第二波）：原子化命令 + 网络代理

**目标**：提供受控的外部交互能力

| 工具类型 | 示例工具 | 风险级别 | 为下一波提供的安全装置 |
|---------|---------|---------|---------------------|
| **原子化命令** | `install_dependency`、`git_push`、`create_pr` | 中 | 为编排提供可分解副作用 |
| **网络代理** | `curl_via_proxy`、`fetch_url`（+ 白名单） | 中 | 为集成测试提供外部依赖 |
| **沙箱隔离** | `run_in_sandbox`（Docker） | 中 | 为 Shell 提供隔离边界 |

**上线条件**：
- W1 的验证闭环已稳定运行 2 周
- 幂等账本（RT-007）已上线
- Policy Gateway（SEC-003）可拦截高风险参数

### 2.4 W3（第三波）：审计 Shell（非通用 Shell）

**目标**：提供可审计、可重放的 Shell 能力

| 工具类型 | 示例工具 | 风险级别 | 限制条件 |
|---------|---------|---------|---------|
| **审计 Shell** | `bash_audited`（记录完整 Effect Log） | 高 | 1. 禁止 `rm -rf /`<br>2. 禁止读取环境变量中的凭据<br>3. 禁止子进程逃逸<br>4. 所有副作用可分解 |

**上线条件**：
- W2 的沙箱隔离已稳定运行 4 周
- Effect Log 完整性校验已上线
- 补偿工作流（REL-007）已验证

**通用 Shell 推迟到 V2+**：需要完整审计与回放能力，不在 MVP 范围。

### 2.5 工具注册表 7 件必填事项

每个工具上线时必须同时具备（对应 Effect Log 必填字段）：

| 必填事项 | 说明 | 对应 Effect Log 字段 |
|---------|------|-------------------|
| 1. **Allowlist/Denylist** | 参数白名单/黑名单 | `policy_constraints` |
| 2. **超时与资源上限** | `timeout_ms`、`max_memory_mb` | `resource_limits` |
| 3. **输出上限** | `max_output_bytes` | `output_limits` |
| 4. **幂等故事** | 是否可重放（idempotent key 语义） | `idempotency_mode` |
| 5. **可逆性标注** | `reversible: true/false` | `reversible` |
| 6. **Pivot 标注** | `pivot`（内部状态变更）、`external_visibility`（外部可见） | `pivot`、`external_visibility` |
| 7. **补偿与对账探针接口** | `compensate()`、`reconcile()` | `compensation_handler` |

**工具注册 Schema**（概念层）：
```typescript
interface ToolRegistration {
  tool_id: string;
  tool_name: string;
  schema_version: string;
  schema_hash: string;  // 必须，纳入版本指纹
  
  // 7 件必填事项
  policy_constraints: {
    allowlist?: string[];
    denylist?: string[];
  };
  resource_limits: {
    timeout_ms: number;
    max_memory_mb?: number;
    max_cpu_percent?: number;
  };
  output_limits: {
    max_output_bytes: number;
  };
  idempotency_mode: 'idempotent' | 'non_idempotent' | 'conditional';
  reversible: boolean;
  pivot: 'internal' | 'external_invisible' | 'external_visible';
  external_visibility: boolean;
  compensation_handler?: string;  // 补偿函数引用
  reconcile_handler?: string;     // 对账函数引用
}
```

**版本指纹规则**：
- `schema_hash = SHA256(tool_name + schema_version + 7件必填事项的序列化)`
- Schema 变更 → 新 `schema_hash` → 旧幂等键与旧检查点全部作废
- 决策引擎必须在决策指纹里包含 `schema_hash`

---

## 3. 分类器设计

### 3.1 职责边界

**分类器职责**：
- 接收 `RawToolResult`（原始工具输出）
- 输出 `ClassificationResult`（校准分数 + 证据 + 症状）

**分类器不负责**：
- 裁决阈值设定（归全局决策表）
- 重试决策（归 REL-003）
- 工具准入控制（归 Policy Gateway）

### 3.2 输入规范

```typescript
interface RawToolResult {
  tool_id: string;
  schema_hash: string;  // 工具 schema 版本指纹
  
  // 基础信号
  exit_code: number | null;
  signal: string | null;  // 如 SIGSEGV
  timeout_occurred: boolean;
  elapsed_ms: number;
  
  // 输出
  has_output: boolean;
  output: string | object | null;
  output_schema_valid: boolean;
  output_truncated: boolean;
  
  // 上下文
  context: {
    task_id: string;
    workflow_id: string;
    action_id: string;
    trace_id: string;
    tool_wave: 'W1' | 'W2' | 'W3';  // 工具波次
  };
  
  // 工具元数据
  tool_metadata: {
    reversible: boolean;
    pivot: string;
    external_visibility: boolean;
  };
}
```

### 3.3 输出规范

```typescript
interface ClassificationResult {
  // REL-001 契约字段
  symptom: FailureSymptom;
  stage: ExecutionStage;
  root_cause_hint: RootCause | null;  // 初始推断，可后续修订
  
  // 校准分数（不含阈值）
  calibrated_score: number;  // [0, 1]
  calibration_method: string;  // 'platt_scaling' | 'isotonic_regression' | 'heuristic'
  calibration_version: string;
  
  // 证据
  evidence: ClassificationEvidence[];
  evidence_count: number;
  signal_strength: 'STRONG' | 'MODERATE' | 'WEAK';
  
  // 工具错误细分
  tool_error_type: ToolErrorType | null;
  is_test_failure: boolean;  // 显式标记业务测试失败
  
  // 补偿与 Pivot 信息（从工具元数据复制）
  reversible: boolean;
  pivot: string;
  external_visibility: boolean;
  
  // 版本与追溯
  classification_version: string;
  detector_id: string;
  timestamp: string;
  trace_id: string;
}

enum ToolErrorType {
  VALIDATION_ERROR = 'validation_error',
  EXTERNAL_SERVICE_FAILURE = 'external_service_failure',
  TIMEOUT = 'timeout',
  PERMISSION_DENIED = 'permission_denied',
  BUSINESS_RULE_VIOLATION = 'business_rule_violation',
  RATE_LIMIT = 'rate_limit',
  TOOL_CRASH = 'tool_crash',
  OUTPUT_MALFORMED = 'output_malformed',
  ENVIRONMENT_ERROR = 'environment_error',
  UNKNOWN = 'unknown',
}
```

### 3.4 分类流程（14 步）

**Step 1：输入验证与工具波次检查**
- 验证 `schema_hash` 是否在注册表中
- 验证 `tool_wave` 是否已上线
- 未注册工具 → 拒绝分类，返回 `UNKNOWN_FAILURE`

**Step 2：信号强度初判**
```
if signal !== null:
    signal_strength = STRONG
    preliminary_symptom = EXECUTION_ABORTED
elif exit_code === 0 && has_output:
    signal_strength = MODERATE
elif timeout_occurred:
    signal_strength = STRONG
    preliminary_symptom = OPERATION_TIMED_OUT
else:
    signal_strength = WEAK
```

**Step 3：测试结果特殊处理（仅 W1 测试执行器）**
```
if tool_id in ['run_test', 'lint', 'typecheck']:
    test_result = parseTestOutput(output)
    if test_result.failed > 0:
        return {
            symptom: TASK_VALIDATION_FAILED,
            is_test_failure: true,
            tool_error_type: BUSINESS_RULE_VIOLATION,
            calibrated_score: 0.95,  # 高置信度
            signal_strength: STRONG
        }
```

**Step 4：工具崩溃检测**
```
if signal in ['SIGSEGV', 'SIGABRT', 'SIGKILL']:
    return {
        symptom: EXECUTION_ABORTED,
        tool_error_type: TOOL_CRASH,
        calibrated_score: 0.98,
        signal_strength: STRONG
    }
```

**Step 5：超时细分（参考 RT-007 对账逻辑）**
```
if timeout_occurred:
    if tool_metadata.reversible:
        # 可逆工具超时 → 可安全重试
        return {
            symptom: OPERATION_TIMED_OUT,
            tool_error_type: TIMEOUT,
            calibrated_score: 0.85,
            recovery_hint: 'Safe to retry: operation is reversible'
        }
    elif tool_metadata.pivot === 'external_visible':
        # 外部可见操作超时 → 需对账
        return {
            symptom: OPERATION_TIMED_OUT,
            tool_error_type: TIMEOUT,
            calibrated_score: 0.80,
            recovery_hint: 'Requires reconciliation: external side-effect may exist'
        }
    else:
        return {
            symptom: OPERATION_TIMED_OUT,
            tool_error_type: TIMEOUT,
            calibrated_score: 0.75
        }
```

**Step 6：HTTP 状态码映射（W2 网络工具）**
```
if tool_wave === 'W2' && http_status:
    mapping = {
        429: {symptom: DEPENDENCY_THROTTLED, tool_error_type: RATE_LIMIT},
        401/403: {symptom: REQUEST_REJECTED, tool_error_type: PERMISSION_DENIED},
        404: {symptom: RESOURCE_NOT_FOUND, tool_error_type: VALIDATION_ERROR},
        500/502/503/504: {symptom: DEPENDENCY_UNAVAILABLE, tool_error_type: EXTERNAL_SERVICE_FAILURE}
    }
```

**Step 7：输出有效性检查**
```
if exit_code === 0 && !has_output:
    return {
        symptom: RESULT_INVALID,
        tool_error_type: OUTPUT_MALFORMED,
        calibrated_score: 0.70,
        evidence: ['Zero exit code but no output']
    }

if !output_schema_valid:
    return {
        symptom: RESULT_INVALID,
        tool_error_type: OUTPUT_MALFORMED,
        calibrated_score: 0.75
    }
```

**Step 8：权限拒绝委托 SEC 模块**
```
if detectPermissionDenial(output):
    return {
        symptom: SAFETY_CONTROL_BLOCKED,
        tool_error_type: PERMISSION_DENIED,
        calibrated_score: 0.90,
        sec_decision_required: true  # 标记需 SEC 最终判定
    }
```

**Step 9-14**：环境错误、速率限制、业务规则等（参考 § 3.3 ToolErrorType 映射）

### 3.5 置信度校准

**校准方法（按数据可用性递减）**：

| 校准方法 | 数据要求 | 精度 | MVP 使用 |
|---------|---------|------|---------|
| **Platt Scaling** | ≥1000 标注样本 + 正负样本均衡 | 高 | V2+ |
| **Isotonic Regression** | ≥500 标注样本 | 中高 | V2+ |
| **启发式规则** | 无需标注数据 | 中 | ✅ MVP |

**MVP 启发式校准**：
```
base_score = 基于信号强度的初始分数
    STRONG (直接信号如 exit_code/signal) → 0.9
    MODERATE (结构化输出解析) → 0.7
    WEAK (文本推断) → 0.5

evidence_multiplier = 1.0 - (0.05 * max(0, 3 - evidence_count))
    # 证据少于 3 条时降低置信度

calibrated_score = min(base_score * evidence_multiplier, 0.99)
```

**校准版本化**：
```
calibration_version = f"heuristic-v{SCHEMA_VERSION}"
# Schema 变更 → 校准版本变更 → 历史分数不可比
```

---

## 4. 配置管理

### 4.1 配置分层

**三层配置（从高到低优先级）**：

| 层级 | 存储位置 | 变更频率 | 示例 |
|------|---------|---------|------|
| **运行时覆盖** | 内存（热更新） | 高（应急） | Kill Switch 触发时临时禁用工具 |
| **租户策略** | 数据库（按租户） | 中（按需） | 租户 A 禁用 Shell，租户 B 允许 |
| **全局基线** | 版本化配置文件 | 低（版本发布） | W1 工具默认配置 |

### 4.2 MVP 配置文件格式

```yaml
# tool-registry-v1.yaml
version: "1.0"
schema_version: "2026-09-26"

tools:
  - tool_id: "read_file"
    tool_name: "read_file"
    wave: "W1"
    schema_hash: "sha256:abc123..."
    
    # 7 件必填事项
    policy_constraints:
      allowlist: []  # 空表示无限制（由 Policy Gateway 控制）
      denylist: ["/etc/shadow", "/root/.ssh/*"]
    
    resource_limits:
      timeout_ms: 5000
      max_memory_mb: 100
    
    output_limits:
      max_output_bytes: 10485760  # 10MB
    
    idempotency_mode: "idempotent"
    reversible: true
    pivot: "internal"
    external_visibility: false
    
    compensation_handler: null  # 只读工具无需补偿
    reconcile_handler: null

  - tool_id: "write_file"
    tool_name: "write_file"
    wave: "W1"
    schema_hash: "sha256:def456..."
    
    policy_constraints:
      denylist: ["*.exe", "*.dll", "/etc/*", "/sys/*"]
    
    resource_limits:
      timeout_ms: 10000
    
    output_limits:
      max_output_bytes: 1048576  # 1MB
    
    idempotency_mode: "idempotent"
    reversible: true  # 通过 tombstone 实现
    pivot: "internal"
    external_visibility: false
    
    compensation_handler: "compensate_write_file"
    reconcile_handler: "reconcile_file_write"

  - tool_id: "run_test"
    tool_name: "run_test"
    wave: "W1"
    schema_hash: "sha256:ghi789..."
    
    resource_limits:
      timeout_ms: 300000  # 5 分钟
      max_memory_mb: 2048
    
    output_limits:
      max_output_bytes: 52428800  # 50MB
    
    idempotency_mode: "idempotent"
    reversible: false  # 测试执行本身不可逆
    pivot: "internal"
    external_visibility: false
    
    compensation_handler: null
    reconcile_handler: null
```

### 4.3 启动期校验

```typescript
function validateToolRegistry(config: ToolRegistryConfig): ValidationResult {
  const errors = [];
  
  for (const tool of config.tools) {
    // 1. 检查 7 件必填事项
    if (!tool.resource_limits?.timeout_ms) {
      errors.push(`Tool ${tool.tool_id}: missing timeout_ms`);
    }
    
    if (!tool.output_limits?.max_output_bytes) {
      errors.push(`Tool ${tool.tool_id}: missing max_output_bytes`);
    }
    
    if (tool.idempotency_mode === undefined) {
      errors.push(`Tool ${tool.tool_id}: missing idempotency_mode`);
    }
    
    if (tool.reversible === undefined) {
      errors.push(`Tool ${tool.tool_id}: missing reversible`);
    }
    
    if (tool.pivot === undefined) {
      errors.push(`Tool ${tool.tool_id}: missing pivot`);
    }
    
    if (tool.external_visibility === undefined) {
      errors.push(`Tool ${tool.tool_id}: missing external_visibility`);
    }
    
    // 2. 检查 schema_hash 一致性
    const computed_hash = computeSchemaHash(tool);
    if (computed_hash !== tool.schema_hash) {
      errors.push(`Tool ${tool.tool_id}: schema_hash mismatch`);
    }
    
    // 3. 检查波次依赖
    if (tool.wave === 'W2' && !isWaveReady('W1')) {
      errors.push(`Tool ${tool.tool_id}: W2 tools require W1 to be stable`);
    }
    
    // 4. 检查补偿处理器引用
    if (tool.reversible && !tool.compensation_handler) {
      errors.push(`Tool ${tool.tool_id}: reversible tools require compensation_handler`);
    }
  }
  
  if (errors.length > 0) {
    throw new ConfigValidationError(errors);
  }
  
  return { valid: true };
}
```

### 4.4 配置版本化与回滚

**版本标识**：
```
config_version = f"{schema_version}+{git_commit_sha[:7]}"
# 例：2026-09-26+abc1234
```

**变更流程**：
1. 修改 `tool-registry-v1.yaml`
2. 运行 `validate-config.sh` 校验
3. 提交 Git → 触发 CI 校验
4. 部署到测试环境 → 运行回归测试
5. 部署到生产环境
6. 如有问题 → Git revert → 自动回滚

---

## 5. 与 REL-003 的集成

### 5.1 分类结果 → 重试决策流程

```
ClassificationResult
    │
    ▼
REL-003 Step 3: 症状匹配
    ├─ symptom in retryable_symptoms?
    ├─ is_test_failure === true? → 跳过重试
    ├─ calibrated_score < confidence_threshold? → ESCALATE
    └─ 继续后续步骤（幂等闸门、熔断器、预算）
```

**关键集成点**：
- `is_test_failure === true` → 强制跳过重试，进入诊断流程
- `calibrated_score` → 传递给 REL-003，由全局决策表裁决
- `reversible`、`pivot`、`external_visibility` → 传递给幂等闸门（REL-003 Step 2）

### 5.2 工具准入控制

**Policy Gateway 集成**（REL-003 Step 5）：
```typescript
function checkToolAdmission(
  tool_id: string,
  tenant_id: string,
  classification: ClassificationResult
): AdmissionResult {
  // 1. 检查工具是否在租户允许列表中
  if (!isTenantAllowed(tool_id, tenant_id)) {
    return { decision: 'DENY', reason: 'Tool not allowed for tenant' };
  }
  
  // 2. 检查工具波次是否已上线
  const tool = getToolRegistration(tool_id);
  if (!isWaveReady(tool.wave)) {
    return { decision: 'DENY', reason: `Wave ${tool.wave} not ready` };
  }
  
  // 3. 检查分类结果是否触发阻断
  if (classification.symptom === 'SAFETY_CONTROL_BLOCKED') {
    return { decision: 'DENY', reason: 'Safety control blocked' };
  }
  
  return { decision: 'ALLOW' };
}
```

**与 Q2 裁决面的关系**：
- 分类器输出 `calibrated_score` → 全局决策表查询阈值 → `ALLOW/ESCALATE/DENY`
- 裁决结果 → Policy Gateway → 工具级准入闸门

---

## 6. 验收标准

| 编号 | 验收标准 | 验证方法 |
|------|---------|---------|
| V1 | W1 工具（只读观测 + 可逆写入 + 测试执行器）全部完成 7 件必填事项注册 | 启动期校验通过 |
| V2 | 测试执行器返回「failed > 0」映射到 `TASK_VALIDATION_FAILED` + `is_test_failure = true` | 单元测试 |
| V3 | 工具崩溃（signal !== null）映射到 `EXECUTION_ABORTED` + `TOOL_CRASH` | 单元测试 |
| V4 | 工具超时 + `reversible = true` 映射到可重试；`external_visible = true` 映射到需对账 | 单元测试 |
| V5 | 分类器只输出 `calibrated_score`，不包含裁决阈值 | 代码审查 |
| V6 | `schema_hash` 纳入工具注册，变更触发版本更新 | 集成测试 |
| V7 | 配置文件校验失败时启动拒绝 | 启动测试 |
| V8 | W2 工具在 W1 未稳定前拒绝上线 | 启动测试 |
| V9 | 分类结果的 `reversible`、`pivot`、`external_visibility` 正确复制自工具元数据 | 单元测试 |
| V10 | 裁决结果（ALLOW/DENY）能落到工具级准入闸门 | 集成测试 |
| V11 | 配置变更可通过 Git revert 回滚 | 回滚演练 |
| V12 | 分类延迟 P99 < 10ms | 性能测试 |

---

## 7. 依赖与接口

### 7.1 上游依赖

| 依赖 | 说明 |
|------|------|
| REQ-REL-001 | 症状、阶段、根因三维分类模型 |
| REQ-RT-007 | 幂等键与副作用边界 |
| REQ-RT-003 | 事件契约（发布分类事件） |
| REQ-SEC-003 | Policy Gateway（工具准入控制） |

### 7.2 下游接口

| 接口 | 消费者 | 说明 |
|------|--------|------|
| `ClassificationResult` | REL-003 重试决策引擎 | 提供症状、分数、是否测试失败 |
| `ToolRegistration` | REQ-HAR-003 Tool Adapter | 工具注册契约 |
| `tool-registry-v1.yaml` | 启动期校验 | 配置文件格式 |

---

## 8. 参考资料

以下为公开来源，访问日期均为 2026-09-26：

- OpenAI Codex 错误分类：[error.rs](https://github.com/openai/codex/blob/f1affbac/codex-rs/protocol/src/error.rs)
- Claude Code 工具执行层错误边界：[Error Handling](https://claude-wiki.com/error-handling-and-recovery.html)
- Cursor SDK 两层错误模型：[docs/errors.md](https://github.com/cursor/sdk-bridge/blob/main/docs/errors.md)
- Kimi Code 错误参考：[错误参考](https://www.kimi.com/code/docs/kimi-code/error-reference.html)
- Dify 节点失败处理：[Handle Errors](https://docs.dify.ai/en/cloud/use-dify/build/predefined-error-handling-logic)
- Temporal Activity 契约：[Activity Definition](https://docs.temporal.io/activities)
- Kubernetes API 演进：[API Changes](https://kubernetes.io/docs/reference/using-api/api-concepts/)

---

## 9. 决策记录

| 决策项 | 决策 | 依据 |
|-------|------|------|
| 工具分波顺序 | W1 只读观测 + 可逆写入 + 测试执行器 → W2 原子化命令 + 网络代理 → W3 审计 Shell | 用户需求 Q1 + Kubernetes API 演进 |
| 通用 Shell 时机 | 推迟到 V2+，MVP 不提供 | 用户需求 Q1 + Effect Log 语义重建困难 |
| 置信度阈值归属 | 分类器不持有，归全局决策表 | 用户需求 Q2 + 关注点分离 |
| 配置方式 | 版本化配置文件 + 启动期校验 | 用户需求 Q3 + 云原生实践 |
| `schema_hash` 必须性 | 必须纳入版本指纹 | 用户需求 Q1 + 幂等键失效问题 |
| 7 件必填事项时机 | 工具注册时同步完成 | 用户需求 Q1 + Effect Log 必填字段 |

---

**文档创建时间**：2026-09-26  
**最后更新时间**：2026-09-26  
**维护团队**：架构组
