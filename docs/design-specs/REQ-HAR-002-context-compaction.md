# REQ-HAR-002: Context Compaction（上下文压缩）详细设计

> **需求编号**: REQ-HAR-002  
> **需求名称**: Context Compaction（上下文压缩）  
> **优先级**: P0  
> **状态**: v0.1-designed（待跨模块评审与冻结）  
> **创建日期**: 2026-09-27  
> **依赖**: REQ-CTX-008（上下文压缩与分层加载）、REQ-REL-004（Checkpoint 保存与保留策略）  
> **被依赖**: REQ-HAR-003、REQ-HAR-004、REQ-HAR-005、REQ-HAR-006

---

## 一、设计目标

### 1.1 核心定位

**Context Compaction 是长期任务执行的关键能力**，负责在有限 Token 预算内支持复杂、长程的研发任务，通过智能压缩保证任务可持续执行且关键信息不丢失。

**核心价值**：
- 降低 Token 消耗成本 40-60%
- 支持更长期、更复杂的任务（200+ 工具调用）
- 保证任务可恢复性和一致性
- 提供可观测的压缩质量

### 1.2 设计原则

| 原则 | 说明 |
|------|------|
| **渐进式触发** | 使用三级阈值（warning/compaction/max），避免一次性强制压缩 |
| **平衡保留** | 工具调用-结果对必须完整保留，不在配对中间截断 |
| **决策优先** | 保留架构决策、约束条件、关键事实，丢弃冗余内容 |
| **可验证性** | 快照包含校验和，支持完整性验证和历史回溯 |
| **优雅降级** | 压缩失败时逐级降级，不阻塞任务执行 |

---

## 二、行业调研与可借鉴设计

### 2.1 竞品研究总结

| 大厂产品 | 触发机制 | 保留策略 | 恢复语义 | 核心亮点 |
|----------|----------|----------|----------|----------|
| **OpenAI** | 固定阈值 + 服务器端 | 压缩项不透明 | 链式 `previous_response_id` | KV Cache 复用 |
| **Claude** | 最小 50K，触发 150K | 架构决策、约束、关键事实 | 类型化 `compaction` block | CLEAR/COMPACT/REMEMBER 分治 |
| **Cursor** | 窗口接近满时自动 | 文件化长输出 | 聊天历史增强摘要 | 46.9% Token 减少 |
| **DeepSeek** | 压力测量 + 溢出 | 平衡保留工具调用对 | 检查点替换 + 溢出恢复 | 模块化引擎 + KV Cache 复用 |
| **KIMI** | 步骤边界触发 | 保留最近 N 对 | 支持取消 + 溢出限制 | 空输出自动收缩 |
| **LangGraph** | Token 阈值 | 增量摘要 | 双状态键（完整/摘要） | 增量摘要 + 状态分离 |
| **Microsoft** | Before/After 双阶段 | 多策略组合 | 策略可插拔 | 双阶段执行 |
| **ACM（学术）** | Agent 自主决定 | 原始消息外部化 | 标识符映射 + 按需检索 | 无损管理 |

**核心设计原则总结**：
1. **触发时机**：固定阈值最常用，Agent 自主触发更智能（v2.0）
2. **保留策略**：平衡保留工具调用对 + 增量摘要
3. **恢复语义**：压缩块作为规范状态 + 检查点可验证
4. **分层管理**：CLEAR（最便宜）/ COMPACT（中等开销）/ REMEMBER（最完整）

