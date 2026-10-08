# REQ-HAR-004: Hook Registry - Hook注册表、签名、顺序、失败策略和兼容性

> **需求编号**: REQ-HAR-004  
> **需求名称**: Hook Registry  
> **优先级**: P0  
> **状态**: v0.1-designed(待跨模块评审与冻结)  
> **创建日期**: 2026-10-02  
> **依赖**: REQ-HAR-001(Harness生命周期)、REQ-SEC-001(威胁模型和风险评分)  
> **被依赖**: REQ-HAR-005(LSP/MCP/Skill统一路由)、REQ-HAR-006(Harness契约测试)

---

## 一、设计目标

### 1.1 核心定位

**Hook Registry是可信、可审计、可演进的Hook注册与执行体系**,职责包括:
- 支持平台、组织、项目、Worker和Plugin多层级Hook注册
- 提供细粒度生命周期事件覆盖(Action/Tool/Model/Approval/Workflow/Worker)
- 实现明确的失败策略(fail-closed/fail-open/degraded/retry/escalate/wait-approval)
- 保证版本兼容性(manifest schema版本化、事件演进协议)
- 提供安全审计能力(签名验证、执行记录、证据保全)

**Hook Registry是Harness Engineering的核心基础设施**,为所有Worker实例提供Hook注册、匹配、执行、合并和审计服务。

### 1.2 设计原则

| 原则 | 说明 |
|------|------|
| **分层注册** | 平台级(全局观测) + Worker级(实例定制) + Plugin级(沙箱隔离) |
| **安全优先** | 安全类Hook强制签名、fail-closed失败策略、Plugin Hook沙箱隔离 |
| **响应式架构** | Worker监听Hook-added/Hook-removed事件动态更新 |
| **版本兼容** | manifest schema版本化、事件演进协议、兼容期保证 |
| **可观测性** | 结构化审计日志、多维度查询、180天留存 |

---

## 二、竞品研究摘要

### 2.1 OpenAI Agents SDK

**访问日期**: 2026-10-02  
**来源**: https://openai.github.io/openai-agents-python/ref/lifecycle/

**核心设计**:
- **双层Hook体系**: RunHooks(全局观测) + AgentHooks(实例级)
- **生命周期回调**: on_agent_start/end、on_llm_start/end、on_tool_start/end、on_handoff
- **上下文传播**: AgentHookContext包装原始context+运行usage状态
- **Plugin集成**: 通过extensions.com.openai.hooks声明Hook路径

**可借鉴点**: 双层Hook注册、上下文包装器隔离、Plugin manifest声明

---

### 2.2 Claude Code

**访问日期**: 2026-10-02  
**来源**: https://code.claude.com/docs/en/hooks

**核心设计**:
- **20+生命周期事件**: PreToolUse、PostToolUse、SessionStart/End、SubagentStart/Stop等
- **五种Hook类型**: command/http/mcp_tool/prompt/agent
- **响应合并协议**: ask>block>allow优先级,user_message串联
- **Plugin Hook作用域**: scoped name(`mcp__plugin_<id>__<tool>`)隔离

**可借鉴点**: 细粒度事件、多Hook类型、响应合并规则、作用域隔离

---

### 2.3 LangChain/LangGraph 1.0

**访问日期**: 2026-10-02  
**来源**: https://www.langchain.com/blog/agent-middleware

**核心设计**:
- **Middleware装饰器风格**: @before_model/@after_model/@wrap_tool_call
- **洋葱模型执行顺序**: before顺序、after逆序
- **内置12种Middleware**: Summarization/HITL/PII/Retry/Fallback等

**可借鉴点**: 装饰器API、洋葱模型、内置最佳实践Middleware

---

### 2.4 Cursor

**访问日期**: 2026-10-02  
**来源**: https://cursor.com/docs/hooks

**核心设计**:
- **双Plugin格式**: Agent Plugins(开放标准) + Cursor Plugins(私有扩展)
- **多级Hook合并**: Enterprise>Team>Project>User>Claude兼容(7层优先级)
- **23+生命周期事件**: Agent/Tab/App lifecycle全覆盖
- **第三方兼容**: 自动加载.claude/settings.json

**可借鉴点**: 多级优先级、第三方格式兼容、企业策略下发

---

### 2.5 Dify

**访问日期**: 2026-10-02  
**来源**: https://dify.ai/blog/dify-plugin-system-design-and-implementation

**核心设计**:
- **Plugin Daemon独立管理**: 解耦运行时与业务逻辑
- **四种运行时**: subprocess/TCP/Lambda/Remote
- **Reverse Call机制**: Plugin反向调用平台服务

