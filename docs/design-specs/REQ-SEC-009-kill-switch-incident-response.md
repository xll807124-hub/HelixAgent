# REQ-SEC-009：Kill Switch 与事故响应

> 需求编号：`REQ-SEC-009`  
> 优先级：P0  
> 所属模块：安全（SEC）  
> 设计版本：`v0.1-designed`  
> 状态：详细设计已完成，待跨模块评审与冻结；未实现、未验证  
> 前置依赖：`REQ-RT-002`（状态机）、`REQ-SEC-003`（Policy Gateway）  
> 协同依赖：`REQ-SEC-005`（凭据代理）、`REQ-RT-005`（Checkpoint）、`REQ-RT-007`（幂等键）、`REQ-OBS-005`（告警联动）、`REQ-REL-007`（补偿工作流）  
> 设计日期：2026-09-23  
> 特殊说明：本次设计采纳用户确认的 7 项深度优化方案（Q1-7），整合自 Gloo Forge、AI IR Overlay、Agent Patterns、Sanctum、NIST SP 800-61r3、Microsoft Entra 紧急访问账户最佳实践等公开标杆及阿里 1-5-10 框架。

---

## 1. 需求基本信息

| 属性 | 内容 |
|------|------|
| 编号 | `REQ-SEC-009` |
| 名称 | Kill Switch 与事故响应 |
| 优先级 | P0 |
| 所属模块 | 安全（SEC） |
| 原始位置 | `docs/design-specs/PENDING-REQUIREMENTS.md`，安全（SEC）待办表 |
| 原始描述 | Kill Switch 与事故响应；停止、凭据撤销、现场保存和恢复流程 |
| 设计状态 | `v0.1-designed`；不表示实现、验证或冻结 |

---

## 2. 核心设计理念

### 2.1 Kill Switch 不是单一按钮，是一套状态机 + 传播机制 + 授权契约

> **本设计的根本性约束**：Kill Switch 不是单一"开关"实体，而是一套由三部分组成的系统：
> 1. **状态机**（Kill Switch State Machine）：宣告"当前是什么模式"
> 2. **传播机制**（Enforcement Mesh）：将模式状态同步到所有执行点
> 3. **授权契约**（Authorization Contract）：定义各组件在特定模式下的行为边界

Kill Switch State Machine 发布"当前是什么模式"，Policy Gateway（`REQ-SEC-003`）负责具体的阻断策略裁决。两者耦合过紧会导致"想封一个连接器却要动全局开关"。本设计明确规定：
- **Kill Switch**：全局状态宣告者，发布"现在是什么模式"
- **Policy Gateway**：PEP（Policy Enforcement Point），执行具体阻断策略
- 两者通过标准模式枚举（`M0` 至 `M5`）通信，不直接耦合

### 2.2 Kill Switch 的定位

| 职责 | 非职责 |
|------|-------|
| 止血（遏制威胁扩散） | 治病（根因修复） |
| 决策下发（发布模式） | 策略评估（Policy Gateway 负责） |
| 凭据撤销编排（触发 SEC-005） | 凭据撤销执行（SEC-005 负责） |
| 证据快照（保存现场） | 根因分析（事后） |
| 分阶段恢复编排（执行 M5 协议） | 修复方案制定（人工负责） |

---

## 3. Kill Switch 状态机

### 3.1 模式枚举（六模式体系）

> 参照 AI IR Overlay 六模式，结合 NIST SP 800-61r3 遏制阶段和 Microsoft AI 事件响应分阶段遏制设计。

| 模式 | 名称 | 语义 | 自动触发？ | 自动解除？ | 人工确认 |
|------|------|------|-----------|-----------|---------|
| `M0` | OBSERVE | 正常运行，收集指标 | 不适用 | 不适用 | 不适用 |
| `M1` | READ_ONLY | 禁止写操作、网络外发和凭据使用；只允许幂等查询和只读操作 | ✅（单信号即可） | ✅（5 分钟，观察期 24h） | 事后通知 |
| `M2` | APPROVALS_REQUIRED | 所有写操作、高风险操作需双人审批 | ✅（需两个独立信号） | ✅（15 分钟，观察期 24h） | 事后 1h 内复核 |
| `M3` | TOOL_TIERING | 指定工具/连接器禁用；其余功能受限 | ⚠️（需爆破半径 < 5% 租户） | ✅（30 分钟，观察期 24h） | 事前或事中确认 |
| `M4` | FULL_DISABLE | 指定组织/项目/租户完全停止新 Action | ❌ | ❌ | 必须（双人审批） |
| `M5` | CONTROLLED_REENABLE | 分阶段恢复（演练阶段，非运营模式） | ❌ | ❌ | CISO/IC + 副手 Quorum |

### 3.2 模式切换规则

```
允许的切换路径（严格有序）：
M0 → M1 → M2 → M3 → M4
 ↑_______↓_______↓_____↓（逐级降低，不允许跳跃）
M5（恢复阶段专用）只能从 M4/M3/M2/M1 进入
```

**铁律**：模式不允许跳跃下降（如 M4 直接跳到 M0）。每次降级必须经过中间档位。

### 3.3 Kill Switch 状态存储

| 属性 | 要求 |
|------|------|
| 存储位置 | 跨 AZ 高可用存储（如 etcd、DynamoDB Global Table） |
| 客户端可直读 | 是（Agent、Tool Gateway、Policy Gateway 均需直读） |
| 防篡改 | WORM（一次写入多次读取）或区块链锚定 |
| TTL | 全局缓存 TTL ≤ 30s；服务故障时缓存过期即 fail-closed |
| 状态广播 | 激活后通过事件总线主动广播，各下游服务需 ack |

