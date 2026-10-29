# REQ-CTX-008 上下文压缩与分层加载详细设计

> 版本：v0.2-designed
> 状态：G-CTX r2 限定文档基线已于 2026-10-29 用户确认；待工作包验收，未全项冻结或实现。
> 原文创建日期：2026-10-04；修订日期：2026-10-29。

## 1. 修订来源与目标

本次重建缺失 §1～5.1，不声称找回历史原稿。原稿及本地唯一可见提交均从代码围栏中途开始；历史证据和原断片见 [G-CTX §3](../development/contracts/context.md)。新增类型和限额来自用户确认的 `gctx-review-20261029-r2` §10～14。

目标：在有限模型窗口内按任务优先级压缩文件/符号上下文，保留安全约束、审批事实及完整工具调用对，并与 HAR 对话压缩协调。快照与索引始终绑定租户、资源和固定代码版本。

## 2. 范围与边界

支持六种已有任务类型，任务优先级沿用 §5.2；支持分层压缩、L1/L2/L3 按需加载和可验证快照。MVP 不含 Agent 自主触发、动态阈值、长期记忆或学习模型。现有厂商收益数字及存储代码示例不代表本项目实测或生产依赖授权。Runtime 实体/事件/Checkpoint 冻结字段保持不变。

## 3. 请求、结果与引用结构


下表中“提案”字段为本次补拟；现有 DTO 保持原名与字段，补拟对象位于适配/协调层。标识复用 Runtime 的真实坐标，禁止以 org 代替 project 或以 workflow 代替 task。

| 对象 | 字段与类型 | 约束及来源 |
|---|---|---|
| CompressionScope（提案） | organization_id、project_id、repository_id、task_id、workflow_id、worker_id?: string；source_revision、index_version: string | 请求上下文经授权后注入；索引与代码版本匹配；不扩改冻结 Runtime 实体 |
| ContextRevision（提案） | context_version: integer；scope: CompressionScope | context_version ≥0，协调层维护的上下文递增版本，不等同事件 sequence |
| CompressionRequest（补拟） | request_id、trace_id: string；base: ContextRevision；task_type: 六类枚举；trigger: pressure/overflow/manual；context_tokens、max_context_tokens、reserved_output_tokens、reserved_tool_tokens: integer；tokenizer_version: string；items: ContextItem[] | 均必填；计数非负，max_context_tokens >0；保留预算和必须小于窗口；request_id 为关联标识，不作为新的幂等键生成规则 |
| ContextItem（提案） | item_id: string；kind: system/constraint/decision/tool_pair/symbol/document；content: string；required: boolean；estimated_tokens: integer；source_refs: SourceRef[] | required 项不可自动丢弃；system/constraint/审批决定强制 required；tool_pair 是完整调用及结果单元，不按消息数拆开 |
| SourceRef（提案） | file_id、file_path、file_hash: string；symbol_id?: string；range: CTX-001.SourceRange；source_revision、index_version: string | 规范化相对路径；哈希与绑定快照一致；符号可选，文件引用不可缺；SourceRange 先原样透传，不擅改行列起点 |
| LayerMarker（补拟） | marker_id: string；source: SourceRef；target_layer: L2/L3；estimated_tokens: integer | marker 不是授权令牌；展开必须按当前权限重新检查，revision 不可替换成 latest |
| CompressionResult（补拟） | request_id、trace_id: string；base_context_version: integer；committed_context_version?: integer；outcome: success/partial/skipped/failed/cancelled；before_tokens、after_tokens: integer；items: ContextItem[]；layers: SymbolCompressionResult；snapshot_ref?: string；warnings: string[]；failure_kind?: string | success/partial 只有 CAS 发布成功后才带 committed_context_version；其他结果不得更新权威上下文；失败/取消返回空 items，旧上下文由调用方保留 |

SymbolCompressionResult 继续沿用原文的 l1_summary、l2_context、l3_markers；源示例的 `estimated_tokens: 50/200` 是估计示意，不作为精确计数或固定字面量类型。提案将实际估计置于运行时计数，使用 tokenizer_version 复算，实际总 Token 不得超过可用输入预算。