**可借鉴点**: 独立Daemon、多运行时、双向调用

---

### 2.6 Kimi Code CLI

**访问日期**: 2026-10-02  
**来源**: https://github.com/MoonshotAI/kimi-cli

**核心设计**:
- **阻断事件vs观测事件分离**: 可阻断事件exit code 2阻断
- **Plugin Hook环境**: 工作目录自动设置为plugin root,注入KIMI_PLUGIN_ROOT环境变量
- **安全约束**: 禁止manifest声明cwd/env字段防止逃逸

**可借鉴点**: 阻断/观测分离、Plugin Hook工作目录、manifest安全约束

---

## 三、Hook注册协议设计

### 3.1 注册源与优先级

**六层注册源**(按优先级从高到低):

| Source | 优先级 | 注册权限 | 审批要求 | 签名要求 |
|--------|-------|---------|---------|---------|
| platform | 1000 | 平台开发者 | 代码审查+安全审查 | 必须(Platform Key) |
| enterprise | 900 | 组织管理员 | 平台管理员审批 | 可选 |
| team | 800 | 团队管理员 | Enterprise管理员审批(可选) | 不要求 |
| project | 600 | 项目维护者 | 不需要审批 | 不要求 |
| user | 400 | 任何用户 | 不需要审批 | 不要求 |
| plugin | 200 | Plugin已安装 | Plugin安装时用户确认 | 安全类必须签名 |

**优先级规则**:
- 同事件多Hook匹配时,按source优先级排序
- 同优先级Hook按priority字段(1-1000)二次排序
- Enterprise Hook优先级最高,无法被项目或用户Hook覆盖

---

### 3.2 Hook注册Schema

```typescript
interface HookRegistration {
  // 基础信息
  hook_id: string;                    // 唯一标识,格式: <source>:<event>:<index>
  source: HookSource;                  // platform/enterprise/team/project/user/plugin
  event: HookEvent;                    // 生命周期事件名称
  
  // Hook定义
  type: HookType;                      // command/http/mcp_tool/approval/inline
  command?: string;                    // command类型: shell命令
  http_config?: HttpConfig;            // http类型: 端点配置
  mcp_config?: McpToolConfig;          // mcp_tool类型: MCP工具配置
  approval_config?: ApprovalConfig;    // approval类型: 审批配置
  inline_code?: string;                // inline类型: 嵌入代码(沙箱执行)
  
  // 匹配与过滤
  matcher?: string;                    // 正则表达式,匹配tool/action/worker name
  if_condition?: string;               // 条件表达式,支持CEL语法
  
  // 执行控制
  timeout: number;                     // 超时(ms),默认30000
  failure_strategy: FailureStrategy;   // fail-closed/fail-open/degraded/retry/escalate/wait-approval
  retry_config?: RetryConfig;          // retry策略: 重试配置
  
  // 优先级与分类
  priority: number;                    // 优先级,1-1000,默认500
  category: HookCategory;              // security/compliance/observability/performance/custom
  
  // 安全与审计
  signature?: string;                  // 签名,格式: sha256:hex
  signed_by?: string;                  // 签名者公钥ID
  requires_approval?: boolean;         // 是否需要平台审批才能注册
  
  // 元数据
  description?: string;
  version?: string;
  created_at: string;
  created_by: string;
}
```

---

### 3.3 签名验证

**签名算法**: SHA-256 + RSA-2048/Ed25519

**签名验证流程**:
1. 提取signature和signed_by字段
2. 计算manifest canonical JSON的SHA-256 hash(排除signature字段)
3. 使用signed_by对应的公钥验证signature
4. 验证失败: 拒绝注册并记录审计日志

**签名要求**:
- 安全类Hook(category=security/compliance): 强制签名
- Platform Hook: 强制签名(Platform Key)
- Plugin Hook(安全类): 强制签名
- 其他类型: 可选签名

---

## 四、生命周期事件清单

### 4.1 事件分类

| 分类 | 事件数 | 示例 |
|------|-------|------|
| Action生命周期 | 4 | before-action、after-action、action-error、action-timeout |
| Tool生命周期 | 5 | before-tool-use、after-tool-use、tool-error、tool-timeout、tool-approval-required |
| Model生命周期 | 4 | before-model-call、after-model-call、model-error、model-timeout |
| Approval生命周期 | 4 | before-approval、after-approval、approval-timeout、approval-escalated |
| Workflow生命周期 | 3 | workflow-transition、workflow-completed、workflow-failed |
| Worker生命周期 | 5 | worker-start、worker-handoff、worker-pause、worker-resume、worker-stop |
| Session生命周期 | 2 | session-start、session-end |
| Compaction | 2 | before-compaction、after-compaction |

