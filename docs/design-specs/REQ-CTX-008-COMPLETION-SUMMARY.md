# REQ-CTX-008 上下文压缩与分层加载 - 设计完成摘要

## 执行摘要

**时间**：2026-10-04  
**需求编号**：REQ-CTX-008  
**需求名称**：上下文压缩与分层加载  
**状态**：✅ v0.1-designed（设计完成，待跨模块评审与冻结）

---

## 一、完成内容

### 1.1 文档变更

| 文件 | 操作 | 说明 |
|------|------|------|
| `REQ-CTX-008-context-compression-tiered-loading.md` | **新建** | 完整的需求设计文档（16 个章节） |
| `PENDING-REQUIREMENTS.md` | **更新** | 待办清单状态更新、进度统计更新 |
| `04-context-and-code-indexing.md` | **更新** | 已完成专项设计列表更新 |

### 1.2 设计要点

#### 核心设计决策

| 维度 | 设计 | 对标 |
|------|------|------|
| **触发机制** | 三级阈值（70%/80%/95%）+ 双触发条件 | GitHub Copilot 80%、KIMI 双触发 |
| **压缩策略** | 分层压缩流水线（L0 清理 → L1 摘要 → L2 符号） | Claude/Dify 三层分治 |
| **任务感知** | 6 种任务类型的差异化优先级矩阵 | 通义灵码任务驱动分配 |
| **符号压缩** | L1/L2/L3 渐进式暴露模型 | Cursor 动态上下文发现 |
| **协同机制** | 与 REQ-HAR-002 的委托模式 | 职责分离、避免重复 |
| **快照管理** | 校验和 + 回溯查询 + 90 天 TTL | GitHub Copilot 检查点 + ISO 27001 |
| **降级策略** | 五级降级（正常→简单→截断→紧急→拒绝） | 优雅降级最佳实践 |

#### 关键算法

1. **三级阈值触发算法**：
   - Level 1 (70%)：静默通知
   - Level 2 (80%)：正常压缩
   - Level 3 (95%)：强制压缩

2. **任务类型优先级矩阵**：
   - BUG_FIX：错误上下文 35%、架构决策 20%
   - FEATURE_DEVELOPMENT：架构决策 35%、工具结果 20%
   - REFACTORING：架构决策 30%、工具结果 30%

3. **符号级压缩算法**：
   - L1: Compact Summary（~50 tokens/item）
   - L2: Timeline Context（~200 tokens/item）
   - L3: Full Code（~500-1000 tokens/item）

4. **快照校验和算法**：
   - SHA-256 校验和验证
   - 消息引用完整性检查
   - 抽样验证机制

#### 性能目标

| 指标 | 目标值 |
|------|--------|
| 压缩比 | ≥ 50% |
| 信息保留率 | ≥ 90% |
| p95 延迟（同步） | < 2s |
| p95 延迟（异步） | < 500ms |
| 快照创建成功率 | ≥ 99.9% |
| Token 节省 | 40-60% |

---

## 二、竞品研究总结

### 2.1 研究范围

成功联网搜索并分析了 **9 家大厂产品**的上下文压缩设计：

1. **OpenAI Codex** - compaction 块 + body_after_prefix 预算分离
2. **Anthropic Claude** - 三层分治（压缩/清理/记忆）
3. **Cursor** - 渐进式暴露 + 文件化存储（46.9% Token 减少）
4. **DeepSeek** - 溢出存储 + 保留尾
5. **KIMI / Moonshot** - 双触发条件（85% 比率 + 保留空间）
6. **GitHub Copilot** - 80% 阈值 + 检查点文件持久化
7. **通义灵码（阿里）** - 本地 RAG + 任务驱动分配
8. **Dify / LangGraph** - 分层压缩（3 对保留 → 20 条保留 → 摘要）
9. **豆包（字节）** - 三级阈值（L1/L2/L3）+ 前缀缓存感知

### 2.2 关键洞察

| 洞察 | 来源 | 应用 |
|------|------|------|
| 80%-90% 是最佳触发阈值 | GitHub Copilot、Claude、Dify | 采用 80% 作为压缩阈值 |
| 工具结果清理优先于摘要 | Claude、Dify | L0 清理层设计 |
| 保留尾策略必不可少 | DeepSeek、KIMI、Dify | 保留最近 5-10 对 |
| 文件化存储提升效率 | Cursor | 分层加载标记设计 |
| 任务类型影响压缩策略 | 通义灵码 | 任务类型优先级矩阵 |
| 双触发互补提升可靠性 | KIMI | 比率触发 + 保留空间触发 |

---

## 三、进度统计更新

### 3.1 模块进度

| 模块 | 更新前 | 更新后 | 变化 |
|------|--------|--------|------|
| **上下文（CTX）** | 7/9 (77.8%) | **8/9 (88.9%)** | +11.1% |
| **总进度** | 45/59 (76.3%) | **46/59 (78.0%)** | +1.7% |

