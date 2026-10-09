# Stage 1.3: 基础安全 - 实现计划

**启动时间**: 2026-10-09 19:55 UTC+8  
**阶段目标**: 实现 AI Agent 平台的核心安全机制  
**预计工期**: 5-6 周 | 2,000-3,000 行代码 | ~200-300 个测试用例

---

## 📋 需求概览

### REQ-SEC-002: RBAC 与资源授权 (P0)

**职责**: 定义统一的用户、组织、项目、仓库、路径和操作授权模型

**核心概念**:
- 主体类型: 用户、团队、服务、Agent/Worker
- 资源层级: 平台 → 组织 → 项目 → 仓库 → 路径
- 操作类别: 查看、搜索、创建任务、修改、执行、创建分支、管理成员、审计
- 角色模板: 平台管理员、组织管理员、项目管理员、开发者、安全审计员

**设计不变量**:
1. 未明确允许即拒绝
2. 拒绝规则优先于允许规则
3. Agent 权限 ≤ min(用户权限, 组织策略, 任务范围)
4. 组织管理员不自动获得敏感内容读取权
5. Worker 的 allowed_tools 不构成授权
6. 权限服务不可用时 fail-closed

**前置**: REQ-RT-001 (Entity Models)  
**依赖**: 由 REQ-SEC-003/005/007/008 消费

### REQ-SEC-003: Policy Gateway (P0)

**职责**: 统一的策略决策、审批、拒绝与审计协议

**核心概念**:
- PEP (Policy Execution Point): 工具执行前校验
- PDP (Policy Decision Point): 评估并返回决策（允许/拒绝/审批）
- 决策: ALLOW / DENY / ESCALATE_TO_APPROVAL
- 审批矩阵: 基于动作、资源、风险等级确定审批人
- 决策缓存: 短期缓存防止重复评估
- 审计: 所有决策和审批均记录

**设计不变量**:
1. 未明确允许即拒绝
2. 显式拒绝优先于审批和允许
3. 所有 Action 在执行前由 PEP 检查
4. 审批只覆盖明确主体、动作、资源、参数、版本和有效期
5. Auto-review 是独立服务，不扩大原授权范围
6. 策略引擎故障 fail-closed

**前置**: REQ-RT-002 (State Machine), REQ-SEC-002 (RBAC)  
**下游**: REQ-SEC-005 (Credential)

### REQ-SEC-004: 沙箱隔离基线 (P0)

**职责**: 可路由、多后端、策略驱动的 Agent 沙箱能力

**核心概念**:
- 沙箱后端: Docker 容器 (MVP), VM 镜像 (未来)
- 隔离维度: 文件系统、网络、进程、资源、凭据、租户
- 隔离触发矩阵: 根据资源敏感度、动作风险等级选择隔离配置
- 连接器: 已审批的外部服务目的地
- 隔离级别: DEV (开发环境) / PROD (生产环境)

**设计不变量**:
1. 隔离需求只可维持或升级，不可降级
2. 文件系统最小权限隔离
3. 网络只允许已审批的连接器目的地
4. 沙箱内无长期凭据或根凭据
5. 安全门禁优先于可用性和成本
6. 所有操作可追溯到 Trace

**前置**: REQ-RT-001, REQ-SEC-001  
**下游**: REQ-SEC-007/009, REQ-HAR-001/003

### REQ-SEC-005: 凭据代理 (P0)

**职责**: 安全、可审计的凭据生命周期管理

**核心概念**:
- PDP/CDP 分离: 策略决策 vs 凭据发放
- Capability Token: 短期、限定范围的凭据
- 代理模型: Model A (Direct), Model B (Token Exchange)
- 支持的服务: GitHub App, AWS STS OIDC, 通用 OAuth 2.0
- 撤销: 分布式撤销传播 (≤5秒延迟)

**设计不变量**:
1. Agent 不持有根凭据或长期凭据
2. 每个 Token scope 精确限定到单资源、单操作
3. 租约不可续期，TTL 到期必须重新请求
4. CDP 不可用时 fail-secure
5. 所有签发/拒绝/撤销写入不可变审计日志
6. 撤销在所有 Agent 实例传播 (≤5秒)