**总计**: 29个生命周期事件

---

### 4.2 详细事件定义

#### 4.2.1 Action生命周期事件

| 事件名 | 触发时机 | 可阻断 | 典型用途 |
|--------|---------|-------|---------|
| `before-action` | Action执行前 | ✓ | 权限检查、预算校验 |
| `after-action` | Action执行后 | ✗ | 结果验证、审计记录 |
| `action-error` | Action执行失败 | ✗ | 错误分析、告警 |
| `action-timeout` | Action执行超时 | ✗ | 超时分析、降级 |

---

#### 4.2.2 Tool生命周期事件

| 事件名 | 触发时机 | 可阻断 | 典型用途 |
|--------|---------|-------|---------|
| `before-tool-use` | Tool调用前 | ✓ | 安全扫描、参数校验 |
| `after-tool-use` | Tool调用后 | ✗ | 输出验证、审计记录 |
| `tool-error` | Tool执行失败 | ✗ | 错误分类、重试决策 |
| `tool-timeout` | Tool执行超时 | ✗ | 超时分析、告警 |
| `tool-approval-required` | Tool需要审批 | ✓ | 强制审批、风险提示 |

**before-tool-use事件上下文**:
```typescript
interface BeforeToolUseContext {
  tool: string;              // 工具名称
  tool_args: any;            // 工具参数
  risk_level: RiskLevel;     // 风险等级
  user_id: string;
  permissions: string[];
}
```

---

#### 4.2.3 Model生命周期事件

| 事件名 | 触发时机 | 可阻断 | 典型用途 |
|--------|---------|-------|---------|
| `before-model-call` | Model调用前 | ✓ | Prompt注入检测、预算检查 |
| `after-model-call` | Model调用后 | ✗ | 输出过滤、使用统计 |
| `model-error` | Model调用失败 | ✗ | Fallback决策、告警 |
| `model-timeout` | Model调用超时 | ✗ | 超时分析、重试 |

---

#### 4.2.4 Approval生命周期事件

| 事件名 | 触发时机 | 可阻断 | 典型用途 |
|--------|---------|-------|---------|
| `before-approval` | 创建审批请求前 | ✓ | 审批必要性判断 |
| `after-approval` | 审批完成后 | ✗ | 审批决策记录 |
| `approval-timeout` | 审批超时 | ✗ | 自动拒绝或升级 |
| `approval-escalated` | 审批升级 | ✗ | 升级通知 |

---

#### 4.2.5 Workflow生命周期事件

| 事件名 | 触发时机 | 可阻断 | 典型用途 |
|--------|---------|-------|---------|
| `workflow-transition` | Workflow节点转换 | ✓ | 转换条件验证 |
| `workflow-completed` | Workflow完成 | ✗ | 完成通知、归档 |
| `workflow-failed` | Workflow失败 | ✗ | 失败分析、补偿 |

---

#### 4.2.6 Worker生命周期事件

| 事件名 | 触发时机 | 可阻断 | 典型用途 |
|--------|---------|-------|---------|
| `worker-start` | Worker启动 | ✓ | 环境准备、权限检查 |
| `worker-handoff` | Worker间切换 | ✓ | Handoff条件验证 |
| `worker-pause` | Worker暂停 | ✗ | 暂停状态保存 |
| `worker-resume` | Worker恢复 | ✓ | 恢复条件检查 |
| `worker-stop` | Worker停止 | ✗ | 清理、归档 |

---

#### 4.2.7 Session生命周期事件

| 事件名 | 触发时机 | 可阻断 | 典型用途 |
|--------|---------|-------|---------|
| `session-start` | Session创建 | ✓ | 初始化、加载配置 |
| `session-end` | Session结束 | ✗ | 清理、统计上报 |

---

#### 4.2.8 Compaction事件

| 事件名 | 触发时机 | 可阻断 | 典型用途 |
|--------|---------|-------|---------|
| `before-compaction` | Context压缩前 | ✓ | 压缩策略调整 |
| `after-compaction` | Context压缩后 | ✗ | 压缩效果统计 |

---

## 五、Hook类型与执行环境

### 5.1 五种Hook类型

