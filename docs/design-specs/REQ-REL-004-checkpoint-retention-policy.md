# REQ-REL-004 Checkpoint 保存与保留策略详细设计

> 所属基线：`Failure Recovery Baseline v1-draft`
> 需求编号：`REQ-REL-004`
> 优先级：P0
> 设计版本：`v0.1-designed`
> 设计状态：详细设计已完成，待跨模块冻结
> 前置依赖：`REQ-RT-005`（Checkpoint Protocol）、`REQ-REL-001`（Failure Taxonomy）、`REQ-SEC-008`（多租户与数据治理）
> 下游依赖：`REQ-REL-005`（恢复决策）、`REQ-HAR-002`（Context Compaction）、`REQ-OBS-007`（审计留存和完整性）
> 设计范围：检查点保存时机决策矩阵、保留期计算模型、清理保护谓词、容量配额管理、数据治理合规、清理并发控制
> 不包含：检查点 Schema 定义（归属 REQ-RT-005）、恢复决策逻辑（归属 REQ-REL-005）、Context Compaction 算法（归属 REQ-HAR-002）

---

## 1. 需求定义

### 1.1 需求目标

建立检查点保存与保留的完整策略体系，使系统能够在：
- 明确每种失败场景应保存何种类型的检查点
- 平衡恢复能力、存储成本和数据治理合规
- 防止存储无序增长，支持多租户容量配额
- 满足法规要求的保留期，同时支持数据删除权利
- 确保清理操作的幂等性、双向合规指标和可审计性

### 1.2 设计原则

**核心原则（三条铁律）**：

1. **风险等级只能延长，不能缩短**
   - 事件的定级常在事后调整，若低风险已在短保留期后删除，取证链将永久断裂
   - 延长动作必须回溯应用到已落盘数据（通过更新 `expires_at` 实现，而非重跑写入）

2. **expires_at 必须在写入时计算并固化为独立字段**
   - 基准用 `event_time` 与 `ingested_at` 双字段（取较早者防时钟漂移）
   - 绝不在查询时动态计算，否则改策略等于全表重写

3. **策略变更不得追溯缩短**
   - 从 180 天改为 90 天必须走变更审批 + 明确迁移任务 + 通知义务人
   - 默认行为是"新数据按新策略，旧数据按旧策略"

### 1.3 保留期计算模型

```
保留期 = max(类别基线, 风险加权延长, 关联案件/法律保留, 合同与法规下限)
```

---

## 2. 检查点分类与保留基线

### 2.1 检查点分类

检查点按内容性质分为以下类别：

| 类别 | 内容 | 热存储基线 | 冷存储基线 | 风险加权延长 |
|------|------|-----------|-----------|-------------|
| **取证档** | principal/tool/决策结果/沙箱ID/升降级/密钥指纹 | 30d | 180d | CRITICAL/HIGH 事件关联记录自动延长至 ≥1 年，且进 WORM |
| **运营档** | 启动/退出码/资源峰值/命中率 | 30d | 90d | 不延长 |
| **内容档** | stdin/stdout/快照 | 7-14d | 仅 SEC-006 高危命中保留 180d | 其余到期物理删除，不因风险延长（含 PII，延长会与 GDPR 冲突） |
| **案卷档** | 被定级为安全事件的完整证据链 | — | 3 年（可延至 5 年） | 由案件生命周期驱动，不由事件等级驱动 |

**特殊覆盖**：
- **Legal Hold**：无限期，至 Hold 解除，压倒一切，包括租户删除

### 2.2 合规基线对照

| 法规/标准 | 保留要求 | 对本设计的影响 |
|-----------|---------|----------------|
| PCI DSS 10.5.1 | ≥12 个月，其中 ≥3 个月立即可取 | 取证档基线 ≥180d，热存储满足 3 个月要求 |
| 等保三级 | ≥6 个月 | 运营档热存储 30d + 冷存储 90d 总计 120d，满足要求 |
| GDPR Art 5(1)(e) | 存储限制原则 | 内容档到期即删，不因风险延长，避免 PII 长期留存 |

---

## 3. 检查点保存时机决策矩阵

