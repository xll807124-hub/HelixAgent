# 📅 阶段 2 第 1 周详细日程 (2026-10-14 ~ 2026-10-18)

**目标**: 完成需求分析、API 设计、规范文档  
**工期**: 5 天 × 8 小时 = 40 小时  
**负责人**: 全栈开发团队

---

## 🗓️ Day 1 (Monday 2026-10-14)

### 上午 (9:00 - 12:00)

#### 任务 1.1: SAST 需求分析 (1 小时)

**投入**: 1 人

**要点:**
```
问题: 代码中的安全缺陷如何自动检测?
方案:
  ○ 选择工具: Semgrep (推荐)
  ○ 扫描时机: PolicyGateway.check_pre_execution()
  ○ 失败策略: BLOCK (高危), WARN (中危), INFO (低危)
  ○ 性能: 单次扫描 < 3 秒

输出: STAGE-2-SAST-REQUIREMENTS.md (500 字)
```

#### 任务 1.2: Secret 需求分析 (1 小时)

**投入**: 1 人

**要点:**
```
问题: 硬编码的 API key 如何阻止进入仓库?
方案:
  ○ 选择工具: detect-secrets (推荐)
  ○ 扫描时机: CoderWorker._act() 执行前
  ○ 失败策略: BLOCK 无例外
  ○ 性能: 单次扫描 < 1 秒

输出: STAGE-2-SECRET-REQUIREMENTS.md (500 字)
```

#### 任务 1.3: OTel 需求分析 (1 小时)

**投入**: 1 人

**要点:**
```
问题: 如何完整追踪分布式系统中的请求?
方案:
  ○ 选择后端: Jaeger (推荐本地部署)
  ○ Signals: Traces (优先), Metrics (可选), Logs (可选)
  ○ Sampling: 开发 100%, 生产 10%
  ○ 成本: 不应该增加 > 5% 的开销

输出: STAGE-2-OTEL-REQUIREMENTS.md (500 字)
```

### 下午 (13:00 - 17:00)

#### 任务 1.4: 接口设计 - SAST (1 小时)

**投入**: 1 人 + Review

**产出**: interface 草图
```python
# 伪代码
class SastReport:
    issues: List[SastIssue]
    scan_time_ms: int
    total_files: int
    
class SastIssue:
    rule_id: str
    severity: Literal["HIGH", "MEDIUM", "LOW"]
    file: str
    line: int
    message: str
    remediation: str  # 修复建议

async def scan(paths: List[str], config: SastConfig) -> SastReport:
    """扫描代码并返回问题列表"""
    pass
```

#### 任务 1.5: 接口设计 - Secret (1 小时)

```python
class SecretMatch:
    secret_type: str  # "aws_key", "api_key", etc
    file: str
    line: int
    confidence: float  # 0-1
    context: str  # 前后几行代码

async def scan(paths: List[str]) -> List[SecretMatch]:
    """扫描并返回检测到的密钥"""
    pass
```

#### 任务 1.6: 接口设计 - OTel (1 小时)

```python
class OTelContext:
    trace_id: str
    span_id: str
    
async def start_span(name: str, attributes: Dict) -> Span:
    """启动一个 span"""
    pass

def set_baggage(key: str, value: str) -> None:
    """设置跨请求的上下文"""
    pass
```

#### 任务 1.7: 架构草图 (1 小时)

**产出**: 3 份 ASCII 图或 Mermaid 图
```
SAST Flow:
  CoderWorker._act()
    ↓
  PolicyGateway.check_pre_execution()
    ↓
  SastScanner.scan() [3s timeout]
    ↓
  返回 BLOCK / WARN / ALLOW

Secret Flow:
  CoderWorker._act()
    ↓
  SecretScanner.scan() [1s timeout]
    ↓
  返回 BLOCK 或 ALLOW

OTel Flow:
  ReActLoop.run()
    ↓
  start_span("react_loop_run")
    ├─ observe() span
    ├─ reason() span
    └─ act() span
      ↓
  导出到 Jaeger
```