| 类型 | 执行环境 | 适用场景 | 延迟目标(p95) |
|------|---------|---------|--------------|
| command | 本地subprocess | 本地脚本、工具调用 | < 100ms |
| http | 远程HTTP端点 | 云端服务、外部系统 | < 500ms |
| mcp_tool | MCP服务器 | Plugin能力调用 | < 200ms |
| approval | Approval Service | 人工审批决策 | < 30s |
| inline | 沙箱代码执行 | 轻量逻辑、快速验证 | < 50ms |

---

### 5.2 command类型Hook

**执行环境**: Platform进程内启动subprocess

**隔离机制**:
- seccomp默认策略限制系统调用
- AppArmor限制文件系统访问(只读plugin root)
- 资源限制: CPU/内存/进程数

**配置示例**:
```json
{
  "type": "command",
  "command": "./hooks/security-scan.sh",
  "timeout": 5000,
  "failure_strategy": "fail-closed"
}
```

**输入输出**:
- 输入: stdin接收JSON格式的HookInput
- 输出: stdout返回JSON格式的HookOutput
- 阻断: exit code 2显式阻断

---

### 5.3 http类型Hook

**执行环境**: 调用远程HTTP端点

**配置示例**:
```json
{
  "type": "http",
  "http_config": {
    "url": "https://security-api.company.com/scan",
    "method": "POST",
    "headers": {
      "Authorization": "Bearer ${SECURITY_API_TOKEN}"
    },
    "timeout": 10000
  },
  "failure_strategy": "retry",
  "retry_config": {
    "max_retries": 3,
    "initial_backoff": 1000
  }
}
```

**安全约束**:
- 端点URL必须在Plugin manifest中声明
- 支持环境变量替换(${VAR_NAME})
- TLS证书验证强制开启

---

### 5.4 approval类型Hook

**执行环境**: 集成Approval Service

**配置示例**:
```json
{
  "type": "approval",
  "approval_config": {
    "timeout": 1800000,
    "on_timeout": "escalate",
    "escalation_targets": ["admin@company.com"],
    "approval_matrix": {
      "risk_high": ["manager", "security-team"],
      "risk_medium": ["manager"]
    }
  }
}
```

**审批流程**:
1. Hook检测到需审批操作,返回`approval_required: true`
2. Platform创建审批请求
3. 通知审批者(Slack/Email)
4. 审批者批准/拒绝
5. 超时后执行on_timeout策略(escalate/fail-closed/fail-open)

---

## 六、失败策略设计

### 6.1 六种失败策略

| 策略 | 适用场景 | 超时行为 | 执行失败行为 | 安全性 | 可用性 |
|------|---------|---------|------------|--------|--------|
| fail-closed | 安全类、合规类 | block | block | 最高 | 最低 |
| fail-open | 诊断类、监控类 | allow | allow+warning | 最低 | 最高 |
| degraded | 业务类、通知类 | allow | block | 中 | 中 |
| retry | 网络类、外部依赖 | 重试后fail-closed | 重试后fail-closed | 中 | 中 |
| escalate | 高风险、异常情况 | 创建ticket+block | 创建ticket+block | 高 | 低 |
| wait-approval | 合规要求、人工决策 | escalate | escalate | 高 | 低 |

---

### 6.2 失败策略执行算法

```python
def apply_failure_strategy(failure_type, strategy):
    match strategy:
        case 'fail-closed':
            return HookOutput(decision='block', reason=f'{failure_type}: fail-closed')
        
        case 'fail-open':
            log_warning(f'{failure_type}: fail-open, allowing')
            return HookOutput(decision='allow', reason=f'{failure_type}: fail-open fallback')
        
        case 'degraded':
            if failure_type == 'timeout':
                return HookOutput(decision='allow', reason='timeout: degraded allow')
            else:
                return HookOutput(decision='block', reason='failure: degraded block')
        
        case 'retry':
            if retry_count < max_retries:
                retry_count += 1
                backoff = initial_backoff * (2 ** (retry_count - 1))
                sleep(backoff)
                return execute_hook()
            else:
                return HookOutput(decision='block', reason='retry exhausted')
        
        case 'escalate':
            create_escalation_ticket({
                "hook_id": hook_id,
                "failure_type": failure_type,
                "context": execution_context
            })
            return HookOutput(decision='block', reason='escalated')
        
        case 'wait-approval':
            approval = create_approval_request(timeout=approval_timeout)
            result = wait_for_approval(approval)
            if result.approved:
                return HookOutput(decision='allow')
            else:
                return HookOutput(decision='block', reason='approval denied')
```

---

### 6.3 失败策略与Hook分类关联