### 3.1 决策矩阵

| 失败症状（来自 REL-001） | 检查点类型（来自 RT-005） | 保存决策 | 副作用处理 |
|------------------------|--------------------------|---------|-----------|
| TRANSIENT_CONNECTIVITY | RECOVERY | 保存 + 记录副作用状态 | 幂等查询确认结果 |
| DEPENDENCY_THROTTLED | RECOVERY | 保存 + 记录副作用状态 | 检查配额和速率限制 |
| EXECUTION_ABORTED | RUNNING | 保存 + 重放验证 | 核查未完成 Action |
| STATE_INTEGRITY_FAILED | RECOVERY | 保存 + 标记 INVALID | 进入隔离审查流程 |
| USER_OR_APPROVAL_STOP | PAUSE | 保存 + 等待用户 | 不记录为失败 |
| SAFETY_CONTROL_BLOCKED | APPROVAL | 保存 + 等待审批 | 记录阻断原因 |
| RESOURCE_LIMIT_REACHED | RUNNING | 保存 + 暂停消耗 | 停止预算消耗 |
| TASK_VALIDATION_FAILED | RUNNING | 保存 + 记录结果 | 进入诊断流程 |
| UNKNOWN_FAILURE | RECOVERY | 保存 + 升级 | 保全现场证据 |

### 3.2 保存前置条件

1. 获取 Workflow 最新事实序列
2. 确认事件序列无缺口
3. 确认状态投影不是不可恢复的 `BLOCKED`
4. 确认父子实体引用完整
5. 确认 Artifact/Evidence 可解析且版本一致
6. 确认 Workspace 和 `working_revision` 可验证
7. 执行敏感字段检测和脱敏
8. 计算并固化 `expires_at`
9. 生成规范化内容并计算哈希
10. 持久化检查点并验证哈希
11. 追加 `CheckpointCreated` 事件

---

## 4. 清理保护谓词

### 4.1 保护谓词定义

**保护谓词 = 引用 ∨ 关联 ∨ 时间地板 ∨ 计数地板（四者取或）**

```
protected iff any of:
  (a) referenced_by_open_case      -- 被未结案的安全事件/工单/DSAR 引用
  (b) under_legal_hold             -- 命中 Legal Hold（按 case_id 锁定）
  (c) age < floor_TTL              -- 时间地板：取证档 7d / 运营档 3d / 内容档 24h
  (d) rank ≤ floor_count           -- 计数地板：每 (tenant, category) 最近 N=100 条
  (e) in_cooling_off_period        -- 租户处于删除冷静期（SEC-009 挂钩）
```

### 4.2 保护谓词说明

| 谓词 | 作用 | 防护场景 |
|------|------|---------|
| **(a) referenced_by_open_case** | 保价值 | 正在调查的安全事件相关证据不被清理 |
| **(b) under_legal_hold** | 保价值 | Legal Hold 期间数据不可删除 |
| **(c) age < floor_TTL** | 保刚发生的事 | 防止低价值事件洪峰挤掉关键事件 |
| **(d) rank ≤ floor_count** | 保新租户/低流量租户 | 纯 TTL 方案的漏洞：新租户可能无历史可查 |
| **(e) in_cooling_off_period** | 保撤销能力 | SEC-009 冷静期内数据不可清理 |

### 4.3 为什么四条谓词都要

- **(a)(b)**：保护高价值数据
- **(c)**：防止刚发生的事被立刻扫走（这是计数方案的最大漏洞）
- **(d)**：保证新租户/低流量租户永远有东西可查（纯 TTL 方案的漏洞）
- **(e)**：保证与 SEC-009 不自相矛盾

---

## 5. 软删除与物理删除延迟

### 5.1 双阶段删除模型

```
到期检查 → 标记 EXPIRED → 48h 宽限期 → 物理删除
```

**流程说明**：
1. 到期检查通过时，先标记 `status = expired`
2. 48h 宽限期内可人工解封（unexpire）
3. 宽限期结束后执行物理删除
4. 这是"误删可恢复"的唯一廉价手段，成本近乎为零

### 5.2 解封操作

