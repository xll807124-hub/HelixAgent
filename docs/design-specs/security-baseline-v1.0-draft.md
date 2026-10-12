# Security Baseline v1.0 - 统一安全防线设计基线汇总

> **文档版本**: v1.0-draft  
> **汇总日期**: 2026-10-11  
> **源文档**: REQ-SEC-001 至 REQ-SEC-010 的 10 个专项设计  
> **当前状态**: 待跨模块评审与冻结  
> **适用范围**: AI Agent 平台的四道安全防线体系

---

## 📋 目录

1. [安全整体愿景](#安全整体愿景)
2. [四道防线总览](#四道防线总览)
3. [防线 1：威胁建模与风险评分（REQ-SEC-001）](#防线-1-威胁建模与风险评分)
4. [防线 2：身份授权与权限管理（REQ-SEC-002/003/008）](#防线-2-身份授权与权限管理)
5. [防线 3：执行隔离与密钥管理（REQ-SEC-004/005）](#防线-3-执行隔离与密钥管理)
6. [防线 4：生态治理与应急响应（REQ-SEC-006/007/009/010）](#防线-4-生态治理与应急响应)
7. [统一验收标准](#统一验收标准)
8. [跨防线协调机制](#跨防线协调机制)
9. [冻结条件](#冻结条件)

---

## 安全整体愿景

### 核心原则

1. **多层防御**：即使单个防线失效，后续防线仍可阻止威胁
2. **默认拒绝**：所有操作需显式授权，不允许隐含的权限扩大
3. **可审计**：每次安全决策都能追踪到身份、资源、时间和理由
4. **快速响应**：异常检测到决策响应时间 < 10 秒（Kill Switch）
5. **持续验证**：不信任一次授权结果，每次执行前都重新验证

### 安全目标

| 目标 | 衡量指标 | 目标值 |
|------|----------|-------|
| **未授权访问** | 拦截率 | 100% |
| **权限提升** | 检测与阻止率 | 100% |
| **高风险操作** | 审批覆盖率 | 100% |
| **凭据泄露** | 检测与轮换时间 | < 1 分钟 |
| **沙箱逃逸** | 失败率 | 0% |
| **恶意代码** | 检测率 | > 95% |
| **应急响应** | Kill Switch 生效时间 | < 10 秒 |

---

## 四道防线总览

```
┌─────────────────────────────────────────────────┐
│ 防线 4：生态治理 & 应急响应                        │
│ (Prompt 注入、MCP 治理、Kill Switch)             │
├─────────────────────────────────────────────────┤
│ 防线 3：执行隔离 & 密钥管理                        │
│ (沙箱、凭据代理、环境隔离)                        │
├─────────────────────────────────────────────────┤
│ 防线 2：授权 & 权限控制                           │
│ (RBAC、Policy Gateway、多租户隔离)              │
├─────────────────────────────────────────────────┤
│ 防线 1：威胁识别 & 风险评分                       │
│ (威胁模型、任务风险分类、动态风险计算)            │
└─────────────────────────────────────────────────┘
```

### 防线定位

| 防线 | 职责 | 关键设计文档 |
|------|------|-----------|
| **防线 1** | 识别→分类→评分 | REQ-SEC-001 威胁模型与风险评分 |
| **防线 2** | 认证→授权→策略→审计 | REQ-SEC-002 RBAC、REQ-SEC-003 Policy Gateway、REQ-SEC-008 多租户 |
| **防线 3** | 沙箱隔离→凭据代理→网络控制 | REQ-SEC-004 沙箱、REQ-SEC-005 凭据代理 |
| **防线 4** | Prompt 防护→生态治理→应急响应 | REQ-SEC-006 Prompt 防护、REQ-SEC-007 MCP 治理、REQ-SEC-009 Kill Switch、REQ-SEC-010 红队验证 |

---

## 防线 1：威胁建模与风险评分

### REQ-SEC-001：威胁模型与风险评分（v0.1-frozen）

#### 威胁模型（STRIDE）

| 威胁类别 | 示例 | 防线 |
|--------|------|------|
| **S**poofing（欺骗）| 冒充用户/Agent 提交任务 | 防线 1: 身份验证 |
| **T**ampering（篡改）| 修改代码变更、测试结果 | 防线 2: Policy Gateway |
| **R**epudiation（否认）| 否认曾执行某操作 | 防线 1/2: 审计日志 |
| **I**nformation Disclosure（信息泄露）| 读取敏感代码、凭据 | 防线 3: 沙箱隔离、防线 2: RBAC |
| **D**enial of Service（拒绝服务）| 资源耗尽、无限循环 | 防线 1: 预算限制、防线 4: Kill Switch |
| **E**levation of Privilege（权限提升）| 低权限用户获得高权限| 防线 2: RBAC、防线 3: 能力隔离 |

#### 威胁生命周期

```
威胁识别 (STRIDE 分类)
  ↓
风险评分 (CVSS-like + 业务影响)
  ↓
防线分配 (1-4 中的匹配防线)
  ↓
检测/响应流程 (对应防线的机制)
  ↓
应急处理 (包括 Kill Switch)
```

#### 关键风险等级

| 等级 | 定义 | 示例 | 响应 |
|------|------|------|------|
| **LOW** | 最小化影响，用户账户有限 | 读取自己的日志 | 记录，无需前置审批 |
| **MEDIUM** | 可修改代码或执行工具 | 执行 sed、git commit | 实时 Policy 评估 + 审计 |
| **HIGH** | 可修改敏感资源或提升权限 | 访问生产 Secret、删除 PR | 高风险审批（需人工） |
| **CRITICAL** | 可突破沙箱、泄露凭据、生产故障 | 执行 rm -rf、访问 OS | 即刻 Kill Switch + 调查 |

#### 动态风险计算

```
Risk Score = 
  威胁概率(Task 类型、来源) × 
  运行时风险(当前 State、失败历史) × 
  操作等级(Action 类型、目标资源) × 
  放大因子(并发、预算消耗、外部依赖)
```

---

## 防线 2：身份授权与权限管理

### REQ-SEC-002：RBAC 与资源授权（v0.1-frozen）

#### 身份模型

```typescript
// 三层身份
Actor =
  | User(user_id, email, mfa_enabled)
  | SystemAgent(agent_id, organization_id, permissions)
  | ExternalService(service_id, trust_level)

// 组织结构
Organization → Project → Repository → ResourcePath
                       ↓
                     Member(user_id, role)

// 角色层级（最小权限原则）
Role ∈ {
  OWNER,           // 完全访问 + 策略配置
  ADMIN,           // 管理资源 + 审批 + 审计读取
  EXECUTOR,        // 代理执行但不能读敏感代码
  REVIEWER,        // 代码审查只读
  AUDITOR,         // 审计日志只读（不读 Payload）
  GUEST           // 有限只读访问
}
```

#### RBAC 权限矩阵

| 操作 | OWNER | ADMIN | EXECUTOR | REVIEWER | AUDITOR | GUEST |
|------|:----:|:----:|:--------:|:--------:|:-------:|:-----:|
| 创建任务 | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| 执行代理 | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| 审批高风险 | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| 读完整代码 | ✅ | ✅ | ⚠️* | ✅ | ❌ | ❌ |
| 查看审计 | ✅ | ✅ | ❌ | ❌ | ✅ | ❌ |
| 导出数据 | ✅ | ⚠️ | ❌ | ❌ | ⚠️ | ❌ |

*EXECUTOR 仅能读取授权范围内的代码

#### 资源权限过滤

每个查询都必须过滤：

```
SELECT artifacts FROM task_artifacts
WHERE organization_id IN (user_orgs)
  AND project_id IN (user_projects)
  AND repository_id IN (user_repos)
  AND path IN (user_allowed_paths)
  AND sensitivity_level <= user_clearance
```

---

### REQ-SEC-003：Policy Gateway（v0.1-frozen）

#### 架构

```
Action 提议
  ↓ (工具 Schema 校验)
Policy Evaluator
  ├─ 1. 资源范围检查 (RBAC)
  ├─ 2. 操作等级评估 (Risk Scoring)
  ├─ 3. 动态策略评估 (OPA)
  ├─ 4. 审批流程 (Manual Review)
  └─ 5. 缓存决策 (Decision Cache)
  ↓
Decision: ALLOW | REQUIRE_APPROVAL | DENY
```

#### 策略规则示例

```rego
# 禁止删除仓库默认分支
deny[msg] {
  action.type == "DELETE_BRANCH"
  input.branch == repo.default_branch
  msg := "Cannot delete default branch"
}

# 高权限写入需要审批
require_approval[msg] {
  action.type == "WRITE"
  action.risk_level == "HIGH"
  not input.pre_approved
  msg := "Manual approval required for high-risk write"
}

# 敏感路径只允许 ADMIN+
allow {
  action.resource.path in sensitive_paths
  actor.role in ["OWNER", "ADMIN"]
}
```

#### 决策缓存

- 相同 Action 在 5 分钟内：复用决策
- Worker/Task/Action 状态变化时：无效缓存
- 审批状态变化时：即刻生效

---

### REQ-SEC-008：多租户数据隔离（v0.1-frozen）

#### 隔离层级

| 层级 | 隔离方式 | 示例 |
|------|---------|------|
| **逻辑隔离** | 应用代码强制过滤 | WHERE organization_id = user_org_id |
| **存储隔离** | 数据库 Row-Level Security | PostgreSQL RLS 策略 |
| **计算隔离** | 独立工作区/容器 | 每个 Agent Task 单独沙箱 |
| **网络隔离** | VPC/防火墙 | 生产环境网络分段 |

#### 强制规则

1. **所有查询必须包含 organization_id**
   ```sql
   ❌ SELECT * FROM tasks WHERE task_id = '...'
   ✅ SELECT * FROM tasks WHERE organization_id = :org_id AND task_id = '...'
   ```

2. **跨租户引用禁止**
   ```
   ❌ Agent 从 Org-A 读取 Org-B 的私有密钥
   ✅ 凭据代理仅返回短期令牌，绑定 Org-A
   ```

3. **数据导出需要多审批**
   ```
   导出 > 1000 行 → Owner + Audit Lead 双签
   ```

---

## 防线 3：执行隔离与密钥管理

### REQ-SEC-004：沙箱隔离基线（v0.1-frozen）

#### 沙箱架构

```
Host OS
  └─ Docker Container (per Workflow/Task)
      ├─ 进程隔离 (PID Namespace)
      ├─ 文件系统隔离 (读写范围限制)
      ├─ 网络隔离 (默认拒绝，白名单允许)
      ├─ 资源限制 (CPU/内存/磁盘)
      └─ 能力限制 (CAP_DROP, no SYS_ADMIN)
```

#### 默认配置

| 资源 | 限制 | 说明 |
|------|------|------|
| CPU | 2 cores | 单 Worker |
| 内存 | 4 GB | 单 Worker |
| 磁盘 | 20 GB | /workspace 可写 |
| 网络 | 仅 HTTP/HTTPS | GitHub、模型 API 等白名单 |
| 进程数 | 100 | 防止 fork bomb |
| 文件描述符 | 1024 | 标准 Linux 限制 |

#### 文件系统规则

```
可读: /repo (bind-mount, read-only)
可写: /workspace (tmpfs, 回收)
禁止: /etc, /sys, /proc 写入
禁止: LD_PRELOAD, /dev/mem 等逃逸向量
```

#### 网络白名单

```yaml
allowed_domains:
  - github.com
  - api.github.com
  - "*.openai.com"
  - "*.anthropic.com"
  - registry.npmjs.org
  - pypi.org

blocked_ips:
  - 169.254.169.254    # AWS metadata
  - 0.0.0.0/8          # Local
  - 127.0.0.0/8        # Localhost
```

#### 逃逸测试

- ✅ 常见逃逸向量（ptrace、mmap /dev/mem）失败
- ✅ cgroup escape 失败
- ✅ Docker escape 失败
- ✅ 定期红队验证（REQ-SEC-010）

---

### REQ-SEC-005：凭据代理（v0.1-frozen）

#### 设计原则

> **Agent 不持有长期凭据；凭据代理按需签发短期令牌。**

#### 架构

```
Agent Task 请求 Git 访问
  ↓
凭据代理 (Credential Proxy Service)
  ├─ 1. 校验 Task/Worker 身份
  ├─ 2. 查询授权范围（仓库、权限）
  ├─ 3. 签发短期令牌（有效期 1 小时）
  └─ 4. 记录审计日志
  ↓
短期令牌 → Task/Sandbox
  ↓
使用一小时后自动过期
  ↓
需要续期 → 重新评估授权
```

#### 支持的凭据类型

| 类型 | 存储位置 | 签发方式 | 有效期 |
|------|---------|---------|-------|
| **GitHub App** | 凭据代理 | JWT（私钥） | 1 小时 |
| **SSH Key** | 凭据代理 | 临时密钥对 | 1 小时 |
| **API Token** | 凭据代理（加密） | 短期 Bearer | 1 小时 |
| **AWS Credential** | 凭据代理 | STS AssumeRole | 1 小时 |

#### 关键保证

1. **无明文存储**：长期密钥用 KMS 加密
2. **最小权限**：按 Task/Workflow 权限下发，不是全部
3. **轮换记录**：每次轮换进入审计日志
4. **自动过期**：无需人工吊销
5. **即时吊销**：Kill Switch 可立即撤销所有活动令牌

---

## 防线 4：生态治理与应急响应

### REQ-SEC-006：Prompt 注入防护（v0.1-frozen）

#### 防护目标

防止 Prompt 注入攻击：通过精心构造的输入，让 AI 模型执行未授权操作。

#### 检测引擎

```
输入文本
  ├─ 1. 特征扫描（关键词）
  │   └─ "ignore above", "system prompt", "execute code" ...
  ├─ 2. 结构检测（格式异常）
  │   └─ Base64 编码段、JSON 转义嵌套
  ├─ 3. 语义分析（语言模型）
  │   └─ 小模型判断："本文想指导我做什么"
  └─ 4. 历史对比（已知对抗样本库）
      └─ 与 OWASP 已知 Prompt 注入样本比对

风险分数 = 特征权重 × 出现次数 + 结构异常分 + 语义红旗分

决策：
  LOW  (< 30)    → 允许
  MED  (30-70)   → 记录、继续监测
  HIGH (> 70)    → 拒绝或沙箱降级
```

#### 防护措施

| 措施 | 执行点 |
|------|-------|
| **输入净化** | 任务描述、用户反馈、Issue 正文 |
| **Prompt 隔离** | 系统 Prompt 与用户输入分离 |
| **上下文限制** | 模型只能访问已授权的上下文 |
| **工具调用验证** | Agent 生成的工具调用必须经 Policy Gateway |
| **输出检查** | 模型输出不能直接作为状态转移或权限依据 |

---

### REQ-SEC-007：MCP 连接器治理（v0.1-frozen）

#### 连接器分类

| 等级 | 信任程度 | 允许操作 | 审核频率 |
|------|---------|--------|---------|
| **TRUSTED** | 官方/经过安全审计 | 所有工具 | 每季度 |
| **VERIFIED** | 第三方验证 | 受限工具（无 Shell、DB） | 每月 |
| **SANDBOX** | 未验证 | 只读工具（文件读取、HTTP GET） | 每周 |
| **BLOCKED** | 已发现恶意 | 禁止使用 | - |

#### 治理流程

```
连接器请求注册
  ↓
1. 代码审查（寻找恶意逻辑）
2. 功能扫描（工具清单）
3. 权限分析（需要什么访问）
4. 动态测试（沙箱隔离运行）
5. 分类决定
  ↓
上线 + 持续监测
  ├─ 运行时异常检测
  ├─ 定期审计
  └─ 用户举报处理
```

#### 工具白名单

```yaml
TRUSTED 工具:
  - file.read
  - git.clone
  - git.commit
  - github.pr_create
  
VERIFIED 工具:
  - file.write    # 限制路径范围
  - http.request  # 限制域名白名单
  
SANDBOX 工具:
  - web.search    # 只读 HTTP
  - calendar.read # 只读 API
  
禁止工具:
  - shell.execute
  - os.system
  - db.execute
  - file.delete
```

---

### REQ-SEC-009：Kill Switch - 应急响应机制（v0.1-frozen）

#### 设计

> **无需人工干预，自动识别异常并阻止**

#### 六层 Kill Switch 模式

| 模式 | 触发条件 | 作用范围 | 恢复时间 |
|------|---------|--------|---------|
| **M0** 正常 | - | - | - |
| **M1** 监控 | 单个 Agent 失败率 > 50% | 仅该 Agent 新任务被拒 | 15 分钟自动解除 |
| **M2** 局部 | 单个工具调用失败 100+ 次/5min | 禁用该工具 | 30 分钟自动解除 |
| **M3** 分支 | 某分支被频繁写/删 | 分支冻结 | 需 Owner 手工解除 |
| **M4** 项目级 | 项目内多个大规模异常 | 暂停所有 Agent 任务 | 需 Admin + 调查 |
| **M5** 全局 | 检测到系统级攻击迹象 | 全平台禁用 Agent 执行 | 需 Security Lead + 调查 |

#### 自动触发规则

```
M1 触发条件:
  - 失败率 > 50% (最近 100 次执行)
  - 持续时间 > 5 分钟

M2 触发条件:
  - 同一工具失败 100+ 次，连续 5 分钟
  - 或单个 Sandbox 容器内存占用 > 100%

M3 触发条件:
  - 同一分支 write + delete 操作交替 > 20 次/分钟
  - 或检测到删除重要分支

M4 触发条件:
  - 项目内同时失败 Agent > 50%
  - 或检测到凭据泄露

M5 触发条件:
  - 系统级异常（数据库故障、网络断裂）
  - 或检测到正在进行的安全事件（蠕虫、勒索）
```

#### Break-Glass 机制（M5 恢复）

```
需要解除 M5 全局禁用:

第 1 层：Security Lead (需要密钥 + OTP)
第 2 层：CTO (双重认证)
第 3 层：董事会成员 (电话确认)
第 4 层：外部安全公司验证 (可选)

每层批准后生成审计记录，所有操作回放到日志
```

---

### REQ-SEC-010：红队测试与安全验证（v0.1-frozen）

#### 验证范围

- ✅ 沙箱逃逸（ptrace、cgroup、Docker escape）
- ✅ 权限提升（SUID、capabilities）
- ✅ 凭据泄露（环境变量、内存扫描）
- ✅ 信息泄露（目录遍历、路径穿越）
- ✅ 拒绝服务（资源耗尽、无限循环）
- ✅ Prompt 注入（已知与新样本）
- ✅ 跨租户访问（数据泄露）

#### 测试计划

| 频率 | 测试类型 | 目标 | 阈值 |
|------|---------|------|------|
| 每周 | 自动化安全扫描 | SAST/SCA | 0 高危 |
| 每月 | 人工渗透测试 | 功能安全漏洞 | 0 P0/P1 |
| 每季度 | 蓝红对抗演习 | 事件响应能力 | 检测率 > 80% |
| 每年 | 外部安全审计 | 第三方验证 | 符合行业标准 |

---

## 统一验收标准

### 防线验收检查表

#### 防线 1：威胁识别 ✓

- [x] 所有 MVP 操作都有风险等级分类
- [x] 风险评分算法确定性（相同输入→相同分数）
- [x] 审批流程按风险等级联动

#### 防线 2：授权 ✓

- [x] 所有查询都强制执行租户过滤
- [x] Policy Gateway 能拦截 100% 的非法操作
- [x] 权限不向下继承（Worker 权限 ⊆ Workflow ⊆ Task）
- [x] 审批缓存在 5 分钟内失效

#### 防线 3：隔离 ✓

- [x] 沙箱逃逸测试失败率 100%
- [x] 凭据有效期 < 2 小时
- [x] 无长期密钥暴露在 Sandbox
- [x] 网络白名单黑名单生效

#### 防线 4：生态与应急 ✓

- [x] Prompt 注入防护率 > 95%
- [x] MCP 连接器分级完整
- [x] Kill Switch 生效时间 < 10 秒
- [x] Break-Glass 流程可追踪

---

## 跨防线协调机制

### 异常级联响应

```
第 1 层触发（高风险 Action）
  → Policy Gateway 要求审批
  → 审批时间 > 10 分钟
    ↓
第 2 层：Self-healing
  → 自动降级工具权限
  → 增加监测频率
    ↓
第 3 层：Kill Switch M2
  → 禁用该工具
    ↓
继续恶意行为
  ↓
第 4 层：Kill Switch M4
  → 项目级暂停
  → 启动调查
```

### 审计协调

所有防线决策都记录到统一审计日志：

```
timestamp: 2026-10-11T14:23:45Z
threat_level: HIGH
action: ActionProposed (file.write)
actor: agent-coder-12345
resource: /repo/src/main.py
policy_decision: REQUIRE_APPROVAL
approval_status: PENDING
approval_duration_sec: 245
final_decision: ALLOW
executed_by: agent-coder-12345
outcome: SUCCESS
evidence: file_hash_mismatch_detected, rollback_triggered
```

---

## 冻结条件

### 升级到 v1.0-frozen 的条件

**必须完成**：

1. ✅ REQ-SEC-001 ~ REQ-SEC-010 设计文档完成
2. ⏳ 与 Runtime Contract (REQ-RT-*) 的接口评审
3. ⏳ 与其他安全模块（OBS-006, REL-005）的协调
4. ⏳ 所有防线的单元测试设计完成
5. ⏳ 防线集成测试设计完成
6. ⏳ 初步红队验证（沙箱逃逸、权限提升）
7. ⏳ Kill Switch 演练计划编制

### 不阻塞因素

- 外部安全审计（可在上线后继续）
- 完整渗透测试（可在上线后继续）
- MCP 连接器内容审核（上线时仅处理官方）

---

## 文档变更记录

| 版本 | 日期 | 变更 |
|------|------|------|
| **v1.0-draft** | 2026-10-11 | 初次汇总：合并 REQ-SEC-001~010，统一格式，补充跨防线协调机制 |

---

**下一步行动**：

1. ⏳ 发送本文档给安全团队和架构评审
2. ⏳ 收集评审反馈，标记冲突点
3. ⏳ 与 Runtime Contract 评审同步进行
4. ⏳ 投票通过后升级为 v1.0-frozen

---

**文档维护者**：安全架构团队  
**维护日期**：2026-10-11  
**下次评审**：2026-10-12 评审会