**强制关联规则**:
- security类Hook: 必须fail-closed或wait-approval
- compliance类Hook: 必须fail-closed或wait-approval
- observability类Hook: 建议fail-open或degraded
- performance类Hook: 建议fail-open或degraded
- custom类Hook: 可任意配置

**验证**: Hook注册时验证failure_strategy与category匹配,不匹配拒绝注册

---

## 七、Hook匹配与执行流程

### 7.1 Hook匹配算法

**倒排索引 + 双层过滤**:

```python
def find_matching_hooks(event: HookEvent, context: ExecutionContext) -> List[Hook]:
    # 1. 从倒排索引查找候选Hook
    candidates = hook_registry.index[event]
    
    # 2. 第一层过滤: 正则matcher
    matched_hooks = []
    for hook in candidates:
        if hook.matcher is None or regex_match(hook.matcher, context.target_name):
            matched_hooks.append(hook)
    
    # 3. 第二层过滤: CEL条件表达式
    filtered_hooks = []
    for hook in matched_hooks:
        if hook.if_condition is None:
            filtered_hooks.append(hook)
        else:
            result = cel_eval(hook.if_condition, context)
            if result == True:
                filtered_hooks.append(hook)
    
    # 4. 排序: source优先级 + priority
    sorted_hooks = sorted(
        filtered_hooks,
        key=lambda h: (-h.source_priority, -h.priority)
    )
    
    return sorted_hooks
```

**复杂度**:
- 时间: O(n + m*k),n为候选数,m为过滤后数,k为CEL复杂度
- 空间: O(n),倒排索引大小

---

### 7.2 Hook执行流程

**分层并行执行**:

```
1. 事件触发
   ↓
2. 查找匹配Hook (倒排索引 + 双层过滤)
   ↓
3. 按source优先级分组
   - Enterprise (priority 1000)
   - Team (priority 800)
   - Project (priority 600)
   - User (priority 400)
   - Plugin (priority 200)
   ↓
4. 逐层串行执行,同层并行
   - 执行Enterprise Hook (并行,最多10个)
   - 收集响应
   - 若有block决策,可选择提前终止或继续执行低优先级Hook
   ↓
5. 响应合并
   - 应用block>allow>observe规则
   - 串联user_message
   - 合并metadata和evidence
   ↓
6. 应用决策
   - block: 阻断Action执行
   - allow: 继续Action执行
   - observe: 记录但不影响执行
   ↓
7. 审计记录
   - 写入Hook执行日志
   - 包含所有Hook的decision/reason/evidence
```

**执行超时处理**:
- 每个Hook独立超时控制(默认30s)
- 超时后应用failure_strategy
- 记录超时事件到审计日志

---

### 7.3 响应合并协议

**合并规则**: block > allow > observe

**算法实现**:
```python
def merge_responses(responses: List[HookOutput]) -> MergedHookOutput:
    # 1. 决策合并
    decisions = [r.decision for r in responses]
    if 'block' in decisions:
        final_decision = 'block'
    elif 'allow' in decisions:
        final_decision = 'allow'
    else:
        final_decision = 'observe'
    
    # 2. 消息串联
    user_messages = [r.user_message for r in responses if r.user_message]
    merged_user_message = ' | '.join(user_messages)
    
    agent_messages = [r.agent_message for r in responses if r.agent_message]
    merged_agent_message = '\n'.join(agent_messages)
    
    # 3. 元数据合并(高优先级覆盖)
    merged_metadata = {}
    for r in reversed(responses):
        merged_metadata.update(r.metadata or {})
    
    # 4. 证据聚合
    merged_evidence = []
    for i, r in enumerate(responses):
        for e in (r.evidence or []):
            e['hook_index'] = i
            merged_evidence.append(e)
    
    return MergedHookOutput(
        decision=final_decision,
        reason=responses[0].reason if responses else None,
        user_message=merged_user_message,
        agent_message=merged_agent_message,
        metadata=merged_metadata,
        evidence=merged_evidence
    )
```

---

## 八、Plugin Hook隔离与安全

### 8.1 Plugin Hook沙箱隔离

**隔离机制**:
- **文件系统**: 只读plugin root,读写plugin data目录
- **网络**: 默认禁止,仅允许manifest声明的端点
- **系统调用**: seccomp默认策略,禁止危险调用(mount/ptrace/keyctl等)
- **资源限制**: CPU 1核、内存512MB、进程数10、运行时长60s

