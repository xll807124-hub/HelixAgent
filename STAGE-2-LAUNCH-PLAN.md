# 🚀 阶段 2 启动计划

**启动时间**: 2026-10-12 21:50 PM UTC+8  
**优先级**: 🔴 **立即启动**  
**预计工期**: 2 周 (第 1 周规划 + 第 2 周实现)

---

## 📊 阶段 2 目标

基于阶段 1.5 Coder Worker 完成，启动 **可观测性和安全性增强**：

### 三大支柱

```
1️⃣ SAST 集成 (静态代码分析)
   └─ 在 Coder 执行工具前进行安全分析
   
2️⃣ Secret 扫描加强
   └─ 防止硬编码密钥进入代码库
   
3️⃣ OpenTelemetry 集成
   └─ 完整的分布式追踪和可观测性
```

---

## 🎯 第 1 周: 需求分析和设计 (5 天)

### Monday 2026-10-14

**任务 1: 需求分析** (3 小时)

```
○ SAST 集成需求
  ├─ 支持工具: Semgrep, Snyk, SonarQube 哪个?
  ├─ 扫描时机: tool 执行前还是后?
  ├─ 失败策略: block 还是 warn?
  └─ 性能: 扫描超时限制?

○ Secret 扫描加强
  ├─ 目标: 防止 API key/credential 泄露
  ├─ 工具: detect-secrets, TruffleHog, git-secrets?
  ├─ 位置: Coder Worker 中哪里集成?
  └─ 结果: 如何处理检测结果?

○ OTel 集成
  ├─ 信号: trace, metrics, logs?
  ├─ Exporter: Jaeger, Datadog, 还是标准 OTLP?
  ├─ Instrumentation: 哪些关键路径?
  └─ 成本: Sampling 策略?
```

**任务 2: 接口设计** (2 小时)

```
○ SAST 接口
  ├─ Input: Code path, rules config
  ├─ Output: Issues list + severity + remediation
  └─ Error: 超时、工具不可用如何处理?

○ Secret Scanner 接口
  ├─ Input: File paths, patterns
  ├─ Output: Matches + confidence + context
  └─ Integration: 与 PolicyGateway 的关系?

○ OTel Tracer 接口
  ├─ Context: TraceID, SpanID 传播
  ├─ Attributes: 关键信息记录
  └─ Baggage: 跨服务上下文
```

**任务 3: 架构草图** (1 小时)

```
生成 3 份架构草图:
  1. SAST Integration Architecture
  2. Secret Scanning Flow
  3. OTel Context Propagation
```

### Tuesday 2026-10-15

**任务 1: API 设计文档** (2 小时)

```
○ src/security/sast/interface.py
  ├─ class SastScanner(Protocol)
  ├─ method scan(paths, config) -> SastReport
  └─ def make_report(issues) -> Evidence

○ src/security/secret/scanner.py
  ├─ class SecretScanner(Protocol)
  ├─ method scan(paths) -> SecretMatches
  └─ def filter_false_positives(matches)

○ src/runtime/observability/tracer.py
  ├─ class OTelContext
  ├─ method get_current_span()
  └─ method set_baggage(key, value)
```

**任务 2: 依赖分析** (1 小时)

```
需要新增的库:
  - semgrep (SAST)
  - detect-secrets (Secret scanning)
  - opentelemetry-api, opentelemetry-sdk
  - opentelemetry-exporter-jaeger or datadog

版本和许可证检查
```

**任务 3: 集成点识别** (1 小时)

```
在以下位置集成:
  1. CoderWorker._act() - 执行工具前 SAST
  2. PolicyGateway.check_pre_execution() - Secret 检查
  3. ReActLoop._observe() - OTel 追踪
  4. ActionExecutor.execute_action() - OTel span
```

### Wednesday 2026-10-16

**任务 1: 详细规范编写** (3 小时)

```
○ STAGE-2-SAST-DESIGN.md (1500 字)
  ├─ 需求分析
  ├─ API 设计
  ├─ 错误处理
  └─ 性能考量

○ STAGE-2-SECRET-DESIGN.md (1500 字)
  ├─ 扫描策略
  ├─ 集成点
  ├─ 误报处理
  └─ 审计记录

○ STAGE-2-OTEL-DESIGN.md (2000 字)
  ├─ 追踪策略
  ├─ Span 设计
  ├─ Context 传播
  └─ 成本优化
```

