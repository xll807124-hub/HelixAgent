└── 成本：本地计算
```

### 5.2 任务类型优先级矩阵（借鉴通义灵码）

| 任务类型 | 错误上下文 | 架构决策 | 工具结果 | 测试信息 | 文档 |
|----------|------------|----------|----------|----------|------|
| BUG_FIX | **0.35** | 0.20 | 0.15 | 0.20 | 0.10 |
| FEATURE_DEVELOPMENT | 0.15 | **0.35** | 0.20 | 0.15 | 0.15 |
| REFACTORING | 0.15 | **0.30** | **0.30** | 0.15 | 0.10 |
| CODE_REVIEW | 0.20 | 0.15 | 0.10 | **0.35** | 0.20 |
| UNIT_TEST | 0.15 | 0.15 | 0.20 | **0.35** | 0.15 |
| DOCUMENTATION | 0.15 | 0.20 | 0.10 | 0.10 | **0.45** |

---

## 六、与 REQ-HAR-002 的协同机制

### 6.1 职责边界

| 模块 | 职责 | 触发时机 | 粒度 |
|------|------|----------|------|
| **REQ-HAR-002** | Harness 级别的上下文压缩 | 任务执行过程中的长对话管理 | 对话级别 |
| **REQ-CTX-008** | Context 级别的压缩与分层加载 | 检索结果和上下文选择时 | 文件/符号级别 |

### 6.2 协作接口

```typescript
interface HAR002Collaboration {
  // CTX-008 查询 HAR-002 状态
  async queryHAR002Status(): Promise<{
    is_compacting: boolean;
    last_compaction_at?: Timestamp;
    compaction_count: number;
  }>;
  
  // CTX-008 通知 HAR-002 即将压缩
  async notifyCompressionPending(request: CompressionRequest): Promise<void>;
  
  // CTX-008 委托给 HAR-002（当对话历史压力为主因）
  async delegateToHAR002(request: CompressionRequest): Promise<CompressionResult>;
  
  // HAR-002 完成后回调 CTX-008
  async onHAR002Completed(result: HAR002CompactionResult): Promise<void>;
}
```

### 6.3 协同决策流程

```
压缩触发
    ↓
分析压力来源
    ├── 对话历史过长？ → 委托 HAR-002
    ├── 检索结果过多？ → CTX-008 执行
    └── 两者兼有？ → 先 HAR-002，后 CTX-008
```

---

## 七、符号级压缩算法

### 7.1 分层加载模型（借鉴 Cursor）

```typescript
interface SymbolCompressionResult {
  // L1: Compact Summary（始终加载）
  l1_summary: {
    file_path: string;
    symbol_signatures: string[];   // ['UserService.login(user, pass)', 'UserService.logout()']
    one_line_summary: string;      // "用户认证服务，包含登录和登出功能"
    estimated_tokens: 50;
  }[];
  
  // L2: Timeline Context（按优先级加载）
  l2_context: {
    symbol_definition: string;     // function login(user: string, pass: string): Promise<User>
    key_dependencies: string[];    // ['AuthService', 'Database', 'Logger']
    call_chain: string[];          // ['validateCredentials', 'createSession', 'updateLastLogin']
    estimated_tokens: 200;
  }[];
  