每个请求必须在服务端授权范围内取材；模型生成的摘要仅为不可信派生数据，不能覆盖系统约束、审批事实或产生新权限。输入包含必须保留但已无权访问的内容时拒绝请求，不以压缩方式继续传播。


## 4. 触发、预算与协作状态机


压力定义提案：`usable = max_context_tokens - reserved_output_tokens - reserved_tool_tokens`；`pressure = context_tokens / usable`。usable ≤0 为非法输入。CTX 阈值保持 70%/80%/95%，HAR 保持 70%/85%/95%；两者统一使用该请求记录的预算坐标，避免一个含输出预留、另一个不含预留的隐式误差。阈值使用整数比较：`100 * context_tokens >= threshold_pct * usable`。

| CTX 条件 | 必须响应 |
|---|---|
| pressure <70% | 不自动压缩；手动请求仍允许按授权执行 |
| 70% ≤ pressure <80% | 只产生压力提示，不自动修改上下文 |
| 80% ≤ pressure <95% | 在工具调用边界安排常规压缩 |
| pressure ≥95% 或 overflow | 优先压缩，停止继续向模型派发超预算输入；仍不得截断活跃工具调用对 |

压缩流水线沿用 L0 清理 → L1 摘要 → L2 符号。此处流水线等级与展示层级 L1/L2/L3 是两套概念：展示层 L1 是摘要、L2 是定义与依赖、L3 是完整代码的按需引用。先去除确证冗余，再选择可压缩非 required 项；保留项自身超预算时返回 failed，不能删除安全约束硬凑成功。预览使用相同输入/版本/配置，只返回估计变更和风险，不写快照或发布状态；实际执行重新校验权限、预算与版本。

协调状态机提案：`IDLE → WAITING_BOUNDARY → HAR_RUNNING（如需）→ CTX_RUNNING（如需）→ VALIDATING → COMMITTED`；任一步失败或取消进入 FAILED/CANCELLED，释放本次租约并保留旧版本。仅有历史压力时委托 HAR；仅检索压力时由 CTX 处理；混合压力先 HAR 后重新测量，只有仍需压缩时执行 CTX。

协调层每个 `(organization_id, task_id, workflow_id)` 同时一个压缩操作，使用存储租约和 fencing token；最终提交以 context_version 做 CAS。收到已过期租约/旧版本回调、重复完成回调或取消后的回调时不发布内容；返回重复/版本冲突诊断。context_version 未变化的重复请求复用既有终态结果；内容变化必须重新评估。真正持久化写操作沿用 RT-007/REL-006 的已批准逻辑意图、首次派发前持久化及重试复用规则，本材料不定义替代幂等算法。

五分钟冷却沿用原文用于抑制常规重复压缩；不允许因冷却把超过窗口的输入交给模型，紧急时无法安全压缩即停止并返回明确失败。HAR 的 active_tool_calls 不为空时先等边界，在截止时间前未完成则返回 skipped，不截断、不强行取消外部工具。


## 5. 处理流程与失败边界

### 5.1 快照、限额及异常


沿用 CTX-008 原文 §8 的 summary、preserved_decisions/context/constraints、original_messages_ref、checksum、created_at、expires_at 等语义。快照是应用层恢复资产，不能当成 RT-005 WorkflowCheckpoint 本体；与 Runtime 快照使用 asset 引用关联。storage_path 只保留服务内部，外部返回授权校验后的 snapshot_ref，不能返回可任意读取的路径。

提案：校验和覆盖完整语义载荷（含保留约束、源引用、版本和租户范围），采用明确的 canonical JSON/UTF-8 序列化和 SHA-256；原示例只摘要部分字段，不能证明全载荷防篡改。SHA-256 用于完整性比对，可信摘要存储与写权限仍须隔离，不能把无密钥哈希宣称为攻击者可写存储中的真实性证明。原文 90 天为保留目标，不能覆盖安全删除和冻结 RT 留存规则；实际生效期限受批准的资源留存策略约束。

