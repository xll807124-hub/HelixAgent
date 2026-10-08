# REQ-CTX-006: Context Selector 与预算

> **需求编号**: REQ-CTX-006  
> **需求名称**: Context Selector 与预算  
> **优先级**: P1  
> **所属模块**: 上下文管理（CTX）  
> **状态**: v0.1-designed  
> **设计日期**: 2026-10-03  
> **前置依赖**: REQ-CTX-004（混合检索与排序）、REQ-RT-007（Idempotency Key）

---

## 一、需求目标

### 1.1 功能目标

实现基于 Token 预算的智能上下文选择机制，支持多维度优先级排序、可配置的多级裁剪策略，并提供可解释的上下文选择记录。

**核心交付**：
1. Token 预算分配算法（基于任务类型）
2. 多维度优先级计算（相关性、依赖、中心性、新鲜度）
3. 渐进式上下文暴露（L1/L2/L3 三层）
4. 三种裁剪策略（GREEDY/SELECTIVE/AGGRESSIVE）
5. 可解释性记录（SelectionReason）

### 1.2 用户价值

| 价值维度 | 具体收益 |
|----------|----------|
| 任务成功率 | 确保关键上下文被优先选中，减少因上下文不足导致的任务失败 |
| 成本效率 | 合理分配 Token 预算，避免浪费，Token 使用率目标 80%-95% |
| 可调试性 | 可追溯的上下文选择记录，便于优化策略 |
| 用户体验 | 透明的上下文管理，用户可理解和控制 |

### 1.3 行业对标

本设计参考以下行业标杆：

| 产品 | 核心架构 | 关键技术 | 可借鉴点 |
|------|----------|----------|----------|
| **Cursor** | 渐进式上下文暴露 | L1/L2/L3 三层模型、图中心性排序 | 三层暴露模型 |
| **Anthropic** | 块级嵌入 | Contextual Retrieval、层级摘要 | 上下文注入、摘要增强 |
| **通义灵码** | 任务驱动分配 | 任务类型差异化预算 | 任务类型分配比例 |
| **DeepSeek** | 自适应压缩 | 三阶段流水线、截断/降级 | 多级压缩策略 |
| **GitHub Copilot** | 分层上下文 | 任务复杂度评估 | 复杂度自适应 |

---

## 二、设计范围

### 2.1 包含内容

1. ✅ Token 预算计算和分配
2. ✅ 任务类型驱动的预算分配（6 种任务类型）
3. ✅ 多维度优先级计算
4. ✅ 贪心选择算法
5. ✅ 三种裁剪策略
6. ✅ 渐进式上下文暴露（L1/L2/L3）
7. ✅ 摘要降级
8. ✅ 可解释性记录
9. ✅ 权限过滤集成
10. ✅ 链路追踪和指标监控

### 2.2 不包含内容（后续阶段）

1. ❌ 学习型优先级权重（Phase 3）
2. ❌ 端到端反馈优化（Phase 3）
3. ❌ 多模态上下文（Phase 3）

---

## 三、目标用户与使用场景

### 3.1 目标用户

| 用户类型 | 使用场景 |
|----------|----------|
| **AI Agent（内部）** | Worker 执行任务时选择上下文 |
| **开发者** | 通过 API 查询上下文选择结果 |
| **平台运营** | 配置和调优上下文选择策略 |
| **安全审计** | 审查上下文选择的合规性 |

### 3.2 典型使用场景

| 场景 | 查询类型 | 上下文选择策略 |
|------|----------|-----------------|
| Bug 修复 | 定位错误代码 + 理解上下文 | 相关代码优先 + 依赖分析 |
| 功能开发 | 理解现有架构 + 添加新功能 | 结构理解优先 + 依赖图 |
| 代码审查 | 检查变更质量 | Diff 相关 + 测试覆盖 |
| 重构 | 理解影响范围 | 依赖链优先 + 影响分析 |

---

## 四、输入与输出定义

### 4.1 输入定义

```typescript
interface ContextSelectorInput {
  // 任务上下文
  task_context: {
    task_id: string;
    task_type: TaskType;
    description: string;
    base_revision: string;
  };
  
  // 检索结果（来自 REQ-CTX-004）
  retrieval_candidates: RetrievalCandidate[];
  
  // 可选：种子符号
  seed_symbols?: string[];
  
  // 预算配置
  budget_config: BudgetConfig;
  
  // 权限上下文
  permission_context: {
    user_id: string;
    organization_id: string;
  };
}

type TaskType = 
  | 'BUG_FIX'
  | 'FEATURE_DEVELOPMENT'
  | 'REFACTORING'
  | 'CODE_REVIEW'
  | 'UNIT_TEST'
  | 'DOCUMENTATION';
```

### 4.2 输出定义

```typescript
interface ContextSelectorOutput {
  selected_context: SelectedContext[];
  statistics: ContextStatistics;
  selection_reasons: SelectionReason[];
  warnings: SelectionWarning[];
  trace_id: string;
}
```

完整接口定义见附录。

---

## 五、处理逻辑与流程

### 5.1 总体流程

```
检索候选结果（REQ-CTX-004）
  ↓
步骤1：预处理（Token估算、权限过滤、去重）
  ↓
步骤2：意图分析（任务类型识别、复杂度评估）
  ↓
步骤3：预算分配（按任务类型计算各类预算）
  ↓
步骤4：优先级计算（多维度评分）
  ↓
步骤5：贪心选择（按预算约束选择）
  ↓
步骤6：裁剪（触发检查、执行策略）
  ↓
步骤7：后处理（暴露层级调整、统计生成）
  ↓
步骤8：输出（返回上下文、统计、理由）
```