  // L3: Full Code（按需加载）
  l3_markers: LayerMarker[];       // 引用标记，不直接加载
}
```

### 7.2 符号重要性计算

```typescript
function calculateSymbolImportance(
  symbol: Symbol,
  task_type: TaskType,
  context_hints: string[]
): number {
  let score = 0;
  
  // 基础权重
  if (symbol.visibility === 'public') score += 0.3;
  if (symbol.kind === 'function') score += 0.2;
  
  // 任务类型加权
  const taskWeights = TASK_TYPE_SYMBOL_WEIGHTS[task_type];
  score += taskWeights[symbol.kind] || 0;
  
  // 上下文相关性
  const contextRelevance = computeContextRelevance(symbol, context_hints);
  score += contextRelevance * 0.3;
  
  // 图中心性
  const centrality = symbol.dependencies.length + symbol.dependents.length;
  score += Math.min(centrality / 10, 0.2);
  
  return Math.min(score, 1.0);
}
```

---

## 八、快照管理机制

### 8.1 快照创建与验证（借鉴 GitHub Copilot + DeepSeek）

```typescript
class SnapshotManager {
  async createSnapshot(
    summarization: SummarizationResult,
    originalMessages: Message[],
    taskId: string
  ): Promise<CompressionSnapshot> {
    // 1. 生成消息引用
    const messageRefs = await this.createMessageRefs(originalMessages);
    
    // 2. 持久化原始消息到 RT-005 Checkpoint 存储
    await this.persistMessages(originalMessages, taskId);
    
    // 3. 组装快照
    const snapshot: CompressionSnapshot = {
      snapshot_id: uuid(),
      compression_id: uuid(),
      source_revision: this.getCurrentRevision(),
      task_id: taskId,
      summary: summarization.summary,
      summary_format: 'structured',
      preserved_decisions: summarization.preserved_decisions,
      preserved_context: summarization.preserved_context,
      preserved_constraints: summarization.constraints,
      original_messages_ref: messageRefs,
      checksum: this.computeSnapshotChecksum(messageRefs, summarization),
      verifiable: true,
      created_at: new Date(),
      expires_at: this.computeExpiryDate(90), // 90 天 TTL
      storage_path: this.getStoragePath(taskId),
      schema_version: 'compression.snapshot.v1'
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
}
```

### 8.2 历史回溯查询

```typescript
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
  
  // 3. 从存储加载匹配的消息
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
```

---

## 九、异常与降级处理

### 9.1 降级策略层级

| 级别 | 名称 | 操作 | 保留内容 | 延迟 |
|------|------|------|----------|------|
| **0** | 正常压缩 | 完整压缩流程 | 摘要 + 保留尾 + 快照 | ~2s |
| **1** | 简单摘要 | 跳过快照 | 摘要 + 保留尾 | ~1s |
| **2** | 截断 | 固定截断 | 最后 20 条消息 | ~100ms |
| **3** | 紧急截断 | 最小截断 | 系统消息 + 最后 5 条 | ~50ms |
| **4** | 拒绝压缩 | 不压缩 | 全部保留，返回警告 | 0ms |

### 9.2 异常处理矩阵

| 异常类型 | 检测条件 | 处理策略 | 降级路径 |
|----------|----------|----------|----------|
| **压缩超时** | duration > 10s | 降级到简单截断 | Level 0 → Level 2 |
| **快照创建失败** | 存储写入失败 | 跳过快照，继续压缩 | Level 0 → Level 1 |
| **摘要生成失败** | LLM API 返回错误 | 使用模板摘要 | Level 0 → Level 1 |
| **权限检查失败** | 权限服务不可用 | 拒绝压缩 | Level 0 → Level 4 |
| **循环压缩** | 压缩后 5 分钟内再次触发 | 延迟压缩 + 扩大保留窗口 | 添加冷却期 |
| **Token 估算错误** | 估算值与实际偏差 > 20% | 重新估算 | 使用固定估算 |

---

## 十、性能、成本、延迟考量

### 10.1 延迟预算

| 阶段 | 预算 | 说明 |
|------|------|------|
| 压力检测 | 5ms | 内存中计算 |
| 策略选择 | 10ms | 查表 + 简单计算 |
| L0 清理 | 20ms | 内存操作 |
| L1 摘要（同步） | 2s | LLM API 调用 |
| L1 摘要（异步） | 50ms | 触发异步调用 |
| L2 符号压缩 | 100ms | 本地计算 |
| 快照创建 | 50ms | 存储写入 |
| **总计（同步）** | **2.2s** | SLO p95 ≤ 3s |
| **总计（异步）** | **200ms** | SLO p95 ≤ 500ms |

### 10.2 性能目标

| 指标 | 目标值 | 说明 |
|------|--------|------|
| 压缩比 | ≥ 50% | 压缩后 Token / 压缩前 Token ≤ 0.5 |
| 信息保留率 | ≥ 90% | 关键信息覆盖率 |
| p95 延迟 | < 2s（同步）/ < 500ms（异步） | 含 LLM 调用 |
| p99 延迟 | < 5s（同步）/ < 1s（异步） | 含 LLM 调用 |
| 吞吐量 | ≥ 100 compressions/hour | 单实例 |
| 快照创建成功率 | ≥ 99.9% | 含存储重试 |
| 快照验证成功率 | ≥ 99.99% | 校验和匹配 |

---

## 十一、可观测性设计

### 11.1 核心指标

```typescript
const COMPRESSION_METRICS = {
  // 触发指标
  'ctx.compression.trigger.total': {
    type: 'counter',
    labels: ['task_type', 'trigger_type'],
    description: '压缩触发总次数'
  },
  
  // 效果指标
  'ctx.compression.ratio': {
    type: 'histogram',
    buckets: [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7],
    labels: ['task_type'],
    description: '压缩比分布'
  },
  
  'ctx.compression.tokens.saved': {
    type: 'histogram',
    buckets: [500, 2000, 5000, 10000, 50000],
    description: '节省的 Token 数'
  },
  
  // 质量指标
  'ctx.compression.information.preservation': {
    type: 'histogram',
    buckets: [0.5, 0.7, 0.85, 0.95, 1.0],
    labels: ['information_type'],
    description: '信息保留率'
  },
  
  // 性能指标
  'ctx.compression.duration.seconds': {
    type: 'histogram',
    buckets: [0.1, 0.5, 1, 2, 5, 10],
    labels: ['phase'],
    description: '各阶段压缩耗时'
  },
  
  // 异常指标
  'ctx.compression.failure': {
    type: 'counter',
    labels: ['error_type'],
    description: '压缩失败次数'
  },
  
  'ctx.compression.degradation': {
    type: 'counter',
    labels: ['from_level', 'to_level'],
    description: '降级次数'
  }
};
```

### 11.2 告警规则

| 告警名称 | 条件 | 严重性 | 动作 |
|----------|------|--------|------|
| `compression_ratio_low` | compression.ratio < 0.3 | warning | 记录日志 + 调整策略 |
| `compression_failure_rate_high` | failure.count / trigger.total > 0.1 | critical | 告警 + 排查 LLM API |
| `compression_duration_high` | duration.p95 > 5s | warning | 告警 + 优化流程 |
| `force_compression_high` | force_compaction.count > 10/hour | critical | 告警 + 检查预算配置 |
| `snapshot_verification_failed` | verification.failed > 0 | critical | 阻断 + 告警 |

---

## 十二、验收标准

### 12.1 功能验收

| 编号 | 验收标准 | 验证方法 | 目标值 |
|------|----------|----------|--------|
| CTX-008-F01 | 支持任务类型驱动的差异化压缩 | 配置不同任务类型，验证压缩结果差异 | 6 种任务类型各有不同的保留优先级 |
| CTX-008-F02 | 支持符号级粒度压缩 | 对大型文件执行压缩，验证符号粒度 | 符号签名保留完整 |
| CTX-008-F03 | 支持 L1/L2/L3 分层加载 | 验证分层加载标记正确 | 引用可按需加载 |
| CTX-008-F04 | 与 HAR-002 协同压缩 | 模拟 HAR-002 压缩场景 | 不重复、不冲突 |
| CTX-008-F05 | 支持快照回溯查询 | 创建快照后查询历史 | 查询成功率 ≥ 99% |
| CTX-008-F06 | 支持手动触发压缩 | 调用 `/compact` 命令 | 命令执行成功 |
| CTX-008-F07 | 支持压缩前预览 | 触发压缩前查看预览 | 预览信息完整 |

### 12.2 质量验收

| 编号 | 验收标准 | 验证方法 | 目标值 |
|------|----------|----------|--------|
| CTX-008-Q01 | 平均压缩比 | 统计 100 次压缩结果 | ≥ 50% |
| CTX-008-Q02 | 信息保留率 | 人工评估压缩摘要质量 | ≥ 90% |
| CTX-008-Q03 | 架构决策保留率 | 验证架构决策未被丢弃 | 100% |
| CTX-008-Q04 | 摘要可读性 | 人工评估摘要语义完整性 | ≥ 4/5 分 |

### 12.3 性能验收

| 编号 | 验收标准 | 验证方法 | 目标值 |
|------|----------|----------|--------|
| CTX-008-P01 | 压缩耗时 p95（同步） | 性能测试 | < 2s |
| CTX-008-P02 | 压缩耗时 p95（异步） | 性能测试 | < 500ms |
| CTX-008-P03 | 支持并发压缩 | 压力测试 | ≥ 10 concurrent |
| CTX-008-P04 | 快照创建成功率 | 连续测试 | ≥ 99.9% |

### 12.4 安全验收

| 编号 | 验收标准 | 验证方法 | 目标值 |
|------|----------|----------|--------|
| CTX-008-S01 | 快照权限边界正确 | 安全测试 | 未授权访问率 0% |
| CTX-008-S02 | 审计日志完整 | 审计测试 | 日志覆盖率 100% |
| CTX-008-S03 | 快照校验和防篡改 | 安全测试 | 篡改检测率 100% |

---

## 十三、依赖与接口

### 13.1 上游依赖

| 依赖模块 | 依赖内容 | 接口 | 说明 |
|----------|----------|------|------|
| REQ-CTX-006 | Context Selector 与预算 | `BudgetConfig` | 复用预算分配逻辑 |
| REQ-HAR-002 | Context Compaction | `HAR002Collaboration` | 协同压缩，避免重复 |
| REQ-RT-005 | Checkpoint Protocol | `CheckpointStorage` | 快照持久化 |
| REQ-RT-001 | 核心实体 Schema | `Task/Message` 定义 | 数据结构基础 |
| REQ-OBS-001 | OpenTelemetry 语义约定 | `Span/Metric` | 链路追踪集成 |
| REQ-CTX-005 | 检索权限与敏感路径 | `PermissionFilter` | 敏感信息过滤 |

### 13.2 下游接口

| 接口 | 下游消费者 | 说明 |
|------|----------|------|
| `CompressionTrigger` | Worker, Task Orchestrator | 压缩触发接口 |
| `CompressedContext` | REQ-CTX-006, Worker | 压缩后上下文 |
| `CompressionSnapshot` | REQ-RT-005 | 快照存储 |
| `LayerMarker` | Worker | 分层加载标记 |
| `CompressionEvent` | REQ-OBS-001~007 | 可观测性事件 |

---

## 十四、版本与演进计划

### 14.1 v1.0 基线（MVP）

**功能范围**：
- 三级阈值触发（70%/80%/95%）
- 任务类型差异化（6 种预定义任务类型）
- 分层压缩（L0 清理 → L1 摘要 → L2 符号）
- 符号级粒度压缩
- 分层加载标记（L1/L2/L3）
- 快照管理（基于 RT-005）
- HAR-002 基本协同

**不包含**：
- Agent 自主触发
- 动态阈值调整
- 增量压缩优化
- 长期记忆集成

### 14.2 v1.1 增强

**新增功能**：
- 动态阈值调整（基于历史趋势）
- 增量摘要（只摘要变化部分）
- 改进摘要质量（专用摘要模型）
- 快照完整性验证增强

### 14.3 v2.0 高级

**新增功能**：
- Agent 自主触发（参考 ACM 训练管道）
- 自适应压缩策略（基于任务反馈）
- 与长期记忆集成（参考 Claude Memory）
- 压缩质量模型训练

---

## 十五、实施计划

### 15.1 Phase 1：核心机制（2 周）

- [ ] 实现 CompressionTrigger（三级阈值触发）
- [ ] 实现 TaskAwareCompressionStrategy（任务类型优先级）
- [ ] 实现 L0/L1/L2 分层压缩流水线
- [ ] 实现 SymbolCompressor（符号级压缩）
- [ ] 单元测试覆盖率 ≥ 80%

### 15.2 Phase 2：协同与快照（1 周）

- [ ] 实现 HAR002Collaboration（协同接口）
- [ ] 实现 SnapshotManager（快照管理）
- [ ] 与 RT-005 Checkpoint Protocol 集成
- [ ] 实现历史回溯查询
- [ ] 集成测试覆盖关键路径

### 15.3 Phase 3：可观测性（1 周）

- [ ] 实现压缩指标
- [ ] 实现告警规则
- [ ] 实现 OpenTelemetry 追踪
- [ ] 实现压缩质量评估

### 15.4 Phase 4：验收与文档（1 周）

- [ ] 执行验收测试
- [ ] 压力测试（100+ 工具调用任务）
- [ ] 性能基准测试
- [ ] 完善用户文档和 API 文档

---

## 十六、决策记录

| 决策项 | 决策 | 依据 |
|-------|------|------|
| 触发机制 | 三级阈值（70%/80%/95%） + 双触发条件 | GitHub Copilot、KIMI 最佳实践 |
| 保留策略 | 分层压缩（L0 清理 → L1 摘要 → L2 符号） | Claude、Dify 分层设计 |
| 符号压缩 | L1/L2/L3 渐进式暴露 | Cursor 动态上下文发现 |
| 快照存储 | 复用 RT-005 Checkpoint 存储 | 统一存储架构 |
| 协同机制 | 委托模式（CTX-008 → HAR-002） | 职责分离、避免重复 |
| 降级策略 | 五级降级（正常 → 简单 → 截断 → 紧急 → 拒绝） | 优雅降级最佳实践 |
| 任务类型 | 6 种预定义类型 + 优先级矩阵 | 通义灵码任务驱动分配 |

---

**文档创建时间**：2026-10-04  
**维护团队**：架构组  
**状态**：v0.1-designed，待跨模块评审与冻结
