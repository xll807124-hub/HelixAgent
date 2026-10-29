"""
SEC-007 MCP Connector Governance - Unit Tests
Day 1 核心功能测试
"""


import pytest

from src.security.mcp_connector_governance.models import (
    AuthConfig,
    AuthenticationMode,
    Connector,
    ConnectorConfig,
    ConnectorIdentity,
    ConnectorLifecycleState,
    ConnectorStatus,
    SignatureVerification,
    ToolCapability,
    ToolInputSchema,
    ToolRiskProfile,
    ToolSchema,
    TransportConfig,
    TransportType,
    TrustLevel,
    classify_trust_level,
    get_trust_level_config,
)
from src.security.mcp_connector_governance.policies import (
    GlobalBlacklist,
    PolicyEngine,
    QuotaManager,
)
from src.security.mcp_connector_governance.registry import (
    ConnectorRegistry,
)


class TestTrustLevel:
    """测试信任等级功能"""
    
    def test_trust_level_quota_weights(self):
        """测试信任等级配额权重"""
        l1_config = get_trust_level_config(TrustLevel.L1_PLATFORM_MANAGED)
        l2_config = get_trust_level_config(TrustLevel.L2_ORG_VERIFIED)
        l3_config = get_trust_level_config(TrustLevel.L3_RESTRICTED_CONDITIONAL)
        l4_config = get_trust_level_config(TrustLevel.L4_UNVERIFIED_UNTRUSTED)
        
        assert l1_config.quota_weight == 0.5
        assert l2_config.quota_weight == 1.0
        assert l3_config.quota_weight == 3.0
        assert l4_config.quota_weight == 5.0
    
    def test_trust_level_classification(self):
        """测试信任等级分类"""
        # L1: 平台托管
        level = classify_trust_level(is_platform_managed=True)
        assert level == TrustLevel.L1_PLATFORM_MANAGED
        
        # L2: 组织验证
        level = classify_trust_level(is_org_verified=True)
        assert level == TrustLevel.L2_ORG_VERIFIED
        
        # L3: 有签名和版本固定
        level = classify_trust_level(has_signature=True, has_version_pin=True)
        assert level == TrustLevel.L3_RESTRICTED_CONDITIONAL
        
        # L4: 未验证
        level = classify_trust_level()
        assert level == TrustLevel.L4_UNVERIFIED_UNTRUSTED


class TestToolSchema:
    """测试工具 Schema 功能"""
    
    def test_schema_digest_computation(self):
        """测试 Schema 摘要计算"""
        tool = ToolSchema(
            tool_name="test_tool",
            description="Test tool",
            input_schema=ToolInputSchema(
                properties={"param1": {"type": "string"}},
                required=["param1"]
            ),
            risk_profile=ToolRiskProfile(
                risk_level="medium",
                is_read_only=True,
                requires_human_approval=False,
                data_sensitivity="L2",
                network_access_required=False,
                filesystem_access_required=False,
                credential_access_required=False,
            ),
            capability=ToolCapability(),
        )
        
        digest = tool.compute_schema_digest()
        assert len(digest) == 64  # SHA256 hex digest
        
        # 相同内容应产生相同摘要
        digest2 = tool.compute_schema_digest()
        assert digest == digest2
    
    def test_breaking_change_detection(self):
        """测试破坏性变更检测"""
        old_tool = ToolSchema(
            tool_name="test_tool",
            description="Old version",
            input_schema=ToolInputSchema(
                properties={"param1": {"type": "string"}},
                required=["param1"]
            ),
            risk_profile=ToolRiskProfile(
                risk_level="low",
                is_read_only=True,
                requires_human_approval=False,
                data_sensitivity="L2",
                network_access_required=False,
                filesystem_access_required=False,
                credential_access_required=False,
            ),
            capability=ToolCapability(),
        )
        
        # 添加必需参数 = 破坏性变更
        new_tool_breaking = ToolSchema(
            tool_name="test_tool",
            description="New version",
            input_schema=ToolInputSchema(
                properties={
                    "param1": {"type": "string"},
                    "param2": {"type": "number"}
                },
                required=["param1", "param2"]  # 新必需参数
            ),
            risk_profile=old_tool.risk_profile,
            capability=old_tool.capability,
        )
        
        assert new_tool_breaking.is_breaking_change(old_tool) is True
        
        # 添加可选参数 = 安全变更
        new_tool_safe = ToolSchema(
            tool_name="test_tool",
            description="New version",
            input_schema=ToolInputSchema(
                properties={
                    "param1": {"type": "string"},
                    "param2": {"type": "number"}
                },
                required=["param1"]  # 保持原有必需参数
            ),
            risk_profile=old_tool.risk_profile,
            capability=old_tool.capability,
        )
        
        assert new_tool_safe.is_breaking_change(old_tool) is False


