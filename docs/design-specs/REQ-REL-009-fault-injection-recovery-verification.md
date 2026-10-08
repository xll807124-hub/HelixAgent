# REQ-REL-009 故障注入和恢复验证场景详细设计

> 版本：v0.1-designed  
> 优先级：P0  
> 状态：详细设计已完成，待跨模块评审与冻结；未实现、未验证  
> 所属模块：可靠性（REL）  
> 前置依赖：REQ-REL-001 至 REQ-REL-008  
> 下游依赖：REQ-EVA-004、REQ-OBS-005  
> 设计完成日期：2026-09-26

---

## 1. 目标与范围

### 1.1 核心目标

建立覆盖全故障类型的故障注入框架，支持 HTTP 层、SDK 层、系统调用层的多层故障注入，并设计可验证的故障场景库和恢复验证协议，确保 REL-001~008 设计的失败分类、重试决策、恢复机制按预期工作。

**核心价值主张**：
- **生产前验证**：在生产前发现和修复可靠性问题
- **恢复路径验证**：验证恢复路径的正确性和完整性
- **韧性信心建立**：建立对系统韧性的可量化信心
- **自动化回归**：支持故障场景的自动化回归测试

### 1.2 设计边界

**包含**：
- 系统化故障分类法，映射到 REL-001 的 14 类症状
- HTTP/SDK/系统调用三层故障注入机制
- 行为契约验证协议
- 完整恢复路径验证（决策→执行→完成）
- 自动化验证流水线
- 故障注入安全控制和审计

**不包含**：
- 生产环境无限制故障注入（需额外审批）
- 真实用户流量下的故障注入
- 跨组织的分布式故障注入
- ML 辅助的故障场景自动发现（V2+ 特性）

---

## 2. 行业标杆研究与设计依据

### 2.1 公开事实

以下为经验证的公开资料，访问日期均为 2026-09-26：