**seccomp策略**:
```json
{
  "defaultAction": "SCMP_ACT_ERRNO",
  "syscalls": [
    {
      "names": ["read", "write", "open", "close", "stat", "fstat"],
      "action": "SCMP_ACT_ALLOW"
    },
    {
      "names": ["execve"],
      "action": "SCMP_ACT_ALLOW",
      "args": [
        {
          "index": 0,
          "value": "/plugin/root/hooks/*",
          "op": "SCMP_CMP_MASKED_EQ"
        }
      ]
    }
  ]
}
```

**AppArmor策略**:
```
profile plugin_hook {
  /plugin/root/** r,
  /plugin/data/** rw,
  
  deny /etc/** rw,
  deny /var/** rw,
  deny /sys/** rw,
  deny /proc/** rw,
  
  network inet stream,
  network inet6 stream,
}
```

---

### 8.2 Plugin Hook命名空间隔离

**scoped name机制**: Plugin Hook访问MCP工具时使用scoped name

**命名格式**: `mcp__plugin_<plugin_id>__<tool_name>`

**示例**:
- Plugin ID: `security-scanner`
- 原始tool name: `scan_file`
- Scoped name: `mcp__plugin_security-scanner__scan_file`

**隔离效果**:
- Plugin A无法调用Plugin B的MCP工具
- Plugin Hook matcher必须使用scoped name匹配

---

### 8.3 Plugin Hook安全检查

**注册时检查**:
```python
def validate_plugin_hook(hook: HookRegistration) -> ValidationResult:
    violations = []
    
    # 1. 安全类Hook强制签名
    if hook.category in ['security', 'compliance']:
        if not hook.signature:
            violations.append("安全类Hook必须签名")
    
    # 2. 禁止访问plugin root外文件
    if hook.type == 'command':
        if '..' in hook.command or hook.command.startswith('/'):
            violations.append("禁止访问plugin root外文件")
    
    # 3. 网络端点必须在manifest声明
    if hook.type == 'http':
        if hook.http_config.url not in plugin.manifest.allowed_endpoints:
            violations.append("HTTP端点未在manifest声明")
    
    # 4. 禁止manifest声明cwd/env字段
    if 'cwd' in hook or 'env' in hook:
        violations.append("Plugin Hook禁止声明cwd/env字段")
    
    return ValidationResult(passed=len(violations)==0, violations=violations)
```

---

## 九、版本兼容性与演进

### 9.1 manifest schema版本化

**当前版本**: `manifest_version: "1.0"`

**版本演进**:
- v1.0: 初始版本,基础字段
- v1.1: 新增retry_config、approval_config(向后兼容)
- v1.2: 新增inline类型Hook(向后兼容)
- v2.0: 不兼容变更(移除deprecated事件、统一为inline类型)

**兼容性保证**:
- 小版本升级(v1.0 -> v1.1): 新字段可选,老manifest有效
- 大版本升级(v1.x -> v2.0): 允许不兼容变更,提供迁移工具

---

### 9.2 事件名称演进协议

**演进流程**:

1. **新增事件**: 直接添加,不影响现有Hook
2. **重命名事件**:
   - 宣布兼容期(6个月)
   - 兼容期内新旧事件同时触发
   - 文档标注deprecated,推荐新名称
   - 兼容期后废弃旧事件
3. **废弃事件**:
   - 标记为deprecated(12个月)
   - 继续触发但记录warning
   - 文档说明替代事件
4. **移除事件**:
   - 只在大版本升级时移除
   - 提前12个月宣布
   - 提供自动化迁移工具

**示例: pre-tool-use重命名为before-tool-call**:
```
2026-01-01: 宣布pre-tool-use重命名,兼容期6个月
2026-01-01 ~ 2026-07-01: 新旧事件同时触发
2026-07-01: pre-tool-use标记为deprecated,推荐before-tool-call
2027-01-01: pre-tool-use在v2.0移除
```

---

### 9.3 第三方格式兼容(可选)

**Claude Code hooks兼容**:
- 自动加载`.claude/settings.json`中的hooks配置
- 事件名称映射: `PreToolUse` -> `before-tool-use`
- 响应格式映射: nested hookSpecificOutput -> flat HookOutput
- 优先级: Claude hooks作为User层Hook(priority 400)

**配置示例**:
```json
// .claude/settings.json
{
  "hooks": {
    "PreToolUse": [
      {
        "command": "./hooks/security-scan.sh"
      }
    ]
  }
}
```

**自动映射为**:
```json
{
  "hook_id": "user:before-tool-use:claude-compat-0",
  "source": "user",
  "event": "before-tool-use",
  "type": "command",
  "command": "./.claude/hooks/security-scan.sh",
  "priority": 400
}
```

---