class TestConnectorRegistry:
    """测试连接器注册表"""
    
    def test_connector_registration(self):
        """测试连接器注册"""
        registry = ConnectorRegistry()
        
        connector = self._create_test_connector("conn_001")
        registry.register(connector)
        
        # 验证注册成功
        assert registry.count() == 1
        retrieved = registry.get("conn_001")
        assert retrieved is not None
        assert retrieved.connector_id == "conn_001"
    
    def test_list_by_trust_level(self):
        """测试按信任等级查询"""
        registry = ConnectorRegistry()
        
        # 注册不同信任等级的连接器
        conn_l1 = self._create_test_connector("conn_l1", TrustLevel.L1_PLATFORM_MANAGED)
        conn_l2 = self._create_test_connector("conn_l2", TrustLevel.L2_ORG_VERIFIED)
        
        registry.register(conn_l1)
        registry.register(conn_l2)
        
        # 查询 L1
        l1_connectors = registry.list_by_trust_level(TrustLevel.L1_PLATFORM_MANAGED)
        assert len(l1_connectors) == 1
        assert l1_connectors[0].connector_id == "conn_l1"
    
    def _create_test_connector(
        self,
        connector_id: str,
        trust_level: TrustLevel = TrustLevel.L2_ORG_VERIFIED
    ) -> Connector:
        """创建测试用连接器"""
        identity = ConnectorIdentity(
            connector_id=connector_id,
            organization_id="org_test",
            namespace="test",
            display_name="Test Connector",
            version="1.0.0",
            created_by="test_user",
        )
        
        config = ConnectorConfig(
            identity=identity,
            trust_level=trust_level,
            transport=TransportConfig(type=TransportType.HTTP, endpoint="http://localhost"),
            auth=AuthConfig(mode=AuthenticationMode.NONE),
            signature=SignatureVerification(is_signed=False),
        )
        
        status = ConnectorStatus(
            connector_id=connector_id,
            lifecycle_state=ConnectorLifecycleState.ACTIVE,
        )
        
        return Connector(config=config, status=status)


class TestGlobalBlacklist:
    """测试全局黑名单"""
    
    def test_add_connector_to_blacklist(self):
        """测试添加连接器到黑名单"""
        blacklist = GlobalBlacklist()
        
        blacklist.add_connector(
            connector_id="conn_malicious",
            reason="Security vulnerability CVE-2024-001",
            added_by="admin",
            severity="critical"
        )
        
        assert blacklist.is_connector_blocked("conn_malicious") is True
        assert blacklist.is_connector_blocked("conn_safe") is False
    
    def test_namespace_blacklist(self):
        """测试命名空间黑名单"""
        blacklist = GlobalBlacklist()
        
        blacklist.add_namespace(
            namespace="malicious_publisher",
            reason="Known malicious actor",
            added_by="admin"
        )
        
        assert blacklist.is_namespace_blocked("malicious_publisher") is True
        assert blacklist.is_namespace_blocked("trusted_publisher") is False


class TestQuotaManager:
    """测试配额管理"""
    
    def test_quota_initialization(self):
        """测试配额初始化"""
        manager = QuotaManager()
        
        manager.initialize_org_quota("org_001", base_quota=1000.0)
        quota = manager.get_quota("org_001")
        
        assert quota is not None
        assert quota.base_quota == 1000.0
        assert quota.remaining() == 1000.0
    
    def test_quota_consumption(self):
        """测试配额消耗"""
        manager = QuotaManager()
        manager.initialize_org_quota("org_001", base_quota=1000.0)
        
        # 消耗配额
        success = manager.consume_quota("org_001", 100.0)
        assert success is True
        
        quota = manager.get_quota("org_001")
        assert quota.current_usage == 100.0
        assert quota.remaining() == 900.0
    
    def test_quota_exceeded(self):
        """测试配额超限"""
        manager = QuotaManager()
        manager.initialize_org_quota("org_001", base_quota=100.0)
        
        # 消耗超过限额
        success = manager.consume_quota("org_001", 150.0)
        assert success is False
        
        quota = manager.get_quota("org_001")
        assert quota.current_usage == 0.0  # 未消耗


class TestPolicyEngine:
    """测试策略引擎"""
    
    def test_connector_access_allowed(self):
        """测试连接器访问允许"""
        engine = PolicyEngine()
        engine.quota_manager.initialize_org_quota("org_001", base_quota=10000.0)
        
        connector = self._create_test_connector("conn_001")
        
        decision = engine.evaluate_connector_access(
            org_id="org_001",
            connector=connector,
        )
        
        assert decision.allowed is True
    
    def test_connector_blocked_by_blacklist(self):
        """测试黑名单阻止"""
        engine = PolicyEngine()
        engine.global_blacklist.add_connector(
            connector_id="conn_blocked",
            reason="Security issue",
            added_by="admin"
        )
        
        connector = self._create_test_connector("conn_blocked")
        
        decision = engine.evaluate_connector_access(
            org_id="org_001",
            connector=connector,
        )
        
        assert decision.allowed is False
        assert decision.blocked_by == "global_blacklist"
    
    def _create_test_connector(self, connector_id: str) -> Connector:
        """创建测试连接器"""
        identity = ConnectorIdentity(
            connector_id=connector_id,
            organization_id="org_test",
            namespace="test",
            display_name="Test Connector",
            version="1.0.0",
        )
        
        config = ConnectorConfig(
            identity=identity,
            trust_level=TrustLevel.L2_ORG_VERIFIED,
            transport=TransportConfig(type=TransportType.HTTP),
            auth=AuthConfig(mode=AuthenticationMode.NONE),
            signature=SignatureVerification(is_signed=False),
        )
        
        status = ConnectorStatus(
            connector_id=connector_id,
            lifecycle_state=ConnectorLifecycleState.ACTIVE,
        )
        
        return Connector(config=config, status=status)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