---

## 🗓️ Day 2 (Tuesday 2026-10-15)

### 上午 (9:00 - 12:00)

#### 任务 2.1: API 详细设计 (1.5 小时)

**投入**: 2 人

**产出**: 3 份 API 设计文档

**SAST API**:
```
src/security/sast/scanner.py
  ├─ class SastScanner
  ├─ async def scan(paths, config) -> SastReport
  ├─ def parse_semgrep_output(output) -> List[SastIssue]
  └─ def severity_to_decision(severity) -> PolicyDecision

Error handling:
  - Semgrep not found → ERROR
  - Scan timeout > 5s → WARN + timeout issues
  - Invalid config → DENY
```

**Secret API**:
```
src/security/secret/scanner.py
  ├─ class SecretScanner
  ├─ async def scan(paths) -> List[SecretMatch]
  ├─ def validate_findings(matches) -> List[SecretMatch]
  └─ def filter_false_positives(matches) -> List[SecretMatch]

Error handling:
  - Detector not installed → ERROR
  - File not accessible → SKIP
  - High confidence match → BLOCK
```

**OTel API**:
```
src/runtime/observability/tracer.py
  ├─ class OTelContext
  ├─ async def start_span(name, attributes)
  ├─ def set_baggage(key, value)
  ├─ def end_span()
  └─ def export()

Context propagation:
  - HTTP headers: traceparent, tracestate
  - Async context: contextvars
  - Baggage: cross-service data
```

#### 任务 2.2: 依赖分析 (0.5 小时)

**产出**: requirements-stage2.txt

```
semgrep==1.45.0          # SAST
detect-secrets==1.4.0    # Secret scanning
opentelemetry-api==1.20  # OTel API
opentelemetry-sdk==1.20  # OTel implementation
opentelemetry-exporter-jaeger==1.20  # Jaeger exporter
```

### 下午 (13:00 - 17:00)

#### 任务 2.3: 集成点分析 (1 小时)

**投入**: 1 人

**产出**: STAGE-2-INTEGRATION-POINTS.md

```
SAST 集成:
  入口: CoderWorker._act() line 370
  检查: 在 PolicyGateway.check_pre_execution() 中
  结果: 转成 Evidence 记录

Secret 集成:
  入口: CoderWorker._act() line 370
  检查: 在 check_pre_execution() 中
  结果: BLOCK 或 warning

OTel 集成:
  ReActLoop.run(): 创建 "react_loop" root span
  ReActLoop._observe(): 创建 "observe" span
  ReActLoop._reason(): 创建 "reason" span
  ReActLoop._act(): 创建 "act" span
  ActionExecutor.execute_action(): 创建 "action_execute" span
  PolicyGateway.check_*(): 创建 "policy_check" span
```

#### 任务 2.4: 错误处理策略 (1 小时)

**产出**: ERROR-HANDLING-STAGE2.md

```
SAST 失败:
  ○ Tool not found → log error, ALLOW (降级)
  ○ Timeout > 5s → log warning, ALLOW (降级)
  ○ Invalid config → DENY (失败)

Secret 失败:
  ○ Detector not installed → log error, ALLOW (降级)
  ○ Scan timeout > 1s → log warning, ALLOW (降级)
  ○ High confidence match → DENY (必须阻止)

OTel 失败:
  ○ Exporter connection fail → log error, continue
  ○ Span creation fail → log warning, continue
  ○ Context propagation fail → use default context
```

#### 任务 2.5: 性能预算 (0.5 小时)

**产出**: PERFORMANCE-BUDGET-STAGE2.md