**任务 2: 依赖试验** (1 小时)

```
安装并测试:
  □ pip install semgrep
  □ pip install detect-secrets
  □ pip install opentelemetry-api
  
验证:
  □ semgrep --version
  □ detect-secrets scan --help
  □ python -c "from opentelemetry import trace"
```

### Thursday 2026-10-17

**任务 1: 用例设计** (2 小时)

```
为每个功能设计 3 个用例:

SAST 用例:
  1. 发现 SQL injection 风险 → block
  2. 发现低风险问题 → warn
  3. 扫描超时 → fallback

Secret 用例:
  1. 检测到 AWS key → block
  2. 检测到高置信度 API key → block
  3. 检测到低置信度 token → warn

OTel 用例:
  1. 追踪 Coder Worker 完整生命周期
  2. 追踪单个工具执行
  3. 导出到 Jaeger 并查询
```

**任务 2: 测试计划** (1 小时)

```
单元测试:
  ○ SAST: 10 个测试
  ○ Secret: 8 个测试
  ○ OTel: 6 个测试

集成测试:
  ○ E2E: Coder 完整流程
  ○ 性能: 扫描开销 < 10%
```

### Friday 2026-10-18

**任务 1: 规范评审** (1 小时)

```
审查三份设计文档:
  □ 需求完整性
  □ API 一致性
  □ 错误处理
  □ 性能考量
```

**任务 2: 实现计划** (1 小时)

```
第 2 周工作分解:
  Day 1: SAST 核心实现
  Day 2: Secret 扫描实现
  Day 3: OTel 集成
  Day 4: 完整测试
  Day 5: 文档和优化
```

**任务 3: 风险评估** (1 小时)

```
识别风险:
  □ SAST 工具选择
  □ 性能影响
  □ 依赖冲突
  □ OTel 成本
  
制定缓解方案
```

---

## 🎯 第 2 周: 实现和测试 (5 天)

### Monday 2026-10-21

**任务: SAST 核心实现** (8 小时)

```
○ src/security/sast/scanner.py
  ├─ class SastScanner
  ├─ method scan()
  ├─ method parse_results()
  └─ error handling

○ src/security/sast/rules.py
  ├─ Security rules config
  ├─ Severity mapping
  └─ Auto-remediation suggestions

○ tests/unit/security/sast/
  ├─ test_scanner.py (8 个测试)
  └─ fixtures/ (test cases)
```

### Tuesday 2026-10-22

**任务: Secret 扫描实现** (8 小时)

```
○ src/security/secret/detector.py
  ├─ class SecretDetector
  ├─ method scan()
  ├─ method validate_findings()
  └─ confidence scoring

○ src/security/secret/patterns.py
  ├─ Regex patterns
  ├─ Custom detectors
  └─ False positive filters

○ tests/unit/security/secret/
  ├─ test_detector.py (8 个测试)
  └─ fixtures/ (PII/secret samples)
```

### Wednesday 2026-10-23

**任务: OTel 集成** (8 小时)

```
○ src/runtime/observability/tracer.py
  ├─ class OTelContext
  ├─ Trace context initialization
  ├─ Span lifecycle management
  └─ Exporter configuration

○ src/runtime/observability/instrumentation.py
  ├─ Instrument ReActLoop
  ├─ Instrument ActionExecutor
  ├─ Instrument PolicyGateway
  └─ Instrument Workers

○ tests/unit/observability/
  ├─ test_tracer.py (6 个测试)
  └─ test_instrumentation.py
```

### Thursday 2026-10-24

**任务: 完整测试和集成** (8 小时)

```
○ E2E 测试
  ├─ Coder Worker 完整流程 + SAST
  ├─ Secret 检测和阻止
  ├─ OTel 追踪导出
  └─ Jaeger UI 验证

○ 性能测试
  ├─ SAST 扫描开销
  ├─ Secret 扫描开销
  ├─ OTel 采样影响
  └─ 总体影响 < 10%

○ 错误处理测试
  ├─ 工具不可用
  ├─ 扫描超时
  ├─ 依赖缺失
```