---

## 4. 三态 Fail-Closed 体系

> 参照 Gloo Forge dispatch 阻断原则和 Microsoft 零信任默认拒绝设计。避免"平台完全停止"成为 DoS 攻击向量。

### 4.1 三态定义

| 状态 | 触发条件 | 新任务创建 | 运行中任务 | 只读/幂等 Action |
|------|---------|-----------|-----------|----------------|
| **正常态（NORMAL）** | Kill Switch 服务正常，无活跃事件 | ✅ 放行 | ✅ 正常执行 | ✅ 放行 |
| **降级态（DEGRADED）** | Kill Switch 服务不可达，但无活跃事件 | ❌ 拒绝（fail-closed） | ✅ 允许用已持有短期令牌跑完，禁止续期/刷新 | ⚠️ 可配置放行 |
| **封锁态（LOCKED）** | Kill Switch 明确处于 M1-M4 | ❌ 拒绝 | ⚠️ 按模式决定终止或观察 | ⚠️ 按模式决定 |

### 4.2 降级态详细行为

**"降级态"的关键约束**：

1. **缓存策略**：本地缓存"最后已知良好状态"，TTL ≤ 30s。超时即视为不可信，回落 fail-closed。**禁止"缓存永久有效"，那是 fail-open 的伪装**。

2. **令牌管理**：
   - 已签发的短期令牌（TTL ≤ 15min）允许自然续用至到期
   - **不**等于"鉴权服务不可用时放宽权限"
   - 禁止令牌续期/刷新操作

3. **只读 Action 放行**：幂等查询（GET/LIST）可配置放行，但必须在 Policy Gateway 侧显式声明，不做隐式信任。

4. **服务恢复**：Kill Switch 服务恢复后，自动从降级态切回正常态，无需人工干预。

### 4.3 封锁态按模式行为

| 模式 | 运行中任务行为 | 禁止的 Action 类型 |
|------|-------------|------------------|
| M1 | 允许跑完当前 Action，禁止新写操作 | WRITE、NETWORK、CREDENTIAL |
| M2 | 暂停等待审批，新 Action 需双人审批 | 同上 + 全部写操作需双人 |
| M3 | 指定工具/连接器关联的任务暂停，其余正常 | 指定工具的所有调用 |
| M4 | 所有任务暂停，保留证据快照 | 所有 Action |

---

## 5. 分层粒度体系（七级）

> 参照 Gloo Forge 三层粒度和 Agent Patterns 的集中 Policy Layer 设计。分级粒度越小，影响范围越精确，误触成本越低。

| 粒度层级 | 范围 | 触发权限 | 恢复权限 | 典型使用场景 |
|---------|------|---------|---------|------------|
| `ACTION` | 单个具体 Action | 认证用户 | 认证用户 | 单次异常工具调用 |
| `TOOL` | 特定工具类型（所有对该工具的调用） | 认证用户 | 认证用户 | 某个 MCP 连接器异常 |
| `CONNECTOR` | 特定连接器（所有通过该连接器的调用） | 项目管理员 | 项目管理员 | 某外部服务异常 |
| `TASK` | 单个任务实例 | 任务创建者、项目成员、安全团队 | 同触发者 | 单个任务失控 |
| `WORKFLOW` | 单个工作流实例 | 项目管理员 | 项目管理员 | 特定工作流异常 |
| `PROJECT` | 单个项目（所有该项目的任务） | 项目管理员、安全团队 | 安全团队 Lead | 项目级安全事件 |
| `ORG` | 单个组织（所有该组织的任务） | 安全团队 | 安全团队 Lead | 组织级数据泄露 |
| `GLOBAL` | 平台所有任务 | CISO / IC | CISO / IC | 平台级安全危机 |

**设计约束**：
- 分级 Kill Switch 优先于全局 Kill Switch。per-connector / per-tenant / per-action 三级先落地，全局开关作为最后手段。
- 全局开关一旦误触成本极高，使用频率应趋近于零。

---

## 6. 传播机制（Enforcement Mesh）

### 6.1 Kill Check 执行点

Kill Switch 状态在以下执行点强制检查：

```
User Request
    ↓
[Gate 0: Identity & Auth] → REQ-SEC-002
    ↓
[Gate 1: Kill Check] ← Kill Switch 状态强制检查
    ↓
[Gate 2: Policy Gateway] → REQ-SEC-003（Policy Decision）
    ↓
[Gate 3: Policy Enforcement] → PEP 执行裁决
    ↓
[Tool Gateway: 工具执行] → SEC-004 Sandbox
```

**Gate 1（Kill Check）的职责**：
- 读取 Kill Switch 状态（来自缓存或直读）
- 返回 BLOCK 或 ALLOW
- **不**执行 Policy 裁决（那是 Gate 2 的职责）
- Kill check 必须为 O(1) 复杂度，p99 ≤ 5ms

### 6.2 缓存与同步策略

| 组件 | 缓存 TTL | 同步机制 | 直读条件 |
|------|---------|---------|---------|
| Agent Runtime | ≤ 2s | 事件总线推送 + ack | 缓存 miss 或 TTL 过期 |
| Tool Gateway | ≤ 2s | 事件总线推送 + ack | 同上 |
| Policy Gateway | ≤ 2s | 事件总线推送 + ack | 同上 |
| 客户端（CLI/SDK） | ≤ 30s | 轮询 + WebSocket | 状态不一致时 |

