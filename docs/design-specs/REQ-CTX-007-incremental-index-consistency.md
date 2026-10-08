# REQ-CTX-007 增量索引一致性 详细设计

> 版本：v0.1-designed  
> 优先级：P1  
> 状态：详细设计已完成，待跨模块评审与冻结  
> 所属模块：上下文管理（CTX）  
> 前置依赖：REQ-CTX-001（索引实体和关系 Schema）、REQ-RT-001（核心运行时实体）  
> 下游依赖：REQ-CTX-008（上下文压缩与分层加载）、REQ-CTX-009（检索评测）

---

## 1. 目标与范围

### 1.1 需求目标

确保代码索引能够高效增量更新，保证多版本索引的一致性，支持并发读取场景。

**核心价值**：
- 代码变更后索引快速更新，Agent 始终理解最新代码
- 索引版本可追溯，出现问题时可回退
- 并发任务不互相干扰，保证一致性
- 增量索引性能优化，降低索引成本

### 1.2 设计边界

**包含**：
- Merkle 树增量变更检测算法
- 索引版本与 Git SHA 绑定协议
- 索引回退机制
- 并发读取一致性保证（MVCC）
- 索引状态机设计
- 增量索引触发流程

**不包含**：
- 具体 AST 解析实现（归属 REQ-CTX-003）
- 混合检索算法（归属 REQ-CTX-004）
- 权限过滤规则（归属 REQ-CTX-005）
- 上下文压缩策略（归属 REQ-CTX-008）

---

## 2. 行业调研与可借鉴设计

### 2.1 Cursor Codebase Indexing

**设计原则**：
- Merkle 树检测文件变更
- SHA-256 文件哈希计算
- O(log N) 变更检测复杂度
- 仅重嵌入变更块，更新向量数据库

**核心算法**：
```
文件变更检测流程：
1. 计算当前文件哈希列表（叶子节点）
2. 递归计算父节点哈希（Merkle 树）
3. 根哈希代表整个仓库指纹
4. 对比新旧 Merkle 树根哈希
5. 不同则递归找出差异子树
6. 差异叶子节点即为变更文件
```

**可借鉴点**：
1. Merkle 树 O(log N) 变更检测
2. 零配置增量更新
3. 混淆路径隐私保护

