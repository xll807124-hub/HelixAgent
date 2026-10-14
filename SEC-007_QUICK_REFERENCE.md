# SEC-007 MCP 连接器治理 - 快速参考

**项目**: SEC-007 MCP Connector Governance  
**状态**: Day 3/5 完成 (60%)  
**代码**: 32 文件 | 6,668 行 | 38 测试 ✅  

---

## 📚 核心概念速查

### 信任等级 (L1-L4)

```python
from src.security.mcp_connector_governance import TrustLevel

L1 = TrustLevel.L1_PLATFORM_MANAGED        # quota: 0.5x
L2 = TrustLevel.L2_ORG_VERIFIED            # quota: 1.0x
L3 = TrustLevel.L3_RESTRICTED_CONDITIONAL  # quota: 3.0x
L4 = TrustLevel.L4_UNVERIFIED              # quota: 5.0x
```

### 生命周期状态

```python
from src.security.mcp_connector_governance import ConnectorLifecycleState

DRAFT → PENDING_VERIFICATION → PENDING_APPROVAL → APPROVED_INACTIVE
   ↓                             ↓                      ↓
(重新起草)                   (等待批准)            (激活)
                                                    ↓
                              ACTIVE ←─┬─ PENDING_REVIEW
                                       ├─ RESTRICTED
                                       ├─ HEALTH_ANOMALY
                                       └─ PAUSED
                                       
                              REVOKED (终态)
                              EXPIRED (可重试)
```

### 配额计算

```python
# 公式
cost = trust_weight × tool_count × risk_multiplier × network_multiplier × cred_multiplier

# 示例
L2, 3 tools, medium risk, network access:
1.0 × 3 × 1.0 × 1.5 × 1.0 = 4.5 配额单位
```

---

## 🔧 API 速查

### 1. 工具执行

```python
from src.security.mcp_connector_governance import ToolExecutor
from src.security.mcp_connector_governance.policies import PolicyEngine

# 初始化
engine = PolicyEngine()
executor = ToolExecutor(engine)

# 执行工具
result = await executor.execute_tool(
    org_id="org_001",
    user_id="user_001",
    connector=connector_obj,
    tool=tool_obj,
    parameters={"param": "value"}
)

# 检查结果
if result.success:
    print(result.result)  # 工具输出
else:
    print(result.error)  # 错误信息
```

### 2. 签名验证

```python
from src.security.mcp_connector_governance import UnifiedSignatureVerifier

verifier = UnifiedSignatureVerifier()

# 添加 GPG 密钥
verifier.gpg.add_trusted_key("fingerprint", "key_data")

# 添加内部 PKI 证书
verifier.internal_pki.register_certificate("cert_id", "cert_pem")

# 验证签名
result = await verifier.verify(
    artifact_bytes=b"connector_binary",
    signature_info={
        "algorithm": "sigstore-oidc",  # or "gpg", "internal-pki"
        "signature": "...",
        "certificate": "...",
    }
)

if result.is_valid:
    print(f"Verified by {result.algorithm}")
```

### 3. 策略检查

```python
from src.security.mcp_connector_governance.policies import PolicyEngine

engine = PolicyEngine()

# 初始化组织配额
engine.quota_manager.initialize_org_quota(
    org_id="org_001",
    base_quota=1000.0
)

# 评估连接器访问
decision = engine.evaluate_connector_access(
    org_id="org_001",
    connector=connector_obj
)

if not decision.allowed:
    print(f"Denied: {decision.reason}")
```

### 4. 连接器注册

```python
from src.security.mcp_connector_governance.registry import ConnectorRegistry
from src.security.mcp_connector_governance.models import Connector

registry = ConnectorRegistry()

# 注册连接器
registry.register(connector_obj)

# 查询
connector = registry.get("conn_001")

# 按信任等级列表
connectors = registry.list_by_trust_level(TrustLevel.L2_ORG_VERIFIED)
```

---

## 🧪 测试运行

### 运行所有测试

```bash
cd G:\项目\Ai_agent

# 所有测试
python -m pytest tests/test_mcp_governance_day*.py -v

# 特定天数
python -m pytest tests/test_mcp_governance_day1.py -v  # Day 1
python -m pytest tests/test_mcp_governance_day2.py -v  # Day 2
python -m pytest tests/test_mcp_governance_day3.py -v  # Day 3

# 显示覆盖率
python -m pytest tests/ --cov=src/security/mcp_connector_governance
```

### 测试统计

```
Day 1: 13 个测试 ✅
Day 2: 9 个测试 ✅
Day 3: 16 个测试 ✅
最近一次 pytest 运行: 89 通过, 0 失败 (含 test_mcp_signature_verification、test_mcp_handler_blacklist、test_mcp_tool_executor_v2)
```

