# REQ-MEM-004 记忆生命周期详细设计

> 版本：v0.1-designed  
> 状态：详细设计已完成，待跨模块评审与冻结  
> 优先级：P1  
> 所属模块：记忆管理（MEM）  
> 设计日期：2026-10-05  
> 前置依赖：REQ-MEM-001 Memory Schema、REQ-SEC-008 多租户与数据治理  
> 后续依赖：REQ-CTX-006 Context Selector、REQ-EVA-001 Golden Dataset

---

## 1. 需求基本信息

| 属性 | 内容 |
|---|---|
| 编号 | REQ-MEM-004 |
| 名称 | 记忆生命周期 |
| 优先级 | P1 |
| 所属模块 | 记忆管理（MEM） |
| 原始位置 | `docs/design-specs/PENDING-REQUIREMENTS.md`，第 150-151 行 |
| 原始描述 | 衰减、过期、删除和数据驻留 |
| 原定目标 | 建立记忆的衰减模型、过期策略、删除机制和数据驻留规则 |
| 前置依赖 | MEM-001、SEC-008 |
| 设计状态 | v0.1-designed；不代表实现或验证完成 |

---

## 2. 目标、范围与边界

### 2.1 目标

建立统一、确定、可审计的记忆生命周期管理机制，确保：
1. **衰减管理**：基于时间、访问频率、置信度的多维度衰减评分
2. **过期策略**：支持确定性过期（expires_at）和条件过期（TTL、访问超时）
3. **删除机制**：软删除→归档→硬删除三阶段，支持 GDPR 删除权
4. **数据驻留**：按组织配置存储区域，支持数据导出和跨境传输限制
5. **清理触发**：定时清理、事件触发清理、手动清理三种模式

### 2.2 范围

**本需求包含**：
- 衰减评分算法（时间×访问频率×置信度×时效性）
- 过期策略（确定性 + 条件过期）
- 删除流程（软删除→归档→硬删除）
- 数据驻留合规（区域配置、跨境限制、GDPR 导出）
- 清理触发条件和执行策略
- 状态机定义和转换规则
- 权限模型和审计要求

**本需求不包含**：
- 具体的存储后端选型（PostgreSQL / MongoDB / Redis）
- 归档存储的具体实现
- 定时任务框架选型
- 通知渠道具体实现
- 记忆压缩算法（归属 REQ-CTX-008）

### 2.3 非目标

- MVP 不实现机器学习衰减模型（Phase 2）
- MVP 不实现跨组织记忆共享（Phase 2）
- MVP 不实现记忆版本历史（Phase 2）

---

## 3. 问题分析

当前 `PENDING-REQUIREMENTS.md` 中仅有"衰减、过期、删除和数据驻留"十字描述，存在以下系统性缺口：

### 3.1 原设计漏洞

| 维度 | 漏洞描述 | 影响 |
|------|----------|------|
| 衰减算法缺失 | 仅"衰减"二字，未定义衰减模型、触发条件、衰减速率 | 记忆不会自动衰减，占用存储但价值降低 |
| 过期策略模糊 | 未定义过期条件（时间/访问/存储压力）、过期后状态转换 | 过期记忆无法正确处理 |
| 删除语义不清 | 未区分软删除/硬删除、未定义删除后数据保留期 | GDPR 合规风险、数据残留 |
| 数据驻留缺失 | 未定义记忆的地理存储位置、跨境传输限制 | 合规风险（GDPR、数据主权） |
| 清理触发条件缺失 | 未定义何时触发清理（定时/事件/手动） | 存储成本不可控 |
| 与 MEM-001 断链 | MEM-001 定义了 decay_score 和 expires_at，但未定义使用方式 | Schema 与实现脱节 |

### 3.2 影响分析

**对用户价值的影响**：
- 存储成本无限增长
- 检索质量下降（低价值记忆干扰）
- 合规风险（GDPR 删除权、数据驻留）
- 用户无法控制数据生命周期

**对系统架构的影响**：
- 存储后端需要支持 TTL、清理任务、数据归档
- 上下文加载需要排除过期记忆
- 审计系统需要完整记录删除操作

---

## 4. 标杆依据与公开事实/推断

研究访问日期：2026-10-05。公开产品做法仅作为设计参考。

### 4.1 Zep/Graphiti — 时序知识图谱