## 十、审计与可观测性

### 10.1 Hook执行审计日志

**日志Schema**:
```typescript
interface HookExecutionLog {
  event_id: string;
  hook_id: string;
  event: HookEvent;
  timestamp: string;
  
  context: {
    task_id: string;
    workflow_id?: string;
    worker_id?: string;
    action_id?: string;
    tool?: string;
    user_id: string;
    organization_id: string;
  };
  
  execution: {
    status: 'success' | 'timeout' | 'failure';
    duration_ms: number;
    timeout_ms: number;
    decision: HookDecision;
    reason?: string;
  };
  
  evidence: Evidence[];
  
  audit: {
    retention_days: number;
    immutable: boolean;
    trace_id: string;
  };
}
```

**留存策略**:
- 热存储: 30天(PostgreSQL)
- 冷存储: 180天(对象存储)
- 合规保留: Legal Hold期间不删除

---

### 10.2 Hook执行指标

**per hook_id指标**:
- `hook_execution_count`: 执行总次数
- `hook_execution_duration_p95`: 执行延迟p95
- `hook_timeout_rate`: 超时率(目标<1%)
- `hook_failure_rate`: 失败率(目标<1%)
- `hook_block_rate`: 返回block决策比例
- `hook_retry_count`: 重试总次数

**系统健康指标**:
- `hook_registry_size`: 已注册Hook总数
- `hook_matching_latency_p95`: 匹配延迟p95(目标<10ms)
- `hook_parallel_execution_overhead`: 并行调度开销(目标<20ms)
- `hook_decision_conflict_rate`: 决策冲突率(目标<5%)

**影响指标**:
- `action_blocked_by_hook_rate`: Action被Hook阻断比例
- `task_delay_caused_by_hook_p95`: Hook导致Task延迟p95(目标<500ms)
- `approval_wait_time_p95`: 审批等待时间p95(目标<5min)

---

### 10.3 审计查询API

**支持的查询维度**:
- 按hook_id查询: 特定Hook的所有执行记录
- 按event查询: 特定事件的所有Hook执行
- 按decision查询: 所有block决策及原因
- 按user_id查询: 特定用户触发的Hook执行
- 按时间范围查询: 指定时间段的Hook执行
- 按organization_id查询: 组织级审计追溯

**查询接口**(概念):
```typescript
interface HookAuditQuery {
  hook_id?: string;
  event?: HookEvent;
  decision?: HookDecision;
  user_id?: string;
  organization_id?: string;
  start_time?: string;
  end_time?: string;
  limit?: number;
  offset?: number;
}

interface HookAuditQueryResult {
  total: number;
  logs: HookExecutionLog[];
  has_more: boolean;
}
```

---

## 十一、性能与成本

### 11.1 延迟目标

| Hook类型 | 延迟目标(p95) | 延迟预算 | 超时配置 |
|---------|-------------|---------|---------|
| command | < 100ms | 5% | 30s |
| http | < 500ms | 10% | 60s |
| mcp_tool | < 200ms | 5% | 30s |
| approval | < 30s | N/A | 30min |
| inline | < 50ms | 2% | 10s |

**延迟分解**:
```
总延迟 = 匹配延迟 + 执行延迟 + 合并延迟 + 应用延迟

匹配延迟 (目标<10ms):
  = 倒排索引查询 O(1)
  + 正则过滤 O(n)
  + CEL过滤 O(n*k)
  + 排序 O(n log n)

执行延迟 (并行,目标<100ms):
  = max(Hook1, Hook2, ..., HookN)
  + 并行调度开销 (~10ms)

合并延迟 (目标<5ms):
  = 决策合并 O(n)
  + 消息串联 O(n*m)
  + 元数据合并 O(n*p)

应用延迟 (目标<1ms):
  = 决策逻辑 O(1)
```

---

### 11.2 成本优化

**成本来源**:
- 计算: subprocess启动、http请求、mcp_tool调用
- 网络: http类型出站流量
- 存储: 审计日志180天留存
- 人工: approval类型审批时间

**优化策略**:
- Hook执行预算: 每Task限制Hook总时长(默认10s)
- 审计日志压缩: JSON压缩,减少存储成本
- 审批批量: 相似审批请求批量处理
- Hook禁用: 连续失败Hook自动禁用

---

## 十二、验收标准

