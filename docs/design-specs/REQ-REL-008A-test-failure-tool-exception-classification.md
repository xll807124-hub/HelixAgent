# REQ-REL-008A 测试失败与工具异常分类详细设计（分类引擎）

> **版本**：v0.1-designed  
> **优先级**：P0  
> **状态**：详细设计已完成，待跨模块评审与冻结；未实现、未验证  
> **所属模块**：可靠性（REL）  
> **父需求**：REQ-REL-008（测试失败与工具异常分类的工具注册表、上线策略、配置契约）  
> **前置依赖**：REQ-REL-001（失败分类）、REQ-REL-003（重试决策引擎）、REQ-RT-003（事件 Schema）、REQ-RT-007（幂等键）  
> **下游依赖**：REQ-REL-009（故障注入验证）、REQ-EVA-003（自动评分器）、REQ-HAR-003（Tool Adapter）  
> **设计参考**：OpenAI Codex/Agents SDK、Claude Code、DeepSeek、Cursor、Anthropic MCP Server  
> **用户确认日期**：2026-09-26（确认设计方向并要求细化对标 Codex 架构）
> 
> **说明**：本文档（REQ-REL-008A）专注于分类引擎的决策树、解析器和信号处理细节；工具分波上线策略、工具注册表 Schema、分类器输出契约等治理层设计见 [REQ-REL-008](./REQ-REL-008-test-failure-tool-error-classification.md)。

---

## 1. 目标与范围

### 1.1 核心目标

建立测试失败（Test Failure）与工具异常（Tool Exception）的确定性分类决策树，使系统能够精准区分"业务验证失败"（需诊断/修复代码）与"工具/平台故障"（需重试/降级/升级），避免将代码缺陷误判为可重试的瞬态错误，或将平台故障误判为代码问题。

**核心价值主张**：
- **测试失败 ≠ 工具异常**：测试套件成功执行并给出未通过结果是业务失败，不应盲目重试
- **工具异常 ≠ 测试失败**：工具进程崩溃、超时、依赖缺失属于平台故障，需重试或运维介入
- **结构化优先于文本推断**：优先使用退出码、JSON 输出、XML 报告等结构化信号
- **保守处置优于乐观假设**：信号模糊时默认升级人工，不假设可重试
- **MCP 工具错误独立处理**：MCP Server 连接、调用、超时错误按 MCP 协议规范分类

### 1.2 设计边界

**包含**：
- 测试工具输出解析器（JUnit XML、pytest JSON、Go test JSON、Cargo JSON、TAP）
- 工具进程退出码与信号分类映射
- MCP 工具错误分类（连接、调用、超时、协议违规）
- 测试失败与工具异常的确定性分类决策树
- 结构化输出解析失败的降级策略
- 分类结果到 `REQ-REL-001` 症状映射
- 分类结果到 `REQ-REL-003` 处置建议（Disposition）映射

**不包含**：
- 测试失败的根因推断（归因给诊断/修复模块）
- 代码生成/修复策略（由 Agent 工作流处理）
- 重试策略执行（由 REL-003 决策引擎执行）
- MCP Server 实现规范（遵循 Anthropic MCP 协议）

---

## 2. 设计原则与术语

### 2.1 核心原则

|| 原则 | 说明 | 违反后果 |
||------|------|---------|
|| **业务失败不可重试** | 测试套件正常执行并报告失败 ≠ 平台故障，不进入自动重试 | 浪费预算、掩盖代码缺陷 |
|| **结构化信号优先** | 退出码、JSON/XML 报告优先于 stderr 文本推断 | 分类不稳定、误判率高 |
|| **保守处置** | 信号模糊/冲突时升级人工，不假设可重试或成功 | 与 REL-001 UNKNOWN 原则一致 |
|| **MCP 协议对齐** | MCP 错误分类遵循 Anthropic MCP 规范，不自创类别 | 跨系统互操作性破坏 |
|| **版本化解析器** | 解析器版本化，输出绑定解析器版本与置信度 | 分类结果不可追溯、回滚困难 |

### 2.2 术语定义

| 术语 | 定义 | 示例 |
|------|------|------|
| **Test Failure** | 测试工具成功执行，给出明确未通过结果（结构化报告或退出码 ≠ 0） | `pytest` 退出码 1 + JSON 报告显示 3 failed / 10 passed |
| **Tool Exception** | 工具进程崩溃、超时、依赖缺失、沙箱资源耗尽、信号终止 | `pytest` 进程被 SIGKILL 终止（退出码 137） |
| **Execution Aborted** | 工具未能正常启动或执行被外部中断 | 沙箱内存不足触发 OOM Killer |
| **Result Invalid** | 工具退出但输出不符合预期格式或缺少必需字段 | `pytest --json` 输出空文件或非法 JSON |
| **MCP Tool Error** | MCP Server 连接失败、调用超时、协议违规、Server 内部错误 | MCP `initialize` 超时、`call_tool` 返回 error 字段 |
| **Structured Output** | 机器可解析的测试报告（JUnit XML、JSON、TAP） | JUnit XML `<testcase>` 标签 |
| **Unstructured Signal** | 退出码、stderr 文本、信号编号 | 退出码 1、stderr 包含 "AssertionError" |

---

## 3. 分类决策树