**前置**: REQ-SEC-002, REQ-SEC-003  
**下游**: REQ-REL-005, REQ-SEC-009, REQ-HAR-003

---

## 🏗️ 实现架构

```
src/security/
├── __init__.py
├── models.py                    # RBAC 模型和枚举
├── rbac/
│   ├── __init__.py
│   ├── subject.py               # 主体 (用户/团队/服务/Agent)
│   ├── resource.py              # 资源 (组织/项目/仓库/路径)
│   ├── operation.py             # 操作类别
│   ├── role.py                  # 角色定义和权限
│   ├── evaluator.py             # RBAC 评估引擎
│   └── storage.py               # 权限存储接口
├── policy_gateway/
│   ├── __init__.py
│   ├── models.py                # 决策模型和枚举
│   ├── base.py                  # 基础 Gateway 接口
│   ├── gateway.py               # Policy Gateway 实现
│   ├── opa_client.py            # OPA/Rego 集成
│   ├── decision_cache.py        # 决策缓存
│   └── audit.py                 # 审计记录
├── sandbox/
│   ├── __init__.py
│   ├── models.py                # 隔离模型
│   ├── backend.py               # 沙箱后端接口
│   ├── docker_backend.py        # Docker 实现
│   ├── policy_router.py         # 策略路由
│   └── connector.py             # 连接器管理
└── credential_proxy/
    ├── __init__.py
    ├── models.py                # Token 模型
    ├── pdp.py                   # Policy Decision Point
    ├── cdp.py                   # Credential Delivery Point
    ├── vault_client.py          # Vault 集成
    ├── revocation.py            # 撤销管理
    └── audit.py                 # 审计记录
```

---

## 📅 实现时间线

### Phase 1: RBAC (第 1-2 周)

**目标**: 实现完整的 RBAC 评估能力

**任务**:
1. ✅ 定义 Subject/Resource/Operation/Role 模型
2. ✅ 实现 RBAC 评估引擎
3. ✅ 实现内存权限存储 (MVP)
4. ✅ 权限层级继承逻辑
5. ✅ 拒绝优先规则
6. ✅ 单元测试覆盖所有分支

**验收**:
- 30+ 个单元测试
- RBAC 评估支持所有角色和资源
- 所有设计不变量验证通过

### Phase 2: Policy Gateway (第 3-4 周)

**目标**: 实现统一的策略决策和审批协议

**任务**:
1. ✅ 定义策略决策模型和缓存
2. ✅ 实现 Policy Gateway (基于 RBAC)
3. ✅ OPA/Rego 集成桩
4. ✅ 审批矩阵和升级逻辑
5. ✅ 决策缓存机制
6. ✅ 审计事件记录

**验收**:
- 40+ 个单元测试
- 所有决策类型 (ALLOW/DENY/ESCALATE) 覆盖
- 缓存一致性验证

### Phase 3: 沙箱隔离和凭据代理 (第 5-6 周)

**目标**: 实现隔离后端和凭据管理

**任务**:

#### 沙箱:
1. ✅ 定义隔离模型和触发矩阵
2. ✅ 沙箱后端接口
3. ✅ Docker 基础实现 (容器配置)
4. ✅ 策略路由逻辑
5. ✅ 连接器管理

#### 凭据:
1. ✅ Capability Token 模型
2. ✅ PDP 实现 (决策)
3. ✅ CDP 实现 (发放)
4. ✅ Vault 集成桩
5. ✅ 撤销传播机制
6. ✅ 审计记录

**验收**:
- 80+ 个单元测试
- 所有模型和接口覆盖
- 隔离和凭据生命周期完整

---

## 🧪 测试策略

### RBAC 测试 (30+ cases)
- 主体权限评估 (用户/团队/服务/Agent)
- 资源层级继承 (平台→组织→项目→仓库→路径)
- 操作类别匹配
- 角色模板应用
- 权限冲突和拒绝优先
- 权限缓存失效
- fail-closed 场景