| 编号 | 验收标准 | 验证方法 |
|-----|---------|---------|
| AC-01 | 支持platform/enterprise/team/project/user/plugin六种注册源 | 单元测试:注册六种source Hook |
| AC-02 | 安全类Hook签名验证失败拒绝注册 | 集成测试:伪造signature验证拒绝 |
| AC-03 | Hook匹配支持正则matcher和CEL if_condition | 单元测试:matcher+CEL双层过滤 |
| AC-04 | 响应合并遵循block>allow>observe优先级 | 单元测试:3 Hook[allow,block,allow]返回block |
| AC-05 | fail-closed策略超时/失败返回block | 集成测试:Hook超时验证返回block |
| AC-06 | Plugin Hook无法访问plugin root外文件 | 沙箱逃逸测试:读/etc/passwd被阻断 |
| AC-07 | command类型Hook执行延迟p95<100ms | 性能测试:1000次执行统计p95 |
| AC-08 | 审计日志包含必需字段 | 审计测试:验证字段完整性 |
| AC-09 | manifest schema版本向后兼容 | 兼容性测试:v1.0在v2.0注册成功 |
| AC-10 | 事件重命名兼容期同时触发新旧事件 | 兼容性测试:注册v1事件在v2触发 |
| AC-11 | wait-approval超时escalate到管理员 | 集成测试:模拟超时验证escalation |
| AC-12 | 审计记录按5种维度查询 | 查询测试:hook_id/event/decision/user/时间 |

---

## 十三、依赖与接口

### 13.1 依赖的上游模块

| 模块 | 依赖内容 | 接口(概念) |
|------|---------|----------|
| REQ-HAR-001 | Harness生命周期、Worker实例管理 | Worker.on_hook_added()/reload_hooks() |
| REQ-SEC-001 | 威胁模型、签名要求、fail-closed策略 | ThreatModel.get_hook_security_level() |
| REQ-SEC-003 | Policy Gateway授权、注册权限验证 | PolicyGateway.check_hook_permission() |
| REQ-RT-001 | Task/Workflow/Worker/Action实体 | Entity.get_audit_context() |
| REQ-RT-003 | Event Schema、Hook执行事件 | Event.HookExecutionStarted/Completed |

---

### 13.2 为下游提供的接口

| 接口(概念) | 下游消费者 | 说明 |
|----------|----------|------|
| HookRegistry.register() | HAR-005、Plugin Manager | 注册Hook |
| HookRegistry.find_matching_hooks() | Worker、Action Executor | 查找匹配Hook |
| HookExecutor.execute() | Worker、Action Executor | 执行Hook |
| ResponseMerger.merge() | Worker、Action Executor | 合并响应 |
| HookAuditLogger.log() | OBS-006、合规报告 | 记录审计 |

---

## 十四、实施计划

### 14.1 MVP范围(4周)

**Week 1: 核心注册与匹配**
- HookRegistry基础实现
- 六层注册源支持
- 倒排索引+双层过滤匹配算法
- 签名验证(SHA-256+RSA-2048)

**Week 2: 执行与合并**
- command/http类型Hook执行器
- 并行执行调度(goroutine pool)
- 响应合并协议实现
- 六种失败策略

**Week 3: 隔离与安全**
- Plugin Hook沙箱(seccomp+AppArmor)
- scoped name命名空间隔离
- 安全检查与逃逸测试

**Week 4: 审计与观测**
- 结构化审计日志
- 多维度查询API
- 执行指标收集
- 性能基准测试

---

### 14.2 后续演进

**Phase 2(v1.1): 增强能力**
- approval类型Hook
- inline类型Hook(沙箱代码执行)
- retry策略增强(exponential backoff)
- Claude Code兼容层

**Phase 3(v1.2): 企业特性**
- Enterprise Hook强制下发
- 审批矩阵(按risk_level分级)
- Hook成本分析与优化建议
- 合规报告自动生成

---

## 十五、参考资料

| 来源 | 内容 | 访问日期 |
|------|------|---------|
| OpenAI Agents SDK | 双层Hook、上下文包装器、Plugin manifest | 2026-10-02 |
| Claude Code | 20+事件、五种类型、响应合并、作用域隔离 | 2026-10-02 |
| LangChain 1.0 | Middleware装饰器、洋葱模型、内置Middleware | 2026-10-02 |
| Cursor | 多级合并、第三方兼容、企业策略 | 2026-10-02 |
| Dify | Plugin Daemon、四种运行时、Reverse Call | 2026-10-02 |
| Kimi Code CLI | 阻断/观测分离、Plugin Hook环境、安全约束 | 2026-10-02 |

---

**文档版本**: v0.1-designed  
**创建日期**: 2026-10-02  
**作者**: 架构组  
**状态**: 待跨模块评审与冻结