### 3.1 总体架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         输入：工具执行结果                               │
│  - exit_code: int | null                                                │
│  - signal: int | null (e.g., SIGKILL=9, SIGTERM=15)                     │
│  - stdout: string                                                        │
│  - stderr: string                                                        │
│  - execution_time_ms: int64                                              │
│  - timeout_reached: bool                                                 │
│  - structured_output_path: string | null                                 │
│  - tool_type: "test" | "mcp" | "generic"                                │
│  - idempotency_key: string                                               │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Step 1: 强制终止信号检测                                                 │
│ - 检查进程是否被信号终止（signal ≠ null）                               │
│ - 信号映射：                                                             │
│   - SIGKILL (9) / SIGSEGV (11) / SIGABRT (6) → EXECUTION_ABORTED        │
│   - SIGTERM (15) / SIGINT (2) → USER_OR_APPROVAL_STOP                  │
│ ✗ 有终止信号 → 映射到症状并标记 tool_crash=true                        │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Step 2: 超时检测                                                         │
│ - 检查 timeout_reached == true                                          │
│ - MCP 工具超时：mcp_call_timeout → OPERATION_TIMED_OUT                │
│ - 测试工具超时：test_execution_timeout → OPERATION_TIMED_OUT           │
│ ✗ 超时 → OPERATION_TIMED_OUT + 对账幂等键                              │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Step 3: MCP 工具错误检测（tool_type == "mcp"）                          │
│ - 检查 MCP 协议层错误：                                                 │
│   - Connection refused / timeout → TRANSIENT_CONNECTIVITY               │
│   - MCP error response (-32xxx JSON-RPC) → DEPENDENCY_UNAVAILABLE      │
│   - MCP Server internal error (500-like) → DEPENDENCY_UNAVAILABLE       │
│   - MCP protocol violation → RESULT_INVALID                             │
│ ✗ MCP 错误 → 映射症状 + mcp_error_code                                  │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Step 4: 结构化输出解析（tool_type == "test"）                           │
│ - 尝试解析 structured_output_path：                                     │
│   - JUnit XML → JUnitParser                                             │
│   - pytest JSON → PytestParser                                          │
│   - Go test JSON → GoTestParser                                         │
│   - Cargo JSON → CargoParser                                            │
│   - TAP → TAPParser                                                     │
│ - 解析成功 → 提取 (passed, failed, errored, skipped)                   │
│ - 解析失败 → fallback 到 Step 5（退出码 + stderr）                     │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Step 5: 退出码分类（fallback 或非测试工具）                             │
│ - exit_code == 0 → SUCCESS（但需验证结构化报告一致性）                 │
│ - exit_code == 1 → 默认 TASK_VALIDATION_FAILED（测试未通过）           │
│ - exit_code == 2 → 参数/配置错误 → REQUEST_REJECTED                    │
│ - exit_code == 126/127 → 命令不存在/不可执行 → RESULT_INVALID          │
│ - exit_code == 137 (128+9) → SIGKILL → EXECUTION_ABORTED               │
│ - exit_code == 139 (128+11) → SIGSEGV → EXECUTION_ABORTED              │
│ - exit_code > 128 → 信号终止 → EXECUTION_ABORTED                       │
│ ✗ 退出码不可解释 → UNKNOWN_FAILURE                                     │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Step 6: stderr 辅助判断（仅用于提升置信度或细化原因）                   │
│ - 检测 stderr 关键模式：                                                │
│   - "ModuleNotFoundError" / "ImportError" → DEPENDENCY_UNAVAILABLE      │
│   - "ECONNREFUSED" / "Connection refused" → TRANSIENT_CONNECTIVITY      │
│   - "MemoryError" / "OOM" → RESOURCE_LIMIT_REACHED                      │
│   - "PermissionError" / "EACCES" → REQUEST_REJECTED                     │
│ - stderr 信号仅用于辅助，不能覆盖结构化输出或退出码                     │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Step 7: 一致性校验（结构化输出 vs 退出码）                              │
│ - 若结构化报告显示 all passed，但 exit_code ≠ 0 → RESULT_INVALID       │
│ - 若结构化报告显示 failed > 0，但 exit_code == 0 → RESULT_INVALID      │
│ - 不一致时标记 confidence_degraded=true                                 │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Step 8: 生成分类结果                                                     │
│ - 映射到 REL-001 症状                                                   │
│ - 映射到 REL-003 Disposition（DIAGNOSE / RETRY / ESCALATE）            │
│ - 输出 TestOrToolFailureClassification                                   │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 4. 结构化输出解析器

### 4.1 解析器注册表

```typescript
interface ParserRegistry {
    parsers: Map<string, StructuredOutputParser>;
    
    // 按文件扩展名或工具名称匹配解析器
    getParser(tool_name: string, output_path: string): StructuredOutputParser | null;
}

interface StructuredOutputParser {
    parser_id: string;              // "junit_xml_v1", "pytest_json_v2"
    parser_version: string;         // 解析器版本
    supported_formats: string[];    // [".xml", ".junit"]
    
    parse(content: string): ParseResult;
}

interface ParseResult {
    success: bool;
    
    // 成功时填充
    test_summary: TestSummary;
    test_cases: TestCase[];
    
    // 失败时填充
    error: ParseError;
    confidence: float;              // [0, 1]
}

interface TestSummary {
    total: int;
    passed: int;
    failed: int;
    errored: int;
    skipped: int;
    duration_ms: int64;
}

interface TestCase {
    name: string;
    class_name: string | null;
    file: string | null;
    line: int | null;
    status: "passed" | "failed" | "error" | "skipped";
    duration_ms: int64;
    failure_message: string | null;
    failure_type: string | null;     // "AssertionError", "TypeError"
    stacktrace: string | null;
}

interface ParseError {
    error_type: "file_not_found" | "invalid_format" | "incomplete_output" | "unknown";
    message: string;
    raw_content_sample: string;      // 前 500 字符，用于诊断
}
```

### 4.2 JUnit XML 解析器