**状态广播协议**：
- Kill Switch 激活后，通过事件总线（Event Bus）主动广播到所有服务
- 各下游服务必须 ack（确认收到）
- UI 显示"已生效 X/Y 服务"，让操作者判断是"没下发"还是"下发未生效"

### 6.3 Kill Check 路由算法

```
Input: Action(action_type, target, actor, tenant_id, task_id, tool_name, connector_id)
Output: ALLOW | BLOCK(mode, reason, blast_radius_preview)

1. 读取 global_kill_mode:
   if mode == M4 or M5: return BLOCK(M4, "global_kill_active", full_platform_blast_radius)
2. 读取 org_kill_mode[actor.tenant_id]:
   if mode >= M4: return BLOCK(M4, "org_kill_active", org_blast_radius)
3. 读取 project_kill_mode[actor.tenant_id][target.project_id]:
   if mode >= M4: return BLOCK(M4, "project_kill_active", project_blast_radius)
4. 读取 workflow_kill[workflow_id]:
   if workflow_id in kill_set: return BLOCK(M4, "workflow_kill_active", workflow_blast_radius)
5. 读取 task_kill[task_id]:
   if task_id in kill_set: return BLOCK(M4, "task_kill_active", task_blast_radius)
6. 读取 connector_kill[connector_id]:
   if connector_id in kill_set: return BLOCK(M3, "connector_disabled", connector_blast_radius)
7. 读取 tool_kill[tool_name]:
   if tool_name in kill_set: return BLOCK(M3, "tool_disabled", tool_blast_radius)
8. 读取 action_kill[action_id]:
   if action_id in kill_set: return BLOCK(M4, "action_kill_active", minimal_blast_radius)
9. 读取 mode-specific rules:
   if mode == M1:
     if action_type in WRITE | NETWORK | CREDENTIAL:
       return BLOCK(M1, "read_only_mode", write_action_blast_radius)
   if mode == M2:
     if action_type in WRITE | NETWORK | CREDENTIAL:
       return REQUIRE_APPROVAL  # 由 Policy Gateway 处理双人审批
10. return ALLOW
```

---

## 7. 自动化触发与三维判定矩阵

### 7.1 三维判定矩阵

> 自动化触发不是静态规则映射，而是三维判定：**严重度 × 置信度 × 爆破半径**。参照 NIST SP 800-61r3 事件分类和 Microsoft AI 事件响应设计。

| 维度 | 含义 | 取值范围 |
|------|------|---------|
| **严重度**（Severity） | 事件对业务的影响程度 | LOW / MEDIUM / HIGH / CRITICAL |
| **置信度**（Confidence） | 检测系统的判断确定性 | LOW / MEDIUM / HIGH |
| **爆破半径**（Blast Radius） | 预计影响的范围 | MINIMAL / LIMITED / SIGNIFICANT / MASSIVE |

**三维矩阵到模式的映射**：

| 严重度 \ 置信度 \ 爆破半径 | LOW 置信度 | MEDIUM 置信度 | HIGH 置信度 |
|--------------------------|-----------|--------------|------------|
| **LOW / MINIMAL** | M0 | M1（5min） | M1（5min） |
| **LOW / LIMITED** | M1（5min） | M1（5min） | M2（15min） |
| **MEDIUM / MINIMAL** | M1（5min） | M2（15min） | M2（15min） |
| **MEDIUM / LIMITED** | M2（15min） | M2（15min） | M3（30min） |
| **HIGH / SIGNIFICANT** | M3（30min） | M3（30min） | ⚠️ M4（人工） |
| **CRITICAL / MASSIVE** | ⚠️ M4（人工） | ⚠️ M4（人工） | ⚠️ M4（人工双人） |

### 7.2 自动触发的三条铁律

**铁律 1：爆破半径上限**
自动触发必须有爆破半径上限：
- 单次最多影响 ≤5% 租户 或 ≤1 个连接器
- 超限即降级为"高优告警 + 人工决策"
- 这是防止误触雪崩的唯一闸门

**铁律 2：自动解除分档**
30 分钟是硬天花板而非默认值：
- M1 自动解除：5 分钟（限流类天然短生命周期）
- M2 自动解除：15 分钟
- M3 自动解除：30 分钟
- M4/M5：永不自动解除
- 每次自动解除都必须生成"是否复发"的回检
- 若同一信号在窗口内复发 N 次（防抖阈值可配置），则锁定为人工模式并升级告警

**铁律 3：观察期**
自动解除 ≠ 风险消除：
- 解除后进入**观察期**（建议 24h）
- 观察期内同一信号再次命中则直接升级一级
- 避免"振荡式开合"（Kill Switch 开开关关）

### 7.3 凭据泄露的特殊处理

> **关键约束**：凭据泄露（如"密钥读取"）的正确响应归属 SEC-005 / CB4A 的凭据吊销流程，Kill Switch 只做**上层编排**，不直接绑定具体事件类型。

- 检测到凭据泄露信号 → 触发 SEC-005 凭据撤销流程
- 同时 Kill Switch 发布 M3/M4 模式（限制新 Action 使用已泄露凭据的范围）
- Kill Switch 不执行具体撤销操作，由 SEC-005 负责

---

## 8. TTA（Time-To-Activate）指标体系