```
总开销预算: < 10% (即 < 100ms per action)

SAST: 3 秒 (或取消)
  - 小文件 (< 10KB): 100ms
  - 中文件 (10-100KB): 500ms
  - 大文件 (> 100KB): 2 秒

Secret: 1 秒
  - 快速扫描: 200ms average
  - 超时处理: 如果 > 1s 则 ALLOW

OTel: < 10ms
  - Span creation: 1-2ms
  - Context propagation: < 1ms
  - Exporting (async): 不计入
```

---

## 🗓️ Day 3 (Wednesday 2026-10-16)

### 全天: 规范文档编写 (8 小时)

#### 任务 3.1: SAST 规范 (2.5 小时)

**产出**: STAGE-2-SAST-DESIGN.md (1500 字)

```
目录:
  1. 概述
  2. 需求分析
  3. API 设计
  4. 集成策略
  5. 错误处理
  6. 性能考量
  7. 测试计划
  8. 实现时间表
```

#### 任务 3.2: Secret 规范 (2.5 小时)

**产出**: STAGE-2-SECRET-DESIGN.md (1500 字)

#### 任务 3.3: OTel 规范 (2 小时)

**产出**: STAGE-2-OTEL-DESIGN.md (2000 字)

#### 任务 3.4: 三份规范的交叉评审 (1 小时)

**检查清单**:
- [ ] API 一致性 (都用 async def, Protocol, 等)
- [ ] 错误处理一致性
- [ ] 性能假设一致性
- [ ] 依赖冲突检查
- [ ] 集成点兼容性

---

## 🗓️ Day 4 (Thursday 2026-10-17)

### 上午 (9:00 - 12:00)

#### 任务 4.1: 用例设计 (2 小时)

**产出**: USE-CASES-STAGE2.md

**SAST 用例**:
```
UC1: 检测 SQL injection → 高危 → BLOCK
  输入: file_write("query = f'SELECT * FROM users WHERE id={user_id}'")
  预期: SAST 检测到, PolicyGateway DENY, Evidence 记录

UC2: 检测低风险 → 中危 → WARN
  输入: 使用已弃用的加密函数
  预期: SAST 检测到, PolicyGateway 允许但记录警告

UC3: 扫描超时 → 降级
  输入: 超过 5 秒的大型文件
  预期: 超时后自动允许, 记录日志
```

**Secret 用例**:
```
UC4: 检测到 AWS key → BLOCK
  输入: file_write("AWS_KEY=AKIA2...")
  预期: Secret 检测到, DENY, Evidence 记录

UC5: 置信度低 → WARN
  输入: file_write("token=abcd1234")
  预期: 检测到但置信度低, 允许但记录
```

**OTel 用例**:
```
UC6: 追踪完整 workflow
  输入: CoderWorker.run()
  预期: 生成 trace -> observe -> reason -> act spans

UC7: 导出到 Jaeger
  输入: 启用 OTel exporter
  预期: Jaeger 能查询到 trace

UC8: 跨服务传播
  输入: Worker A 调用 Worker B
  预期: trace ID 一致, 能看到完整链路
```

### 下午 (13:00 - 17:00)

#### 任务 4.2: 依赖试验 (1.5 小时)

**投入**: 1 人

**步骤**:
```bash
# 1. 创建虚拟环境
python -m venv stage2-venv
source stage2-venv/bin/activate

# 2. 安装依赖
pip install semgrep detect-secrets opentelemetry-api opentelemetry-sdk

# 3. 测试 semgrep
semgrep --version
semgrep scan --config=p/security-audit /tmp/test.py

# 4. 测试 detect-secrets
detect-secrets scan /tmp/
detect-secrets audit /tmp/.secrets.baseline

# 5. 测试 OpenTelemetry
python -c "from opentelemetry import trace; print(trace.get_tracer('test'))"

# 输出: STAGE-2-DEPENDENCY-TEST.md (安装验证报告)
```

#### 任务 4.3: 风险评估 (1.5 小时)

**产出**: RISK-ASSESSMENT-STAGE2.md