---

## 六、算法设计分析

### 6.1 Token 预算分配算法

**默认分配比例**（FIXED 模式）：

| 任务类型 | 任务描述 | 核心代码 | 依赖代码 | 测试代码 | 文档 |
|----------|----------|----------|----------|----------|------|
| BUG_FIX | 10% | 50% | 20% | 15% | 5% |
| FEATURE_DEVELOPMENT | 8% | 45% | 25% | 15% | 7% |
| REFACTORING | 8% | 40% | 30% | 15% | 7% |
| CODE_REVIEW | 5% | 35% | 15% | 30% | 15% |
| UNIT_TEST | 5% | 30% | 20% | 40% | 5% |
| DOCUMENTATION | 10% | 25% | 15% | 10% | 40% |

### 6.2 多维度优先级计算

**评分公式**：

```
priority = w1×relevance + w2×dependency + w3×centrality + w4×freshness
```

**默认权重**：
- w1=0.4（相关性）
- w2=0.25（依赖）
- w3=0.25（中心性）
- w4=0.1（新鲜度）

**任务类型调整**：
- BUG_FIX: w1=0.5（相关性优先）
- REFACTORING: w2=0.35, w3=0.35（结构优先）

### 6.3 贪心选择算法

```python
for category in ['core_code', 'dependency_code', 'test_code', 'documentation']:
    category_budget = budgets[category]
    candidates = filter_by_category(all_candidates, category)
    sorted_candidates = sort_by_priority(candidates)
    
    for candidate in sorted_candidates:
        if remaining_budget[category] >= candidate.estimated_tokens:
            select(candidate)
            remaining_budget[category] -= candidate.estimated_tokens
```

### 6.4 裁剪策略

**三种模式**：

1. **GREEDY**：从低优先级开始移除
2. **SELECTIVE**（默认）：保留前 K 个，其余裁剪
3. **AGGRESSIVE**：截断 + 摘要降级

---

## 七、异常与失败处理

| 异常类型 | 检测条件 | 处理策略 |
|----------|----------|----------|
| 候选列表为空 | candidates.length == 0 | 返回空上下文 + 警告 |
| Token 估算失败 | 估算服务不可用 | 使用固定估算 |
| 预算超限严重 | used > budget × 1.2 | 强制 AGGRESSIVE 裁剪 |
| 权限服务超时 | 权限检查超时 | 使用缓存或 DENY |

---

## 八、性能、成本、延迟考量

### 8.1 延迟预算

| 阶段 | 预算 | 说明 |
|------|------|------|
| Token 估算 | 10ms | 缓存命中 < 1ms |
| 权限过滤 | 20ms | 批量检查 + 缓存 |
| 优先级计算 | 10ms | 图查询 + 评分 |
| 贪心选择 | 20ms | 排序 + 选择 |
| 裁剪执行 | 10ms | 条件判断 |
| **总计** | **78ms** | SLO p95 ≤ 100ms |

---

## 九、验收标准

### 9.1 功能验收

- [ ] 支持 Token 预算分配
- [ ] 支持任务类型驱动的分配
- [ ] 支持多维度优先级计算
- [ ] 支持贪心选择
- [ ] 支持三种裁剪策略
- [ ] 支持渐进式暴露
- [ ] 输出可解释性记录
- [ ] 权限过滤正确执行

### 9.2 性能验收

- [ ] p95 延迟 < 100ms
- [ ] 支持 100 QPS
- [ ] 内存使用 < 200MB

### 9.3 质量验收

- [ ] Token 使用率 80%-95%
- [ ] 覆盖率 > 85%
- [ ] 裁剪率 < 20%

---

## 十、依赖与接口

### 10.1 前置依赖

| 依赖编号 | 依赖内容 |
|----------|----------|
| REQ-CTX-004 | 混合检索与排序 |
| REQ-CTX-005 | 检索权限与敏感路径 |
| REQ-RT-007 | Idempotency Key |

### 10.2 下游依赖

| 被依赖编号 | 依赖内容 |
|------------|----------|
| REQ-CTX-008 | 上下文压缩与分层加载 |
| REQ-HAR-002 | Context Compaction |

---

## 十一、版本与演进计划

### 11.1 MVP 版本（Phase 1）

- 固定分配策略（FIXED）
- 基础优先级计算
- GREEDY 裁剪模式
- L1/L2/L3 渐进暴露

### 11.2 Phase 2 扩展

- 自适应分配策略（ADAPTIVE）
- SELECTIVE 裁剪模式
- 摘要降级

### 11.3 Phase 3 优化

- 学习型优先级权重
- 端到端反馈优化

---

## 十二、参考资料

### 12.1 行业标杆文档

1. **Cursor 渐进式上下文暴露**
   - 来源：项目文档 REQ-CTX-004 引用
   - 关键内容：L1/L2/L3 三层模型

2. **Anthropic Contextual Retrieval**
   - 来源：项目文档 REQ-CTX-004 引用
   - 关键内容：块级嵌入、层级摘要

3. **通义灵码任务驱动分配**
   - 来源：项目文档 REQ-CTX-004 引用
   - 关键内容：任务类型差异化预算

---

## 十三、变更记录

| 版本 | 日期 | 变更内容 | 作者 |
|------|------|----------|------|
| v0.1-designed | 2026-10-03 | 初始设计完成 | 架构团队 |

---

**文档结束**