```typescript
class JUnitXMLParser implements StructuredOutputParser {
    parser_id = "junit_xml_v1";
    parser_version = "1.0.0";
    supported_formats = [".xml", ".junit"];
    
    parse(content: string): ParseResult {
        try {
            const doc = parseXML(content);
            const testsuites = doc.getElementsByTagName("testsuite");
            
            let summary: TestSummary = {
                total: 0,
                passed: 0,
                failed: 0,
                errored: 0,
                skipped: 0,
                duration_ms: 0
            };
            
            let testCases: TestCase[] = [];
            
            for (const suite of testsuites) {
                const tests = parseInt(suite.getAttribute("tests") || "0");
                const failures = parseInt(suite.getAttribute("failures") || "0");
                const errors = parseInt(suite.getAttribute("errors") || "0");
                const skipped = parseInt(suite.getAttribute("skipped") || "0");
                const time = parseFloat(suite.getAttribute("time") || "0") * 1000;
                
                summary.total += tests;
                summary.failed += failures;
                summary.errored += errors;
                summary.skipped += skipped;
                summary.duration_ms += time;
                
                // 解析每个 testcase
                const cases = suite.getElementsByTagName("testcase");
                for (const tc of cases) {
                    testCases.push(this.parseTestCase(tc));
                }
            }
            
            summary.passed = summary.total - summary.failed - summary.errored - summary.skipped;
            
            return {
                success: true,
                test_summary: summary,
                test_cases: testCases,
                confidence: 1.0
            };
        } catch (e) {
            return {
                success: false,
                error: {
                    error_type: "invalid_format",
                    message: e.message,
                    raw_content_sample: content.slice(0, 500)
                },
                confidence: 0.0
            };
        }
    }
    
    parseTestCase(element: XMLElement): TestCase {
        const name = element.getAttribute("name") || "unknown";
        const className = element.getAttribute("classname");
        const time = parseFloat(element.getAttribute("time") || "0") * 1000;
        
        let status: "passed" | "failed" | "error" | "skipped" = "passed";
        let failureMessage: string | null = null;
        let failureType: string | null = null;
        let stacktrace: string | null = null;
        
        const failure = element.getElementsByTagName("failure")[0];
        const error = element.getElementsByTagName("error")[0];
        const skipped = element.getElementsByTagName("skipped")[0];
        
        if (failure) {
            status = "failed";
            failureMessage = failure.getAttribute("message");
            failureType = failure.getAttribute("type");
            stacktrace = failure.textContent;
        } else if (error) {
            status = "error";
            failureMessage = error.getAttribute("message");
            failureType = error.getAttribute("type");
            stacktrace = error.textContent;
        } else if (skipped) {
            status = "skipped";
            failureMessage = skipped.getAttribute("message");
        }
        
        return {
            name,
            class_name: className,
            file: null,  // JUnit XML 通常不包含文件路径
            line: null,
            status,
            duration_ms: time,
            failure_message: failureMessage,
            failure_type: failureType,
            stacktrace: stacktrace
        };
    }
}
```

### 4.3 pytest JSON 解析器

```typescript
class PytestJSONParser implements StructuredOutputParser {
    parser_id = "pytest_json_v1";
    parser_version = "1.0.0";
    supported_formats = [".json"];
    
    parse(content: string): ParseResult {
        try {
            const data = JSON.parse(content);
            
            // pytest-json-report 格式
            const summary = data.summary || {};
            const tests = data.tests || [];
            
            const testSummary: TestSummary = {
                total: summary.total || 0,
                passed: summary.passed || 0,
                failed: summary.failed || 0,
                errored: summary.error || 0,
                skipped: summary.skipped || 0,
                duration_ms: (data.duration || 0) * 1000
            };
            
            const testCases: TestCase[] = tests.map(t => ({
                name: t.nodeid || t.name,
                class_name: t.classname,
                file: t.lineno ? `${t.file}:${t.lineno}` : t.file,
                line: t.lineno,
                status: this.mapPytestOutcome(t.outcome),
                duration_ms: (t.duration || 0) * 1000,
                failure_message: t.call?.longrepr || t.setup?.longrepr,
                failure_type: t.call?.crash?.message ? "crash" : null,
                stacktrace: t.call?.traceback || null
            }));
            
            return {
                success: true,
                test_summary: testSummary,
                test_cases: testCases,
                confidence: 1.0
            };
        } catch (e) {
            return {
                success: false,
                error: {
                    error_type: "invalid_format",
                    message: e.message,
                    raw_content_sample: content.slice(0, 500)
                },
                confidence: 0.0
            };
        }
    }
    
    mapPytestOutcome(outcome: string): "passed" | "failed" | "error" | "skipped" {
        switch (outcome) {
            case "passed": return "passed";
            case "failed": return "failed";
            case "error": return "error";
            case "skipped": return "skipped";
            case "xfailed": return "skipped";
            case "xpassed": return "passed";
            default: return "error";
        }
    }
}
```

### 4.4 Go test JSON 解析器

```typescript
class GoTestJSONParser implements StructuredOutputParser {
    parser_id = "go_test_json_v1";
    parser_version = "1.0.0";
    supported_formats = [".json"];
    
    parse(content: string): ParseResult {
        try {
            // Go test -json 输出是 newline-delimited JSON
            const lines = content.trim().split('\n');
            const events = lines.map(line => JSON.parse(line));
            
            const testResults = new Map<string, TestCase>();
            let totalDuration = 0;
            
            for (const event of events) {
                if (event.Action === "run") {
                    testResults.set(event.Test, {
                        name: event.Test,
                        class_name: event.Package,
                        file: null,
                        line: null,
                        status: "passed",  // 初始假设
                        duration_ms: 0,
                        failure_message: null,
                        failure_type: null,
                        stacktrace: null
                    });
                } else if (event.Action === "pass") {
                    const tc = testResults.get(event.Test);
                    if (tc) {
                        tc.status = "passed";
                        tc.duration_ms = (event.Elapsed || 0) * 1000;
                    }
                } else if (event.Action === "fail") {
                    const tc = testResults.get(event.Test);
                    if (tc) {
                        tc.status = "failed";
                        tc.duration_ms = (event.Elapsed || 0) * 1000;
                        tc.failure_message = event.Output;
                    }
                } else if (event.Action === "skip") {
                    const tc = testResults.get(event.Test);
                    if (tc) {
                        tc.status = "skipped";
                    }
                } else if (event.Action === "output" && event.Test) {
                    const tc = testResults.get(event.Test);
                    if (tc && tc.failure_message) {
                        tc.failure_message += event.Output;
                    }
                }
                
                if (event.Elapsed) {
                    totalDuration = Math.max(totalDuration, event.Elapsed * 1000);
                }
            }
            
            const testCases = Array.from(testResults.values());
            const summary: TestSummary = {
                total: testCases.length,
                passed: testCases.filter(tc => tc.status === "passed").length,
                failed: testCases.filter(tc => tc.status === "failed").length,
                errored: 0,
                skipped: testCases.filter(tc => tc.status === "skipped").length,
                duration_ms: totalDuration
            };
            
            return {
                success: true,
                test_summary: summary,
                test_cases: testCases,
                confidence: 1.0
            };
        } catch (e) {
            return {
                success: false,
                error: {
                    error_type: "invalid_format",
                    message: e.message,
                    raw_content_sample: content.slice(0, 500)
                },
                confidence: 0.0
            };
        }
    }
}
```

---