宽限期内可通过以下操作解封：
- 管理员手动解封
- 被未结案安全事件/工单引用时自动解封
- Legal Hold 解除后重新计算 `expires_at`

---

## 6. 删除批次清单与校验和

### 6.1 删除凭证结构

每次清理操作生成 `deleted_manifest`：

```text
DeletedManifest
- manifest_id: UUID
- tenant_id: EntityId
- category: CheckpointCategory
- batch_id: string
- record_count: integer
- time_range_start: Timestamp
- time_range_end: Timestamp
- created_at: Timestamp
- hash: string (SHA-256 of batch content)
- operator_id: EntityId
- reason: CleanupReason
```

### 6.2 凭证归档要求

- `deleted_manifest` 必须写入不可篡改日志
- 作为清理操作的凭证归档
- 没有此凭证，无法向审计证明"删的是该删的、没删不该删的"

---

## 7. 容量配额管理

### 7.1 三层配额结构

| 层级 | 配额定义 | 调整因素 |
|------|---------|---------|
| **组织级** | 总检查点存储上限 | 按套餐/合同定义 |
| **仓库级** | 单仓库检查点存储上限 | min(仓库代码量 × 系数, 上限) |
| **任务级** | 单任务检查点数量上限 | min(预估步骤数 × 单步大小, 上限) |

### 7.2 动态调整

- 仓库活跃度影响配额权重
- 任务紧急程度可临时借用配额
- 超出配额时触发告警和强制清理

---

## 8. 清理触发机制

### 8.1 混合触发机制

| 触发类型 | 触发条件 | 执行时机 |
|---------|---------|---------|
| **容量触发** | 达到配额的 80% | 立即触发 |
| **时间触发** | 每日低峰期（02:00-04:00 UTC） | 定时执行 |
| **启动触发** | 系统启动时 | 启动时执行 |
| **手动触发** | 管理员命令 | 按需执行 |

### 8.2 清理优先级

从低到高：
1. `ARCHIVED` 状态的压缩检查点
2. `ACTIVE` 状态但已过保留期的检查点
3. `ACTIVE` 状态且关联任务已完成超过 30 天的检查点
4. 关联任务已取消/失败的检查点
5. 超出组织/仓库配额时，按 LRU 排序删除

**保护规则**：
- 包含未完成副作用的检查点不得清理
- 包含待审批状态的检查点不得清理
- 最后 N 个检查点不得清理（N 可配置，默认按保护谓词 (d) = 100 条）

---

## 9. 清理并发控制

### 9.1 分片键控并发

```
分片键 = (tenant_id, category, day_bucket)
```

- 每个分片互不干扰，天然并行
- 避免全局锁导致的跨租户阻塞

### 9.2 执行模型

- 每分片一个清理任务（队列/Temporal workflow）
- Consumer group 消费模式
- 避免某个超大租户的清理任务阻塞其他租户

### 9.3 幂等删除

```sql
DELETE FROM checkpoints
WHERE expires_at <= now()
  AND status = 'active'
  AND id IN (SELECT id FROM checkpoints_batch WHERE ...)
```

使用条件删除，确保：
- 重复执行 = 删 0 行
- 绝不报错
- 绝不重删

### 9.4 锁机制（仅用于限流）

- 同分片内加短租约锁（TTL 5min）
- 包含 owner + epoch 标识
- 用于防止同一分片两个 worker 同时扫描
- **不用于保证 correctness**

### 9.5 退避与限流

| 机制 | 配置 |
|------|------|
| 退避策略 | 指数退避 + jitter |
| QPS 上限 | 每分片独立限制 |
| 全局限流 | 令牌桶（清理本身不能打爆存储/审计 API） |
| 断点续跑 | cursor 分页，worker 重启不重头扫描 |

---

## 10. 双向合规指标

### 10.1 必选指标

| 指标名称 | 定义 | 告警阈值 |
|---------|------|---------|
| `overdue_delete_count` | 到期未删数量 | > 0，立即告警 |
| `premature_delete_count` | 未到期被删数量 | 必须 = 0，硬告警 |
| `cleanup_lag_p99` | 清理延迟 P99 | > 阈值 |
| `cleanup_failure_rate` | 清理失败率 | > 1% |
| `batch_delete_count` | 每批次删除量 | 监控异常峰值 |