**参考资料**（访问日期：2026-09-26）：
- [Compaction | OpenAI API](https://developers.openai.com/api/docs/guides/compaction)
- [Context engineering | Claude Cookbook](https://platform.claude.com/cookbook/tool-use-context-engineering-context-engineering-tools)
- [Dynamic context discovery · Cursor](https://cursor.com/blog/dynamic-context-discovery)
- [DeepSeek Harness Compaction](https://github.com/deepseek-ai/deepseek-harness)
- [ACM: Agentic Context Management](https://arxiv.org/pdf/2607.23809)

---

## 三、核心实体 Schema

### 3.1 CompactionConfig（压缩配置）

```typescript
interface CompactionConfig {
  // 阈值配置
  warning_threshold: number;      // 默认 0.70 (70%)
  compaction_threshold: number;   // 默认 0.85 (85%)
  max_threshold: number;          // 默认 0.95 (95%)
  
  // 保留策略
  retain_tool_pairs: number;      // 保留最近的工具调用对数量，默认 10
  retain_system_messages: boolean; // 是否保留系统消息，默认 true
  
  // 摘要策略
  summarization_model?: string;   // 摘要模型，默认使用主模型
  summary_max_tokens: number;     // 摘要最大 Token 数，默认 512
  summary_prompt_template?: string; // 摘要指令模板
  
  // 快照策略
  snapshot_enabled: boolean;      // 是否启用快照，默认 true
  snapshot_retention: Duration;   // 快照保留期，默认 24h
  
  // 触发策略
  enable_dynamic_threshold: boolean; // 是否启用动态阈值调整，默认 false
  enable_agent_trigger: boolean;    // 是否允许 Agent 自主触发，默认 false（v2.0）
}
```

### 3.2 CompactionTriggerInput（触发输入）

```typescript
interface CompactionTriggerInput {
  // 触发条件
  trigger_type: 'pressure' | 'overflow' | 'manual' | 'agent_decided';
  
  // 当前上下文状态
  context_tokens: number;
  max_context_tokens: number;
  token_budget_remaining: number;
  
  // 活跃操作
  active_tool_calls: ToolCall[];
  
  // 用户意图
  user_task_summary?: string;
  
  // 请求元数据
  workflow_id: UUID;
  worker_id?: UUID;
  source_revision: RevisionRef;
}
```

### 3.3 CompactionResult（压缩结果）

```typescript
interface CompactionResult {
  // 压缩结果
  outcome: 'success' | 'partial' | 'failed' | 'skipped';
  
  // 压缩前状态
  before_tokens: number;
  before_context_summary: string;
  
  // 压缩后状态
  after_tokens: number;
  after_context_summary: string;
  
  // 快照信息
  snapshot?: CompactionSnapshot;
  
  // 统计
  compressed_pairs: number;        // 压缩的工具调用对数
  retained_pairs: number;         // 保留的工具调用对数
  compression_ratio: number;       // 压缩比
  
  // Token 节省
  tokens_saved: number;
  estimated_cost_saved: number;   // 估算节省的成本
  
  // 元数据
  compaction_id: UUID;
  triggered_at: Timestamp;
  duration_ms: number;
  
  // Trace
  trace_id: TraceId;
  parent_span_id?: SpanId;
}
```

### 3.4 CompactionSnapshot（压缩快照）

```typescript
interface CompactionSnapshot {
  // 快照标识
  snapshot_id: UUID;
  compaction_id: UUID;
  source_revision: RevisionRef;
  workflow_id: UUID;
  
  // 摘要内容
  summary: string;               // 压缩摘要
  summary_format: 'structured' | 'plain'; // 默认 structured
  
  // 保留的关键信息
  preserved_decisions: PreservedDecision[];  // 保留的决策
  preserved_context: PreservedContext[];    // 保留的上下文项
  preserved_constraints: string[];          // 保留的约束条件
  
  // 原始消息引用（用于回溯）
  original_messages_ref: MessageRef[];
  
  // 可验证性
  checksum: string;              // 快照校验和（SHA-256）
  verifiable: boolean;            // 是否可验证
  
  // 元数据
  created_at: Timestamp;
  expires_at: Timestamp;
  storage_path: string;
  
  // 版本
  schema_version: string;        // "compaction.snapshot.v1"
}

interface PreservedDecision {
  type: 'architectural' | 'constraint' | 'approach' | 'rejection';
  description: string;
  rationale?: string;
  source_message_ids: string[];
  importance: 'critical' | 'high' | 'medium';
}

interface PreservedContext {
  type: 'modified_file' | 'pending_task' | 'test_status' | 'constraint' | 'error_context';
  content: string;
  importance: 'critical' | 'high' | 'medium';
  source_message_ids: string[];
  metadata?: Record<string, any>;
}

interface MessageRef {
  message_id: string;
  message_type: string;
  checksum: string;
  storage_path: string;
  timestamp: Timestamp;
}
```

---

## 四、压缩触发机制

### 4.1 分层阈值触发

```typescript
class CompactionTrigger {
  private config: CompactionConfig;
  private tokenMeter: TokenMeter;
  private pressureHistory: Deque<number>; // 最近 10 次压力记录
  
  constructor(config: CompactionConfig) {
    this.config = config;
    this.tokenMeter = new TokenMeter();
    this.pressureHistory = new Deque(10);
  }
  
  shouldCompact(context: Context): TriggerDecision {
    // 1. 测量当前压力
    const currentPressure = this.tokenMeter.measure(context);
    this.pressureHistory.push(currentPressure);
    
    // 2. 检查阈值
    if (currentPressure >= this.config.max_threshold) {
      return {
        trigger: 'overflow',
        reason: 'exceeded_max_threshold',
        severity: 'critical',
        action: 'force_compact',
        pressure: currentPressure
      };
    }
    
    if (currentPressure >= this.config.compaction_threshold) {
      return {
        trigger: 'pressure',
        reason: 'exceeded_compaction_threshold',
        severity: 'high',
        action: 'normal_compact',
        pressure: currentPressure
      };
    }
    
    if (currentPressure >= this.config.warning_threshold) {
      return {
        trigger: null,
        reason: 'approaching_threshold',
        severity: 'warning',
        action: 'notify_only',
        pressure: currentPressure
      };
    }
    
    // 3. 动态阈值调整（可选）
    if (this.config.enable_dynamic_threshold && this.isPressureRising()) {
      return {
        trigger: 'preemptive',
        reason: 'pressure_trend_rising',
        severity: 'medium',
        action: 'prepare_compact',
        pressure: currentPressure
      };
    }
    
    return {
      trigger: null,
      action: 'continue',
      pressure: currentPressure
    };
  }
  
  private isPressureRising(): boolean {
    if (this.pressureHistory.length < 3) return false;
    
    const recent = Array.from(this.pressureHistory).slice(-3);
    return recent.every((v, i) => i === 0 || v > recent[i - 1]);
  }
}
```

### 4.2 活跃操作等待

```typescript
class ActiveOperationGuard {
  async waitForOperationsComplete(
    activeToolCalls: ToolCall[],
    timeout: Duration = Duration.seconds(30)
  ): Promise<WaitResult> {
    const deadline = Date.now() + timeout.milliseconds;
    
    while (activeToolCalls.some(call => !call.isComplete())) {
      if (Date.now() >= deadline) {
        return {
          success: false,
          reason: 'timeout',
          pending_calls: activeToolCalls.filter(c => !c.isComplete())
        };
      }
      
      await sleep(Duration.milliseconds(100));
    }
    
    return { success: true };
  }
}
```

---

## 五、保留策略设计

### 5.1 平衡保留算法

```typescript
class RetentionPolicy {
  // 重要性分级
  static readonly IMPORTANCE_TIERS = {
    'critical': ['architectural_decision', 'constraint', 'security_requirement'],
    'high': ['modified_file', 'pending_task', 'test_status', 'error_context'],
    'medium': ['tool_result', 'user_feedback', 'plan_update'],
    'low': ['exploration', 'clarification', 'retry_attempt']
  };
  
  applyRetention(
    messages: Message[],
    config: CompactionConfig
  ): RetentionResult {
    // 1. 按时间排序
    const sorted = messages.sort((a, b) => a.timestamp - b.timestamp);
    
    // 2. 分离系统消息和对话消息
    const systemMessages = sorted.filter(m => m.isSystem);
    const dialogMessages = sorted.filter(m => !m.isSystem);
    
    // 3. 配对工具调用和结果
    const toolPairs = this.pairToolCalls(dialogMessages);
    
    // 4. 确定保留边界
    const retainedPairs = toolPairs.slice(-config.retain_tool_pairs);
    const toSummarizePairs = toolPairs.slice(0, -config.retain_tool_pairs);
    
    // 5. 提取待摘要的对话
    const toSummarizeDialog = toSummarizePairs.flat();
    
    // 6. 优先级提升（确保关键信息不被摘要）
    const preservedContext = this.extractPreservedContext(messages);
    
    return {
      systemMessages,
      retainedPairs,
      toSummarizeDialog,
      preservedContext
    };
  }
  
  private pairToolCalls(messages: Message[]): [Message, Message][] {
    const pairs: [Message, Message][] = [];
    let pendingCall: Message | null = null;
    
    for (const msg of messages) {
      if (msg.type === 'tool_call') {
        pendingCall = msg;
      } else if (msg.type === 'tool_result' && pendingCall) {
        pairs.push([pendingCall, msg]);
        pendingCall = null;
      }
    }
    
    // 未配对的工具调用保留到下一轮
    if (pendingCall) {
      pairs.push([pendingCall, null as any]); // 标记为不完整
    }
    
    return pairs;
  }
  
  private extractPreservedContext(messages: Message[]): PreservedContext[] {
    const preserved: PreservedContext[] = [];
    
    for (const msg of messages) {
      // 提取架构决策
      if (this.isArchitecturalDecision(msg)) {
        preserved.push({
          type: 'modified_file',
          content: msg.content,
          importance: 'critical',
          source_message_ids: [msg.id]
        });
      }
      
      // 提取约束条件
      if (this.isConstraint(msg)) {
        preserved.push({
          type: 'constraint',
          content: msg.content,
          importance: 'high',
          source_message_ids: [msg.id]
        });
      }
      
      // 提取测试状态
      if (this.isTestStatus(msg)) {
        preserved.push({
          type: 'test_status',
          content: msg.content,
          importance: 'high',
          source_message_ids: [msg.id]
        });
      }
    }
    
    return preserved;
  }
}
```

---

## 六、摘要生成策略

### 6.1 结构化摘要模板

```typescript
const SUMMARY_PROMPT_TEMPLATE = `
你是一个任务压缩助手。请将以下对话历史压缩为结构化摘要。

## 当前任务
{task_summary}

## 压缩要求
1. **保留架构决策**：关键的代码结构、设计模式、技术选型决策
2. **保留约束条件**：安全约束、性能要求、兼容性要求
3. **保留已完成工作**：已完成的关键修改、测试通过的功能
4. **保留待完成工作**：待办事项、待修改文件、待解决问题
5. **丢弃冗余内容**：重复的探索、失败的尝试、中间步骤

## 待摘要的对话
{dialog_to_summarize}

## 已保留的最近工具调用对
{retained_pairs}

## 输出格式（Markdown）

### 任务状态
[任务整体进度和当前阶段]

### 保留的架构决策
- **决策1**: [原因和影响]
- **决策2**: [原因和影响]

### 保留的约束条件
- [约束1]
- [约束2]

### 已完成的关键工作
- [完成1]：[验证状态]
- [完成2]：[验证状态]

### 待完成的重点任务
- [待做1]：[优先级]
- [待做2]：[优先级]

### 关键上下文
[其他需要保留的重要信息]

---
**压缩统计**：原始 {original_count} 条消息，保留最近 {retained_count} 对工具调用。
`;
```

### 6.2 摘要执行器

```typescript
class CompactionSummarizer {
  private llm: LLM;
  
  async summarize(
    retention: RetentionResult,
    taskSummary: string,
    config: CompactionConfig
  ): Promise<SummarizationResult> {
    // 1. 构建摘要指令
    const instruction = this.buildInstruction(retention, taskSummary, config);
    
    // 2. 调用 LLM 生成摘要
    const response = await this.llm.generate({
      prompt: instruction,
      max_tokens: config.summary_max_tokens,
      model: config.summarization_model,
      temperature: 0.3, // 低温度保证一致性
      purpose: 'compaction' // 标记用途
    });
    
    // 3. 解析摘要
    const parsed = this.parseSummary(response.content);
    
    // 4. 验证摘要质量
    if (this.estimateTokens(parsed.summary) > config.summary_max_tokens) {
      return await this.shrinkSummary(parsed, config);
    }
    
    return {
      summary: parsed.summary,
      preserved_decisions: parsed.decisions,
      preserved_context: parsed.context,
      token_count: this.estimateTokens(parsed.summary)
    };
  }
  
  private buildInstruction(
    retention: RetentionResult,
    taskSummary: string,
    config: CompactionConfig
  ): string {
    return SUMMARY_PROMPT_TEMPLATE
      .replace('{task_summary}', taskSummary)
      .replace('{dialog_to_summarize}', this.formatDialog(retention.toSummarizeDialog))
      .replace('{retained_pairs}', this.formatPairs(retention.retainedPairs))
      .replace('{original_count}', retention.toSummarizeDialog.length.toString())
      .replace('{retained_count}', retention.retainedPairs.length.toString());
  }
  
  private parseSummary(content: string): ParsedSummary {
    // 解析 Markdown 结构化输出
    const sections = this.extractMarkdownSections(content);
    
    return {
      summary: content,
      decisions: this.extractDecisions(sections['保留的架构决策']),
      context: this.extractContext(sections),
      constraints: this.extractConstraints(sections['保留的约束条件'])
    };
  }
  
  private async shrinkSummary(
    parsed: ParsedSummary,
    config: CompactionConfig
  ): Promise<SummarizationResult> {
    // 空输出自动收缩（参考 KIMI）
    const shrinkInstruction = `
请将以下摘要进一步压缩到 ${config.summary_max_tokens} tokens 以内，
但必须保留所有架构决策和约束条件。

原始摘要：
${parsed.summary}
`;
    
    const response = await this.llm.generate({
      prompt: shrinkInstruction,
      max_tokens: config.summary_max_tokens,
      model: config.summarization_model,
      temperature: 0.3
    });
    
    return {
      summary: response.content,
      preserved_decisions: parsed.decisions,
      preserved_context: parsed.context,
      token_count: this.estimateTokens(response.content)
    };
  }
}
```

---

## 七、快照管理机制

### 7.1 快照创建与验证

```typescript
class SnapshotManager {
  private storage: SnapshotStorage;
  
  async createSnapshot(
    summarization: SummarizationResult,
    originalMessages: Message[],
    contextId: string,
    workflowId: UUID
  ): Promise<CompactionSnapshot> {
    // 1. 生成消息引用
    const messageRefs = await this.createMessageRefs(originalMessages, contextId);
    
    // 2. 持久化原始消息
    await this.persistMessages(originalMessages, contextId);
    
    // 3. 组装快照
    const snapshot: CompactionSnapshot = {
      snapshot_id: uuid(),
      compaction_id: uuid(),
      source_revision: this.getCurrentRevision(),
      workflow_id: workflowId,
      summary: summarization.summary,
      summary_format: 'structured',
      preserved_decisions: summarization.preserved_decisions,
      preserved_context: summarization.preserved_context,
      preserved_constraints: summarization.constraints,
      original_messages_ref: messageRefs,
      checksum: this.computeSnapshotChecksum(messageRefs, summarization),
      verifiable: true,
      created_at: new Date(),
      expires_at: this.computeExpiryDate(),
      storage_path: this.getStoragePath(contextId),
      schema_version: 'compaction.snapshot.v1'
    };
    
    // 4. 持久化快照
    await this.storage.persistSnapshot(snapshot);
    
    // 5. 验证快照完整性
    const verified = await this.verifySnapshot(snapshot);
    if (!verified) {
      throw new Error('Snapshot verification failed');
    }
    
    return snapshot;
  }
  
  private async createMessageRefs(
    messages: Message[],
    contextId: string
  ): Promise<MessageRef[]> {
    const refs: MessageRef[] = [];
    
    for (const msg of messages) {
      const ref: MessageRef = {
        message_id: msg.id,
        message_type: msg.type,
        checksum: this.computeChecksum(msg),
        storage_path: this.getMessageStoragePath(msg, contextId),
        timestamp: msg.timestamp
      };
      refs.push(ref);
    }
    
    return refs;
  }
  
  private computeChecksum(message: Message): string {
    const content = JSON.stringify(message.content, Object.keys(message.content).sort());
    return crypto.createHash('sha256').update(content).digest('hex');
  }
  
  private computeSnapshotChecksum(
    refs: MessageRef[],
    summarization: SummarizationResult
  ): string {
    const data = {
      refs: refs.map(r => ({ id: r.message_id, checksum: r.checksum })),
      summary: summarization.summary,
      decisions: summarization.preserved_decisions
    };
    const content = JSON.stringify(data, Object.keys(data).sort());
    return crypto.createHash('sha256').update(content).digest('hex');
  }
  
  async verifySnapshot(snapshot: CompactionSnapshot): Promise<boolean> {
    // 1. 验证快照校验和
    const expected = this.computeSnapshotChecksum(
      snapshot.original_messages_ref,
      {
        summary: snapshot.summary,
        preserved_decisions: snapshot.preserved_decisions,
        preserved_context: snapshot.preserved_context,
        constraints: snapshot.preserved_constraints
      }
    );
    
    if (snapshot.checksum !== expected) {
      console.error('Snapshot checksum mismatch', {
        expected,
        actual: snapshot.checksum
      });
      return false;
    }
    
    // 2. 验证每条消息的校验和（抽样）
    const sampleSize = Math.min(10, snapshot.original_messages_ref.length);
    const samples = this.randomSample(snapshot.original_messages_ref, sampleSize);
    
    for (const ref of samples) {
      const stored = await this.loadMessage(ref);
      const computed = this.computeChecksum(stored);
      if (computed !== ref.checksum) {
        console.error('Message checksum mismatch', {
          message_id: ref.message_id,
          expected: ref.checksum,
          actual: computed
        });
        return false;
      }
    }
    
    return true;
  }
  
  async queryHistoricalContext(
    snapshotId: UUID,
    query: string
  ): Promise<HistoricalContextResult> {
    // 1. 加载快照
    const snapshot = await this.storage.loadSnapshot(snapshotId);
    
    // 2. 搜索匹配的消息引用
    const matchedRefs = snapshot.original_messages_ref.filter(ref =>
      this.matchesQuery(ref, query)
    );
    
    // 3. 加载匹配的消息
    const messages = await Promise.all(
      matchedRefs.map(ref => this.loadMessage(ref))
    );
    
    return {
      snapshot_id: snapshotId,
      matched_count: messages.length,
      messages,
      query
    };
  }
}
```

---

## 八、压缩执行流程

### 8.1 完整执行流程

```typescript
class CompactionExecutor {
  private trigger: CompactionTrigger;
  private retention: RetentionPolicy;
  private summarizer: CompactionSummarizer;
  private snapshotManager: SnapshotManager;
  
  async executeCompaction(
    context: Context,
    config: CompactionConfig
  ): Promise<CompactionResult> {
    const startTime = Date.now();
    const compactionId = uuid();
    
    try {
      // Phase 1: 触发检测
      const triggerDecision = this.trigger.shouldCompact(context);
      if (triggerDecision.action === 'continue') {
        return this.skipCompaction(triggerDecision);
      }
      
      // Phase 2: 等待活跃操作完成
      const waitResult = await this.waitForActiveOperations(context);
      if (!waitResult.success) {
        return this.skipCompaction(triggerDecision, 'active_operations_timeout');
      }
      
      // Phase 3: 应用保留策略
      const retention = this.retention.applyRetention(context.messages, config);
      
      // Phase 4: 生成摘要
      const summarization = await this.summarizer.summarize(
        retention,
        context.taskSummary,
        config
      );
      
      // Phase 5: 创建快照
      let snapshot: CompactionSnapshot | undefined;
      if (config.snapshot_enabled) {
        snapshot = await this.snapshotManager.createSnapshot(
          summarization,
          retention.toSummarizeDialog,
          context.id,
          context.workflowId
        );
      }
      
      // Phase 6: 更新上下文
      const updatedContext = this.updateContext(
        context,
        retention,
        summarization,
        snapshot
      );
      
      // Phase 7: 发布事件
      await this.publishCompactionEvents(compactionId, context, retention, snapshot);
      
      // Phase 8: 返回结果
      return {
        outcome: 'success',
        before_tokens: context.tokenCount,
        before_context_summary: this.summarizeContext(context),
        after_tokens: updatedContext.tokenCount,
        after_context_summary: this.summarizeContext(updatedContext),
        snapshot,
        compressed_pairs: retention.toSummarizePairs.length,
        retained_pairs: retention.retainedPairs.length,
        compression_ratio: 1 - (updatedContext.tokenCount / context.tokenCount),
        tokens_saved: context.tokenCount - updatedContext.tokenCount,
        estimated_cost_saved: this.estimateCostSaved(context, updatedContext),
        compaction_id: compactionId,
        triggered_at: new Date(startTime),
        duration_ms: Date.now() - startTime,
        trace_id: context.traceId,
        parent_span_id: context.spanId
      };
      
    } catch (error) {
      // 降级处理
      return await this.handleCompactionFailure(error, context, config, compactionId);
    }
  }
  
  private updateContext(
    context: Context,
    retention: RetentionResult,
    summarization: SummarizationResult,
    snapshot?: CompactionSnapshot
  ): Context {
    // 1. 移除待摘要的消息
    const filteredMessages = context.messages.filter(msg =>
      !retention.toSummarizeDialog.some(sm => sm.id === msg.id)
    );
    
    // 2. 插入摘要消息块
    const summaryMessage: Message = {
      id: uuid(),
      type: 'compaction_summary',
      role: 'system',
      content: summarization.summary,
      metadata: {
        compaction_id: snapshot?.compaction_id,
        snapshot_id: snapshot?.snapshot_id,
        compressed_count: retention.toSummarizeDialog.length,
        preserved_decisions: summarization.preserved_decisions
      },
      timestamp: new Date()
    };
    
    // 3. 重新组装消息列表
    const newMessages = [
      ...retention.systemMessages,
      summaryMessage,
      ...retention.retainedPairs.flat()
    ];
    
    // 4. 创建新上下文
    return {
      ...context,
      messages: newMessages,
      tokenCount: this.estimateTokens(newMessages),
      lastCompaction: {
        compaction_id: snapshot?.compaction_id,
        snapshot_id: snapshot?.snapshot_id,
        timestamp: new Date()
      }
    };
  }
}
```

### 8.2 降级策略

```typescript
class CompactionDegradation {
  private degradationLevels = [
    'full_compaction',      // 完整压缩（摘要 + 快照）
    'simple_summarization', // 简单摘要（无快照）
    'truncation',           // 截断（保留最后 N 条）
    'emergency_truncation'  // 紧急截断（仅保留系统消息）
  ];
  
  private currentLevel = 'full_compaction';
  
  async handleCompactionFailure(
    error: Error,
    context: Context,
    config: CompactionConfig,
    compactionId: UUID
  ): Promise<CompactionResult> {
    // 1. 判断是否应该降级
    if (this.shouldDegrade(error)) {
      this.degrade(error.message);
    }
    
    // 2. 执行降级压缩
    switch (this.currentLevel) {
      case 'simple_summarization':
        return await this.simpleSummarization(context, config);
      
      case 'truncation':
        return await this.truncate(context, config);
      
      case 'emergency_truncation':
        return await this.emergencyTruncate(context, config);
      
      default:
        throw new Error('All degradation levels failed');
    }
  }
  
  private shouldDegrade(error: Error): boolean {
    const degradationTriggers = [
      'SummarizationTimeout',
      'SnapshotPersistenceError',
      'LLMAPIFailure',
      'ChecksumVerificationFailed'
    ];
    return degradationTriggers.includes(error.name);
  }
  
  private degrade(reason: string): void {
    const levelIndex = this.degradationLevels.indexOf(this.currentLevel);
    if (levelIndex + 1 < this.degradationLevels.length) {
      this.currentLevel = this.degradationLevels[levelIndex + 1];
      console.warn('Compaction degraded', {
        reason,
        new_level: this.currentLevel
      });
    }
  }
  
  private async simpleSummarization(
    context: Context,
    config: CompactionConfig
  ): Promise<CompactionResult> {
    // 简单截断：保留最后 N 条消息
    const retainCount = config.retain_tool_pairs * 2;
    const retained = context.messages.slice(-retainCount);
    
    return {
      outcome: 'partial',
      before_tokens: context.tokenCount,
      after_tokens: this.estimateTokens(retained),
      compression_ratio: 1 - (this.estimateTokens(retained) / context.tokenCount),
      // ... 其他字段
    };
  }
}
```

---

## 九、可观测性设计

### 9.1 压缩指标

```typescript
const COMPACTION_METRICS = {
  // 触发指标
  'compaction.trigger.count': {
    type: 'counter',
    labels: ['trigger_type', 'outcome'],
    description: '压缩触发次数'
  },
  
  'compaction.skip.count': {
    type: 'counter',
    labels: ['reason'],
    description: '跳过压缩次数'
  },
  
  // 效果指标
  'compaction.ratio': {
    type: 'histogram',
    buckets: [0.1, 0.3, 0.5, 0.7, 0.9],
    labels: ['compaction_type'],
    description: '压缩比分布'
  },
  
  'compaction.tokens.before': {
    type: 'histogram',
    buckets: [1000, 5000, 10000, 50000, 100000],
    description: '压缩前 Token 数'
  },
  
  'compaction.tokens.after': {
    type: 'histogram',
    buckets: [500, 2000, 5000, 10000, 20000],
    description: '压缩后 Token 数'
  },
  
  'compaction.tokens.saved': {
    type: 'histogram',
    buckets: [500, 2000, 5000, 10000, 50000],
    description: '节省的 Token 数'
  },
  
  // 质量指标
  'compaction.summary.quality': {
    type: 'histogram',
    buckets: [1, 2, 3, 4, 5],
    description: '摘要质量评分（1-5）'
  },
  
  'compaction.information.preservation': {
    type: 'histogram',
    buckets: [0.5, 0.7, 0.85, 0.95, 1.0],
    description: '信息保留率'
  },
  
  // 性能指标
  'compaction.duration.seconds': {
    type: 'histogram',
    buckets: [0.5, 1, 2, 5, 10],
    labels: ['phase'],
    description: '压缩耗时'
  },
  
  // 异常指标
  'compaction.failure.count': {
    type: 'counter',
    labels: ['error_type'],
    description: '压缩失败次数'
  },
  
  'compaction.degradation.count': {
    type: 'counter',
    labels: ['from_level', 'to_level'],
    description: '降级次数'
  }
};
```

### 9.2 告警规则

```typescript
const COMPACTION_ALERTS = {
  'compaction_ratio_low': {
    condition: 'compaction.ratio < 0.3',
    severity: 'warning',
    message: '压缩比过低，可能存在配置问题或摘要质量问题'
  },
  
  'compaction_failure_rate_high': {
    condition: 'compaction.failure.count / compaction.trigger.count > 0.1',
    severity: 'critical',
    message: '压缩失败率过高，需要排查 LLM API 或存储'
  },
  
  'compaction_duration_high': {
    condition: 'compaction.duration.seconds.p95 > 5',
    severity: 'warning',
    message: '压缩耗时过长，可能影响任务体验'
  },
  
  'force_compaction_count_high': {
    condition: 'compaction.trigger.count{trigger_type="overflow"} > 10',
    severity: 'critical',
    message: '强制压缩次数过多，预算管理可能有问题'
  },
  
  'snapshot_verification_failed': {
    condition: 'compaction.snapshot.verification.failed.count > 0',
    severity: 'critical',
    message: '快照验证失败，数据完整性受威胁'
  }
};
```

### 9.3 追踪集成

```typescript
class CompactionTracing {
  startCompactionSpan(
    context: Context,
    trigger: TriggerDecision
  ): Span {
    return tracer.startSpan('harness.compaction', {
      attributes: {
        'compaction.trigger_type': trigger.trigger,
        'compaction.severity': trigger.severity,
        'compaction.pressure': trigger.pressure,
        'compaction.context_tokens': context.tokenCount,
        'compaction.max_tokens': context.maxTokens,
        'workflow.id': context.workflowId,
        'task.id': context.taskId
      }
    });
  }
  
  recordCompactionResult(span: Span, result: CompactionResult): void {
    span.setAttributes({
      'compaction.outcome': result.outcome,
      'compaction.tokens_before': result.before_tokens,
      'compaction.tokens_after': result.after_tokens,
      'compaction.compression_ratio': result.compression_ratio,
      'compaction.tokens_saved': result.tokens_saved,
      'compaction.duration_ms': result.duration_ms,
      'compaction.snapshot_id': result.snapshot?.snapshot_id,
      'compaction.compressed_pairs': result.compressed_pairs,
      'compaction.retained_pairs': result.retained_pairs
    });
    
    if (result.outcome === 'failed') {
      span.setStatus({ code: SpanStatusCode.ERROR });
    }
  }
}
```

---

## 十、人类在环交互

### 10.1 交互模式

| 场景 | 交互类型 | 描述 |
|------|----------|------|
| 达到 warning 阈值 | 静默通知 | 状态栏显示 Token 使用率（黄色），不打断执行 |
| 触发 compaction 前 | 确认可选 | 弹出确认对话框（可配置自动执行），预览压缩内容 |
| 压缩完成后 | 结果展示 | 显示压缩比、快照 ID、保留项列表 |
| 强制压缩（max 阈值） | 强制通知 | 显示红色警告，说明可能丢失信息 |
| 回溯历史 | 按需查询 | 提供 `/history <snapshot_id> <query>` 命令 |

### 10.2 交互接口

```typescript
class CompactionHumanInTheLoop {
  async requestCompactionConfirmation(
    trigger: TriggerDecision,
    preview: CompactionPreview
  ): Promise<ConfirmationResponse> {
    // 显示预览对话框
    const dialog = {
      title: '上下文压缩确认',
      message: `当前 Token 使用率 ${(trigger.pressure * 100).toFixed(1)}%，建议执行压缩`,
      preview: {
        will_summarize: `${preview.toSummarizeCount} 条消息将被摘要`,
        will_retain: `最近 ${preview.retainCount} 对工具调用将被保留`,
        estimated_saved: `预计节省 ${preview.estimatedSaved} tokens`,
        compression_ratio: `预计压缩比 ${(preview.estimatedRatio * 100).toFixed(1)}%`
      },
      actions: ['确认压缩', '取消', '修改保留策略']
    };
    
    return await this.showDialog(dialog);
  }
  
  async notifyCompactionComplete(result: CompactionResult): void {
    const notification = {
      type: 'success',
      title: '上下文压缩完成',
      message: `压缩比 ${(result.compression_ratio * 100).toFixed(1)}%，节省 ${result.tokens_saved} tokens`,
      details: {
        snapshot_id: result.snapshot?.snapshot_id,
        preserved_decisions: result.snapshot?.preserved_decisions?.length || 0,
        preserved_context: result.snapshot?.preserved_context?.length || 0
      },
      actions: ['查看快照', '关闭']
    };
    
    await this.showNotification(notification);
  }
  
  async queryHistoricalContext(
    snapshotId: UUID,
    query: string
  ): Promise<HistoricalContextResult> {
    return await this.snapshotManager.queryHistoricalContext(snapshotId, query);
  }
}
```

---

## 十一、验收标准

### 11.1 功能验收

| 编号 | 验收标准 | 验证方法 | 目标值 |
|------|----------|----------|--------|
| HAR-002-F01 | 支持三级阈值配置 | 配置测试 | warning/compaction/max 可配置 |
| HAR-002-F02 | 工具调用对完整保留 | 单元测试 | 100% 配对完整 |
| HAR-002-F03 | 压缩后任务可继续执行 | 集成测试 | 任务成功率 >= 95% |
| HAR-002-F04 | 快照完整性可验证 | 验证测试 | 校验和匹配率 100% |
| HAR-002-F05 | 支持历史回溯查询 | 功能测试 | 查询成功率 >= 99% |
| HAR-002-F06 | 支持手动触发压缩 | 功能测试 | `/compact` 命令可用 |
| HAR-002-F07 | 压缩事件完整记录 | 审计测试 | 事件覆盖率 100% |

### 11.2 质量验收

| 编号 | 验收标准 | 验证方法 | 目标值 |
|------|----------|----------|--------|
| HAR-002-Q01 | 平均压缩比 | 统计测试 | >= 50% |
| HAR-002-Q02 | 摘要质量评分 | 人工评估 | >= 4/5 |
| HAR-002-Q03 | 信息保留率 | 任务对比测试 | >= 90% |
| HAR-002-Q04 | 架构决策保留率 | 专项测试 | 100% |

### 11.3 性能验收

| 编号 | 验收标准 | 验证方法 | 目标值 |
|------|----------|----------|--------|
| HAR-002-P01 | 压缩耗时 p95 | 性能测试 | < 2s |
| HAR-002-P02 | 压缩触发检测延迟 | 性能测试 | < 5ms |
| HAR-002-P03 | Token 节省 | 统计测试 | >= 40% |
| HAR-002-P04 | 成本降低 | 成本统计 | >= 40% |

### 11.4 安全验收

| 编号 | 验收标准 | 验证方法 | 目标值 |
|------|----------|----------|--------|
| HAR-002-S01 | 快照权限边界正确 | 安全测试 | 未授权访问率 0% |
| HAR-002-S02 | 审计日志完整 | 安全测试 | 日志覆盖率 100% |
| HAR-002-S03 | 快照校验和防篡改 | 安全测试 | 篡改检测率 100% |

---

## 十二、依赖与接口

### 12.1 上游依赖

| 依赖模块 | 依赖内容 | 接口 |
|----------|----------|------|
| REQ-RT-001 | 核心实体 Schema | Task/Workflow/Worker 定义 |
| REQ-RT-005 | Checkpoint Protocol | 快照存储接口 |
| REQ-CTX-008 | 上下文压缩与分层加载 | 压缩策略接口（待设计） |
| REQ-REL-004 | Checkpoint 保存与保留策略 | 持久化接口 |
| REQ-SEC-003 | Policy Gateway | 压缩授权检查 |
| REQ-OBS-001 | OpenTelemetry 语义约定 | 追踪集成 |

### 12.2 下游接口

| 接口 | 下游消费者 | 说明 |
|------|----------|------|
| `CompactionTrigger` | HAR-003~006 | 压缩触发接口 |
| `CompactionResult` | EVA-003 | 压缩质量评估 |
| `CompactionSnapshot` | RT-005 | 快照存储 |
| `CompactionEvent` | OBS-001~007 | 可观测性事件 |

### 12.3 接口定义

```typescript
// 对外暴露的主接口
export interface ICompactionEngine {
  // 检查是否应该压缩
  shouldCompact(context: Context): TriggerDecision;
  
  // 执行压缩
  executeCompaction(context: Context, config?: CompactionConfig): Promise<CompactionResult>;
  
  // 手动触发压缩
  manualCompact(context: Context): Promise<CompactionResult>;
  
  // 查询历史上下文
  queryHistory(snapshotId: UUID, query: string): Promise<HistoricalContextResult>;
  
  // 验证快照
  verifySnapshot(snapshotId: UUID): Promise<boolean>;
}

// 与 Checkpoint Protocol 的集成
export interface ICheckpointIntegration {
  // 保存压缩快照到 Checkpoint 存储
  saveSnapshotToCheckpoint(snapshot: CompactionSnapshot): Promise<void>;
  
  // 从 Checkpoint 恢复压缩快照
  loadSnapshotFromCheckpoint(snapshotId: UUID): Promise<CompactionSnapshot>;
}

// 与 Context 管理的集成
export interface IContextIntegration {
  // 应用压缩结果到上下文
  applyCompaction(context: Context, result: CompactionResult): Context;
  
  // 从快照恢复上下文
  restoreFromSnapshot(snapshot: CompactionSnapshot): Context;
}
```

---

## 十三、版本与演进

### 13.1 v1.0 基线（MVP）

**功能范围**：
- 固定阈值触发（warning/compaction/max）
- 平衡保留策略（工具调用对完整性）
- 结构化摘要生成
- 完整快照机制
- 基础可观测性

**不包含**：
- Agent 自主触发
- 动态阈值调整
- 增量压缩优化
- 长期记忆集成

### 13.2 v1.1 增强

**新增功能**：
- 动态阈值调整（基于历史趋势）
- 改进摘要质量（专用摘要模型）
- 快照完整性验证增强
- 压缩质量自动评估

### 13.3 v2.0 高级

**新增功能**：
- Agent 自主触发（参考 ACM 训练管道）
- 多级压缩策略（细粒度控制）
- 增量压缩优化（只压缩变化部分）
- 与长期记忆集成（参考 DSH ExpMem）
- 压缩质量模型训练

### 13.4 兼容性与迁移

**Schema 版本化**：
- 快照 Schema 版本：`compaction.snapshot.v1`
- 向后兼容：新版本可读取旧版本快照
- 迁移路径：提供快照格式转换工具

**渐进式升级**：
- v1.0 → v1.1：无破坏性变更，配置兼容
- v1.1 → v2.0：需要重新训练摘要模型，但快照格式兼容

---

## 十四、实施计划

### 14.1 Phase 1：核心机制（2 周）

- [ ] 实现 CompactionTrigger（触发检测）
- [ ] 实现 RetentionPolicy（保留策略）
- [ ] 实现 CompactionSummarizer（摘要生成）
- [ ] 实现 SnapshotManager（快照管理）
- [ ] 单元测试覆盖率 >= 80%

### 14.2 Phase 2：集成与优化（1 周）

- [ ] 与 RT-005 Checkpoint Protocol 集成
- [ ] 与事件溯源系统集成
- [ ] 实现降级策略
- [ ] 实现人类在环交互
- [ ] 集成测试覆盖关键路径

### 14.3 Phase 3：可观测性（1 周）

- [ ] 实现压缩指标
- [ ] 实现告警规则
- [ ] 实现 OpenTelemetry 追踪
- [ ] 实现压缩质量评估

### 14.4 Phase 4：验收与文档（1 周）

- [ ] 执行验收测试
- [ ] 压力测试（200+ 工具调用任务）
- [ ] 性能基准测试
- [ ] 完善用户文档和 API 文档

---

## 十五、参考资料

以下为公开来源，访问日期均为 2026-09-26：

- **OpenAI**: [Compaction | OpenAI API](https://developers.openai.com/api/docs/guides/compaction)
- **Claude**: [Context engineering | Claude Cookbook](https://platform.claude.com/cookbook/tool-use-context-engineering-context-engineering-tools)
- **Cursor**: [Dynamic context discovery](https://cursor.com/blog/dynamic-context-discovery)
- **DeepSeek**: [DeepSeek Harness Compaction](https://github.com/deepseek-ai/deepseek-harness)
- **KIMI**: [KIMI Code Compaction](https://github.com/xy200303/spec-kimi-code)
- **LangGraph**: [LangMem Summarization](https://langchain-ai.github.io/langmem/guides/summarization/)
- **Microsoft**: [Agent Framework Compaction](https://learn.microsoft.com/en-us/agent-framework/concepts/agents/conversations/compaction)
- **学术**: [ACM: Agentic Context Management](https://arxiv.org/pdf/2607.23809)

---

## 十六、决策记录

| 决策项 | 决策 | 依据 |
|-------|------|------|
| 触发机制 | 三级阈值（70%/85%/95%） | Claude、Cursor、Microsoft 最佳实践 |
| 保留策略 | 平衡保留工具调用对 | DeepSeek、KIMI 工程实践 |
| 摘要策略 | 结构化摘要 + 决策保留 | Claude、ACM 研究成果 |
| 快照存储 | 复用 RT-005 Checkpoint 存储 | 统一存储架构 |
| Agent 自主触发 | v2.0 支持 | ACM 研究，需要模型后训练 |
| 降级策略 | 四级降级 | 优雅降级最佳实践 |

---

**文档创建时间**：2026-09-27  
**维护团队**：架构组  
**状态**：v0.1-designed，待跨模块评审与冻结
