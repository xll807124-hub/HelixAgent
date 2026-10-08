# REQ-HAR-006: Harness 契约测试详细设计

> **需求编号**: REQ-HAR-006  
> **需求名称**: Harness 契约测试  
> **优先级**: P0  
> **状态**: v0.1-designed（待跨模块评审与冻结）  
> **创建日期**: 2026-10-05  
> **依赖**: REQ-HAR-001~005（Harness各模块）、REQ-EVA-003（自动评分器）、REQ-SEC-004（沙箱隔离）  
> **被依赖**: REQ-EVA-006（发布门禁）、REQ-OBS-001~007（可观测性各模块）

---

## 一、设计目标

### 1.1 核心定位

**Harness 契约测试是验证 Harness Engineering 各模块接口契约、隔离边界、故障注入能力的自动化测试体系**，职责包括：
- 覆盖 HAR-001~005 所有接口契约的结构化测试
- 支持确定性检查、轨迹回放、攻击回放三种测试模式
- 实现五层测试金字塔（L0~L4），对齐行业最佳实践
- 集成到 CI/CD 流水线，实现自动化回归验证

**Harness 契约测试是 Harness Engineering 质量保障的核心基础设施**，为所有 Harness 组件提供接口验证、回归检测、安全验证服务。

### 1.2 设计原则

| 原则 | 说明 |
|------|------|
| **契约优先** | 接口契约测试先于功能测试，确保接口稳定性 |
| **分层测试** | 五层金字塔（L0~L4），确定性检查在最底层 |
| **隔离执行** | 测试使用独立租户（harness-test-*），不污染生产 |
| **可复现** | 轨迹回放支持故障复现和调试 |
| **安全验证** | 攻击回放验证防御机制有效性 |

---

## 二、行业调研与标杆对齐

### 2.1 行业标杆汇总