> 参照阿里 1-5-10 框架（1 分钟发现 / 5 分钟定位 / 10 分钟恢复）和 Microsoft 三阶段遏制设计。单一 TTA 指标不可验证且容易误导。

### 8.1 分层指标定义

| 层级 | 指标名称 | 定义 | 目标 | 说明 |
|------|---------|------|------|------|
| **检测** | MTTD（Mean Time To Detect） | 异常发生 → 告警触发 | ≤ 60s | 靠指标阈值 + 分类器置信度漂移 + 用户举报三路并接 |
| **决策** | MTTA（Mean Time To Act） | 告警触发 → 处置决策 | ≤ 5min（人工）/ ≤ 10s（自动） | 自动仅限 M1-M2 且有爆破半径上限 |
| **传播** | MTTC-p99（Mean Time To Contain p99） | 决策确认 → 全平台 p99 生效 | ≤ 30s | 这是 Kill Switch 自身的工程 SLO，最该盯的一项 |
| **遏制** | MTTC-Actual（实际遏制时间） | 决策确认 → 威胁停止扩散 | ≤ 10min | 这才是用户期望的 TTA，应改名为 MTTC |
| **恢复** | M5-RTO | M5 执行 → 业务恢复正常 | ≤ 30min（标准层） | 与 RTO 对齐，需演练验证 |

### 8.2 按模式分档统计

TTA 必须按模式分档统计，单一数字会掩盖长尾：

| 模式 | 关键 TTA 指标 | 目标 | 考核点 |
|------|-------------|------|--------|
| M1 | 决策到生效 | ≤ 30s | 传播机制效率 |
| M2 | 决策到生效 + 第一个双人审批 | ≤ 5min | 审批流程效率 |
| M3 | 决策到生效 + 通知受影响用户 | ≤ 10min | 通知与生效协同 |
| M4 | 决策到双人审批到生效 | ≤ 10min（含人工审批） | Quorum 效率 |
| M5 | 各阶段恢复时间 | ≤ 30min（含 replay） | M5 协议执行效率 |

### 8.3 三条铁律

**铁律 1：TTA 不包含根因修复**
Kill Switch 的定位是"止血"，不是"治病"。明确这一点，否则团队会为追求 10 分钟而跳过取证。

**铁律 2：每季度 Game Day 实测**
未演练过的 TTA 只是文档里的愿望。演练必须包含：
- 在 Kill Switch 自身部分失效时能否降级生效
- 降级态（DEGRADED）下的人工决策流程
- Break-Glass 应急授权的实际演练

**铁律 3：TTA 超标即触发升级**
- MTTC-Actual > 10 分钟 → P2 运营告警
- MTTC-Actual > 30 分钟 → P1 升级至 IC
- MTTC-Actual > 1 小时 → 触发事故响应流程

---

## 9. 证据保存与分档保留

### 9.1 ISO 27001 的事实澄清

> **重要事实修正**：ISO/IEC 27001:2022 A.8.15（日志）只要求"生成、存储，保护和分析日志"，**保留期由组织依法规和业务需求自定，标准本身不给具体年限**。7 年主要来自 SOX（财务审计文档）、Basel II（3-7 年）等金融规范。GDPR 的"存储限制"原则反而要求"不超过实现目的所需时间"，blanket 存 7 年可能与之冲突。

### 9.2 分档保留机制

| 档位 | 内容 | 保留期 | 存储层级 | 依据 |
|------|------|--------|---------|------|
| **运营档** | 常规审计日志、决策事件、Trace | 热 30d / 冷 180d | 普通存储域 | 对齐 REQ-RT-008，满足等保与日常调查 |
| **事件案卷档** | 被定级为安全事件的完整证据链（Artifact、快照、trace、决策链） | 3 年（可延长至 5 年） | 独立取证存储域 | ISO 27001 / SOC 2 审计周期 + 诉讼时效 |
| **财务/合同关联档** | 涉及计费、合同履约、知识产权的事件 | 7 年 | 独立取证存储域 | SOX / 合同法务需求 |
| **PII 档** | 含个人数据的内容快照 | 最小化，按 GDPR 存储限制 + 脱敏 | 加密隔离存储 | 避免"为了取证违反 GDPR" |

### 9.3 Legal Hold 机制

> **核心设计**：实现 Legal Hold 能力比拍定年限更有价值。

**Legal Hold 的核心能力**：
- 按 `case_id` 锁定数据，防止删除和修改
- 独立于普通保留策略运营
- 到期后经审计释放
- 可同时覆盖 SOX 7 年、诉讼无限期和 GDPR 删除要求

**Legal Hold 的存储要求**：
- WORM（一次写入多次读取）/ 对象锁定
- 独立存储域（取证档**不能**和普通日志同桶）
- 管理员**不能**有删除权限（ISO 27001 审核高频扣分点正是"日志可篡改"）
- 跨 AZ 高可用存储

### 9.4 租户删除的数据保留策略

> 参照 `REQ-SEC-008` 的多租户数据治理设计。租户删除时：
> - 事件案卷档 → 转为匿名化保留（履行审计义务）
> - 内容档 → 物理删除
> - 写入删除凭证（immutable log entry）

---

## 10. 证据快照内容

当 Kill Switch 触发且 `evidence_snapshot=true` 时，必须保存以下内容：