### 10.2 指标说明

- **overdue_delete_count**：到期未删 = 违反存储限制，GDPR 风险
- **premature_delete_count**：未到期被删 = 不可逆的取证/审计事故，严重性更高

---

## 11. 特殊场景处理

### 11.1 租户删除冷静期

租户删除冷静期内暂停该租户的 TTL 清理：
- 与 SEC-009 的"冷静期可撤销"直接挂钩
- 若冷静期内记录被正常 TTL 扫掉，撤销恢复会得到残缺数据

### 11.2 Legal Hold 与清理优先级

1. Hold 解除才重新进入 TTL 计算
2. Hold 期间的到期日需重算
3. 不能沿用旧的 `expires_at`

### 11.3 PII 与取证档冲突

**问题**：GDPR 存储限制要求"最短必要"，审计要求"长期留存"

**解法**：匿名化而非物理删除
- 删除 tenant_id 映射
- 保留事件结构与哈希
- 在 DPA 中写明

### 11.4 定期抽样验证

每月执行：
- 随机抽 N 个已 purge 的 tenant+category，确认物理不可恢复
- 随机抽 N 个未到期记录，确认仍在

没有这一条，整个清理系统不可证伪。

---

## 12. 状态机与生命周期

### 12.1 检查点生命周期状态

```
CREATED → ACTIVE → ARCHIVED → EXPIRED → DELETED
              ↓
           SUPERSEDED → ARCHIVED
              ↓
           INVALID → QUARANTINED → EXPIRED
```

| 状态 | 说明 |
|------|------|
| `CREATED` | 检查点刚创建，等待完整性校验 |
| `ACTIVE` | 完整有效，可用于恢复 |
| `ARCHIVED` | 已压缩为元数据，需要时可通过事件重建 |
| `SUPERSEDED` | 被新检查点替代，但仍可追溯 |
| `INVALID` | 校验失败，需要隔离审查 |
| `QUARANTINED` | 安全或合规原因隔离 |
| `EXPIRED` | 软删除状态，48h 宽限期 |
| `DELETED` | 已物理删除，保留凭证 |

### 12.2 状态转换规则

| 源状态 | 目标状态 | 触发条件 |
|--------|---------|---------|
| CREATED | ACTIVE | 完整性校验通过 |
| CREATED | INVALID | 校验失败 |
| ACTIVE | ARCHIVED | 保留期到期 |
| ACTIVE | SUPERSEDED | 被新检查点替代 |
| ACTIVE | EXPIRED | 保留期到期 + 进入软删除 |
| ARCHIVED | EXPIRED | 冷存储保留期到期 |
| SUPERSEDED | ARCHIVED | 定时压缩 |
| INVALID | QUARANTINED | 安全审查 |
| QUARANTINED | EXPIRED | 审查结束 |
| EXPIRED | ACTIVE | 人工解封（宽限期内） |
| EXPIRED | DELETED | 48h 宽限期结束 |

---

## 13. 数据治理合规

### 13.1 审计日志要求

- 保留期：至少 7 年
- 清理策略变更必须进入不可篡改日志
- 谁改了 expires_at 规则、何时生效、影响了多少存量数据，必须记录

### 13.2 用户数据删除请求

- DSAR（数据主体访问请求）响应期限：30 天
- 检查点删除必须满足数据删除权利
- 但 Legal Hold 期间的数据删除请求需暂缓

### 13.3 跨境数据传输

- 按数据主权要求分区存储
- 跨区域检查点转移需合规评估

---

## 14. 与其他需求的接口约束

### 14.1 REQ-RT-005（Checkpoint Protocol）

- 检查点 Schema 由 RT-005 定义
- 本设计补充 `expires_at` 字段和保留策略
- 检查点保存前置条件遵守 RT-005 规定

### 14.2 REQ-REL-001（Failure Taxonomy）

- 失败症状分类驱动保存决策
- 症状与保留期无直接关联（风险等级只延长不缩短）