| 限额/异常 | 基线候选规则（新增限额为提案） |
|---|---|
| 候选/负载 | 每次最多 1000 项、总 UTF-8 内容最多 8 MiB；超限拒绝，不先无界加载后裁剪 |
| 请求期限 | 服务端端到端最多 10s；调用方可缩短；模型/存储使用剩余期限，取消信号传播；本切片远程失败不自动重试 |
| 质量验证 | 必需项和工具对完整、版本一致、Token 不超预算才可提交；LLM 摘要不作授权依据 |
| 快照失败 | 默认拒绝破坏性替换；仅可返回不提交的预览或保留完整原始材料的可逆展示结果，不报告可恢复快照成功 |
| 摘要失败 | 模板化安全提取后仍需全部验证；失败即拒绝发布，不按“最后 N 条”任意截断 |
| 失效/缺失 marker | 重新按固定 revision 定位并验 hash；无法验证即明确失败，不回退最新代码 |
| 状态持久化或审计失败 | 不宣称提交成功；状态与必需审计采用事务/outbox，交由实现方案落实，不把异步 best-effort 日志当作完成证据 |

错误用 failure_kind 记录语义分类：INVALID_INPUT、ACCESS_DENIED、RULES_UNAVAILABLE、REVISION_UNAVAILABLE、VERSION_CONFLICT、DEADLINE_EXCEEDED、INTEGRITY_FAILURE、BUDGET_UNSATISFIABLE、DEPENDENCY_FAILURE。它们是待确认协调层分类，不是新增 HTTP/RET-* 枚举；HTTP/API 映射由实施方案对齐 G-SEC/G-WEB。


以上为当前批准的明确契约；下文历史示例中冲突的截断/快照代码须遵守本节约束。

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
// 历史流程示意；校验和覆盖及发布约束以 §5.1 为准，不直接照搬下列摘要算法。
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
// 历史流程示意；读取前必须执行租户/资源授权、有效期/校验和验证及有界查询。
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
| **1** | 简单摘要 | 安全模板提取并验证 | 必需约束 + 完整工具对；无快照不破坏性替换 | ~1s（历史估计） |
| **2** | 安全裁剪 | 仅移除非 required 冗余项 | 全部必需约束、审批事实及完整工具对 | ~100ms（历史估计） |
| **3** | 紧急预算处理 | 验证后裁剪；无法满足即拒绝 | 不因紧急状态删除必需项或拆开调用对 | ~50ms（历史估计） |
| **4** | 拒绝压缩 | 不压缩 | 全部保留，返回警告 | 0ms |

### 9.2 异常处理矩阵

| 异常类型 | 检测条件 | 处理策略 | 降级路径 |
|----------|----------|----------|----------|
| **压缩超时** | duration > 10s | 降级到简单截断 | Level 0 → Level 2 |
| **快照创建失败** | 存储写入失败 | 拒绝破坏性替换；仅可返回不提交的可逆展示/预览 | 不发布新权威版本 |
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
**状态**：v0.2-designed，限定 r2 文档基线已确认；待工作包验收，未全项冻结


## 十七、变更记录

| 版本 | 日期 | 变更原因与依据 |
|---|---|---|
| v0.1-designed（历史残稿） | 2026-10-04 | 原始可见文本缺失开头，保留历史说明，不宣称完整 |
| v0.2-designed | 2026-10-29 | 用户确认 gctx-review-20261029-r2：重建 §1～5.1、完整输入输出/预算/协调/快照、收紧不安全降级；不改冻结 Runtime Schema |

原有 §6～16 保留作来源及后续验收清单；与本版明确约束冲突的代码仅为历史流程示意。验收目标未执行，不能因文档补齐标记功能完成。消费接口、规则故障默认拒绝和迁移清单见 [G-CTX §11～15](../development/contracts/context.md)。