**来源**：[Cursor Secure Codebase Indexing](https://cursor.com/blog/secure-codebase-indexing)（访问日期：2026-09-26）

---

### 2.2 GitHub Copilot Repository Indexing

**设计原则**：
- 自动云端索引 GitHub 仓库
- 增量更新机制
- 版本绑定到 Git commit SHA
- 新嵌入模型：检索质量提升 37.6%

**增量更新触发流程**：
```
1. 用户 push 代码变更
2. Webhook 触发索引服务
3. Git diff 获取变更文件列表
4. 对变更文件重新解析 AST
5. 更新符号表和向量索引
6. 发布索引更新事件
```

**可借鉴点**：
1. 版本绑定机制（Git SHA）
2. 语义分块策略（200-400 行）
3. 对比学习嵌入训练范式

**来源**：[GitHub Copilot Repository Indexing](https://docs.github.com/en/copilot/concepts/context/repository-indexing)（访问日期：2026-09-26）

---

### 2.3 Sourcegraph SCIP

**设计原则**：
- Protocol Buffers Schema 定义
- Human-readable string IDs
- 跨仓库符号解析
- 内容寻址存储

**符号标识格式**：
```
<package>.<name>

示例：
- package: github.com/user/repo
- name: src/utils.go:ValidateEmail
- qualified: github.com/user/repo.src/utils.go:ValidateEmail
```

**可借鉴点**：
1. 标准化的索引协议
2. 符号唯一性保证
3. 版本化索引存储

**来源**：[Announcing SCIP](https://sourcegraph.com/blog/announcing-scip)（访问日期：2026-09-26）

---

### 2.4 Qoder Hybrid Retrieval

**设计原则**：
- 服务器端向量数据库
- 客户端代码图（调用、继承）
- 秒级增量更新
- 分支感知检索

**可借鉴点**：
1. 分支感知索引设计
2. 增量更新性能目标（秒级）
3. 图检索与向量检索互补

**来源**：[Qoder Hybrid Retrieval](https://dev.to/qoder/qoders-codebase-aware-code-retrieval-a-hybrid-approach-for-ai-coding-gpm)（访问日期：2026-09-26）

---

### 2.5 通义灵码 GraphTransformer

**设计原则**：
- AST GraphTransformer 图编码
- 引用链追踪
- 增量 AST Diff 事件驱动

**可借鉴点**：
1. 增量 AST Diff 事件驱动架构
2. 引用链追踪
3. 动态相关性识别

**来源**：[通义灵码技术解析](https://developer.aliyun.com/article/1661439)（访问日期：2026-09-27）

---

## 3. 核心设计决策

### 3.1 Merkle 树增量变更检测

**决策**：采用 Merkle 树进行 O(log N) 复杂度的文件变更检测

**理由**：
1. Cursor 生产级实践验证有效
2. 相比简单 Git diff，能够缓存中间结果
3. 支持增量计算，避免全量重扫描
4. 提供内容寻址能力

**算法设计**：

```typescript
interface MerkleNode {
  hash: string;                      // SHA-256
  path?: string;                     // 文件路径（叶子节点）
  children?: MerkleNode[];           // 子节点
}

interface MerkleTree {
  root: MerkleNode;
  repository_id: string;
  source_revision: string;
  computed_at: Timestamp;
}

function detectChanges(
  oldTree: MerkleTree, 
  newTree: MerkleTree
): ChangedFile[] {
  const changes: ChangedFile[] = [];
  
  function traverse(oldNode: MerkleNode, newNode: MerkleNode) {
    // 哈希相同，无变更
    if (oldNode.hash === newNode.hash) {
      return;
    }
    
    // 叶子节点，文件有变更
    if (!oldNode.children) {
      changes.push({
        path: oldNode.path!,
        old_hash: oldNode.hash,
        new_hash: newNode.hash
      });
      return;
    }
    
    // 递归检查子节点
    for (let i = 0; i < oldNode.children.length; i++) {
      traverse(
        oldNode.children[i], 
        newNode.children?.[i] || emptyNode()
      );
    }
  }
  
  traverse(oldTree.root, newTree.root);
  return changes;
}
```

**时间复杂度**：
- 全量构建：O(N)
- 变更检测：O(log N) 平均情况，O(N) 最坏情况（所有文件变更）

---

### 3.2 索引版本绑定协议

**决策**：index_version 与 source_revision 一对一绑定

**理由**：
1. GitHub Copilot 和 Sourcegraph 均采用版本绑定
2. 保证索引可追溯
3. 支持回退和审计
4. 避免版本漂移

**版本号格式**：

```
index_version = "idx-{date}-{sequence}"

示例：
- idx-20261003-001
- idx-20261003-002

组成：
- idx: 固定前缀
- date: UTC 日期（YYYYMMDD）
- sequence: 当日递增序列号
```

**绑定约束**：

```typescript
interface IndexVersionBinding {
  index_version: string;             // 索引版本（唯一）
  source_revision: RevisionRef;     // Git commit SHA（不可变）
  repository_id: RepositoryId;
  created_at: Timestamp;
  state: IndexState;
  
  // 唯一性约束
  unique_constraint: [repository_id, source_revision, state='ACTIVE']
}
```

**一致性保证**：
1. 每个 source_revision 只能有一个 ACTIVE 索引版本
2. 索引写入前验证 source_revision 有效性
3. 索引写入后验证绑定记录存在
4. 读取时验证索引版本与请求 revision 一致

---

### 3.3 索引状态机

**状态定义**：

```typescript
enum IndexState {
  PENDING = "pending",              // 索引任务已创建，等待处理
  BUILDING = "building",            // 正在构建索引
  VALIDATING = "validating",        // 正在验证索引完整性
  ACTIVE = "active",                // 索引已激活，可用于检索
  STALE = "stale",                  // 索引已过期（代码已更新）
  ARCHIVED = "archived",            // 索引已归档（保留用于回退）
  FAILED = "failed"                 // 索引构建失败
}
```

**状态转换规则**：

```
PENDING → BUILDING
  条件：索引任务开始执行
  
BUILDING → VALIDATING
  条件：索引构建完成，开始验证
  
VALIDATING → ACTIVE
  条件：验证通过，激活索引
  
VALIDATING → FAILED
  条件：验证失败
  
ACTIVE → STALE
  条件：新索引版本激活，旧版本变为 STALE
  
STALE → ARCHIVED
  条件：归档旧索引
  
FAILED → PENDING
  条件：重新触发索引（可选）
```

**不变量**：
1. 同一 repository_id 只能有一个 ACTIVE 索引版本
2. ACTIVE 索引必须绑定有效的 source_revision
3. ARCHIVED 索引不可再次激活（只读）
4. FAILED 索引不影响旧版本的可用性

---

## 4. 增量索引触发流程

### 4.1 Webhook 触发

**流程设计**：

```
Step 1: Webhook 接收
  输入：Git push event
  处理：
    1.1 接收 Webhook payload
    1.2 验证 Webhook 签名（HMAC-SHA256）
    1.3 解析仓库信息和分支
    1.4 提取 before/after commit SHA
  输出：ValidatedWebhookPayload

Step 2: 触发条件判断
  输入：ValidatedWebhookPayload
  处理：
    2.1 检查分支是否需要索引（默认 main/master）
    2.2 检查是否强制 push（需要全量重索引）
    2.3 检查变更文件数量（大量变更考虑全量）
  输出：IndexTriggerDecision

Step 3: 创建索引任务
  输入：IndexTriggerDecision
  处理：
    3.1 创建 IncrementalIndexTask
    3.2 记录触发来源和时间
    3.3 分配到索引队列
  输出：IncrementalIndexTask
```

**Webhook 签名验证**：

```typescript
function verifyWebhookSignature(
  payload: string,
  signature: string,
  secret: string
): boolean {
  const expectedSignature = crypto
    .createHmac('sha256', secret)
    .update(payload)
    .digest('hex');
  
  return crypto.timingSafeEqual(
    Buffer.from(signature),
    Buffer.from(`sha256=${expectedSignature}`)
  );
}
```

---

### 4.2 变更检测流程

**流程设计**：

```
Step 1: Git diff 执行
  输入：before_sha, after_sha
  处理：
    1.1 执行 git diff --name-status before_sha after_sha
    1.2 解析变更文件列表
    1.3 分类：Added (A), Modified (M), Deleted (D)
  输出：GitDiffResult

Step 2: 变更文件过滤
  输入：GitDiffResult
  处理：
    2.1 应用 .gitignore 规则
    2.2 过滤非代码文件（.md, .txt, .json 等）
    2.3 应用敏感路径黑名单（集成 REQ-CTX-005）
  输出：FilteredChangedFiles

Step 3: Merkle 树对比
  输入：FilteredChangedFiles
  处理：
    3.1 加载上次索引的 Merkle 树
    3.2 计算当前文件的 Merkle 树
    3.3 对比根哈希
    3.4 递归找出差异子树
  输出：MerkleTreeDiff

Step 4: 增量变更集确定
  输入：MerkleTreeDiff
  处理：
    4.1 确定需要重索引的文件
    4.2 估算增量索引成本
    4.3 决定增量 vs 全量
  输出：IncrementalChangeSet
```

**增量 vs 全量决策**：

```typescript
function shouldUseFullReindex(
  changedFiles: ChangedFile[],
  totalFiles: number
): boolean {
  const changeRatio = changedFiles.length / totalFiles;
  
  // 变更超过 30% 则全量重索引
  if (changeRatio > 0.3) {
    return true;
  }
  
  // 变更文件数超过阈值
  if (changedFiles.length > 1000) {
    return true;
  }
  
  // 包含关键基础设施文件（如 package.json）
  const criticalFiles = [
    'package.json', 
    'requirements.txt', 
    'go.mod'
  ];
  if (changedFiles.some(f => criticalFiles.includes(f.path))) {
    return true;
  }
  
  return false;
}
```

---

### 4.3 增量解析流程

**流程设计**：

```
Step 1: 文件解析
  输入：IncrementalChangeSet
  处理：
    1.1 对 Added/Modified 文件：
        - 读取文件内容
        - 执行 AST 解析（Tree-sitter + LSP）
        - 提取符号和关系
    1.2 对 Deleted 文件：
        - 标记删除
        - 记录删除时间
  输出：ParsedSymbols, ParsedRelations

Step 2: 索引更新
  输入：ParsedSymbols, ParsedRelations
  处理：
    2.1 删除旧符号和关系
    2.2 写入新符号和关系
    2.3 更新调用图
    2.4 更新依赖图
  输出：UpdatedIndexData

Step 3: 向量索引更新
  输入：ParsedSymbols
  处理：
    3.1 为新符号生成向量
    3.2 删除旧向量
    3.3 写入新向量到向量数据库
  输出：UpdatedVectorIndex

Step 4: 全文索引更新
  输入：ParsedSymbols
  处理：
    4.1 更新 BM25 索引
    4.2 更新符号名称索引
    4.3 更新文档字符串索引
  输出：UpdatedFullTextIndex
```

---

### 4.4 版本绑定与发布

**流程设计**：

```
Step 1: 生成索引版本号
  输入：source_revision
  处理：
    1.1 生成版本号：idx-{date}-{seq}
    1.2 验证版本号唯一性
    1.3 创建 IndexVersionMetadata
  输出：IndexVersionMetadata

Step 2: 绑定验证
  输入：IndexVersionMetadata
  处理：
    2.1 验证 source_revision 有效性
    2.2 验证索引数据完整性
    2.3 计算索引统计信息
  输出：ValidationResult

Step 3: 原子发布
  输入：ValidationResult
  处理：
    3.1 开启事务
    3.2 写入 IndexVersionMetadata
    3.3 更新活跃索引指针（ACTIVE）
    3.4 将旧索引标记为 STALE
    3.5 提交事务
  输出：PublishedIndex

Step 4: 事件发布
  输入：PublishedIndex
  处理：
    4.1 发布 IndexUpdatedEvent
    4.2 失效相关缓存（Redis）
    4.3 通知订阅者
  输出：IndexUpdatedEvent
```

**原子发布实现**：

```typescript
async function publishIndexAtomically(
  indexVersion: string,
  sourceRevision: string,
  repositoryId: string
): Promise<void> {
  const transaction = await db.beginTransaction();
  
  try {
    // 1. 写入新索引元数据
    await transaction.insert('index_metadata', {
      index_version: indexVersion,
      source_revision: sourceRevision,
      repository_id: repositoryId,
      state: IndexState.VALIDATING,
      created_at: new Date()
    });
    
    // 2. 验证索引完整性
    const isValid = await validateIndexIntegrity(
      indexVersion, 
      transaction
    );
    if (!isValid) {
      throw new Error('Index integrity validation failed');
    }
    
    // 3. 更新为 ACTIVE
    await transaction.update('index_metadata', {
      state: IndexState.ACTIVE
    }, {
      index_version: indexVersion
    });
    
    // 4. 将旧索引标记为 STALE
    await transaction.update('index_metadata', {
      state: IndexState.STALE
    }, {
      repository_id: repositoryId,
      state: IndexState.ACTIVE,
      index_version: { $ne: indexVersion }
    });
    
    await transaction.commit();
  } catch (error) {
    await transaction.rollback();
    throw error;
  }
}
```

---

## 5. 索引回退机制

### 5.1 回退触发条件

**触发场景**：
1. 索引质量严重下降（检索 Recall 下降 > 20%）
2. 索引构建失败且无法自动恢复
3. 人工检测到索引错误
4. 紧急回退需求

**回退前检查**：

```typescript
interface RollbackValidation {
  target_index_version: string;
  current_index_version: string;
  validation_passed: boolean;
  warnings: string[];
  affected_tasks: TaskId[];
}

async function validateRollback(
  targetVersion: string
): Promise<RollbackValidation> {
  // 1. 检查目标版本存在
  const targetIndex = await getIndexMetadata(targetVersion);
  if (!targetIndex) {
    throw new Error('Target index version not found');
  }
  
  // 2. 检查目标版本状态
  if (targetIndex.state !== IndexState.ARCHIVED) {
    throw new Error('Can only rollback to ARCHIVED index');
  }
  
  // 3. 检查影响的任务
  const affectedTasks = await getTasksUsingIndex(
    getCurrentActiveIndex()
  );
  
  return {
    target_index_version: targetVersion,
    current_index_version: getCurrentActiveIndex(),
    validation_passed: true,
    warnings: affectedTasks.length > 0 
      ? [`${affectedTasks.length} tasks currently using index`]
      : [],
    affected_tasks: affectedTasks.map(t => t.task_id)
  };
}
```

---

### 5.2 回退执行流程

**流程设计**：

```
Step 1: 回退验证
  输入：target_index_version
  处理：
    1.1 检查目标版本存在且为 ARCHIVED
    1.2 检查 parent_index_version 链完整
    1.3 评估回退影响
  输出：RollbackValidation

Step 2: 影响评估
  输入：RollbackValidation
  处理：
    2.1 查询正在使用当前索引的任务
    2.2 评估任务是否会受影响
    2.3 生成影响报告
  输出：ImpactAssessment

Step 3: 人工审批
  输入：ImpactAssessment
  处理：
    3.1 显示回退预览
    3.2 显示影响任务列表
    3.3 要求管理员确认
  输出：ApprovalDecision

Step 4: 原子回退
  输入：ApprovalDecision
  处理：
    4.1 开启事务
    4.2 更新活跃索引指针到目标版本
    4.3 将当前版本标记为 STALE
    4.4 记录回退原因和操作者
    4.5 提交事务
  输出：RollbackCompleted

Step 5: 事件通知
  输入：RollbackCompleted
  处理：
    5.1 发布 IndexRollbackEvent
    5.2 通知受影响的 Agent
    5.3 记录审计日志
  输出：IndexRollbackEvent
```

**回退不中断任务**：

```typescript
// 任务在开始时锁定索引版本
interface TaskIndexLock {
  task_id: TaskId;
  locked_index_version: string;
  locked_at: Timestamp;
}

// 回退后，正在运行的任务继续使用锁定的版本
async function rollbackIndex(
  targetVersion: string
): Promise<void> {
  // 1. 原子更新活跃指针
  await updateActiveIndexPointer(targetVersion);
  
  // 2. 不影响已锁定的任务
  // 任务会继续使用它们锁定的索引版本
  
  // 3. 新任务将使用回退后的版本
  
  // 4. 发布回退事件
  await publishEvent({
    event_type: 'INDEX_ROLLBACK',
    from_version: getCurrentVersion(),
    to_version: targetVersion,
    reason: 'Manual rollback by admin'
  });
}
```

---

## 6. 并发读取一致性

### 6.1 MVCC 快照隔离

**设计原则**：
- 读取不阻塞写入
- 写入不阻塞读取
- 每个读取事务看到一致的快照

**实现方案**：

```typescript
interface IndexSnapshot {
  snapshot_id: number;              // 快照版本号（单调递增）
  index_version: string;            // 索引版本
  created_at: Timestamp;
  valid_until: Timestamp;
}

class MVCCIndexReader {
  // 开启读取事务
  async beginRead(
    sourceRevision: string
  ): Promise<IndexSnapshot> {
    // 1. 查询该 revision 对应的索引版本
    const indexVersion = await getIndexVersion(sourceRevision);
    
    // 2. 获取当前快照 ID
    const snapshotId = await getCurrentSnapshotId();
    
    // 3. 创建快照引用
    const snapshot: IndexSnapshot = {
      snapshot_id: snapshotId,
      index_version: indexVersion,
      created_at: new Date(),
      valid_until: addHours(new Date(), 24)
    };
    
    return snapshot;
  }
  
  // 基于快照读取
  async readWithSnapshot(
    snapshot: IndexSnapshot,
    query: RetrievalQuery
  ): Promise<RetrievalResult> {
    // 只读取 snapshot_id <= query.snapshot_id 的数据
    return await executeQuery({
      ...query,
      snapshot_id: snapshot.snapshot_id,
      index_version: snapshot.index_version
    });
  }
  
  // 释放快照
  async endRead(snapshot: IndexSnapshot): Promise<void> {
    await releaseSnapshotReference(snapshot.snapshot_id);
  }
}
```

---

### 6.2 任务级索引锁定

**设计原则**：
- 任务开始时锁定索引版本
- 任务执行期间使用一致的索引
- 任务结束后释放锁定

**实现方案**：

```typescript
interface TaskIndexLock {
  task_id: TaskId;
  locked_index_version: string;
  source_revision: RevisionRef;
  locked_at: Timestamp;
  released_at: Timestamp | null;
}

class TaskIndexLocker {
  // 任务开始时锁定
  async lockIndexForTask(
    taskId: TaskId,
    sourceRevision: string
  ): Promise<TaskIndexLock> {
    // 1. 查询该 revision 对应的索引版本
    const indexVersion = await getIndexVersion(sourceRevision);
    
    if (!indexVersion) {
      // 如果索引不存在，触发构建
      await triggerIndexBuild(sourceRevision);
      throw new Error('Index not ready, triggered build');
    }
    
    // 2. 创建锁定记录
    const lock: TaskIndexLock = {
      task_id: taskId,
      locked_index_version: indexVersion,
      source_revision: sourceRevision,
      locked_at: new Date(),
      released_at: null
    };
    
    await db.insert('task_index_locks', lock);
    
    // 3. 增加索引引用计数
    await incrementIndexReferenceCount(indexVersion);
    
    return lock;
  }
  
  // 任务结束时释放
  async unlockIndexForTask(
    taskId: TaskId
  ): Promise<void> {
    const lock = await db.findOne('task_index_locks', { task_id: taskId });
    
    if (!lock) {
      return;
    }
    
    // 1. 更新释放时间
    await db.update('task_index_locks', {
      released_at: new Date()
    }, {
      task_id: taskId
    });
    
    // 2. 减少索引引用计数
    await decrementIndexReferenceCount(lock.locked_index_version);
  }
}
```

---

### 6.3 并发控制策略

**读写并发**：

```
场景 1：读取时索引正在更新
  - 读取事务使用快照隔离
  - 读取不阻塞写入
  - 写入生成新快照版本
  - 读取事务看到的是一致的旧快照

场景 2：多个任务并发读取
  - 每个任务获得独立快照
  - 快照之间互不阻塞
  - 快照数据保留直到无引用

场景 3：任务执行时索引回退
  - 任务继续使用锁定的索引版本
  - 回退不影响正在运行的任务
  - 新任务使用回退后的版本
```

**乐观锁冲突检测**：

```typescript
interface IndexUpdateConflict {
  conflicting_updates: IndexUpdate[];
  resolution_strategy: 'retry' | 'abort' | 'merge';
}

async function detectUpdateConflict(
  update: IndexUpdate
): Promise<IndexUpdateConflict | null> {
  // 1. 检查是否有并发更新
  const concurrentUpdates = await getConcurrentUpdates(
    update.repository_id,
    update.started_at
  );
  
  if (concurrentUpdates.length === 0) {
    return null;
  }
  
  // 2. 检测冲突
  const hasConflict = concurrentUpdates.some(u => 
    u.affected_files.some(f => 
      update.affected_files.includes(f)
    )
  );
  
  if (!hasConflict) {
    return null;
  }
  
  // 3. 确定解决策略
  return {
    conflicting_updates: concurrentUpdates,
    resolution_strategy: 'retry'  // 默认重试
  };
}
```

---

## 7. 异常与失败处理

### 7.1 异常场景处理

| 异常场景 | 检测方法 | 处理策略 | 影响范围 | 恢复时间 |
|----------|----------|----------|----------|----------|
| **Git diff 失败** | git 命令返回非零 | 重试 3 次，失败则告警 | 当前增量触发 | < 1min |
| **Merkle 树损坏** | 缓存校验失败 | 回退到全量解析 | 全量重解析 | < 5min |
| **索引构建失败** | BUILDING → FAILED | 保留旧索引，告警 | 不影响旧索引 | N/A |
| **版本绑定冲突** | source_revision 已绑定 | 拒绝写入，告警 | 拒绝新索引 | N/A |
| **回退目标不存在** | 查询返回空 | 拒绝回退，显示错误 | 无影响 | N/A |
| **并发写入冲突** | 乐观锁检测 | 重试或升级锁 | 重试操作 | < 10s |
| **LSP 实例版本不匹配** | LSP 健康检查 | 重启 LSP 实例 | 临时精度下降 | < 30s |
| **向量数据库不一致** | 副本校验失败 | 标记不一致，修复 | 检索质量下降 | < 5min |
| **Webhook 签名失败** | HMAC 验证失败 | 拒绝请求，记录日志 | 拒绝触发 | N/A |
| **索引队列积压** | 队列长度 > 阈值 | 限流新请求，告警 | 延迟增加 | 取决于积压 |

---

### 7.2 失败恢复流程

**索引构建失败恢复**：

```
Step 1: 检测失败
  - 索引构建超时
  - 解析器抛出异常
  - 验证失败

Step 2: 保留现场
  - 保存失败日志
  - 保存部分构建结果
  - 记录失败原因

Step 3: 保持旧索引可用
  - 不删除旧索引
  - 保持 ACTIVE 状态
  - 继续服务检索请求

Step 4: 告警通知
  - 发送告警到管理员
  - 记录审计日志
  - 提供重试选项

Step 5: 自动重试（可选）
  - 等待 5 分钟后重试
  - 最多重试 3 次
  - 重试失败后人工介入
```

**Merkle 树损坏恢复**：

```
Step 1: 检测损坏
  - 加载 Merkle 树失败
  - 哈希校验失败

Step 2: 回退到全量解析
  - 忽略增量检测结果
  - 执行全量 AST 解析
  - 重新构建 Merkle 树

Step 3: 验证恢复
  - 验证新 Merkle 树完整性
  - 对比文件数量和哈希
  - 确认无遗漏

Step 4: 缓存更新
  - 更新 Merkle 树缓存
  - 失效旧缓存
```

---

## 8. 性能、成本、延迟考量

### 8.1 性能目标

| 规模 | 增量索引触发延迟 | 增量索引构建延迟 | 并发读取 QPS | Merkle 树对比延迟 |
|------|-----------------|-----------------|--------------|------------------|
| **SMALL** (<100 文件) | < 1s | < 5s | > 100 | < 50ms |
| **MEDIUM** (100-1000 文件) | < 2s | < 30s | > 50 | < 200ms |
| **LARGE** (1000-10000 文件) | < 5s | < 120s | > 20 | < 500ms |
| **XLARGE** (>10000 文件) | < 10s | < 300s | > 10 | < 1s |

**性能优化策略**：

1. **Merkle 树缓存**：
   - 缓存中间节点哈希
   - 增量计算新哈希
   - 避免全量重扫描

2. **并行解析**：
   - Worker 池并行处理变更文件
   - 每个 Worker 独立 LSP 实例
   - 结果异步聚合

3. **异步写入**：
   - 解析完成后异步写入索引
   - 批量写入优化
   - 流式写入大型索引

4. **快照预热**：
   - 常用索引版本预加载
   - 热点仓库快照缓存

---

### 8.2 成本估算

| 成本项 | 估算 | 说明 |
|--------|------|------|
| **增量索引计算成本** | $0.0001/变更文件 | 增量解析 + 向量生成 |
| **全量索引计算成本** | $0.001/千行代码 | 全量解析 |
| **索引存储成本** | $0.01/文件/月 | 包含向量 + 关系 |
| **Merkle 树存储成本** | $0.001/仓库/月 | Merkle 树缓存 |
| **回退操作成本** | ~ $0 | 仅更新指针 |
| **快照存储成本** | $0.005/快照/天 | MVCC 快照数据 |

**成本优化策略**：

1. **增量优先**：减少全量索引频率
2. **快照生命周期管理**：定期清理无引用快照
3. **归档策略**：旧索引压缩存储
4. **Merkle 树复用**：跨分支共享子树

---

### 8.3 延迟优化

**延迟瓶颈分析**：

```
总延迟 = Webhook 延迟 + 变更检测延迟 + 解析延迟 + 写入延迟 + 发布延迟

典型分布（MEDIUM 仓库，10 文件变更）：
- Webhook 延迟: 0.5s
- Git diff: 0.2s
- Merkle 树对比: 0.1s
- AST 解析: 2s (并行)
- 向量生成: 1s
- 索引写入: 0.5s
- 发布: 0.2s
总计: ~4.5s
```

**优化措施**：

1. **Webhook 优化**：
   - 使用异步处理
   - 快速响应 202 Accepted
   - 后台处理实际索引

2. **Merkle 树优化**：
   - 缓存父节点哈希
   - 仅重算变更路径
   - 使用 Redis 缓存

3. **解析优化**：
   - Worker 池并行
   - LSP 连接复用
   - 结果流式聚合

4. **写入优化**：
   - 批量写入
   - 异步持久化
   - 写入缓冲

---

## 9. 可观测性与评估指标

### 9.1 核心指标

| 指标 | 定义 | 目标 | 告警阈值 | 监控工具 |
|------|------|------|----------|----------|
| `incremental_index_trigger_rate` | 增量索引触发次数 / push 次数 | > 90% | < 80% | Prometheus |
| `incremental_index_success_rate` | 增量索引成功次数 / 触发次数 | > 99% | < 95% | Prometheus |
| `incremental_index_duration_p95` | 增量索引构建延迟 p95 | < 目标 | > 目标 2x | Prometheus |
| `index_version_consistency_rate` | 版本绑定一致次数 / 总查询次数 | 100% | < 99.9% | Prometheus |
| `concurrent_read_consistency_rate` | 并发读取一致次数 / 并发读取总次数 | 100% | < 99.9% | Prometheus |
| `rollback_frequency` | 回退操作次数 / 月 | < 1 | > 5 | Prometheus |
| `index_freshness_seconds` | 索引新鲜度（距最新 commit） | < 60s | > 300s | Prometheus |
| `merkle_tree_hit_rate` | Merkle 树缓存命中率 | > 80% | < 60% | Redis |
| `snapshot_cleanup_lag` | 快照清理延迟 | < 1h | > 24h | Prometheus |

---

### 9.2 OpenTelemetry Trace

**Trace 结构**：

```
Span: IncrementalIndexing
  ├── Span: WebhookReceived
  │     ├── Attribute: repository_id
  │     ├── Attribute: source_revision
  │     └── Attribute: trigger_type
  ├── Span: ChangeDetection
  │     ├── Attribute: git_diff_duration_ms
  │     ├── Attribute: merkle_tree_duration_ms
  │     └── Attribute: changed_files_count
  ├── Span: IncrementalParsing
  │     ├── Attribute: parsed_files_count
  │     ├── Attribute: parsed_symbols_count
  │     └── Attribute: parsing_duration_ms
  ├── Span: IndexUpdate
  │     ├── Attribute: vector_update_duration_ms
  │     ├── Attribute: graph_update_duration_ms
  │     └── Attribute: fulltext_update_duration_ms
  └── Span: IndexPublish
        ├── Attribute: index_version
        ├── Attribute: publish_duration_ms
        └── Attribute: cache_invalidation_duration_ms
```

---

### 9.3 Prometheus Metrics

**计数器**：

```prometheus
# 增量索引触发次数
index_incremental_trigger_total{trigger_type, result}

# 增量索引成功次数
index_incremental_success_total{repository_size}

# 索引回退次数
index_rollback_total{reason}

# 并发读取次数
index_concurrent_read_total{consistency_result}
```

**直方图**：

```prometheus
# 增量索引延迟
index_incremental_duration_seconds{repository_size}

# Merkle 树对比延迟
merkle_tree_diff_duration_seconds{repository_size}

# 并发读取延迟
index_read_duration_seconds{snapshot_mode}
```

**仪表盘**：

```prometheus
# 当前活跃索引版本数量
index_version_active_count{repository_id}

# 快照引用计数
index_snapshot_reference_count{snapshot_id}

# 索引队列积压
index_queue_depth
```

---

### 9.4 审计日志

**日志内容**：

```json
{
  "event_type": "INDEX_UPDATED",
  "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
  "timestamp": "2026-10-03T10:25:00Z",
  "repository_id": "repo_abc123",
  "source_revision": "git:abc123def456",
  "index_version": "idx-20261003-001",
  "trigger_type": "WEBHOOK",
  "changed_files": 10,
  "added_symbols": 25,
  "deleted_symbols": 5,
  "duration_ms": 4500,
  "actor": {
    "type": "SYSTEM",
    "id": "indexer-worker-01"
  }
}
```

**回退审计**：

```json
{
  "event_type": "INDEX_ROLLBACK",
  "trace_id": "...",
  "timestamp": "2026-10-03T10:30:00Z",
  "repository_id": "repo_abc123",
  "from_version": "idx-20261003-002",
  "to_version": "idx-20261003-001",
  "reason": "Index quality degradation",
  "triggered_by": {
    "type": "USER",
    "id": "admin_user_123",
    "name": "John Doe"
  },
  "affected_tasks": ["task_001", "task_002"],
  "approval": {
    "approved_by": "admin_user_123",
    "approved_at": "2026-10-03T10:29:55Z"
  }
}
```

---

## 10. 验收标准

| 编号 | 验收标准 | 验证方法 | 预期结果 | 实际结果 |
|------|----------|----------|----------|----------|
| V1 | 增量索引仅重索引变更文件 | 测试：修改 1 个文件，验证索引文件数 | 重索引文件数 = 1 | 待测试 |
| V2 | 索引版本与 Git SHA 严格绑定 | 测试：同一 SHA 重复索引，验证版本号 | 版本号相同或拒绝 | 待测试 |
| V3 | 增量索引延迟符合目标 | 测试：SMALL 仓库变更，测量延迟 | < 5s | 待测试 |
| V4 | 支持索引回退到历史版本 | 测试：回退操作，验证数据一致性 | 回退后数据正确 | 待测试 |
| V5 | 并发读取不相互阻塞 | 测试：10 并发读取，测量延迟和一致性 | 延迟 < 1s，一致性 100% | 待测试 |
| V6 | 索引回退不中断运行任务 | 测试：任务运行中回退，验证任务继续 | 任务使用旧索引继续 | 待测试 |
| V7 | Webhook 签名验证生效 | 测试：伪造 Webhook，验证拒绝 | 返回 401 Unauthorized | 待测试 |
| V8 | 增量索引触发自动 | 测试：push 代码，验证索引自动触发 | 30s 内触发 | 待测试 |
| V9 | Merkle 树变更检测准确 | 测试：修改内容不变，验证不重索引 | 不触发增量 | 待测试 |
| V10 | 索引状态机转换正确 | 测试：模拟各状态转换，验证合法性 | 符合状态机定义 | 待测试 |
| V11 | 全量 vs 增量决策正确 | 测试：变更 > 30% 文件，验证触发全量 | 触发全量索引 | 待测试 |
| V12 | 快照生命周期管理正确 | 测试：快照无引用后自动清理 | 24h 内清理 | 待测试 |

---

## 11. 依赖与接口

### 11.1 上游依赖

| 依赖 | 接口 | 说明 |
|------|------|------|
| REQ-CTX-001 | FileNode, SymbolNode, RelationEdge, IndexMetadata Schema | 索引实体定义 |
| REQ-RT-001 | repository_id, source_revision, trace_id | 运行时实体坐标 |
| REQ-CTX-003 | MerkleTree, AST Parser, LSP Client | 增量解析基础 |
| REQ-SEC-002 | RBAC 权限 | 索引操作权限控制 |
| REQ-SEC-005 | 敏感路径黑名单 | 过滤敏感文件 |
| REQ-SEC-008 | 多租户隔离 | 索引数据隔离 |

---

### 11.2 下游接口

| 接口 | 消费者 | 说明 |
|------|--------|------|
| `IndexVersionMetadata` | REQ-CTX-004 | 检索服务消费索引 |
| `IndexVersionMetadata` | REQ-CTX-006 | Context Selector 使用索引 |
| `IndexState` | REQ-OBS-001 | 可观测性指标 |
| `IndexUpdatedEvent` | REQ-EVA-005 | 回归测试触发 |
| `TaskIndexLock` | Worker Runtime | 任务锁定索引版本 |
| `MVCCIndexReader` | Retrieval Service | 并发读取接口 |

---

### 11.3 事件接口

**IndexUpdatedEvent**：

```typescript
interface IndexUpdatedEvent {
  event_id: EntityId;
  event_type: 'INDEX_UPDATED';
  repository_id: RepositoryId;
  source_revision: RevisionRef;
  index_version: string;
  previous_version: string | null;
  changed_files_count: number;
  added_symbols_count: number;
  deleted_symbols_count: number;
  index_duration_ms: number;
  trace_id: TraceId;
  timestamp: Timestamp;
}
```

**IndexRollbackEvent**：

```typescript
interface IndexRollbackEvent {
  event_id: EntityId;
  event_type: 'INDEX_ROLLBACK';
  repository_id: RepositoryId;
  from_version: string;
  to_version: string;
  reason: string;
  triggered_by: ActorRef;
  affected_tasks: TaskId[];
  trace_id: TraceId;
  timestamp: Timestamp;
}
```

**IndexBuildFailedEvent**：

```typescript
interface IndexBuildFailedEvent {
  event_id: EntityId;
  event_type: 'INDEX_BUILD_FAILED';
  repository_id: RepositoryId;
  source_revision: RevisionRef;
  index_version: string;
  failure_reason: string;
  retry_count: number;
  trace_id: TraceId;
  timestamp: Timestamp;
}
```

---

## 12. 版本与演进

### 12.1 版本策略

| 阶段 | 功能 | 说明 |
|------|------|------|
| **MVP (v0.1)** | Merkle 树增量检测、版本绑定、基础回退 | 满足核心需求 |
| **Phase 2 (v1.0)** | 并发读取优化、MVCC 增强、快照预热 | 提升一致性保证 |
| **Phase 3 (v2.0)** | 分布式索引支持、多区域复制 | 支持大型仓库 |
| **Phase 4 (v3.0)** | 跨仓库索引一致性、Monorepo 支持 | 企业级场景 |

---

### 12.2 兼容性考虑

**向后兼容**：
1. 索引协议版本化（schema_version）
2. 新版本必须能读取旧版本索引
3. 支持多版本索引共存

**渐进迁移**：
1. 旧索引保留 90 天
2. 新旧索引并行服务
3. 灰度切换到新索引

**升级路径**：

```
v0.1 → v1.0 升级：
1. 部署新版本索引服务
2. 保留 v0.1 索引
3. 新任务使用 v1.0 索引
4. 旧任务继续使用 v0.1 索引
5. 90 天后归档 v0.1 索引
```

---

## 13. 决策记录

| 决策项 | 决策 | 依据 | 替代方案 |
|-------|------|------|----------|
| **变更检测算法** | Merkle 树 | Cursor 生产级实践，O(log N) 复杂度 | Git diff（复杂度 O(N)） |
| **版本绑定** | index_version ↔ source_revision 一对一 | GitHub Copilot 标准 | 松散绑定（风险高） |
| **并发控制** | MVCC 快照隔离 | 数据库成熟实践 | 读写锁（性能差） |
| **回退策略** | 原子更新指针，不删除旧版本 | 保证安全回退 | 直接覆盖（无法回退） |
| **触发机制** | Webhook 自动触发 | 自动化，零配置 | 手动触发（效率低） |
| **全量 vs 增量** | 变更 > 30% 触发全量 | 经验阈值 | 总是增量（可能低效） |

---

## 14. 参考资料

以下为公开来源，访问日期均为 2026-09-26 至 2026-10-03：

- **Cursor Secure Codebase Indexing**：[Blog](https://cursor.com/blog/secure-codebase-indexing)
- **GitHub Copilot Repository Indexing**：[Docs](https://docs.github.com/en/copilot/concepts/context/repository-indexing)
- **Sourcegraph SCIP**：[Blog](https://sourcegraph.com/blog/announcing-scip)
- **Qoder Hybrid Retrieval**：[Dev.to](https://dev.to/qoder/qoders-codebase-aware-code-retrieval-a-hybrid-approach-for-ai-coding-gpm)
- **通义灵码技术解析**：[阿里云开发者](https://developer.aliyun.com/article/1661439)
- **MVCC 并发控制**：PostgreSQL MVCC Documentation
- **Merkle 树算法**：[Wikipedia](https://en.wikipedia.org/wiki/Merkle_tree)

---

**文档创建时间**：2026-10-03  
**维护团队**：架构组