| 内容类别 | 具体包含 | 格式 | 存储域 |
|---------|---------|------|--------|
| **状态快照** | 所有受影响 Task 的当前状态投影（REQ-RT-004） | JSON | 事件案卷档 |
| **Action 历史** | 被阻止的 Action、被终止的 Action、in-flight Action 的状态 | JSON | 事件案卷档 |
| **Policy 决策链** | 所有 Policy Decision ID、决策时间、决策结果 | JSON | 事件案卷档 |
| **审计日志切片** | Kill Switch 触发前 1h 到触发后 24h 的审计日志 | JSON | 事件案卷档 |
| **Checkpoint 引用** | 所有受影响任务的最新 Checkpoint ID 和引用（REQ-RT-005） | JSON | 事件案卷档 |
| **工作区引用** | 所有受影响工作区的快照引用 | JSON | 事件案卷档 |
| **Kill Switch 决策** | `kill_decision_id`、触发者、时间、模式、范围、原因 | JSON | 事件案卷档 |
| **凭据使用记录** | Kill Switch 期间凭据的发放和撤销记录（SEC-005） | JSON | 财务/合同关联档 |

**证据快照不包含**：
- 未脱敏的完整源代码（只包含路径和变更摘要）
- 模型隐藏思维链
- 用户密码、私钥等 L1 数据
- 与事件无关的个人数据

---

## 11. 恢复决策与 M5 分阶段恢复

### 11.1 M5 恢复前置条件

恢复前**必须**完成以下全部条件（缺一不可）：

| # | 条件 | 责任方 | 验证方式 |
|---|------|-------|---------|
| 1 | 根因分析完成（必须有文档） | 安全团队 | 上传根因分析报告 |
| 2 | 受影响凭据已轮换（SEC-005 确认） | 安全团队 | SEC-005 凭据轮换事件 |
| 3 | 受影响 Artifact 已审查（无恶意内容） | 安全团队 | 人工审查签字 |
| 4 | 触发条件已消除（可复现的验证测试） | 安全团队 | Replay 测试通过 |
| 5 | 人工审批（M4 恢复需 Quorum） | 授权人员 | 审批事件记录 |

### 11.2 M5 分阶段恢复协议

```
M5-CONTROLLED-RECOVERY
    ↓
Phase 1: 低风险工具重启用（read-only / 幂等查询）
    ├── 验证：观察 30 分钟
    ├── 通过标准：无异常告警
    ├── 失败处理：回退到 M4
    ↓
Phase 2: 中等风险工具重启用（lint / test / build）
    ├── 验证：观察 60 分钟
    ├── 通过标准：无安全告警
    ├── 失败处理：回退到 Phase 1 或 M4
    ↓
Phase 3: 写操作重启用（文件写入 / Git push）
    ├── 验证：观察 2 小时
    ├── 通过标准：无恶意代码告警
    ├── 失败处理：回退到 Phase 2 或 M4
    ↓
Phase 4: 网络访问重启用（仅对白名单目的地）
    ├── 验证：观察 2 小时
    ├── 通过标准：无数据外泄告警
    ├── 失败处理：回退到 Phase 3 或 M4
    ↓
Phase 5: FULLY_ENABLED（全功能恢复）
    ├── 验证：观察 24 小时
    ├── 通过标准：正常运行
    └── 生成恢复报告，归档为 KILL_SWITCH_RESOLUTION
```

**任意阶段失败**：
- 立即回退到上一阶段或重新触发 M4
- 生成失败报告
- 升级至安全团队 Lead

### 11.3 Replay 验证

每阶段恢复前必须执行 Replay 验证：
- 使用 Kill Switch 触发时的同类任务作为测试用例
- 执行回归测试（REQ-EVA-005 回归流水线）
- Replay 失败率阈值：≤ 10%（超过则阻断该阶段恢复）

---

## 12. 应急授权体系（Break-Glass）

### 12.1 四层应急授权架构

> 参照 Microsoft Entra 紧急访问账户最佳实践和 CyberArk/BeyondTrust break-glass 设计。依赖具体角色的设计在真实事故中必然失败（休假、失联、被钓鱼、甚至就是事故的受害者）。

**第一层：委托链（Delegation Chain）**

```
CISO → 副 CISO → IC（Incident Commander）→ 安全工程负责人 → SOC 值班 Lead
   ↓
每人预先登记备用联络方式（独立于公司邮箱/IM，防止 IdP 本身被打掉）
```

**第二层：Quorum 审批（M4/M5 必需）**

- M4 恢复：需「2 of 3」达成（单人不可独断）
- M5 恢复：需「3 of 5」达成
- 既防单点失联，也防单人被胁迫/账号被盗

**第三层：Break-Glass 账户**

- 至少 2 个以上云原生、非联合、不绑定个人、FIDO2/证书认证
- 至少一个排除于所有 CA/MFA 策略之外
- 凭据物理隔离存放（保险柜）
- 每次使用全程审计
- 事后强制审查
- 每 90 天功能验证

**第四层：带外身份核验**

- 通过 HR 系统 / 已知手机号 / 当面确认
- **不认** ticket、不认邮件、不认 IM（这些可能被攻击者控制）

### 12.2 应急授权的三条铁律

**铁律 1：恢复权限**
触发与恢复不必是同一人，但必须是同等级或更高（≥ 触发权限级别）。恢复必须走完整审计 + 事后复盘，**不允许"静默恢复"**。

**铁律 2：时间盒化**
- 紧急提权必须 TTL ≤ 2h
- 可续期一次（最长额外 2h）
- 到期自动回收
- 只能用于本次声明的应急范围
- 禁止全权授权
- 禁止二次转授