---

## 📁 项目结构

```
src/security/mcp_connector_governance/
├── models/              # 数据模型
│   ├── trust_level.py   # 信任等级定义
│   ├── tool_schema.py   # 工具 Schema 和摘要
│   ├── connector.py     # 连接器模型
│   └── base.py          # 基础模型
├── registry/            # 注册表系统
│   ├── connector_registry.py
│   ├── tool_registry.py
│   ├── signature_verifier.py
├── policies/            # 策略引擎
│   ├── global_blacklist.py
│   ├── org_whitelist.py
│   ├── quota_manager.py
│   └── policy_engine.py
├── lifecycle/           # 生命周期管理
├── authorization/       # OAuth 2.1
├── execution/           # 工具执行
│   ├── tool_executor.py
│   └── tool_executor_v2.py  # Day 3 新增
├── audit/               # 审计日志
├── protocol/            # MCP 协议
│   ├── mcp_handler.py
│   └── transport.py
├── persistence/         # 数据库
│   └── repository.py
└── security/            # 签名验证 (Day 3)
    └── signature_verifier.py
```

---

## 🔐 安全检查清单

### 启用安全

- [ ] 配置信任等级 (L1-L4)
- [ ] 设置全局黑名单
- [ ] 注册可信签名方式
- [ ] 初始化组织配额

### 生产部署

- [ ] 使用 Sigstore OIDC 签名
- [ ] 启用所有 8 层防御
- [ ] 配置审计日志
- [ ] 设置监控告警
- [ ] 准备隔离环境

---

## 📊 性能指标

### 建议的超时设置

```python
# STDIO 执行
STDIOExecutor(timeout_seconds=30)

# HTTP 执行
HTTPExecutor(timeout_seconds=30)

# 工具执行总时限
ToolExecutor timeout: 30-60秒
```

### 配额参考

```
基础配额: 1000 单位/小时

L1 工具执行成本:   0.5 - 2.0 单位
L2 工具执行成本:   1.0 - 5.0 单位
L3 工具执行成本:   3.0 - 15.0 单位
L4 工具执行成本:   5.0 - 50.0 单位

高风险工具倍数:     5.0x
网络访问倍数:       1.5x
凭据访问倍数:       1.5x
```

---

## 🚀 部署步骤

### 1. 环境准备

```bash
# 安装依赖
pip install -r requirements.txt

# 运行测试
python -m pytest tests/

# 检查导入
python -c "from src.security.mcp_connector_governance import *; print('OK')"
```

### 2. 初始化

```python
from src.security.mcp_connector_governance import (
    ConnectorRegistry,
    PolicyEngine,
    ToolExecutor,
    UnifiedSignatureVerifier,
)

# 初始化组件
registry = ConnectorRegistry()
engine = PolicyEngine()
executor = ToolExecutor(engine)
verifier = UnifiedSignatureVerifier()

# 配置信任
verifier.internal_pki.register_certificate(...)
engine.quota_manager.initialize_org_quota(...)
```

### 3. 运行

```python
# 注册连接器
registry.register(connector)

# 执行工具
result = await executor.execute_tool(...)

# 验证签名
verification = await verifier.verify(...)
```

---

## 📝 常见问题

### Q: 如何添加新的信任等级?

A: 目前定义了 L1-L4，如需修改，编辑 `models/trust_level.py`。

### Q: 如何自定义配额?

A: 使用 `QuotaManager.calculate_cost()` 方法，可以调整各个参数。

### Q: 支持哪些签名算法?

A: Sigstore OIDC (优先), GPG (后备), Internal PKI (平台)。

### Q: 超时如何处理?

A: 所有执行器都支持可配置超时，超时自动返回错误并退款配额。

---

## 📞 支持

**文档**:
- 架构图: `SEC-007_ARCHITECTURE_DIAGRAM.md`
- Day 1 报告: `SEC-007_DAY1_COMPLETION_REPORT.md`
- Day 2 报告: `SEC-007_DAY2_COMPLETION_REPORT.md`
- Day 3 报告: `SEC-007_DAY3_COMPLETION_REPORT.md`
- 总结: `SEC-007_3DAY_SUMMARY.md`

**代码示例**:
- tests/test_mcp_governance_day1.py
- tests/test_mcp_governance_day2.py
- tests/test_mcp_governance_day3.py

---

**最后更新**: 2026-10-14 09:40 UTC+8  
**项目进度**: 60% (Day 3/5)  
**测试状态**: 89 通过, 0 失败 (最近一次运行)