**公开事实**：双时态数据模型，`valid_at`（事实成立时间）+ `invalid_at`（失效时间）+ `expired_at`（被废止时间）。检索三路并行：向量 + BM25 + 图遍历。

**生命周期设计**：
- **确定性失效**：`invalid_at` 时间戳精确控制事实有效期
- **时间衰减评分**：`decay_score` 基于事实年龄计算
- **清理策略**：软删除→归档→硬删除的完整链路
- **保留期配置**：按数据类型（USER/PROJECT/ORG）设置不同保留期

**设计推断**：确定性失效优于概率衰减，时序有效性窗口支持审计。

**借鉴点**：双时态模型、确定性失效、多级清理策略。

来源：[Zep: A Temporal Knowledge Graph Architecture for Agent Memory](https://arxiv.org/abs/2501.13956)，访问日期：2026-10-05

**事实/推断标注**：公开事实 + 设计推断

### 4.2 MemGPT/Letta — 分层记忆操作系统

**公开事实**：三层记忆层次：Core Memory（主上下文）→ Recall Store（外部召回）→ Archival Store（归档存储）。Agent 通过工具调用自管理层级提升。

**生命周期设计**：
- **层级淘汰**：Core → Recall → Archival 的单向流动
- **触发条件**：上下文窗口压力、存储成本阈值
- **无显式过期**：依赖层级淘汰而非时间过期

**设计推断**：分层存储支持冷热分离，层级淘汰适用于存储压力场景。

**借鉴点**：分层存储、层级淘汰、自主管理。

来源：[MemGPT: Towards LLMs as Operating Systems](https://arxiv.org/abs/2310.08560)，访问日期：2026-10-05

**事实/推断标注**：公开事实 + 设计推断

### 4.3 LangGraph — Checkpoint + Store 持久化

**公开事实**：两层持久化：Checkpointer（短时、线程作用域）→ Store（长时、跨线程）。命名空间模型：`("user_id", "memories")`。PostgresStore 支持 TTL 自动清理。

**生命周期设计**：
- **TTL 清理**：自动清理过期记忆
- **命名空间隔离**：按 user_id/project_id 分组
- **无显式衰减**：依赖 TTL 和手动删除

**设计推断**：TTL 清理是基础设施级解决方案，简单有效。

**借鉴点**：TTL 自动清理、命名空间隔离、多后端支持。

来源：[LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)，访问日期：2026-10-05

**事实/推断标注**：公开事实

### 4.4 调研结论

本项目 `REQ-MEM-004` 采用以下共同原则：

- **衰减策略**：Zep 的时间衰减评分 + 置信度加权
- **过期机制**：Zep 的确定性过期 + LangGraph 的 TTL
- **删除机制**：Zep 的三阶段删除（软删除→归档→硬删除）
- **数据驻留**：延续 REQ-SEC-008 的数据治理框架
- **清理触发**：定时 + 事件 + 手动三种模式

---

## 5. 核心设计

### 5.1 功能目标与价值

**功能目标**：
1. 衰减管理：多维度衰减评分
2. 过期策略：确定性 + 条件过期
3. 删除机制：三阶段删除
4. 数据驻留：区域配置 + GDPR 合规
5. 清理触发：灵活可控

**用户价值**：
- **用户**：掌控数据生命周期，行使 GDPR 删除权
- **组织**：控制存储成本，满足合规要求
- **Agent**：基于高质量记忆提升任务成功率
- **安全/合规**：完整审计轨迹，满足数据保护法规

### 5.2 目标用户与使用场景

| 目标用户 | 使用场景 |
|----------|----------|
| 终端用户 | 查看记忆保留状态；请求删除个人记忆；导出个人数据 |
| 组织管理员 | 配置组织级保留策略；管理数据驻留区域；审计清理操作 |
| Agent 开发者 | 监听记忆生命周期事件；触发条件清理 |
| 安全/合规团队 | 审计删除操作；验证 GDPR 合规；监控数据驻留 |

### 5.3 用户故事

**用户故事 1**：自动衰减低价值记忆
```
作为系统，我希望记忆根据访问频率和时间自动衰减评分，
以便低价值记忆在检索时权重降低，最终被清理。
```

**用户故事 2**：GDPR 删除权
```
作为终端用户，我希望能够请求删除我的所有个人记忆，
并且系统完全清除数据（包括归档），以便行使 GDPR 删除权。
```

**用户故事 3**：配置组织数据保留期
```
作为组织管理员，我希望能够配置组织级记忆保留期（如 2 年），
以便满足合规要求并控制存储成本。
```

### 5.4 输入与输出定义

**输入**：

| 输入类型 | 描述 | 来源 |
|----------|------|------|
| Memory 对象 | 待管理的记忆 | Agent/User |
| DecayPolicy | 衰减策略配置 | 组织/用户配置 |
| RetentionPolicy | 保留策略配置 | 组织/用户配置 |
| DeletionRequest | 删除请求 | 用户/系统 |
| CleanupTrigger | 清理触发事件 | 定时任务/事件 |

**输出**：

| 输出类型 | 描述 | 消费者 |
|----------|------|--------|
| LifecycleEvent | 生命周期状态变更事件 | 审计、Agent |
| DeletionConfirmation | 删除确认（含数据清除证明） | 用户、合规 |
| StorageMetrics | 存储使用指标 | 运维、监控 |
| RetentionReport | 保留期合规报告 | 合规团队 |

---

## 6. 处理逻辑与流程

### 6.1 衰减管理流程

```
步骤 1：衰减评估触发
  触发条件：
  - 定时触发（每日凌晨 2:00）
  - 记忆访问时触发
  - 存储压力超过阈值时触发
  
步骤 2：衰减评分计算
  输入：Memory.decay_score、访问时间、内容年龄
  算法：
  ① 时间衰减：decay_time_factor = 1 / (1 + days_since_update * decay_rate)
  ② 访问频率衰减：decay_access_factor = access_count < 3 ? 0.5 : 1.0
  ③ 置信度加权：confidence_weight = confidence.value
  
  新 decay_score = 旧 decay_score * 0.95 * decay_time_factor * 
                   decay_access_factor * confidence_weight
  
步骤 3：衰减状态判断
  - decay_score >= 0.5：ACTIVE（正常）
  - 0.2 <= decay_score < 0.5：STALE（低价值，待清理）
  - decay_score < 0.2：候选清理（进入清理队列）

步骤 4：衰减结果记录
  - 更新 Memory.decay_score
  - 更新 Memory.lifecycle.state（如有变更）
  - 生成 LifecycleEvent
```

### 6.2 过期管理流程

```
步骤 1：过期检测
  触发条件：
  - 定时任务每小时检查 expires_at
  - 记忆访问时检查 expires_at
  - expires_at <= 当前时间
  
步骤 2：过期状态变更
  变更规则：
  - lifecycle.state: ACTIVE → EXPIRED
  - 记忆从新检索中排除（软删除等效）
  - 生成 LifecycleEvent，记录过期原因
  
步骤 3：过期后保留
  - 按保留策略决定保留期：
    PRIVATE：30 天后硬删除
    SHARED：90 天后硬删除
    PUBLIC：180 天后硬删除
  - 保留 Provenance 记录用于审计
```

### 6.3 删除管理流程

```
步骤 1：删除请求接收
  请求来源：
  - 用户主动删除（memory_id 或 user_id 批量）
  - 组织策略触发（保留期到期）
  - 系统触发（GDPR 请求、存储压力）
  
步骤 2：权限校验
  - 验证请求者是否有 memory:delete 权限
  - 验证数据驻留是否允许删除（如有法律保留要求）
  
步骤 3：软删除执行
  执行操作：
  - lifecycle.state: ACTIVE/STALE/EXPIRED → DELETED
  - 设置 deleted_at、deleted_by
  - 清除敏感内容映射
  - 清除检索索引
  - 生成 LifecycleEvent
  
步骤 4：归档（可选）
  按组织策略决定是否归档：
  - 归档：内容移动到归档存储，保留元数据和 Provenance
  - 不归档：直接进入硬删除队列
  
步骤 5：硬删除执行（延迟执行）
  执行时机：
  - PRIVATE 记忆：软删除后 30 天
  - SHARED 记忆：软删除后 90 天
  - PUBLIC 记忆：软删除后 180 天
  
  执行操作：
  - 清除 content_text、summary、embedding
  - 保留 memory_id（防重用）、provenance（审计用）
  - 生成最终删除确认
  
步骤 6：GDPR 删除确认
  生成删除证明，包含：
  - 删除的记忆 ID 列表
  - 删除时间
  - 清除的数据类型
```

### 6.4 数据驻留管理流程

```
步骤 1：存储区域判断
  判断规则：
  - 按 organization.data_residency_region 配置
  - 按记忆类型决定存储区域：
    PRIVATE：用户配置区域
    SHARED：组织配置区域
    PUBLIC：默认区域
  
步骤 2：跨区域限制
  限制规则：
  - 敏感记忆（sensitivity=HIGH）不得跨境传输
  - 审计日志必须存储在数据主权区域
  - 临时缓存可以跨区域，但有 TTL 限制
  
步骤 3：导出管理
  导出规则（GDPR 数据可携带）：
  - 用户可导出其 PRIVATE 记忆
  - 导出格式：JSON/CSV
  - 导出内容：content_text、metadata、provenance
```

### 6.5 清理触发流程

```
步骤 1：触发条件判断
  触发类型：
  ① 定时清理：
     - 每日凌晨 2:00：清理 decay_score < 0.2 的候选记忆
     - 每周日凌晨：清理所有 EXPIRED 记忆（保留期到期）
  
  ② 事件触发：
     - 存储使用率 > 80%：紧急清理，优先清理 PUBLIC 记忆
     - 用户请求：立即清理指定记忆
  
  ③ 手动清理：
     - 组织管理员手动触发
     - 支持按 scope、age、decay_score 过滤
  
步骤 2：清理执行
  执行策略：
  - 批量处理，避免锁竞争
  - 生成清理报告
  - 记录清理操作的 audit_id
  
步骤 3：清理结果通知
  通知对象：
  - 清理发起者：清理结果
  - 受影响用户（如有）：记忆被清理通知（可选）
  - 合规团队：GDPR 删除确认（如适用）
```

---

## 7. 算法设计思路

### 7.1 衰减评分算法

```text
输入：Memory 对象、当前时间、组织衰减策略
输出：新 decay_score、衰减原因

算法：

1. 基础衰减计算：
   base_decay = days_since_last_update * decay_rate
   其中 decay_rate 由组织配置，默认 0.01/天

2. 访问频率因子：
   if access_count < 3:
       access_factor = 0.5  // 冷记忆加速衰减
   else if access_count < 10:
       access_factor = 0.8
   else:
       access_factor = 1.0

3. 置信度加权：
   confidence_weight = 1 - memory.confidence.value * 0.2
   高置信度记忆衰减较慢

4. 内容时效性：
   if memory.content_type == FACT and is_time_sensitive(content):
       time_factor = 0.5  // 事实类记忆加速衰减
   else:
       time_factor = 1.0

5. 新 decay_score 计算：
   new_decay_score = max(0.0, 
       old_decay_score - base_decay * access_factor * 
       confidence_weight * time_factor)

6. 衰减边界：
   min_decay_score = 0.05  // 防止完全衰减到 0
   new_decay_score = max(min_decay_score, new_decay_score)

7. 衰减原因记录：
   reason = {
       "type": "TIME_DECAY" | "LOW_ACCESS" | "LOW_CONFIDENCE" | 
               "TIME_SENSITIVE",
       "factors": {...}
   }
```

### 7.2 清理候选选择算法

```text
输入：清理策略、存储压力、候选记忆列表
输出：待清理记忆列表

算法：

1. 候选筛选（满足任一条件）：
   - decay_score < 0.2
   - lifecycle.state == EXPIRED 且保留期到期
   - memory_type == WORKING 且 task 已完成超过 7 天
   - 存储压力 > 80% 时：decay_score < 0.4

2. 清理优先级排序：
   priority = {
       memory_type: {
           WORKING: 1.0, TASK: 0.8, PROJECT: 0.6, ORGANIZATION: 0.4
       },
       decay_score: 1 - decay_score,
       age: days_since_created / 365,
       sensitivity: {LOW: 1.0, MEDIUM: 0.8, HIGH: 0.5}
   }
   
   final_priority = Σ weight_i * priority_i
   按 final_priority 降序清理

3. 清理数量限制：
   max_cleanup_per_batch = min(1000, total_candidates * 0.1)
   避免一次性大量清理影响性能

4. 排除规则：
   - 处于 PENDING_APPROVAL 状态的记忆不清理
   - 关联活跃任务（task.state != COMPLETED）的记忆不清理
   - 法律保留的记忆不清理
```

### 7.3 数据驻留合规算法

```text
输入：Memory 对象、请求者信息、导出类型
输出：合规决策

算法：

1. 存储区域判断：
   target_region = memory.organization.data_residency_region
   storage_region = get_storage_region(memory)

2. 跨境传输检查：
   if storage_region != target_region:
       if memory.sensitivity == HIGH:
           return DENY_STORAGE  // 敏感数据不得跨境
       elif has_cross_border_agreement(target_region, storage_region):
           return ALLOW_STORAGE
       else:
           return REQUIRE_APPROVAL

3. 删除合规检查（GDPR）：
   if request.type == GDPR_DELETE:
       # 检查法律保留要求
       if has_legal_retention_requirement(memory):
           return DENY_DELETE with reason
       
       # 检查是否在保留期内
       if memory.created_at > cutoff_date:
           return ALLOW_DELETE
       else:
           return REQUIRE_LEGAL_REVIEW

4. 导出合规检查：
   if request.type == EXPORT:
       if requestor != memory.owner:
           return DENY_EXPORT
       if memory.sensitivity == HIGH:
           return REQUIRE_REDACTION  // 脱敏后导出
       return ALLOW_EXPORT
```

---

## 8. 状态管理与数据流转

### 8.1 生命周期状态机

```
ACTIVE (正常状态)
  │
  ├─── [decay_score < 0.5] ──> STALE (低价值)
  │       │
  │       ├─── [再次访问] ──> ACTIVE (恢复)
  │       └─── [清理触发] ──> DELETED
  │
  ├─── [expires_at 到达] ──> EXPIRED (过期)
  │       │
  │       └─── [保留期到期] ──> DELETED
  │
  ├─── [用户/系统删除请求] ──> DELETED (软删除)
  │       │
  │       └─── [保留期到期] ──> HARD_DELETED (硬删除)
  │
  └─── [手动归档请求] ──> ARCHIVED (归档)
          │
          ├─── [手动恢复] ──> ACTIVE
          └─── [保留期到期] ──> HARD_DELETED
```

### 8.2 数据流转

```
用户输入 / Agent 提取
       │
       ▼
Memory 创建 (lifecycle.state = ACTIVE, decay_score = 1.0)
       │
       ▼
衰减循环（定时/访问触发）
       │
       ├─── decay_score >= 0.5 ──> 继续 ACTIVE
       │
       └─── decay_score < 0.5 ──> STALE
               │
               ├─── 再次访问 ──> 恢复 ACTIVE
               │
               └─── decay_score < 0.2 ──> 候选清理队列
                       │
                       ▼
               过期检测 / 清理触发
                       │
                       ├─── expires_at 到达 ──> EXPIRED
                       │
                       ├─── 保留期到期 ──> DELETED（软删除）
                       │
                       └─── 手动删除请求 ──> DELETED（软删除）
                               │
                               ▼
                       硬删除队列（延迟执行）
                               │
                               ▼
                       HARD_DELETED（物理清除）
```

---

## 9. 交互设计与人类在环

### 9.1 用户交互

| 操作 | 交互流程 | 说明 |
|------|----------|------|
| 查看记忆保留状态 | 用户请求 → 显示 decay_score、expires_at、状态 | 用户了解记忆健康度 |
| 请求删除记忆 | 用户请求 → 确认对话框 → 执行软删除 → 发送确认 | 支持批量删除 |
| 导出个人数据 | 用户请求 → 验证身份 → 生成导出包 → 下载 | GDPR 数据可携带 |
| 配置保留策略 | 管理员配置 → 组织级策略生效 | 仅管理员可配置 |
| 请求恢复记忆 | 用户请求（STALE 状态）→ 验证权限 → 恢复 ACTIVE | 仅 STALE 状态可恢复 |

### 9.2 人类在环

| 场景 | 人类介入点 | 介入方式 |
|------|-----------|----------|
| 敏感记忆删除 | GDPR 删除涉及法律保留要求 | 合规团队人工审核 |
| 批量清理确认 | 存储压力清理超过阈值 | 管理员确认 |
| 归档恢复 | 归档记忆恢复需要审查 | 管理员审批 |

---

## 10. 异常与失败处理

| 异常场景 | 检测条件 | 处理策略 | 降级方案 |
|----------|----------|----------|----------|
| 衰减计算超时 | 单条记忆衰减 > 100ms | 跳过该记忆，继续处理 | 记录错误，继续下一条 |
| 软删除失败 | 存储写入错误 | 重试 3 次，失败则标记 DELETED_FAILED | 告警 + 人工处理 |
| 硬删除失败 | 存储删除错误 | 保留在硬删除队列 | 重试 + 告警 |
| 归档存储不可用 | 无法写入归档 | 跳过归档，直接硬删除 | 告警 + 记录 |
| 清理任务中断 | 任务崩溃 | 幂等设计，支持断点续传 | 重启任务 |
| GDPR 删除冲突 | 法律保留要求 | 拒绝删除，返回原因 | 合规团队介入 |

---

## 11. 权限、安全与合规

### 11.1 权限模型

| 权限 | 主体 | 描述 |
|------|------|------|
| memory:lifecycle:read | Owner、SHARED 成员 | 查看衰减状态、过期时间 |
| memory:lifecycle:decay | System | 系统执行衰减评分更新 |
| memory:delete:soft | Owner、Admin、System | 软删除记忆 |
| memory:delete:hard | Admin、System | 硬删除记忆 |
| memory:restore | Owner、Admin | 恢复 STALE/ARCHIVED 记忆 |
| memory:export | Owner（仅 PRIVATE）、Admin | 导出个人记忆 |
| memory:retention:configure | Admin | 配置组织保留策略 |
| memory:gdpr:delete | Owner（个人数据） | GDPR 删除请求 |

### 11.2 安全约束

| 约束 | 实现方式 |
|------|----------|
| 删除不可逆性 | 硬删除需要双重确认，记录所有删除操作 |
| 审计完整性 | 所有生命周期操作写入不可变审计日志 |
| 数据隔离 | 删除时彻底清除内容，保留 ID 防重用 |
| 防止数据泄露 | 删除确认包含数据范围证明，不包含已删除内容 |

### 11.3 合规要求

| 要求 | 实现方式 |
|------|----------|
| GDPR 删除权 | 软删除后 30 天硬删除，支持删除证明 |
| GDPR 数据可携带 | 导出 API 支持 JSON/CSV 格式 |
| 数据驻留 | 按组织配置存储区域，敏感数据不跨境 |
| 审计保留 | 生命周期操作审计日志保留 7 年 |
| 法律保留 | 合规 flag 阻止删除，记录拒绝原因 |

---

## 12. 性能、成本、延迟考量

### 12.1 性能目标

| 操作 | 目标延迟 | 说明 |
|------|----------|------|
| 衰减评分更新（单条） | p99 < 50ms | 含状态变更判断 |
| 衰减评分更新（批量 100 条） | p99 < 2s | 批量处理 |
| 软删除执行 | p99 < 200ms | 含索引清理 |
| 硬删除执行 | p99 < 500ms | 含归档（可选） |
| 清理任务（1000 条） | p99 < 30s | 批量处理 |
| 存储区域验证 | p99 < 20ms | 缓存优先 |

### 12.2 成本考量

| 成本项 | 估算 | 优化策略 |
|--------|------|----------|
| 存储成本 | 活跃记忆 100GB/月 | 定期清理低价值记忆 |
| 清理任务计算 | 50 元/百万次 | 批量处理，减少任务数 |
| 归档存储 | 10 元/TB/月 | 压缩后归档，定期删除 |
| 审计日志 | 20GB/月 | 压缩 + 分级存储 |

---

## 13. 可观测性与评估指标

### 13.1 关键指标

| 指标 | 定义 | SLO | 告警阈值 |
|------|------|-----|----------|
| memory_decay_rate | 每日衰减评分下降平均值 | - | > 0.1/天 |
| memory_stale_count | 当前 STALE 状态记忆数 | < 10000 | > 50000 |
| memory_expired_count | 当前 EXPIRED 状态记忆数 | < 5000 | > 20000 |
| memory_deleted_count | 每日软删除记忆数 | - | > 10000/天 |
| memory_hard_deleted_count | 每日硬删除记忆数 | - | > 5000/天 |
| memory_gdpr_deletion_rate | GDPR 删除请求比例 | < 5% | > 10% |
| storage_cleanup_latency_p99 | 清理任务延迟 p99 | < 30s | > 60s |
| retention_compliance_rate | 保留期合规率 | > 99.9% | < 99% |

### 13.2 Trace 关联

| 事件 | 关联字段 |
|------|----------|
| memory_decay_updated | memory_id、old_decay_score、new_decay_score、decay_reason |
| memory_state_changed | memory_id、old_state、new_state、trigger |
| memory_soft_deleted | memory_id、deleted_by、retention_days |
| memory_hard_deleted | memory_id、hard_deleted_by、archived（boolean） |
| storage_cleanup_completed | batch_id、count、duration_ms、trigger_type |
| gdpr_deletion_requested | user_id、memory_ids、request_id |

---

## 14. 验收标准

| 编号 | 验收标准 | 验证方法 |
|------|----------|----------|
| AC-01 | 记忆根据衰减算法自动降低 decay_score | 单元测试：给定时间/访问频率，验证衰减计算 |
| AC-02 | decay_score < 0.2 时进入候选清理队列 | 集成测试：批量衰减后检查候选队列 |
| AC-03 | expires_at 到达后记忆状态变为 EXPIRED | 定时任务测试：时间推进验证状态变更 |
| AC-04 | 软删除后记忆从新检索中排除 | 检索测试：删除后查询验证 |
| AC-05 | 软删除后 30/90/180 天执行硬删除 | 延迟任务测试：时间推进验证硬删除 |
| AC-06 | GDPR 删除请求完全清除数据 | 合规测试：删除后验证无残留 |
| AC-07 | 敏感记忆不跨境存储 | 合规测试：跨区域写入验证拒绝 |
| AC-08 | 清理任务记录完整审计日志 | 审计测试：验证日志完整性 |
| AC-09 | 存储压力 > 80% 时自动触发紧急清理 | 压力测试：模拟存储压力验证清理 |
| AC-10 | STALE 记忆再次访问可恢复为 ACTIVE | 恢复测试：访问后验证状态变更 |
| AC-11 | 归档记忆可手动恢复 | 归档恢复测试：恢复后验证可用性 |
| AC-12 | 组织可配置保留策略并生效 | 配置测试：修改配置后验证行为 |
| AC-13 | p99 清理延迟 < 30s | 性能测试：1000 条记忆清理延迟 |
| AC-14 | 衰减状态变更生成 LifecycleEvent | 事件测试：验证事件格式和内容 |

---

## 15. 依赖与跨模块接口

### 15.1 前置依赖

| 依赖编号 | 依赖内容 | 接口要求 |
|----------|----------|----------|
| REQ-MEM-001 | Memory Schema | 复用 Memory、MemoryLifecycle、decay_score 字段 |
| REQ-SEC-002 | RBAC 授权 | 复用权限校验接口 |
| REQ-SEC-008 | 多租户与数据治理 | 复用 DataSensitivity、data_residency_region |

### 15.2 下游接口

| 下游 | 接口 | 描述 |
|------|------|------|
| 记忆存储 | update(Memory)、delete(memory_id) | 状态更新和删除 |
| 检索索引 | remove(memory_id) | 清除检索索引 |
| 归档存储 | archive(Memory) | 归档大型记忆 |
| 审计系统 | log(LifecycleEvent) | 写入审计日志 |
| 通知系统 | notify(User, Notification) | 发送删除确认等通知 |

---

## 16. MVP 范围与后续扩展

### 16.1 MVP 包含

- 衰减评分算法（时间×访问×置信度×时效性）
- 确定性过期（expires_at）+ TTL
- 三阶段删除（软删除→归档→硬删除）
- GDPR 删除权和导出
- 定时 + 事件 + 手动清理
- 数据驻留基础合规

### 16.2 Phase 2 扩展候选

| 扩展方向 | 触发条件 | 优先级 |
|----------|----------|--------|
| 机器学习衰减模型 | 积累足够反馈数据 | P2 |
| 记忆版本历史 | 用户需要查看变更历史 | P1 |
| 分层存储集成 | 上下文窗口压力增大 | P1 |
| 跨组织记忆共享 | 组织协作场景 | P2 |

---

## 17. 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1-designed | 2026-10-05 | 基于 Zep、MemGPT、LangGraph 等行业标杆完成详细设计；定义衰减算法、过期策略、三阶段删除、数据驻留、清理触发、状态机、验收标准；待跨模块评审与冻结 |