**铁律 3：事后必须行动**
- 立即轮换 break-glass 凭据
- 撤销临时成员关系
- 生成应急审计报告
- 72h 内复盘（若涉及 EU 个人数据泄露，GDPR 72 小时报告时钟从"知晓"起算，别等到复盘完才想起来）

---

## 13. API / CLI / UI 统一入口

### 13.1 统一状态机原则

> 三种渠道**不是**三种并列实现，而应是同一个 Kill Switch State Machine 的三个入口。

**设计要求**：
- 所有渠道写入同一状态源（Single Source of Truth）
- 所有渠道读取同一视图
- CLI 触发的在 UI 可见，反之亦然
- 有传播回执：UI 显示"已生效 X/Y 服务"
- 触发前必须显示影响预览（blast radius preview）

### 13.2 渠道分层约束

| 渠道 | 触发速度 | 权限要求 | 影响预览 | 回执确认 | 适用场景 |
|------|---------|---------|---------|---------|---------|
| **API** | 最快（程序化调用） | 同 RBAC | 可选 | 必需 | CI/CD 集成、自动化系统 |
| **CLI** | 快（命令行） | 同 RBAC | 必需 | 必需 | 现场事故响应 |
| **UI** | 最慢（图形界面） | 同 RBAC | 必需 | 必需 | 日常运营 |

### 13.3 状态广播机制

Kill Switch 激活后：
1. 通过事件总线主动广播到所有 Agent、Tool Gateway、Policy Gateway
2. 各下游服务 ack（确认收到）
3. Agent 和连接器收到后快速失败（而不是超时等待）
4. UI 显示各服务的生效状态

### 13.4 误触回滚 SLO

> **关键设计**：既然有 fail-closed，就必须有同等重视的"一键解除"路径。

- 误触回滚 SLO：≤ 60s（从发现误触到恢复）
- 解除路径的可用性必须**高于**触发路径
- 历史上太多事故是"关得掉、开不了"，本设计要求解除路径有独立的高可用保障

---

## 14. Kill Switch 自身的安全

> **Kill Switch 是最高价值目标**。攻击者拿到它等于拿到全平台。

**设计约束**：
- Kill Switch 状态存储独立于业务 IAM
- Kill Switch 管理操作独立审计流（不混入普通审计）
- 硬件密钥保护（HSM/FIDO2）
- 双人操作（M4/M5 级别操作必须双人）
- 所有尝试（含失败的）全记录
- 定期安全评估（季度渗透测试）

---

## 15. 与 Policy Gateway 的职责边界

> 这是本设计最重要的架构决策之一。

| 组件 | 职责 | 决策内容 |
|------|------|---------|
| **Kill Switch** | 发布"现在是什么模式" | 模式枚举（M0-M5）、范围、TTL |
| **Policy Gateway** | 执行具体阻断策略（PEP） | ALLOW / DENY / REQUIRE_APPROVAL |

**耦合约束**：
- Kill Switch 和 Policy Gateway 通过标准模式枚举通信
- Kill Switch **不**直接定义"某个 Action 是否允许"
- Policy Gateway **不**需要知道 Kill Switch 的触发原因，只消费模式状态
- 两者耦合过紧会导致"想封一个连接器却要动全局开关"

---

## 16. 核心指标与告警

### 16.1 一级健康指标

| 指标 | 类型 | SLO | 告警阈值 | 用途 |
|------|------|-----|---------|------|
| `killswitch.activation_rate` | Rate | ≤ 5/天 | > 5/小时需审查 | 异常频繁触发可能表明误配置或攻击 |
| `killswitch.mistouch_rate` | Rate | ≤ 1 次/年（全局封锁误触） | > 0 立即告警 | 误触率是一级健康指标 |
| `killswitch.mttc.p99` | Gauge | ≤ 30s（传播） | > 30s 触发 P2 | Kill Switch 自身工程 SLO |
| `killswitch.mttc.actual` | Gauge | ≤ 10min（遏制） | > 10min 触发 P2 | 用户感知的 TTA |
| `killswitch.blocked_actions` | Counter | — | — | 评估 Kill Switch 影响范围 |
| `killswitch.in_flight_leakage` | Counter | 0 | > 0 立即告警 | in-flight Action 产生禁止副作用 |
| `killswitch.recovery.duration` | Histogram | ≤ 30min（M5 标准层） | > 30min 触发升级 | M5 恢复时间过长 |
| `killswitch.replay_failure_rate` | Rate | ≤ 10% | > 10% 阻断恢复 | replay 测试失败表明问题未消除 |
| `killswitch.service.unavailability` | Rate | 0 | > 0 立即告警 | Kill Switch 服务不可用导致 fail-closed |
| `killswitch.oscillation_count` | Counter | 0 | > 3 次触发升级 | 防止振荡式开合 |

### 16.2 TTA 按模式分档统计

| 模式 | MTTD | MTTA（人工） | MTTA（自动） | MTTC-p99（传播） | MTTC-Actual |
|------|------|------------|------------|----------------|------------|
| M1 | ≤ 60s | ≤ 5min | ≤ 10s | ≤ 30s | ≤ 5min |
| M2 | ≤ 60s | ≤ 5min | ≤ 10s | ≤ 30s | ≤ 10min（含审批） |
| M3 | ≤ 60s | ≤ 10min | ≤ 10s | ≤ 30s | ≤ 10min |
| M4 | ≤ 60s | ≤ 10min（Quorum） | ❌ | ≤ 30s | ≤ 10min |