```
风险识别:

R1: Semgrep 规则维护
  影响: 中
  缓解: 使用官方规则集, 定期更新
  
R2: 误报率
  影响: 高 (会 block 合法代码)
  缓解: 多工具配合, false positive 过滤
  
R3: 性能影响
  影响: 中 (可能超过 3 秒)
  缓解: 增量扫描, 预算控制
  
R4: OTel 成本
  影响: 低 (本地 Jaeger)
  缓解: 智能采样, 本地部署

R5: 依赖冲突
  影响: 低
  缓解: 版本锁定, 兼容性测试
```

#### 任务 4.4: 修复时间表 (1 小时)

**产出**: STAGE2-TIMELINE.md

```
第 2 周日程表:
  Monday: SAST 实现 (8h)
  Tuesday: Secret 实现 (8h)
  Wednesday: OTel 实现 (8h)
  Thursday: 完整测试 (8h)
  Friday: 文档优化 (8h)

关键路径:
  Day 1 → Day 2 (SAST/Secret 独立)
  Day 3 (OTel) 可并行但需要 ReActLoop 配合
  Day 4 (测试) 依赖前三天完成
```

---

## 🗓️ Day 5 (Friday 2026-10-18)

### 全天: 规范评审和风险缓解 (8 小时)

#### 任务 5.1: 三份设计规范的内部评审 (2 小时)

**参与者**: 2+ 人

**评审清单**:
- [ ] 需求完整性
- [ ] 技术可行性
- [ ] 性能可接受
- [ ] 错误处理完善
- [ ] 集成点清晰
- [ ] 没有隐藏的技术债

**输出**: DESIGN-REVIEW-COMMENTS.md (反馈汇总)

#### 任务 5.2: 评审反馈整改 (2 小时)

基于评审意见对三份文档进行完善

**输出**: 更新的设计文档 v2

#### 任务 5.3: 依赖最终确定 (1 小时)

```
最终 requirements-stage2.txt
最终版本锁定
兼容性验证 (不与 stage 1.5 冲突)
```

#### 任务 5.4: 第 2 周工作分解 (1 小时)

**产出**: STAGE2-WEEK2-BREAKDOWN.md

```
Day 1 (周一):
  Morning:
    - SAST scanner.py implementation
    - SAST test suite setup
  Afternoon:
    - SAST rules.py
    - SAST unit tests

Day 2 (周二):
  Morning:
    - Secret scanner.py implementation
  Afternoon:
    - Secret patterns.py
    - Secret test suite

Day 3 (周三):
  Full day: OTel integration

Day 4 (周四):
  Full day: E2E testing

Day 5 (周五):
  Morning: Documentation
  Afternoon: Code cleanup & optimization
```

#### 任务 5.5: 风险缓解计划确认 (1 小时)

**产出**: MITIGATION-PLAN-STAGE2.md

```
已识别的风险及对应缓解措施
责任人分配
检查点设置
降级方案
```

---

## 📊 第 1 周交付物总结

### 文档 (7 份)

```
✅ STAGE-2-SAST-DESIGN.md (1500 字)
✅ STAGE-2-SECRET-DESIGN.md (1500 字)
✅ STAGE-2-OTEL-DESIGN.md (2000 字)
✅ STAGE-2-INTEGRATION-POINTS.md (800 字)
✅ USE-CASES-STAGE2.md (1000 字)
✅ RISK-ASSESSMENT-STAGE2.md (1200 字)
✅ STAGE2-TIMELINE.md (500 字)
```

### 代码框架 (3 个)

```
✅ src/security/sast/__init__.py
✅ src/security/secret/__init__.py
✅ src/runtime/observability/__init__.py
```

### 验证

```
✅ 依赖兼容性验证
✅ API 设计评审通过
✅ 集成点确认
✅ 第 2 周工作分解完成
```

---

**第 1 周日程完成** ✓  
**下一步**: 2026-10-21 开始第 2 周实现