1. **AgentChaos**（学术+开源）
   - HTTP 层故障注入，无需修改源码
   - 65+ 预构建故障配置，覆盖崩溃、遗漏、值故障
   - 故障触发验证机制，过滤未触发场景
   - 来源：[GitHub](https://github.com/floritange/AgentChaos/)、[arXiv 论文](https://arxiv.org/pdf/2608.06790.pdf)

2. **faultkit**（商业工具）
   - 多层注入机制：HTTP 语义层、管道层、系统调用层（eBPF）
   - 退出码语义：exit 1=故障触发、exit 3=无匹配流量
   - 场景化配置管理，支持 CI 集成
   - 来源：[faultkit.dev](https://faultkit.dev/)、[GitHub](https://github.com/faultkit/faultkit)

3. **Tumult**（混沌工程代理）
   - 行为契约验证：重试预算、JSON 格式、密钥泄露边界
   - OpenTelemetry 集成，故障 span 与模型调用 span 对齐
   - 场景包管理，支持离线模拟和回放
   - 来源：[TestDevTools](https://testdev.tools/tumult/)

4. **Claude Code**（Anthropic 官方）
   - 10 次指数退避重试，覆盖 429/5xx/超时/断连
   - 流中断保留部分输出，但工具调用可能丢失
   - 已知问题：可能重复执行非幂等操作
   - 来源：[错误文档](https://code.claude.com/docs/en/errors)

5. **DeepSeek Harness**（DeepSeek 官方）
   - 中断 turn 追加合成 `turn/end { reason: 'interrupted' }`
   - 工具调用未知结果标记 `TOOL_OUTCOME_UNKNOWN`
   - 语义持久化策略：模型请求前、工具副作用前、每步边界
   - 来源：[Session Persistence](https://deepseek-harness.github.io/deepseek-harness/en/reference/subsystems/persistence)

6. **LitmusChaos**（CNCF 项目）
   - 稳态假设验证：HTTP probe、cmd probe、k8s probe、prom probe
   - 声明式故障配置，ChaosEngine/ChaosResult 资源
   - Argo Workflows 编排复杂实验场景
   - 来源：[GitHub](https://github.com/litmuschaos/litmus/)

### 2.2 设计推断

本项目采用以下设计决策，结合行业最佳实践与项目现有架构：

1. **故障分类法**：采用 AgentChaos 的系统化分类，映射到 REQ-REL-001 的症状词表
2. **多层注入**：借鉴 faultkit 的三层注入（HTTP/SDK/系统调用）
3. **行为契约**：采用 Tumult 的契约验证模式
4. **恢复验证**：借鉴 DeepSeek Harness 的完整恢复路径验证
5. **安全控制**：参考 LitmusChaos 的稳态假设验证和实验编排

---

## 3. 故障分类法与场景库

### 3.1 系统化故障分类

基于 REQ-REL-001 的 14 类症状词表，建立故障注入场景库：

| 故障层 | 故障类型 | 对应症状 | 注入机制 | 场景编号 |
|-------|---------|---------|---------|---------|
| **HTTP 层** | 429 限流 | `DEPENDENCY_THROTTLED` | HTTP 代理 | FAULT-HTTP-001 |
| HTTP 层 | 503 服务不可用 | `DEPENDENCY_UNAVAILABLE` | HTTP 代理 | FAULT-HTTP-002 |
| HTTP 层 | 500 服务错误 | `DEPENDENCY_UNAVAILABLE` | HTTP 代理 | FAULT-HTTP-003 |
| HTTP 层 | 请求超时 | `OPERATION_TIMED_OUT` | HTTP 代理 | FAULT-HTTP-004 |
| HTTP 层 | 连接断开 | `TRANSIENT_CONNECTIVITY` | HTTP 代理 | FAULT-HTTP-005 |
| HTTP 层 | 畸形 JSON | `RESULT_INVALID` | HTTP 代理 | FAULT-HTTP-006 |
| HTTP 层 | 截断响应 | `RESULT_INVALID` | HTTP 代理 | FAULT-HTTP-007 |
| **SDK 层** | 工具调用失败 | `EXECUTION_ABORTED` | Mock/桩 | FAULT-SDK-001 |
| SDK 层 | 工具超时 | `OPERATION_TIMED_OUT` | Mock/桩 | FAULT-SDK-002 |
| SDK 层 | 工具返回无效 | `RESULT_INVALID` | Mock/桩 | FAULT-SDK-003 |
| **系统层** | Worker 进程崩溃 | `EXECUTION_ABORTED` | SIGKILL | FAULT-SYS-001 |
| 系统层 | 内存耗尽 | `RESOURCE_LIMIT_REACHED` | cgroup | FAULT-SYS-002 |
| 系统层 | 磁盘满 | `RESOURCE_LIMIT_REACHED` | cgroup | FAULT-SYS-003 |
| **权限层** | 策略拒绝 | `SAFETY_CONTROL_BLOCKED` | 策略注入 | FAULT-AUTH-001 |
| 权限层 | 凭据过期 | `REQUEST_REJECTED` | 凭据注入 | FAULT-AUTH-002 |
| **时间层** | 时钟偏移 | `OPERATION_TIMED_OUT` | 时间注入 | FAULT-TIME-001 |

### 3.2 故障场景详细定义

每个场景至少包含：

```yaml
scenario_id: FAULT-HTTP-001
name: "HTTP 429 限流"
symptom: DEPENDENCY_THROTTLED
injection_layer: HTTP
injection_mechanism: proxy
trigger_condition:
  pattern: "POST /v1/chat/completions"
  count: 3
  window_seconds: 10
fault_config:
  status_code: 429
  headers:
    Retry-After: "30"
    X-RateLimit-Remaining: "0"
  body: |
    {
      "error": {
        "message": "Rate limit exceeded",
        "type": "rate_limit_error",
        "code": "rate_limit_exceeded"
      }
    }
duration_seconds: 60
blast_radius: single_tenant
expected_behavior:
  - symptom_detected: DEPENDENCY_THROTTLED
  - retry_decision: RETRY
  - retry_delay_min_ms: 30000
  - retry_delay_max_ms: 32000
  - global_budget_impact: counted
  - circuit_breaker: not_triggered
verification:
  - assert: "symptom == 'DEPENDENCY_THROTTLED'"
  - assert: "decision == 'RETRY'"
  - assert: "delay_ms >= 30000"
  - assert: "delay_ms <= 32000"
```

---

## 4. 故障注入架构

### 4.1 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                     故障注入控制器                               │
│           (FaultInjectionController)                            │
└──────────────────────┬──────────────────────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        │              │              │
        ▼              ▼              ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│  HTTP 代理    │ │  SDK Mock    │ │  系统注入    │
│  Injector    │ │  Injector    │ │  Injector    │
└──────┬───────┘ └──────┬───────┘ └──────┬───────┘
       │                │                │
       ▼                ▼                ▼
┌─────────────────────────────────────────────────┐
│              目标系统 (Agent Runtime)            │
└─────────────────────────────────────────────────┘
       │                │                │
       ▼                ▼                ▼
┌─────────────────────────────────────────────────┐
│              事件收集器 & 验证引擎               │
└─────────────────────────────────────────────────┘
```

### 4.2 HTTP 代理注入器

**设计原则**：
- 透明代理，无需修改目标代码
- 支持选择性拦截（基于 URL 模式）
- 支持故障触发验证
- 支持动态配置更新

**实现方式**：
```
1. 启动本地 HTTP/HTTPS 代理服务器
2. 配置目标系统的环境变量：HTTPS_PROXY、HTTP_PROXY
3. 注入临时 CA 证书（用于 HTTPS 拦截）
4. 拦截匹配的请求，应用故障配置
5. 记录故障触发事件
```

**关键接口**：
- `configure(scenario: FaultScenario)`: 配置故障场景
- `start()`: 启动代理
- `stop()`: 停止代理
- `verify_triggered()`: 验证故障是否被触发

### 4.3 SDK Mock 注入器

**设计原则**：
- 基于依赖注入或 Mock 框架
- 支持工具调用级别的故障注入
- 保持接口契约一致性

**实现方式**：
```
1. 识别工具调用接口
2. 注入 Mock 实现
3. 根据场景配置返回故障响应
4. 记录调用和故障事件
```

### 4.4 系统层注入器

**设计原则**：
- 使用操作系统原生机制
- 支持进程级和资源级故障
- 确保可恢复性

**实现方式**：
```
1. 进程崩溃：发送 SIGKILL 信号
2. 资源耗尽：使用 cgroup 限制内存/CPU/磁盘
3. 时钟偏移：使用 libfaketime 或类似工具
```

---

## 5. 恢复验证协议

### 5.1 验证流程

```
故障注入 → 观察系统响应 → 验证失败分类 → 验证重试决策 → 
验证恢复路径 → 验证状态一致性 → 验证副作用 → 生成报告
```

### 5.2 验证维度

#### 5.2.1 失败分类验证（REL-001 集成）

**验证目标**：确认故障被正确分类为预期症状

**验证方法**：
```python
def verify_classification(fault_scenario, actual_symptom):
    assert actual_symptom == fault_scenario.expected_symptom
    assert detector_confidence >= threshold
    assert evidence_count >= min_evidence
```

#### 5.2.2 重试决策验证（REL-003 集成）

**验证目标**：确认重试决策符合 REL-003 的 11 步流程

**验证方法**：
```python
def verify_retry_decision(fault_scenario, decision_event):
    # 验证幂等闸门
    if fault_scenario.requires_idempotency:
        assert decision_event.idempotency_check_passed
    
    # 验证症状匹配
    assert decision_event.symptom in fault_scenario.retryable_symptoms
    
    # 验证预算
    assert decision_event.budget_remaining > 0
    
    # 验证熔断器
    assert decision_event.circuit_state != 'OPEN'
    
    # 验证延迟
    if fault_scenario.server_retry_after:
        assert decision_event.delay_ms >= fault_scenario.server_retry_after
```

#### 5.2.3 恢复路径验证（REL-005 集成）

**验证目标**：确认恢复路径符合 REL-005 的九态状态机

**验证方法**：
```python
def verify_recovery_path(fault_scenario, recovery_events):
    # 验证状态迁移
    assert_state_transitions(recovery_events, VALID_TRANSITIONS)
    
    # 验证污染半径
    if fault_scenario.has_side_effects:
        assert recovery_events.contamination_radius <= expected_radius
    
    # 验证 Effect Log
    if fault_scenario.has_external_effects:
        assert all_effects_recorded(recovery_events.effect_log)
    
    # 验证副作用
    assert no_duplicate_side_effects(recovery_events)
    
    # 验证恢复完整性
    assert recovery_complete(recovery_events)
```

### 5.3 行为契约验证

每个故障场景定义行为契约，包含：

1. **前置条件**：故障注入前的系统状态
2. **故障注入条件**：触发故障的条件
3. **预期响应**：系统的预期行为
4. **后置条件**：恢复后的系统状态

**示例契约**：
```yaml
contract:
  precondition:
    - task_state: RUNNING
    - worker_state: ACTIVE
    - circuit_state: CLOSED
  
  fault_injection:
    - trigger: "3rd API call within 10s"
    - fault_type: HTTP_429
    - duration: 60s
  
  expected_response:
    - symptom_detected: DEPENDENCY_THROTTLED
    - retry_scheduled: true
    - retry_delay: [30000, 32000]
    - global_budget_consumed: 1
    - circuit_state_unchanged: true
  
  postcondition:
    - task_state: RUNNING
    - worker_state: ACTIVE
    - circuit_state: CLOSED
    - no_duplicate_effects: true
```

---

## 6. 自动化验证流水线

### 6.1 CI/CD 集成

**集成点**：
1. **Pull Request 验证**：提交前自动运行关键故障场景
2. **夜间回归**：完整故障场景库回归测试
3. **发布前门禁**：必须通过所有 P0 故障场景

**退出码语义**（借鉴 faultkit）：
- `0`：所有场景通过
- `1`：至少一个场景失败
- `2`：基础设施错误（故障注入器本身故障）
- `3`：无匹配流量（场景未触发）

### 6.2 本地开发验证

**CLI 接口**：
```bash
# 运行单个场景
fault-inject run --scenario FAULT-HTTP-001

# 运行场景组
fault-inject run --group http_failures

# 交互式调试
fault-inject debug --scenario FAULT-HTTP-001

# 列出场景
fault-inject list

# 验证场景配置
fault-inject validate --scenario FAULT-HTTP-001
```

### 6.3 验证报告

**报告内容**：
1. **执行摘要**：场景总数、通过数、失败数、跳过数
2. **详细结果**：每个场景的验证结果、证据、失败原因
3. **Trace 关联**：关联完整的 Trace 链路
4. **建议行动**：失败场景的修复建议

**报告格式**：
- JSON（机器可读）
- Markdown（人类可读）
- HTML（可视化）

---

## 7. 安全控制与审计

### 7.1 权限控制

**角色定义**：
1. **故障注入操作员**：可执行测试环境的故障注入
2. **高级操作员**：可执行预发布环境的故障注入
3. **安全审核员**：可审批生产环境的故障注入
4. **只读观察员**：可查看验证报告，不可执行注入

**权限矩阵**：

| 角色 | 测试环境 | 预发布环境 | 生产环境 |
|-----|---------|-----------|---------|
| 故障注入操作员 | ✅ | ❌ | ❌ |
| 高级操作员 | ✅ | ✅（需审批）| ❌ |
| 安全审核员 | ✅ | ✅ | ✅（需多人审批）|

### 7.2 爆炸半径限制

**隔离机制**：
1. **租户隔离**：故障只影响指定租户
2. **任务隔离**：故障只影响指定任务
3. **时间限制**：故障自动过期

**示例配置**：
```yaml
blast_radius:
  scope: single_tenant
  tenant_id: "test-tenant-001"
  task_id: "task-123"
  max_duration_seconds: 300
  auto_rollback: true
```

### 7.3 审计跟踪

**审计事件**：
1. 故障注入请求
2. 故障注入执行
3. 故障触发确认
4. 验证结果
5. 异常中止

**审计字段**：
- 操作员身份
- 时间戳
- 场景配置
- 执行环境
- 结果状态
- 影响范围

**留存策略**：
- 测试环境：30 天
- 预发布环境：90 天
- 生产环境：180 天（符合 SEC-008）

---

## 8. 性能与成本

### 8.1 性能影响

**HTTP 代理开销**：
- 延迟增加：< 5ms（P99）
- 吞吐量影响：< 2%
- 内存开销：< 50MB

**验证开销**：
- 单场景验证时间：< 5 分钟
- 完整场景库验证时间：< 2 小时

### 8.2 成本控制

**存储成本**：
- 验证报告：每次 < 10MB
- Trace 数据：每场景 < 50MB
- 审计日志：每天 < 100MB

**计算成本**：
- CI/CD 集成：每次 PR < 15 分钟
- 夜间回归：< 2 小时

---

## 9. MVP 范围与演进

### 9.1 MVP 范围

**MVP 必须包含**：
1. HTTP 层故障注入（5 个场景）
   - FAULT-HTTP-001: 429 限流
   - FAULT-HTTP-002: 503 服务不可用
   - FAULT-HTTP-004: 请求超时
   - FAULT-HTTP-005: 连接断开
   - FAULT-HTTP-006: 畸形 JSON

2. SDK 层故障注入（2 个场景）
   - FAULT-SDK-001: 工具调用失败
   - FAULT-SDK-002: 工具超时

3. 恢复验证（3 个维度）
   - 失败分类验证
   - 重试决策验证
   - 基本恢复路径验证

4. 自动化集成
   - CLI 接口
   - CI/CD 集成
   - 验证报告

**MVP 不包含**：
- 系统层故障注入
- 时间层故障注入
- 生产环境故障注入
- ML 辅助场景发现

### 9.2 演进路线

**V2（Q1 2027）**：
- 系统层故障注入（进程崩溃、资源耗尽）
- 完整恢复路径验证（Effect Log、补偿流程）
- 预发布环境支持

**V3（Q2 2027）**：
- 时间层故障注入
- 生产环境触发式注入（受控）
- 压力测试模式

**V4（Q3 2027）**：
- ML 辅助场景发现
- 自适应故障注入
- 混沌工程平台集成

---

## 10. 验收标准

| 编号 | 验收项 | 验证方法 |
|------|--------|---------|
| V1 | MVP 场景覆盖 | 7 个场景全部实现并可执行 |
| V2 | 故障触发率 | > 95%（过滤未触发场景） |
| V3 | 分类准确性 | 故障症状分类准确率 > 95% |
| V4 | 重试决策准确性 | 重试决策符合 REL-003 设计 > 90% |
| V5 | 恢复路径有效性 | 恢复路径验证通过 > 90% |
| V6 | 副作用验证 | 无重复副作用 = 100% |
| V7 | 性能影响 | HTTP 代理延迟 < 5ms（P99） |
| V8 | CI/CD 集成 | PR 验证时间 < 15 分钟 |
| V9 | 审计完整性 | 所有故障注入操作可审计 |
| V10 | 安全隔离 | 爆炸半径限制生效 = 100% |

---

## 11. 依赖与接口

### 11.1 上游依赖

| 依赖 | 接口 | 说明 |
|------|------|------|
| REQ-REL-001 | `FailureClassifier.classify()` | 获取失败症状分类 |
| REQ-REL-003 | `RetryDecisionEngine.decide()` | 获取重试决策 |
| REQ-REL-005 | `RecoveryCoordinator.recover()` | 获取恢复决策 |
| REQ-RT-006 | `TraceContext` | 关联 Trace |
| REQ-SEC-003 | `PolicyGateway.check()` | 验证策略阻断 |

### 11.2 下游接口

| 接口 | 说明 | 消费者 |
|------|------|-------|
| `FaultInjectionEngine` | 执行故障注入 | CI/CD、SRE |
| `VerificationEngine` | 执行验证 | 测试工程师 |
| `ScenarioRegistry` | 管理场景库 | 开发者 |
| `VerificationReport` | 输出报告 | EVA、OBS |

---

## 12. 参考资料

以下为公开来源，访问日期均为 2026-09-26：

1. AgentChaos: [GitHub](https://github.com/floritange/AgentChaos/)、[arXiv 论文](https://arxiv.org/pdf/2608.06790.pdf)
2. faultkit: [官网](https://faultkit.dev/)、[GitHub](https://github.com/faultkit/faultkit)
3. Tumult: [TestDevTools](https://testdev.tools/tumult/)
4. Claude Code: [错误文档](https://code.claude.com/docs/en/errors)
5. GitHub Copilot SDK: [Session Persistence](https://github.com/github/copilot-sdk/blob/main/docs/features/session-persistence.md)
6. OpenAI Codex: [Rollout Recorder](https://github.com/openai/codex/blob/main/codex-rs/rollout/src/recorder.rs)
7. DeepSeek Harness: [Session Persistence](https://deepseek-harness.github.io/deepseek-harness/en/reference/subsystems/persistence)
8. LitmusChaos: [GitHub](https://github.com/litmuschaos/litmus/)

---

## 13. 决策记录

| 决策项 | 决策 | 依据 |
|-------|------|------|
| 故障分类法 | 系统化分类，映射到 REL-001 症状 | AgentChaos 实践 |
| 注入层级 | HTTP/SDK/系统调用三层 | faultkit 多层设计 |
| 验证协议 | 行为契约验证 | Tumult 契约模式 |
| 恢复验证 | 完整路径验证（决策→执行→完成） | DeepSeek Harness |
| MVP 范围 | HTTP + SDK 层，7 个场景 | 成本与覆盖平衡 |
| 执行环境 | 测试优先，预发布需审批，生产受控 | 安全优先原则 |

---

## 14. 变更记录

| 版本 | 日期 | 变更 |
|------|------|------|
| v0.1-designed | 2026-09-26 | 初始版本，完成详细设计，待跨模块评审与冻结 |

---

**文档创建时间**：2026-09-26  
**维护团队**：可靠性工程组