---

## 17. 与其他模块的接口

### 17.1 上游依赖

| 依赖需求 | 接口内容 |
|---------|---------|
| `REQ-RT-002`（状态机） | Task/Workflow 进入 PAUSED 状态；Kill Switch 触发后受影响 Task 状态联动 |
| `REQ-SEC-002`（RBAC） | Kill Switch 操作权限校验；Break-Glass 授权链 |
| `REQ-SEC-003`（Policy Gateway） | Kill Switch 发布模式枚举；Policy Gateway 消费模式状态执行具体阻断 |
| `REQ-SEC-005`（凭据代理） | Kill Switch 触发后联动凭据撤销；SEC-005 确认凭据轮换完成 |

### 17.2 下游接口

| 接口需求 | 接口内容 |
|---------|---------|
| `REQ-OBS-005`（告警联动） | Kill Switch 触发发送告警；TTA 超标触发升级告警 |
| `REQ-RT-005`（Checkpoint） | 证据快照包含 Checkpoint 数据 |
| `REQ-RT-006/008`（Trace/审计） | Kill Switch 操作审计写入；审计日志切片保存 |
| `REQ-REL-007`（补偿工作流） | in-flight Action 副作用补偿 |
| `REQ-RT-007`（幂等键） | Kill Switch 操作的幂等保证 |

---

## 18. 验收标准

| 编号 | 验收标准 | 验证方式 |
|------|---------|---------|
| SEC-009-AC1 | Kill Switch 触发后，新 Action dispatch 在 ≤ 30s 内 p99 生效（MTTC-p99） | 注 入 Kill Switch + 提交 Action，测量 block 延迟 |
| SEC-009-AC2 | GLOBAL Kill Switch 只影响指定的组织/项目，不影响其他租户 | 跨租户功能测试 |
| SEC-009-AC3 | Kill Switch 触发者的身份、触发时间、触发范围、触发原因、blast radius preview 完整记录在审计日志 | 审计日志完整性测试 |
| SEC-009-AC4 | Kill Switch 服务不可用时，系统进入降级态（DEGRADED）：新任务拒绝，运行中任务允许已持有令牌跑完但禁止续期 | 故障注入测试 |
| SEC-009-AC5 | M5 恢复必须通过 replay 验证，任意阶段失败回退到上一阶段 | M5 恢复流程测试 |
| SEC-009-AC6 | 凭据撤销传播在 ≤ 5s 内生效，新 Action 无法使用已撤销凭据 | 凭据撤销传播测试 |
| SEC-009-AC7 | Kill Switch 可通过 API、CLI 和 UI 三种方式触发，三种渠道写入同一状态源，UI 显示"已生效 X/Y" | 跨接口一致性测试 |
| SEC-009-AC8 | Kill Switch 操作不可由运行中的 Agent 发起 | 安全测试 |
| SEC-009-AC9 | M4 触发后，in-flight Action 完成后产生的禁止副作用被幂等补偿 | 幂等补偿测试 |
| SEC-009-AC10 | Kill Switch 状态存储防篡改，历史记录不可修改或删除 | 防篡改测试 |
| SEC-009-AC11 | MTTC-Actual（遏制时间）目标 ≤ 10min | 实测 |
| SEC-009-AC12 | M4/M5 恢复需要 Quorum 审批，单人不可独断 | 权限测试 |
| SEC-009-AC13 | Break-Glass 凭据每次使用全程审计，事后强制审查 | 审计完整性测试 |
| SEC-009-AC14 | 自动化触发有爆破半径上限（≤ 5% 租户），超限自动降级为人工决策 | 自动化规则测试 |
| SEC-009-AC15 | 误触回滚 SLO ≤ 60s | 实测 |
| SEC-009-AC16 | TTA 按模式分档统计，单一模式不得用平均值掩盖长尾 | 指标统计验证 |
| SEC-009-AC17 | Kill Switch 与 Policy Gateway 通过标准模式枚举通信，不直接耦合 | 集成测试 |

---

## 19. MVP 范围

**MVP 包含**：
- 六模式枚举（M0-M5）和三态 Fail-Closed（NORMAL / DEGRADED / LOCKED）
- 七层粒度（前四级优先：ACTION / TOOL / TASK / ORG）
- Kill check O(1) + 短缓存（≤ 2s TTL）+ 事件总线广播
- Dispatch 层阻断语义（in-flight 单独处理）
- 三维判定矩阵（自动化触发，M1-M2 先行）
- 证据快照（状态投影 + Action 历史 + 审计日志切片）
- 分档保留（运营档 + 事件案卷档 + Legal Hold）
- 凭据撤销联动（SEC-005）
- TTA 指标体系（MTTD / MTTA / MTTC / M5-RTO）
- M5 分阶段恢复（Phase 1-3，Phase 4-5 后续）
- 规范化通知（按模式分级）
- Kill Switch 操作审计
- API + CLI + UI 三种入口（统一状态机）
- Break-Glass 四层授权（委托链 + Quorum）
- 状态广播（各下游 ack）
- 误触回滚 SLO

**MVP 不包含**：
- M5 Phase 4-5（网络访问重启用）
- 自动化触发规则的 ML 优化
- Kill Switch 跨平台标准化（MCP 生态）
- Kill Switch 自身的季度渗透测试（属于 SEC-010）

---

## 20. 待确认问题（已全部解决）

以下问题已在用户确认过程中得到最优解方案：