### 14.3 REQ-SEC-008（多租户与数据治理）

- 租户隔离由 SEC-008 保证
- 数据治理规则与 SEC-008 保持一致

### 14.4 REQ-SEC-009（Kill Switch）

- 冷静期保护与 SEC-009 挂钩
- Kill Switch 期间的检查点保留不受 TTL 影响

### 14.5 REQ-HAR-002（Context Compaction）

- 检查点保留与 Context Compaction 协同
- 压缩操作需通知保留管理器更新引用计数

---

## 15. MVP 范围与 v1.0 演进

### 15.1 MVP 范围（必须实现）

| 能力 | 说明 |
|------|------|
| 类别分区 | 目录/key 前缀区分取证/运营/内容档 |
| per-tenant + per-region 分区 | 支撑租户删除、区域钉扎 |
| 对象锁定/WORM | 取证档必须不可篡改 |
| 生命周期策略 | 热→冷配置化，零代码 |
| expires_at 字段 + 索引 | 必须字段，查询时不再动态计算 |

### 15.2 MVP 不包含

| 能力 | 说明 |
|------|------|
| 冷存检索 SLA | 文档写明不承诺 |
| 独立冷存域 | v1.0 引入 |
| 内容档快照长期留存 | v1.0 仅高危命中 |

### 15.3 v1.0 演进

| 能力 | 说明 |
|------|------|
| 细化分层 | 热/温/冷三层细化 |
| 检索加速 | 冷存索引优化 |
| 独立冷存域 | 跨区域冷存 |
| 内容档高危留存 | 仅 SEC-006 高危命中 |

---

## 16. 验收标准

### 16.1 必选验收标准

| 编号 | 验收标准 | 验证方法 |
|-----|---------|---------|
| R-01 | 每种失败症状类型有明确的检查点保存决策规则 | 审查决策矩阵文档 |
| R-02 | 检查点保存前置条件校验完整 | 单元测试覆盖率 100% |
| R-03 | expires_at 在写入时计算并固化，不动态计算 | Schema 验证 + 时间推进测试 |
| R-04 | 风险等级只能延长保留期，不能缩短 | 变更测试 |
| R-05 | 策略变更不追溯缩短，默认新数据按新策略 | 变更测试 |
| R-06 | 保护谓词 (a)-(e) 全部实现 | 谓词覆盖测试 |
| R-07 | 软删除 + 48h 宽限期实现 | 时间推进测试 |
| R-08 | 删除前生成 deleted_manifest | 清理测试 |
| R-09 | 清理操作幂等，重复执行不报错 | 幂等测试 |
| R-10 | overdue_delete_count = 0，premature_delete_count = 0 | 指标验证 |
| R-11 | 分片键控并发，无全局锁 | 并发测试 |
| R-12 | Legal Hold 压倒一切清理 | 隔离测试 |
| R-13 | 租户删除冷静期暂停 TTL 清理 | 集成测试 |
| R-14 | 定期抽样验证机制定义 | 审查文档 |

### 16.2 目标指标

| 指标 | 目标值 | 说明 |
|------|-------|------|
| 检查点恢复成功率 | ≥ 99% | 含回退到备用点 |
| 检查点保存成功率 | ≥ 99.9% | 含容量不足场景 |
| 容量配额超标告警准确率 | ≥ 95% | 误报率 < 5% |
| 清理操作零失误率 | ≥ 99.99% | 含幂等保证 |
| 清理延迟 P99 | < 10s | 单批次 |

---

## 17. 行业标杆对照

### 17.1 公开事实来源

| 来源 | 相关实践 | 本设计对应 |
|------|---------|-----------|
| AWS S3 Object Lock | WORM + 生命周期策略 | 取证档 WORM + 生命周期配置 |
| Azure Immutable Blob Storage | Legal Hold + 时间锁定 | Legal Hold 机制 |
| Temporal Event History | 事件不可修改 + 分段 | 检查点不可篡改 + 类别分区 |
| LangGraph Checkpointer | 状态持久化 + prune | 状态机 + 清理保护谓词 |
| Claude Code Checkpointing | 100 检查点保护 + 30 天 | 计数地板 + 保留期 |
| Devin CLI | 会话历史 + /revert | 保留期 + 恢复能力 |
| Manus | 文件系统作为上下文 | 取证档持久化 |