### Friday 2026-10-25

**任务: 文档和优化** (8 小时)

```
○ 文档生成
  ├─ STAGE-2-IMPLEMENTATION.md
  ├─ API 文档
  ├─ 集成指南
  └─ 故障排除

○ 代码质量
  ├─ mypy 检查
  ├─ ruff 检查
  ├─ 代码审查

○ 准备发布
  ├─ 版本号更新
  ├─ CHANGELOG
  ├─ 发布说明
```

---

## 🔄 关键交付物

### 第 1 周交付 (设计文档)

```
✅ STAGE-2-SAST-DESIGN.md (1500 字)
✅ STAGE-2-SECRET-DESIGN.md (1500 字)
✅ STAGE-2-OTEL-DESIGN.md (2000 字)
✅ 架构草图 (3 份)
✅ API 设计文档 (3 份)
✅ 集成点分析 (1 份)
```

### 第 2 周交付 (实现代码)

```
✅ src/security/sast/ (完整实现)
✅ src/security/secret/ (完整实现)
✅ src/runtime/observability/ (完整实现)
✅ 单元测试 (24 个)
✅ E2E 测试 (5+ 个)
✅ 集成验证 (完成)
```

---

## 📈 成功标准

### 第 1 周验收

- [x] 三份设计文档完成并评审通过
- [x] 所有 API 接口定义清晰
- [x] 集成点明确
- [x] 依赖列表确定
- [x] 实现计划详细

### 第 2 周验收

- [ ] 所有代码通过 mypy 和 ruff
- [ ] 24 个单元测试全部通过
- [ ] E2E 测试通过
- [ ] 性能开销 < 10%
- [ ] 文档完整

---

## 🚀 启动指令

### 立即执行 (现在)

```bash
# 1. 创建阶段 2 分支
git checkout -b feature/stage-2-security-observability

# 2. 创建目录结构
mkdir -p src/security/sast
mkdir -p src/security/secret
mkdir -p src/runtime/observability

# 3. 创建 __init__.py 文件
touch src/security/sast/__init__.py
touch src/security/secret/__init__.py
touch src/runtime/observability/__init__.py
```

### 周一 (2026-10-14) 启动

```bash
# 1. 第一个任务: 需求分析
# → 输出: STAGE-2-REQUIREMENTS.md

# 2. 每日同步
# → 同步进度、识别风险
```

---

## 💡 关键注意事项

### 依赖选择

```
SAST 工具:
  ○ Semgrep (推荐) - 开源、快速、规则丰富
  ○ Snyk - 云端、更精准、需订阅
  ○ SonarQube - 企业级、重、贵

Secret 扫描:
  ○ detect-secrets (推荐) - 轻量、Python 原生
  ○ TruffleHog - 功能强、偏重
  ○ git-secrets - 简单、仅 Git hooks

OTel:
  ○ Jaeger (推荐) - 开源、独立、本地部署
  ○ Datadog - 商业、完整、付费
  ○ OpenTelemetry Collector - 中立、灵活
```

### 性能考量

```
扫描超时: 5 秒为宜
  - SAST: 3 秒
  - Secret: 1 秒
  - OTel: 不计入

Sampling:
  - 生产: 10% 采样
  - 开发: 100% 追踪
  - 测试: 不采样 (仅关键路径)
```

---

## 📋 当前状态

```
阶段 1.5: ✅ 完成
  ├─ ReActLoop 优化
  ├─ Coder Worker 完整
  ├─ 两层 Checkpoint 恢复
  └─ 5 道完成闸门

阶段 2 准备: ✅ 就绪
  ├─ P0/P1 修复完成
  ├─ 文档齐全
  ├─ 分支准备
  └─ 👇 现在启动
  
阶段 2: 🚀 立即启动
  ├─ 第 1 周: 设计和规划
  ├─ 第 2 周: 实现和测试
  └─ 预计完成: 2026-10-25
```

---

**阶段 2 启动计划完成** ✓  
**推荐**: 立即创建分支并启动周一任务  
**预计**: 2 周内完成实现

祝顺利! 🚀