| # | 问题 | 最终方案 | 来源 |
|---|------|---------|------|
| Q1 | TTA 分档统计 | 分层 MTTD/MTTA/MTTC/M5-RTO，按模式分档，季度 Game Day 实测 | 阿里 1-5-10 框架 + NIST SP 800-61r3 |
| Q2 | Fail-closed 三态 | NORMAL / DEGRADED / LOCKED 三态，缓存 TTL ≤ 30s，跨 AZ 高可用存储 | Gloo Forge + Microsoft 零信任 |
| Q3 | 自动化触发与自动解除 | 三维判定矩阵（严重度×置信度×爆破半径），分档自动解除，观察期 24h，防抖机制 | Microsoft AI 事件响应 |
| Q4 | 证据保留期 | 分档保留 + Legal Hold，WORM 独立存储域，管理员无删除权限 | ISO 27001 + GDPR + SOX |
| Q5 | Break-Glass | 四层：委托链 + Quorum + Break-Glass 账户 + 带外核验，时间盒化 TTL ≤ 2h | Microsoft Entra 最佳实践 |
| Q6 | API/CLI/UI | 统一状态机三入口，状态广播 + ack，显示"已生效 X/Y"，误触回滚 SLO ≤ 60s | Gloo Forge + 行业最佳实践 |
| Q7 | Kill Switch 与 Policy Gateway 边界 | Kill Switch 发布模式枚举（M0-M5），Policy Gateway 执行具体阻断策略 | Agent Patterns + Gloo Forge |

---

## 21. 设计决策记录

```text
需求编号：REQ-SEC-009
功能点：Kill Switch 与事故响应
当前状态：详细设计已完成，待跨模块评审与冻结
前置依赖：REQ-RT-002、REQ-SEC-003
候选方案：
  A. 单一"停止"按钮
  B. 分层 Kill Switch（无模式分级）
  C. 六模式 + 三态 Fail-Closed + 三维判定矩阵 + M5 分阶段恢复 + Break-Glass
公开证据等级：A（基于 Gloo Forge、AI IR Overlay、Agent Patterns、Sanctum、
             Microsoft Entra、NIST SP 800-61r3、阿里 1-5-10 框架）
推荐基线：方案 C
选择理由：
  1. Kill Switch 是止血工具，不是治病工具；TTA 必须分层分档测量
  2. 单一按钮无法满足多租户精准控制需求
  3. Binary on/off 在生产中过度反应，分级更精准
  4. Fail-closed 三态避免 Kill Switch 服务故障成为 DoS 攻击向量
  5. 三维判定矩阵避免静态规则映射的误触雪崩
  6. M5 分阶段恢复确保恢复安全，replay 验证消除带病运行风险
  7. Break-Glass 四层授权消除单点依赖
  8. 统一状态机三入口确保全平台视图一致性
适用边界：
  MVP 先行 ACTION/TOOL/TASK/ORG 四级，M3（Tool Tiering）和 M5（Phase 4-5）后续扩展
替代方案：
  完全依赖 Policy Gateway 执行 Kill Switch（不独立设计 Kill Switch 状态机）
安全约束：
  Kill Switch 状态存储跨 AZ 高可用、防篡改；Kill Switch 管理独立于业务 IAM；
  M4/M5 双人操作；Break-Glass 每次使用全程审计
失败与恢复：
  Kill Switch 服务不可用 → DEGRADED 态（新任务拒绝，运行中任务允许已持有令牌跑完）；
  M5 任意阶段失败 → 回退到上一阶段或重新触发 M4
验收指标：
  MTTC-p99 ≤ 30s，MTTC-Actual ≤ 10min，误触率 ≤ 1 次/年，误触回滚 ≤ 60s
目标版本：REQ-SEC-009 v0.1-designed
```

---

## 22. 参考资料

- Gloo Forge Kill Switches：https://docs.gloo.com/forge/run/kill-switches（访问日期：2026-09-23）
- AI IR Overlay Kill Switch Modes：https://aiir.jacobideji.com/kill-switches/overview.html（访问日期：2026-09-23）
- Agent Patterns Kill Switch：https://www.agentpatterns.tech/en/governance/kill-switch（访问日期：2026-09-23）
- Sanctum AI Agent Incident Response Runbook：https://www.sanctumruntime.com/blog/ai-agent-incident-response-runbook（访问日期：2026-09-23）
- NIST SP 800-61r3 Computer Security Incident Handling Guide
- Microsoft AI Incident Response Phased Containment
- Microsoft Entra Emergency Access Accounts Best Practices
- ISO/IEC 27001:2022 A.8.15（日志）
- ISO/IEC 27001:2022 A.12.4.1（事件日志）/ A.12.4.3（管理员日志）

---

## 23. 变更记录

| 版本 | 日期 | 变更 |
|------|------|------|
| `v0.1-designed` | 2026-09-23 | 基于 Gloo Forge、AI IR Overlay、Agent Patterns、Sanctum、NIST SP 800-61r3、Microsoft Entra 紧急访问最佳实践、阿里 1-5-10 框架，完成 Kill Switch 状态机（6 模式）、三态 Fail-Closed、七层粒度、三维判定矩阵、TTA 分层指标、分档证据保留、M5 分阶段恢复、Break-Glass 四层授权、API/CLI/UI 统一状态机设计 |

---

*文档版本：v0.1-designed*  
*设计日期：2026-09-23*  
*维护团队：架构组 + 安全团队*