### 17.2 合规依据

| 法规/标准 | 要求 | 本设计对应 |
|-----------|------|-----------|
| PCI DSS 10.5.1 | ≥12 个月（≥3 个月立即可取） | 取证档 180d+ 热存储 |
| 等保三级 | ≥6 个月 | 运营档 120d 总计 |
| GDPR Art 5(1)(e) | 存储限制原则 | 内容档到期即删 |
| SOC 2 | 变更可追溯 | deleted_manifest + 审计日志 |

---

## 18. 设计决策记录

```
需求编号：REQ-REL-004
功能点：Checkpoint 保存与保留策略
当前状态：详细设计已完成，待跨模块冻结
前置依赖：REQ-RT-005、REQ-REL-001、REQ-SEC-008
下游依赖：REQ-REL-005、REQ-HAR-002、REQ-OBS-007

候选方案：
  A. 按风险等级分档（已废弃）
  B. 按记录类别 + 合规基线 + 风险延长（采纳）

保留期模型：
  max(类别基线, 风险加权延长, 关联案件/法律保留, 合同与法规下限)
  风险等级只能延长，不能缩短

保护谓词：
  引用 ∨ 关联 ∨ 时间地板 ∨ 计数地板 ∨ 冷静期

清理并发：
  分片键控 + 幂等删除 + 限流锁

公开证据等级：A
推荐基线：方案 B
选择理由：符合行业最佳实践，满足合规要求，避免风险等级驱动不可逆操作

三条铁律：
  1. 风险等级只能延长，不能缩短
  2. expires_at 写入时固化
  3. 策略变更不得追溯缩短

验收指标：overdue_delete_count=0, premature_delete_count=0
目标版本：REQ-REL-004 v0.1-designed
```

---

## 19. 版本和变更记录

### 19.1 变更记录

| 版本 | 日期 | 变更 |
|------|------|------|
| `v0.1-designed` | 2026-09-24 | 基于行业标杆（Temporal/LangGraph/Claude Code/AWS S3）完成详细设计；采纳用户确认的保留期模型、保护谓词、软删除、清理并发控制方案 |

### 19.2 冻结条件

升级到 `v1.0-frozen` 前必须完成：

1. 与 `REQ-RT-005`、`REQ-REL-001` 的交叉一致性评审
2. 与 `REQ-SEC-008`、`REQ-SEC-009` 的数据治理协调评审
3. 与 `REQ-REL-005` 的恢复决策接口评审
4. 与 `REQ-HAR-002` 的 Context Compaction 协同评审
5. 双向合规指标测试设计
6. 清理并发控制故障注入测试
7. PII 与取证档冲突解决方案评审
8. 定期抽样验证机制确认

---

## 20. 参考资料

### 20.1 行业参考资料

- [Temporal Event History](https://docs.temporal.io/workflow-execution/event)，访问日期 2026-09-24
- [LangGraph Checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers)，访问日期 2026-09-24
- [Claude Code Checkpointing](https://code.claude.com/docs/en/checkpointing.md)，访问日期 2026-09-24
- [AWS S3 Object Lock](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html)，访问日期 2026-09-24
- [Azure Immutable Blob Storage](https://learn.microsoft.com/en-us/azure/storage/blobs/immutable-storage-overview)，访问日期 2026-09-24
- [PCI DSS 10.5.1](https://www.pcisecuritystandards.org/)，访问日期 2026-09-24

### 20.2 项目内部文档

- [REQ-RT-005 Checkpoint Protocol](./REQ-RT-005-checkpoint-protocol.md)
- [REQ-REL-001 Failure Taxonomy](./REQ-REL-001-failure-taxonomy.md)
- [REQ-SEC-008 多租户与数据治理](./REQ-SEC-008-multi-tenant-data-governance.md)
- [REQ-SEC-009 Kill Switch 与事故响应](./REQ-SEC-009-kill-switch-incident-response.md)