### 3.2 CTX 模块完成情况

| 编号 | 需求 | 状态 |
|------|------|------|
| REQ-CTX-001 | 索引实体和关系 Schema | ✅ v0.1-designed |
| REQ-CTX-002 | 语言、仓库规模和基准集 | ✅ v0.1-designed |
| REQ-CTX-003 | AST/LSP/依赖解析 | ✅ v0.1-designed |
| REQ-CTX-004 | 混合检索与排序 | ✅ v0.1-designed |
| REQ-CTX-005 | 检索权限与敏感路径 | ✅ v1.0-designed |
| REQ-CTX-006 | Context Selector 与预算 | ✅ v0.1-designed |
| REQ-CTX-007 | 增量索引一致性 | ✅ v0.1-designed |
| REQ-CTX-008 | 上下文压缩与分层加载 | ✅ **v0.1-designed（本次）** |
| REQ-CTX-009 | 检索评测 | ⏳ 待设计 |

---

## 四、设计文档结构

### 4.1 章节概览

```
REQ-CTX-008-context-compression-tiered-loading.md (16 章节)

一、设计目标（核心定位、设计原则）
二、行业调研与可借鉴设计（9 家大厂产品）
三、核心实体 Schema（5 个接口定义）
四、压缩触发机制（三级阈值、双触发条件）
五、分层压缩策略（L0/L1/L2 流水线、任务优先级矩阵）
六、与 REQ-HAR-002 的协同机制（职责边界、协作接口）
七、符号级压缩算法（分层加载模型、重要性计算）
八、快照管理机制（创建验证、历史回溯）
九、异常与降级处理（五级降级、异常矩阵）
十、性能、成本、延迟考量（延迟预算、性能目标）
十一、可观测性设计（核心指标、告警规则）
十二、验收标准（功能、质量、性能、安全）
十三、依赖与接口（上游依赖、下游接口）
十四、版本与演进计划（v1.0/v1.1/v2.0）
十五、实施计划（4 个 Phase）
十六、决策记录（7 项关键决策）
```

### 4.2 核心接口

1. `CompressionConfig` - 压缩配置
2. `CompressionInput` - 压缩输入
3. `CompressionOutput` - 压缩输出
4. `LayerMarker` - 分层加载标记
5. `CompressionSnapshot` - 压缩快照

---

## 五、与其他模块的集成

### 5.1 前置依赖

| 依赖模块 | 集成点 | 说明 |
|----------|--------|------|
| REQ-CTX-006 | `BudgetConfig` | 复用预算分配逻辑 |
| REQ-HAR-002 | `HAR002Collaboration` | 协同压缩，避免重复 |
| REQ-RT-005 | `CheckpointStorage` | 快照持久化 |
| REQ-OBS-001 | `Span/Metric` | 链路追踪集成 |
| REQ-CTX-005 | `PermissionFilter` | 敏感信息过滤 |

### 5.2 下游影响

| 影响模块 | 影响描述 | 缓解措施 |
|----------|----------|----------|
| REQ-HAR-002 | 需要明确协作边界 | 已定义 `HAR002Collaboration` 接口 |
| REQ-CTX-009 | 压缩质量可作为评测对象 | 指标已定义 |
| REQ-MEM-001 | 可共享快照存储 | RT-005 作为共享层 |

---

## 六、下一步行动

### 6.1 立即行动

1. ✅ 文档已写入：`REQ-CTX-008-context-compression-tiered-loading.md`
2. ✅ 待办清单已更新：`PENDING-REQUIREMENTS.md`
3. ✅ 主文档已更新：`04-context-and-code-indexing.md`
4. ✅ 进度统计已更新：CTX 8/9 (88.9%)，总进度 46/59 (78.0%)

### 6.2 后续待办

- [ ] 跨模块评审：与 HAR-002、RT-005、OBS-001 团队评审协作接口
- [ ] 原型验证：实现 MVP 版本，验证压缩比和信息保留率
- [ ] 性能测试：验证 p95 延迟 < 2s（同步）/ < 500ms（异步）
- [ ] 安全评审：评审快照权限边界和审计日志设计

### 6.3 下一项待办

**`REQ-CTX-009` 检索评测**（CTX 模块最后一项待办）

---

## 七、参考资料

所有参考资料均已在文档中标注来源链接和访问日期（2026-10-04）：

- OpenAI Codex Agent Loop
- Anthropic Claude Compaction Docs
- Cursor Dynamic Context Discovery
- DeepSeek Harness Compaction
- KIMI CLI Context Compaction
- GitHub Copilot Context Management
- 通义灵码架构设计
- Dify Context-aware Compaction
- Doubao-TUI Configuration

---

**完成时间**：2026-10-04  
**设计团队**：架构组  
**状态**：✅ 设计完成，已写入文档，待办已更新，进度已同步