| 标杆产品 | 核心设计 | 可借鉴点 | 来源 |
|---------|---------|---------|------|
| **OpenAI Codex** | JSONL轨迹捕获 + Schema约束 + 配对回归 | 轨迹格式、契约验证 | [Eval Skills](https://developers.openai.com/blog/eval-skills) |
| **Cursor Agent SDK** | defineEval + 三层断言 + JUnit XML | 断言机制、CI集成 | [Cursor Evals](https://cdn.jsdelivr.net/npm/@cursor/july@0.2.1/docs/reference/evals.md) |
| **Claude Code** | Builder/Evaluator分离 + Fresh-context grading | 独立评估、证据验证 | [cwc-long-running-agents](https://github.com/anthropics/cwc-long-running-agents) |
| **DeepSeek** | 离线评估 + 合成任务契约 + 计划冻结 | 回归测试、计划校验 | [DeepSeek Eval Framework](https://chat-deep.ai/docs/deepseek-evaluation-framework/) |
| **Kimi K2** | tool_call_f1 + schema_accuracy指标 | 工具调用验证 | [K2 Vendor Verifier](https://github.com/MoonshotAI/K2-Vendor-Verifier) |
| **Qoder** | 五维评估 + 参数化探针 + 证据状态机 | 全链路评估 | [Better Harness](https://docs.qoder.com/user-guide/knowledge-engine/better-harness) |

### 2.2 三种测试模式（行业共识）

根据 OpenAI、Anthropic、Cursor 行业指南，Harness 测试采用三种模式：

1. **契约测试模式**：验证接口Schema、状态机、依赖关系的确定性检查
2. **轨迹回放模式**：重放JSONL轨迹，验证行为一致性
3. **攻击回放模式**：重放故障注入场景，验证防御有效性

**模式路由逻辑**：
```
if (has_oracle) → 契约测试优先
if (需要复现故障) → 轨迹回放
if (需要验证安全) → 攻击回放
```

### 2.3 五层测试金字塔（行业标准）

根据 Google Testing Blog 和 Martin Fowler 测试金字塔理论：

| 层级 | 名称 | 延迟目标 | 执行频率 | 典型用途 |
|------|------|---------|---------|---------|
| L0 | 确定性回归 | < 5min | 每次提交 | Schema验证、状态机检查 |
| L1 | 属性/单元测试 | < 15min | 每次提交 | 接口契约、错误处理 |
| L2 | 单节点故障 | < 30min | 每日/合并前 | 故障注入、恢复验证 |
| L3 | 全链路混沌 | < 2h | 每周/发布前 | 端到端、数据一致性 |
| L4 | 封存集 | < 1h | 仅发布前 | 未知用例、泛化能力 |

---

## 三、核心实体 Schema

### 3.1 TestCase（测试用例）

测试用例定义，描述一个可执行的测试场景。

**核心字段**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `test_id` | String | 是 | 测试用例唯一标识 |
| `test_name` | String | 是 | 测试用例名称 |
| `level` | TestLevel | 是 | 测试层级（L0~L4） |
| `mode` | TestMode | 是 | 测试模式（contract/replay/attack） |
| `target_module` | String | 是 | 目标模块（HAR-001~005） |
| `target_interface` | String | 是 | 目标接口名称 |
| `description` | String | 是 | 测试描述 |
| `input` | Object | 是 | 输入数据 |
| `expected_output` | Object | 否 | 期望输出（contract模式） |
| `trace_file` | String | 否 | 轨迹文件路径（replay模式） |
| `attack_scenario` | String | 否 | 攻击场景ID（attack模式） |
| `assertions` | Array<Assertion> | 是 | 断言列表 |
| `timeout_ms` | Integer | 是 | 超时毫秒数 |
| `retry_policy` | RetryPolicy | 否 | 重试策略 |
| `dependencies` | Array<String> | 否 | 依赖的其他测试用例 |
| `tags` | Array<String> | 否 | 标签 |
| `created_at` | Timestamp | 是 | 创建时间 |

### 3.2 Assertion（断言）

测试用例的验证点，定义期望的行为或结果。

**核心字段**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `assertion_id` | String | 是 | 断言唯一标识 |
| `assertion_type` | AssertionType | 是 | hard/soft/score |
| `check_type` | CheckType | 是 | succeeded/calledTool/notCalledTool/event/check |
| `target` | String | 否 | 检查目标（工具名、事件类型等） |
| `matcher` | Object | 否 | 匹配规则（Zod Schema、正则等） |
| `score_threshold` | Float | 否 | 评分阈值（score类型） |
| `description` | String | 是 | 断言描述 |

### 3.3 TestResult（测试结果）

单个测试用例的执行结果。

**核心字段**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `result_id` | String | 是 | 结果唯一标识 |
| `test_id` | String | 是 | 关联测试用例 |
| `status` | TestStatus | 是 | PASSED/FAILED/SKIPPED/TIMEOUT/INCONCLUSIVE |
| `pass` | Boolean | 是 | 是否通过 |
| `assertions_passed` | Integer | 是 | 通过的断言数 |
| `assertions_failed` | Integer | 是 | 失败的断言数 |
| `assertion_results` | Array<AssertionResult> | 是 | 断言详细结果 |
| `duration_ms` | Integer | 是 | 执行时长 |
| `trace_id` | String | 否 | 关联Trace ID |
| `evidence` | Array<Evidence> | 否 | 证据数据 |
| `error_message` | String | 否 | 错误信息（失败时） |
| `executed_at` | Timestamp | 是 | 执行时间 |

### 3.4 TestSuite（测试套件）

一组测试用例的集合，用于批量执行和报告。

**核心字段**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `suite_id` | String | 是 | 套件唯一标识 |
| `suite_name` | String | 是 | 套件名称 |
| `level` | TestLevel | 是 | 测试层级 |
| `test_cases` | Array<String> | 是 | 测试用例ID列表 |
| `total` | Integer | 是 | 总测试数 |
| `passed` | Integer | 是 | 通过数 |
| `failed` | Integer | 是 | 失败数 |
| `skipped` | Integer | 是 | 跳过数 |
| `inconclusive` | Integer | 是 | 无法判定数 |
| `pass_rate` | Float | 是 | 通过率 |
| `duration_ms` | Integer | 是 | 总执行时长 |
| `executed_at` | Timestamp | 是 | 执行时间 |

---

## 四、五层测试金字塔设计

### 4.1 L0 确定性回归（< 5min）

**测试目标**：验证接口Schema、状态机、依赖关系的确定性属性

**测试内容**：
1. HAR-001~005 接口Schema验证
2. 状态机迁移合法性检查
3. 依赖关系正确性验证
4. 配置文件格式检查

**执行方式**：
```bash
harness-test run --level L0 --mode contract
```

**示例测试用例**：
```yaml
test_id: L0-HAR001-lifecycle-schema
test_name: "验证Harness生命周期状态机Schema"
level: L0
mode: contract
target_module: HAR-001
target_interface: HarnessLifecycleManager
description: "验证状态机定义的完整性和合法性"
input:
  state_machine_definition: "./schemas/harness-lifecycle.yaml"
assertions:
  - assertion_type: hard
    check_type: check
    matcher:
      type: schema
      schema: StateM<<CONTINUATION_MARKER>>
```

<invoke name="StrReplace">
<parameter name="path">g:\项目\Ai_agent\docs\design-specs\REQ-HAR-006-harness-contract-testing.md