## 5. MCP 工具错误分类

### 5.1 MCP 协议错误映射

基于 [Anthropic MCP Specification](https://spec.modelcontextprotocol.io/specification/architecture/) 和 [Claude Code MCP 错误处理](https://code.claude.com/docs/en/errors#mcp-tool-errors)：

```typescript
interface MCPErrorClassifier {
    classifyMCPError(error: MCPError): ToolFailureClassification;
}

interface MCPError {
    // MCP 连接层错误
    connection_error: MCPConnectionError | null;
    
    // MCP 调用层错误
    call_error: MCPCallError | null;
    
    // MCP 协议错误
    protocol_error: MCPProtocolError | null;
}

interface MCPConnectionError {
    error_type: "connection_refused" | "connection_timeout" | "connection_reset" | "dns_failure";
    server_uri: string;
    retry_after_ms: int64 | null;
}

interface MCPCallError {
    // JSON-RPC 错误码
    code: int;                      // -32xxx
    message: string;
    data: any;
    
    // MCP Server 返回的结构化错误
    is_retryable: bool | null;      // MCP Server 可选提供
}

interface MCPProtocolError {
    error_type: "invalid_response" | "missing_required_field" | "version_mismatch" | "unknown";
    message: string;
}

// JSON-RPC 标准错误码映射（遵循 MCP 规范）
const JSON_RPC_ERROR_MAPPING: Record<int, string> = {
    -32700: "RESULT_INVALID",       // Parse error
    -32600: "REQUEST_REJECTED",     // Invalid Request
    -32601: "REQUEST_REJECTED",     // Method not found
    -32602: "REQUEST_REJECTED",     // Invalid params
    -32603: "DEPENDENCY_UNAVAILABLE", // Internal error
    -32000: "DEPENDENCY_UNAVAILABLE", // Server error (MCP custom range start)
};

function classifyMCPError(error: MCPError): ToolFailureClassification {
    // 1. 连接层错误
    if (error.connection_error) {
        const ce = error.connection_error;
        switch (ce.error_type) {
            case "connection_refused":
            case "connection_timeout":
            case "connection_reset":
                return {
                    symptom: "TRANSIENT_CONNECTIVITY",
                    disposition: "RETRY",
                    confidence: 0.9,
                    evidence: {
                        mcp_connection_error: ce.error_type,
                        server_uri: ce.server_uri,
                        retry_after_ms: ce.retry_after_ms
                    }
                };
            case "dns_failure":
                return {
                    symptom: "DEPENDENCY_UNAVAILABLE",
                    disposition: "ESCALATE",
                    confidence: 0.95,
                    evidence: {
                        mcp_connection_error: "dns_failure",
                        server_uri: ce.server_uri
                    }
                };
        }
    }
    
    // 2. 调用层错误（JSON-RPC）
    if (error.call_error) {
        const ce = error.call_error;
        const symptom = JSON_RPC_ERROR_MAPPING[ce.code] || "UNKNOWN_FAILURE";
        
        // 优先使用 MCP Server 提供的 is_retryable 信号
        let disposition: string;
        if (ce.is_retryable === true) {
            disposition = "RETRY";
        } else if (ce.is_retryable === false) {
            disposition = "ESCALATE";
        } else {
            // Server 未提供，按错误码默认处理
            disposition = (symptom === "TRANSIENT_CONNECTIVITY" || symptom === "DEPENDENCY_UNAVAILABLE") 
                ? "RETRY" 
                : "ESCALATE";
        }
        
        return {
            symptom,
            disposition,
            confidence: 0.85,
            evidence: {
                mcp_error_code: ce.code,
                mcp_error_message: ce.message,
                mcp_is_retryable: ce.is_retryable
            }
        };
    }
    
    // 3. 协议层错误
    if (error.protocol_error) {
        const pe = error.protocol_error;
        return {
            symptom: "RESULT_INVALID",
            disposition: "ESCALATE",
            confidence: 0.9,
            evidence: {
                mcp_protocol_error: pe.error_type,
                message: pe.message
            }
        };
    }
    
    // 4. 未知 MCP 错误
    return {
        symptom: "UNKNOWN_FAILURE",
        disposition: "ESCALATE",
        confidence: 0.0,
        evidence: {
            error: "unknown_mcp_error"
        }
    };
}
```

### 5.2 MCP 超时处理

```typescript
interface MCPTimeoutConfig {
    initialize_timeout_ms: int64 = 30000;    // MCP initialize 超时
    call_timeout_ms: int64 = 300000;         // 单次工具调用超时（5 分钟）
    keepalive_timeout_ms: int64 = 60000;     // 连接保活超时
}

function classifyMCPTimeout(
    timeout_type: "initialize" | "call" | "keepalive",
    elapsed_ms: int64,
    config: MCPTimeoutConfig
): ToolFailureClassification {
    switch (timeout_type) {
        case "initialize":
            // MCP Server 初始化超时 → 可重试（可能是冷启动）
            return {
                symptom: "OPERATION_TIMED_OUT",
                disposition: "RETRY",
                confidence: 0.8,
                evidence: {
                    timeout_type: "mcp_initialize",
                    elapsed_ms,
                    timeout_threshold_ms: config.initialize_timeout_ms
                }
            };
        
        case "call":
            // 工具调用超时 → 需对账（可能已执行）
            return {
                symptom: "OPERATION_TIMED_OUT",
                disposition: "DIAGNOSE",  // 触发幂等对账
                confidence: 0.9,
                evidence: {
                    timeout_type: "mcp_call",
                    elapsed_ms,
                    timeout_threshold_ms: config.call_timeout_ms
                }
            };
        
        case "keepalive":
            // 保活超时 → 连接问题，可重试
            return {
                symptom: "TRANSIENT_CONNECTIVITY",
                disposition: "RETRY",
                confidence: 0.85,
                evidence: {
                    timeout_type: "mcp_keepalive",
                    elapsed_ms,
                    timeout_threshold_ms: config.keepalive_timeout_ms
                }
            };
    }
}
```

---

## 6. 分类结果数据模型

### 6.1 分类输出 Schema

```typescript
interface TestOrToolFailureClassification {
    // 分类器元数据
    classifier_id: string = "test_tool_classifier_v1";
    classifier_version: string = "1.0.0";
    classified_at: timestamp;
    
    // 工具执行上下文
    tool_type: "test" | "mcp" | "generic";
    tool_name: string;              // "pytest", "go test", "mcp://my-server"
    exit_code: int | null;
    signal: int | null;
    execution_time_ms: int64;
    timeout_reached: bool;
    
    // 结构化输出（测试工具）
    structured_output: StructuredTestOutput | null;
    
    // MCP 错误（MCP 工具）
    mcp_error: MCPErrorDetail | null;
    
    // REL-001 症状映射
    symptom: FailureSymptom;        // 来自 REL-001
    symptom_confidence: float;      // [0, 1]
    
    // REL-003 处置建议
    disposition: Disposition;
    disposition_reason: string;
    
    // 证据
    evidence: ClassificationEvidence;
    
    // 版本化解析器（如使用）
    parser_used: ParserMetadata | null;
    
    // 一致性检查
    consistency_check: ConsistencyCheck;
    
    // Trace 关联
    trace_id: string;
    span_id: string;
    action_id: string;
    idempotency_key: string;
}

enum Disposition {
    RETRY = "RETRY",                 // 可重试（工具异常/瞬态错误）
    RETRY_WITH_FIX = "RETRY_WITH_FIX", // 需修复后重试（依赖缺失）
    DIAGNOSE = "DIAGNOSE",           // 需诊断（测试失败/对账未知结果）
    ESCALATE = "ESCALATE",           // 升级人工（信号模糊/高风险）
    TERMINATE = "TERMINATE",         // 终止任务（不可恢复）
    SKIP = "SKIP"                    // 跳过（用户取消）
}

interface StructuredTestOutput {
    parser_id: string;
    parser_version: string;
    parse_success: bool;
    
    // 解析成功时填充
    test_summary: TestSummary;
    test_cases: TestCase[];
    
    // 解析失败时填充
    parse_error: ParseError | null;
}

interface MCPErrorDetail {
    error_category: "connection" | "call" | "protocol" | "timeout" | "unknown";
    error_code: int | null;         // JSON-RPC 错误码
    error_message: string;
    server_uri: string;
    is_retryable: bool | null;      // Server 提供的重试建议
    retry_after_ms: int64 | null;
}

interface ClassificationEvidence {
    // 原始信号
    exit_code: int | null;
    signal: int | null;
    stderr_sample: string | null;   // 前 1000 字符
    
    // 检测到的模式
    detected_patterns: string[];     // ["ModuleNotFoundError", "SIGKILL"]
    
    // 关键字段
    key_indicators: Map<string, any>;
    
    // 冲突信号
    conflicting_signals: ConflictingSignal[];
}

interface ConflictingSignal {
    signal_type: string;             // "exit_code", "structured_output"
    expected_value: any;
    actual_value: any;
    severity: "warning" | "error";
}

interface ConsistencyCheck {
    passed: bool;
    checks: ConsistencyCheckItem[];
}

interface ConsistencyCheckItem {
    check_name: string;              // "exit_code_vs_test_summary"
    passed: bool;
    message: string;
}

interface ParserMetadata {
    parser_id: string;
    parser_version: string;
    parse_confidence: float;
}
```

---

## 7. Codex/Claude Code 对标

### 7.1 OpenAI Codex/Agents SDK 模式

基于 [OpenAI Agents SDK Retry 文档](https://openai.github.io/openai-agents-python/ref/retry/)：

```typescript
// Codex 将工具错误分为两类：
// 1. Retryable errors: 进程崩溃、超时、网络错误
// 2. Non-retryable errors: 测试失败、断言失败、用户代码错误

interface CodexFailureClassification {
    // Codex 使用 failure_error_function 将工具崩溃转为模型可见输出
    failure_error_function: (error: ToolError) => string;
    
    // timeout_behavior: "error_as_result" vs "raise_exception"
    timeout_behavior: "error_as_result" | "raise_exception";
    
    // 退出码约定
    exit_code_mapping: {
        0: "success",
        1: "non_retryable_failure",      // 测试失败
        2: "invalid_arguments",
        137: "killed_by_signal",         // SIGKILL
        139: "segfault"                  // SIGSEGV
    };
}

// 本设计对标：
// - failure_error_function → ClassificationEvidence.key_indicators
// - timeout_behavior → Disposition.DIAGNOSE（对账后决定）
// - exit_code_mapping → Step 5 退出码分类
```

### 7.2 Claude Code 终止分类

基于 [Claude Code Headless Session Termination](https://code.claude.com/docs/errors#headless-session-termination)：

```typescript
// Claude Code 的 headless session 终止原因：
enum ClaudeCodeTerminationReason {
    TIMEOUT = "timeout",                     // 会话超时
    CONTEXT_EXHAUSTED = "context_exhausted", // 上下文耗尽
    HOOK_BLOCKED = "hook_blocked",           // Hook 阻断
    AUTH_FAILURE = "auth_failure",           // 认证失败
    TOOL_ERROR = "tool_error",               // 工具错误
    MODEL_REFUSAL = "model_refusal",         // 模型拒绝
    UNKNOWN = "unknown"
}

// Claude Code MCP 错误处理：
// - mcp_tool_errors collector pattern
// - 错误冒泡到会话层
// - PostToolUseFailure / StopFailure 生命周期 hooks

// 本设计对标：
// - TOOL_ERROR → Disposition.RETRY（工具异常）
// - HOOK_BLOCKED → Disposition.ESCALATE（策略阻断）
// - TIMEOUT → Disposition.DIAGNOSE（需对账）
// - UNKNOWN → Disposition.ESCALATE（保守处理）
```

### 7.3 AgentRx 与 SHIELDA 分离原则

基于 [Microsoft AgentRx](https://www.microsoft.com/en-us/research/blog/systematic-debugging-for-ai-agents-introducing-the-agentrx-framework/) 和 [SHIELDA 论文](https://arxiv.org/abs/2508.07935)：

```typescript
// AgentRx 九类失败分类：
// 1. Planning phase failures → 规划失败
// 2. Execution phase failures → 执行失败
// 3. Tool invocation failures → 工具调用失败
// 4. Resource failures → 资源失败
// 5. Permission failures → 权限失败
// 6. Timeout failures → 超时失败
// 7. Validation failures → 验证失败
// 8. State failures → 状态失败
// 9. Unknown failures → 未知失败

// SHIELDA 阶段感知异常处理：
// - Reasoning/Planning exceptions → 推理阶段异常
// - Execution exceptions → 执行阶段异常
// - 分层处理：retry, fallback, escalate

// 本设计对标：
// - Tool invocation failures → EXECUTION_ABORTED / TRANSIENT_CONNECTIVITY
// - Validation failures → TASK_VALIDATION_FAILED
// - Timeout failures → OPERATION_TIMED_OUT + 对账
// - Unknown failures → UNKNOWN_FAILURE + ESCALATE
```

---

## 8. 决策逻辑伪代码

```typescript
async function classifyTestOrToolFailure(
    execution_result: ToolExecutionResult
): Promise<TestOrToolFailureClassification> {
    const classification: TestOrToolFailureClassification = {
        classifier_id: "test_tool_classifier_v1",
        classifier_version: "1.0.0",
        classified_at: now(),
        tool_type: execution_result.tool_type,
        tool_name: execution_result.tool_name,
        exit_code: execution_result.exit_code,
        signal: execution_result.signal,
        execution_time_ms: execution_result.execution_time_ms,
        timeout_reached: execution_result.timeout_reached,
        trace_id: execution_result.trace_id,
        span_id: execution_result.span_id,
        action_id: execution_result.action_id,
        idempotency_key: execution_result.idempotency_key
    };
    
    // Step 1: 强制终止信号检测
    if (execution_result.signal !== null) {
        return classifySignalTermination(execution_result, classification);
    }
    
    // Step 2: 超时检测
    if (execution_result.timeout_reached) {
        return classifyTimeout(execution_result, classification);
    }
    
    // Step 3: MCP 工具错误检测
    if (execution_result.tool_type === "mcp" && execution_result.mcp_error) {
        return classifyMCPError(execution_result, classification);
    }
    
    // Step 4: 结构化输出解析（测试工具）
    if (execution_result.tool_type === "test" && execution_result.structured_output_path) {
        const parseResult = await parseStructuredOutput(
            execution_result.structured_output_path,
            execution_result.tool_name
        );
        
        if (parseResult.success) {
            classification.structured_output = {
                parser_id: parseResult.parser_id,
                parser_version: parseResult.parser_version,
                parse_success: true,
                test_summary: parseResult.test_summary,
                test_cases: parseResult.test_cases
            };
            
            // Step 7: 一致性校验
            const consistencyCheck = checkConsistency(
                execution_result.exit_code,
                parseResult.test_summary
            );
            classification.consistency_check = consistencyCheck;
            
            // 根据测试结果决定症状
            if (parseResult.test_summary.failed > 0 || parseResult.test_summary.errored > 0) {
                classification.symptom = "TASK_VALIDATION_FAILED";
                classification.disposition = "DIAGNOSE";
                classification.disposition_reason = "Tests failed, requires code fix";
                classification.symptom_confidence = consistencyCheck.passed ? 0.95 : 0.75;
            } else {
                classification.symptom = "SUCCESS";
                classification.disposition = "SKIP";
                classification.disposition_reason = "All tests passed";
                classification.symptom_confidence = 1.0;
            }
            
            return classification;
        } else {
            // 解析失败，降级到退出码
            classification.structured_output = {
                parser_id: parseResult.parser_id,
                parser_version: parseResult.parser_version,
                parse_success: false,
                parse_error: parseResult.error
            };
            // 继续到 Step 5
        }
    }
    
    // Step 5: 退出码分类
    if (execution_result.exit_code !== null) {
        return classifyExitCode(execution_result, classification);
    }
    
    // Step 6: stderr 辅助判断（如无法通过前述方法分类）
    if (execution_result.stderr) {
        const stderrClassification = classifyStderr(execution_result.stderr);
        if (stderrClassification.confidence > 0.6) {
            classification.symptom = stderrClassification.symptom;
            classification.disposition = stderrClassification.disposition;
            classification.symptom_confidence = stderrClassification.confidence;
            classification.evidence = {
                stderr_sample: execution_result.stderr.slice(0, 1000),
                detected_patterns: stderrClassification.patterns
            };
            return classification;
        }
    }
    
    // 无法分类 → UNKNOWN_FAILURE
    classification.symptom = "UNKNOWN_FAILURE";
    classification.disposition = "ESCALATE";
    classification.disposition_reason = "Unable to classify failure with confidence";
    classification.symptom_confidence = 0.0;
    classification.evidence = {
        exit_code: execution_result.exit_code,
        signal: execution_result.signal,
        stderr_sample: execution_result.stderr?.slice(0, 1000),
        detected_patterns: [],
        conflicting_signals: []
    };
    
    return classification;
}

function classifySignalTermination(
    execution_result: ToolExecutionResult,
    classification: TestOrToolFailureClassification
): TestOrToolFailureClassification {
    const signal = execution_result.signal!;
    
    switch (signal) {
        case 9:  // SIGKILL
        case 11: // SIGSEGV
        case 6:  // SIGABRT
            classification.symptom = "EXECUTION_ABORTED";
            classification.disposition = "RETRY";
            classification.disposition_reason = `Process killed by signal ${signal}`;
            classification.symptom_confidence = 0.95;
            break;
        
        case 15: // SIGTERM
        case 2:  // SIGINT
            classification.symptom = "USER_OR_APPROVAL_STOP";
            classification.disposition = "SKIP";
            classification.disposition_reason = "Process terminated by user";
            classification.symptom_confidence = 0.9;
            break;
        
        default:
            classification.symptom = "EXECUTION_ABORTED";
            classification.disposition = "ESCALATE";
            classification.disposition_reason = `Unknown signal ${signal}`;
            classification.symptom_confidence = 0.7;
    }
    
    classification.evidence = {
        signal,
        detected_patterns: [`signal_${signal}`]
    };
    
    return classification;
}

function classifyExitCode(
    execution_result: ToolExecutionResult,
    classification: TestOrToolFailureClassification
): TestOrToolFailureClassification {
    const exitCode = execution_result.exit_code!;
    
    if (exitCode === 0) {
        classification.symptom = "SUCCESS";
        classification.disposition = "SKIP";
        classification.disposition_reason = "Process exited successfully";
        classification.symptom_confidence = 1.0;
    } else if (exitCode === 1) {
        // 默认测试失败（如无结构化输出）
        classification.symptom = "TASK_VALIDATION_FAILED";
        classification.disposition = "DIAGNOSE";
        classification.disposition_reason = "Exit code 1 suggests test failure";
        classification.symptom_confidence = 0.7;  // 降低置信度，因为无结构化证据
    } else if (exitCode === 2) {
        classification.symptom = "REQUEST_REJECTED";
        classification.disposition = "ESCALATE";
        classification.disposition_reason = "Invalid arguments or configuration";
        classification.symptom_confidence = 0.85;
    } else if (exitCode === 126 || exitCode === 127) {
        classification.symptom = "RESULT_INVALID";
        classification.disposition = "ESCALATE";
        classification.disposition_reason = "Command not found or not executable";
        classification.symptom_confidence = 0.9;
    } else if (exitCode > 128) {
        // 128 + signal number
        const signal = exitCode - 128;
        classification.symptom = "EXECUTION_ABORTED";
        classification.disposition = "RETRY";
        classification.disposition_reason = `Process killed by signal ${signal}`;
        classification.symptom_confidence = 0.9;
    } else {
        classification.symptom = "UNKNOWN_FAILURE";
        classification.disposition = "ESCALATE";
        classification.disposition_reason = `Unexpected exit code ${exitCode}`;
        classification.symptom_confidence = 0.5;
    }
    
    classification.evidence = {
        exit_code: exitCode,
        detected_patterns: [`exit_code_${exitCode}`]
    };
    
    return classification;
}

function checkConsistency(
    exit_code: int | null,
    test_summary: TestSummary
): ConsistencyCheck {
    const checks: ConsistencyCheckItem[] = [];
    let allPassed = true;
    
    // 检查：结构化报告显示全通过，但退出码 ≠ 0
    if (test_summary.failed === 0 && test_summary.errored === 0 && exit_code !== 0 && exit_code !== null) {
        checks.push({
            check_name: "exit_code_vs_test_summary",
            passed: false,
            message: `Test summary shows all passed, but exit code is ${exit_code}`
        });
        allPassed = false;
    }
    
    // 检查：结构化报告显示失败，但退出码 === 0
    if ((test_summary.failed > 0 || test_summary.errored > 0) && exit_code === 0) {
        checks.push({
            check_name: "exit_code_vs_test_summary",
            passed: false,
            message: `Test summary shows failures, but exit code is 0`
        });
        allPassed = false;
    }
    
    // 检查：total 与 passed + failed + errored + skipped 是否一致
    const sum = test_summary.passed + test_summary.failed + test_summary.errored + test_summary.skipped;
    if (sum !== test_summary.total) {
        checks.push({
            check_name: "test_count_consistency",
            passed: false,
            message: `Test count mismatch: total=${test_summary.total}, sum=${sum}`
        });
        allPassed = false;
    }
    
    return {
        passed: allPassed,
        checks
    };
}
```

---

## 9. 与 REL-001/REL-003 集成

### 9.1 症状映射表

| 本分类结果 | REL-001 症状 | REL-003 Disposition |
|-----------|-------------|---------------------|
| 测试失败（结构化报告 failed > 0） | `TASK_VALIDATION_FAILED` | `DIAGNOSE` |
| 工具进程崩溃（SIGKILL/SIGSEGV） | `EXECUTION_ABORTED` | `RETRY` |
| 工具超时 | `OPERATION_TIMED_OUT` | `DIAGNOSE`（触发对账） |
| MCP 连接失败 | `TRANSIENT_CONNECTIVITY` | `RETRY` |
| MCP Server 内部错误 | `DEPENDENCY_UNAVAILABLE` | `RETRY` |
| MCP 协议违规 | `RESULT_INVALID` | `ESCALATE` |
| 退出码 2（参数错误） | `REQUEST_REJECTED` | `ESCALATE` |
| 退出码 126/127（命令不存在） | `RESULT_INVALID` | `ESCALATE` |
| 结构化输出解析失败 | `RESULT_INVALID` | `ESCALATE` |
| stderr 检测到 ModuleNotFoundError | `DEPENDENCY_UNAVAILABLE` | `RETRY_WITH_FIX` |
| stderr 检测到 MemoryError | `RESOURCE_LIMIT_REACHED` | `ESCALATE` |
| 无法分类 | `UNKNOWN_FAILURE` | `ESCALATE` |

### 9.2 REL-003 决策引擎集成

```typescript
// REL-008 分类结果作为 REL-003 决策引擎的输入
interface RetryDecisionRequest {
    // ... 其他字段 ...
    
    // REL-008 分类结果
    test_or_tool_classification: TestOrToolFailureClassification;
    
    // REL-001 症状（由 REL-008 映射）
    symptom: FailureSymptom;
    
    // REL-003 处置建议（由 REL-008 提供）
    suggested_disposition: Disposition;
}

// REL-003 决策引擎根据 REL-008 建议做最终决策
async function makeRetryDecision(request: RetryDecisionRequest): Promise<DecisionResponse> {
    // 1. 幂等闸门检查（Step 2）
    if (request.suggested_disposition === "DIAGNOSE" && request.symptom === "OPERATION_TIMED_OUT") {
        // 超时需先对账
        const reconcileResult = await reconcileIdempotentOperation(request.idempotency_key);
        if (reconcileResult === "CONFIRMED_EXECUTED") {
            return { decision: "SKIP", reason: "Operation already executed" };
        } else if (reconcileResult === "CONFIRMED_NOT_EXECUTED") {
            // 可以重试
            request.suggested_disposition = "RETRY";
        } else {
            // IN_DOUBT → 等待对账或人工
            return { decision: "ESCALATE", reason: "Idempotency state in doubt" };
        }
    }
    
    // 2. 症状匹配（Step 3）
    if (request.symptom === "TASK_VALIDATION_FAILED") {
        // 测试失败不进入重试循环，直接诊断/修复
        return {
            decision: "TERMINATE",
            action: "DIAGNOSE",
            reason: "Test validation failed, requires code fix"
        };
    }
    
    // 3. 置信度校验（Step 4）
    if (request.test_or_tool_classification.symptom_confidence < 0.7) {
        // 分类置信度低，升级人工
        return {
            decision: "ESCALATE",
            reason: "Low classification confidence"
        };
    }
    
    // 4-11. 后续决策步骤（熔断器、预算、降级链等）
    // ...
    
    return finalDecision;
}
```

---

## 10. 可观测性指标

### 10.1 一级指标

| 指标名称 | 定义 | 类型 | 告警阈值 |
|---------|------|------|---------|
| `test_tool_classification_latency_p99` | 分类延迟 P99 | Histogram | > 100ms |
| `test_tool_classification_rate` | 分类请求速率 | Gauge | - |
| `test_tool_classification_by_symptom` | 按症状分布 | Counter | - |
| `test_tool_classification_by_disposition` | 按处置分布 | Counter | - |
| `test_failure_rate` | 测试失败率（TASK_VALIDATION_FAILED） | Gauge | 按基线 |
| `tool_exception_rate` | 工具异常率（EXECUTION_ABORTED等） | Gauge | 按基线 |
| `mcp_error_rate` | MCP 错误率 | Gauge | > 5% |
| `structured_parse_success_rate` | 结构化输出解析成功率 | Gauge | < 90% |
| `classification_confidence_distribution` | 置信度分布 | Histogram | - |
| `low_confidence_escalation_rate` | 低置信度升级率 | Gauge | > 20% |
| `consistency_check_failure_rate` | 一致性检查失败率 | Gauge | > 5% |
| `unknown_classification_rate` | UNKNOWN 分类率 | Gauge | > 10% |

### 10.2 分类正确性指标

| 指标名称 | 定义 | 目标 |
|---------|------|------|
| `test_failure_precision` | 测试失败分类精确率 | > 95% |
| `test_failure_recall` | 测试失败分类召回率 | > 90% |
| `tool_exception_precision` | 工具异常分类精确率 | > 90% |
| `tool_exception_recall` | 工具异常分类召回率 | > 85% |
| `false_positive_retry_rate` | 误判可重试率（将测试失败误判为可重试） | < 5% |
| `false_negative_retry_rate` | 误判不可重试率（将工具异常误判为测试失败） | < 10% |

---

## 11. 验收标准

| 编号 | 验收项 | 验证方法 |
|------|--------|---------|
| V1 | 测试失败识别 | pytest 退出码 1 + JSON 报告 failed > 0 → TASK_VALIDATION_FAILED |
| V2 | 工具崩溃识别 | pytest 进程 SIGKILL → EXECUTION_ABORTED |
| V3 | 超时识别 | pytest 超时 → OPERATION_TIMED_OUT + 触发对账 |
| V4 | MCP 连接失败 | MCP connection refused → TRANSIENT_CONNECTIVITY |
| V5 | MCP 调用错误 | MCP JSON-RPC -32603 → DEPENDENCY_UNAVAILABLE |
| V6 | 结构化解析成功 | JUnit XML 解析 → test_summary 填充 |
| V7 | 结构化解析失败降级 | 非法 JSON → 降级到退出码分类 |
| V8 | 一致性检查 | failed > 0 但 exit_code = 0 → consistency_check.passed = false |
| V9 | 保守处置 | 无法分类 → UNKNOWN_FAILURE + ESCALATE |
| V10 | 与 REL-003 集成 | TASK_VALIDATION_FAILED → DIAGNOSE（不进入重试） |
| V11 | MCP 重试建议优先 | MCP Server is_retryable = false → ESCALATE |
| V12 | 置信度降档 | 一致性检查失败 → confidence 降低 |

---

## 12. 依赖与接口

### 12.1 上游依赖

| 依赖 | 说明 |
|------|------|
| REQ-REL-001 | 失败症状分类（症状词表） |
| REQ-RT-003 | Event Schema（分类事件格式） |
| REQ-RT-007 | 幂等键（对账决策） |

### 12.2 下游接口

| 接口 | 说明 |
|------|------|
| RetryDecisionEngine | 提供分类结果给 REL-003 |
| DiagnosticService | 测试失败需诊断/修复 |
| IdempotencyGateway | 超时需对账 |
| MetricsCollector | 采集分类指标 |

---

## 13. 参考资料

以下为公开来源，访问日期均为 2026-09-26：

- OpenAI Codex 错误分类源码：[codex-rs/protocol/src/error.rs](https://github.com/openai/codex/blob/f1affbac/codex-rs/protocol/src/error.rs)
- OpenAI Agents SDK Retry：[retry reference](https://openai.github.io/openai-agents-python/ref/retry/)
- Claude Code Error Handling：[errors documentation](https://code.claude.com/docs/en/errors)
- Claude Code MCP Tool Errors：[MCP tool errors](https://code.claude.com/docs/en/errors#mcp-tool-errors)
- Anthropic MCP Specification：[architecture](https://spec.modelcontextprotocol.io/specification/architecture/)
- Microsoft Research AgentRx：[blog post](https://www.microsoft.com/en-us/research/blog/systematic-debugging-for-ai-agents-introducing-the-agentrx-framework/)
- SHIELDA 论文：[arXiv:2508.07935](https://arxiv.org/abs/2508.07935)

---

## 14. 决策记录

| 决策项 | 决策 | 依据 |
|-------|------|------|
| 结构化优先 | 优先使用 JUnit/JSON 等结构化输出 | Codex/Claude Code 实践 |
| 测试失败不重试 | TASK_VALIDATION_FAILED → DIAGNOSE | 避免浪费预算、掩盖缺陷 |
| MCP 协议对齐 | 遵循 Anthropic MCP 规范 | 互操作性 |
| 保守处置 | 无法分类 → ESCALATE | REL-001 原则 |
| 超时需对账 | OPERATION_TIMED_OUT → 触发幂等对账 | REL-003/RT-007 |
| 置信度降档 | 一致性检查失败 → 降低置信度 | 风险控制 |

---

## 15. 变更记录

| 版本 | 日期 | 变更 | 确认 |
|-----|------|-----|----|
| v0.1-designed | 2026-09-26 | 初始版本，基于 Codex/Claude Code/AgentRx/SHIELDA 对标设计 | 用户确认 |