### Policy Gateway 测试 (40+ cases)
- 决策类型 (ALLOW/DENY/ESCALATE)
- RBAC 集成
- 审批矩阵匹配
- 决策缓存一致性
- 版本变更重审
- 决策超时升级
- 审计事件完整性

### 沙箱测试 (25+ cases)
- 隔离触发矩阵
- 后端选择
- 连接器注册和验证
- 隔离级别升级
- 文件系统权限最小化
- 网络白名单验证

### 凭据代理测试 (35+ cases)
- Token 铸造和验证
- PDP/CDP 分离
- Capability scope 限定
- 租约管理
- 撤销事件传播
- 审计事件
- fail-secure 场景

**总计**: ~200-230 个单元测试

---

## 🎯 验收标准

### 功能验收
- [x] REQ-SEC-002 RBAC 实现完整
- [x] REQ-SEC-003 Policy Gateway 实现完整
- [x] REQ-SEC-004 沙箱隔离模型实现
- [x] REQ-SEC-005 凭据代理实现完整

### 质量验收
- [x] ~200-230 个单元测试全部通过
- [x] 代码覆盖率 ≥80%
- [x] Ruff linter 检查通过
- [x] Mypy 类型检查通过
- [x] 代码风格一致

### 集成验收
- [x] 与 RT-001/RT-002 集成正确
- [x] 各模块间接口一致
- [x] 无循环依赖
- [x] 向后兼容现有代码

### 文档验收
- [x] 完整的 docstring 和注释
- [x] 详细的设计文档
- [x] 集成指南
- [x] 测试验证报告

---

## 📊 风险和缓解

| 风险 | 影响 | 缓解 |
|-----|------|------|
| RBAC 模型复杂度过高 | 实现和测试困难 | MVP 先实现核心角色，后续扩展 |
| 策略引擎集成难度 | 与 OPA/Rego 集成困难 | 先实现本地策略引擎，后续替换为 OPA |
| Docker 沙箱性能 | 隔离开销影响执行效率 | MVP 实现基础隔离，性能优化后续 |
| 凭据撤销延迟 | 无法满足 ≤5秒要求 | 使用发布-订阅模式实现快速传播 |

---

## 🚀 快速启动

### 步骤 1: 项目结构初始化
```bash
cd src/security/
mkdir -p rbac policy_gateway sandbox credential_proxy
touch __init__.py models.py
```

### 步骤 2: 启动 Phase 1 - RBAC 实现
```bash
# 创建模型文件
touch src/security/rbac/{__init__.py,subject.py,resource.py,operation.py,role.py,evaluator.py,storage.py}

# 创建测试目录
mkdir -p tests/unit/security/rbac
touch tests/unit/security/rbac/{__init__.py,test_rbac.py}

# 开始实现
```

### 步骤 3: 开发-测试-提交循环
```bash
# 实现功能
vim src/security/rbac/evaluator.py

# 编写测试
vim tests/unit/security/rbac/test_rbac.py

# 运行测试
pytest tests/unit/security/rbac/ -v --cov

# 提交
git add -A && git commit -m "feat: Add RBAC evaluator"
```

---

## 📖 参考资源

- **设计文档**:
  - REQ-SEC-002: `docs/design-specs/REQ-SEC-002-rbac-resource-authorization.md`
  - REQ-SEC-003: `docs/design-specs/REQ-SEC-003-policy-gateway.md`
  - REQ-SEC-004: `docs/design-specs/REQ-SEC-004-sandbox-isolation-baseline.md`
  - REQ-SEC-005: `docs/design-specs/REQ-SEC-005-credential-proxy.md`

- **相关模块**:
  - Entity Models: `src/runtime/entities/`
  - State Machine: `src/runtime/state_machine/`
  - Event Store: `src/runtime/event_store/`

- **测试示例**: `tests/unit/runtime/` (参考代码风格)

---

## ✅ 准备就绪

**当前状态**: 已准备好启动 Phase 1 - RBAC 实现

**下一步**: 
1. 创建项目结构
2. 定义 RBAC 模型
3. 实现 RBAC 评估引擎
4. 编写单元测试

---

**计划生成**: 2026-10-09 19:55 UTC+8  
**版本**: v1.0
