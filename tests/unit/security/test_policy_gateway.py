"""
PolicyGateway 单元测试

测试覆盖：
1. 前置校验（工具存在性、Schema、风险级别）
2. 后置校验（输出格式、敏感信息检测）
3. 策略决策逻辑
4. 边界场景
"""
import pytest

from src.security.policy_gateway import (
    PolicyDecision,
    SimplifiedPolicyGateway,
)
from src.tools import BaseTool, ExecutionContext, RiskLevel, ToolRegistry, ToolResult


class LowRiskTool(BaseTool):
    """低风险测试工具"""

    @property
    def name(self) -> str:
        return "low-risk-tool"

    @property
    def description(self) -> str:
        return "Low risk tool"

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "param": {"type": "string"}
            },
            "required": ["param"]
        }

    @property
    def output_schema(self) -> dict:
        return {"type": "object"}

    @property
    def risk_level(self) -> RiskLevel:
        return RiskLevel.LOW

    async def execute(self, params: dict, context: ExecutionContext) -> ToolResult:
        return ToolResult(success=True, output={"result": "ok"})


class HighRiskTool(BaseTool):
    """高风险测试工具"""

    @property
    def name(self) -> str:
        return "high-risk-tool"

    @property
    def description(self) -> str:
        return "High risk tool"

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string"}
            },
            "required": ["command"]
        }

    @property
    def output_schema(self) -> dict:
        return {"type": "object"}

    @property
    def risk_level(self) -> RiskLevel:
        return RiskLevel.HIGH

    async def execute(self, params: dict, context: ExecutionContext) -> ToolResult:
        return ToolResult(success=True, output={"result": "executed"})


@pytest.fixture
def tool_registry():
    """创建测试用工具注册表"""
    registry = ToolRegistry()
    registry.register(LowRiskTool())
    registry.register(HighRiskTool())
    return registry


@pytest.fixture
def policy_gateway(tool_registry):
    """创建策略网关"""
    return SimplifiedPolicyGateway(tool_registry)


class TestSimplifiedPolicyGateway:
    """SimplifiedPolicyGateway 测试套件"""

    @pytest.mark.asyncio
    async def test_pre_check_tool_not_found(self, policy_gateway):
        """测试：前置检查 - 工具不存在"""
        result = await policy_gateway.check_pre_execution(
            action_id="action-001",
            tool_name="nonexistent-tool",
            params={},
            context={}
        )

        assert result.decision == PolicyDecision.DENY
        assert "not found" in result.reason.lower()
        assert len(result.violations) > 0

    @pytest.mark.asyncio
    async def test_pre_check_invalid_input(self, policy_gateway):
        """测试：前置检查 - 输入参数无效"""
        result = await policy_gateway.check_pre_execution(
            action_id="action-001",
            tool_name="low-risk-tool",
            params={},  # 缺少必填字段 "param"
            context={}
        )

        assert result.decision == PolicyDecision.DENY
        assert "validation failed" in result.reason.lower()
        assert any("param" in v for v in result.violations)

    @pytest.mark.asyncio
    async def test_pre_check_low_risk_tool_allowed(self, policy_gateway):
        """测试：前置检查 - 低风险工具自动通过"""
        result = await policy_gateway.check_pre_execution(
            action_id="action-001",
            tool_name="low-risk-tool",
            params={"param": "value"},
            context={}
        )

        assert result.decision == PolicyDecision.ALLOW
        assert "passed" in result.reason.lower()
        assert result.metadata["risk_level"] == "LOW"

    @pytest.mark.asyncio
    async def test_pre_check_high_risk_tool_requires_approval(self, policy_gateway):
        """测试：前置检查 - 高风险工具需要审批"""
        result = await policy_gateway.check_pre_execution(
            action_id="action-001",
            tool_name="high-risk-tool",
            params={"command": "ls"},
            context={}
        )

        assert result.decision == PolicyDecision.REQUIRES_APPROVAL
        assert "approval" in result.reason.lower()
        assert result.metadata["risk_level"] == "HIGH"
        assert result.metadata["requires_approval"] is True

    @pytest.mark.asyncio
    async def test_post_check_output_not_dict(self, policy_gateway):
        """测试：后置检查 - 输出不是字典"""
        result = await policy_gateway.check_post_execution(
            action_id="action-001",
            tool_name="low-risk-tool",
            output="string output",  # 应该是 dict
            context={}
        )

        assert result.decision == PolicyDecision.DENY
        assert "validation" in result.reason.lower()
        assert any("dict" in v.lower() for v in result.violations)

    @pytest.mark.asyncio
    async def test_post_check_sensitive_api_key(self, policy_gateway):
        """测试：后置检查 - 检测到 API Key"""
        output = {
            "result": "success",
            "config": "api_key=placeholder-not-a-real-key-0000"
        }

        result = await policy_gateway.check_post_execution(
            action_id="action-001",
            tool_name="low-risk-tool",
            output=output,
            context={}
        )

        assert result.decision == PolicyDecision.DENY
        assert "sensitive" in result.reason.lower()
        assert "api_key" in result.metadata["sensitive_patterns"]

    @pytest.mark.asyncio
    async def test_post_check_sensitive_password(self, policy_gateway):
        """测试：后置检查 - 检测到密码"""
        output = {
            "credentials": "password=SuperSecret123!@#"
        }

        result = await policy_gateway.check_post_execution(
            action_id="action-001",
            tool_name="low-risk-tool",
            output=output,
            context={}
        )

        assert result.decision == PolicyDecision.DENY
        assert "sensitive" in result.reason.lower()
        assert "password" in result.metadata["sensitive_patterns"]

    @pytest.mark.asyncio
    async def test_post_check_sensitive_private_key(self, policy_gateway):
        """测试：后置检查 - 检测到私钥"""
        output = {
            "key": "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA..."
        }

        result = await policy_gateway.check_post_execution(
            action_id="action-001",
            tool_name="low-risk-tool",
            output=output,
            context={}
        )

        assert result.decision == PolicyDecision.DENY
        assert "sensitive" in result.reason.lower()
        assert "private_key" in result.metadata["sensitive_patterns"]

    @pytest.mark.asyncio
    async def test_post_check_clean_output_allowed(self, policy_gateway):
        """测试：后置检查 - 干净输出通过"""
        output = {
            "result": "success",
            "data": "some normal data",
            "count": 42
        }

        result = await policy_gateway.check_post_execution(
            action_id="action-001",
            tool_name="low-risk-tool",
            output=output,
            context={}
        )

        assert result.decision == PolicyDecision.ALLOW
        assert "passed" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_post_check_output_size_limit(self, policy_gateway):
        """测试：后置检查 - 输出大小超限"""
        # 创建超过 10MB 的输出
        large_output = {
            "data": "x" * (11 * 1024 * 1024)
        }

        result = await policy_gateway.check_post_execution(
            action_id="action-001",
            tool_name="low-risk-tool",
            output=large_output,
            context={}
        )

        assert result.decision == PolicyDecision.DENY
        assert "size" in result.reason.lower()
        assert any("large" in v.lower() for v in result.violations)

    @pytest.mark.asyncio
    async def test_medium_risk_tool_allowed(self, tool_registry, policy_gateway):
        """测试：中风险工具自动通过（不需要审批）"""

        # 注册中风险工具
        class MediumRiskTool(BaseTool):
            @property
            def name(self) -> str:
                return "medium-risk-tool"

            @property
            def description(self) -> str:
                return "Medium risk"

            @property
            def input_schema(self) -> dict:
                return {"type": "object", "properties": {}}

            @property
            def output_schema(self) -> dict:
                return {"type": "object"}

            @property
            def risk_level(self) -> RiskLevel:
                return RiskLevel.MEDIUM

            async def execute(self, params: dict, context: ExecutionContext) -> ToolResult:
                return ToolResult(success=True, output={})

        tool_registry.register(MediumRiskTool())

        result = await policy_gateway.check_pre_execution(
            action_id="action-001",
            tool_name="medium-risk-tool",
            params={},
            context={}
        )

        assert result.decision == PolicyDecision.ALLOW
        assert result.metadata["risk_level"] == "MEDIUM"

    @pytest.mark.asyncio
    async def test_multiple_sensitive_patterns(self, policy_gateway):
        """测试：检测到多种敏感信息"""
        output = {
            "config": "api_key=placeholder-not-a-real-key-0000",
            "auth": "password=MyPassword123!@#$",
            "token": "token=abc123def456ghi789jkl012mno345"
        }

        result = await policy_gateway.check_post_execution(
            action_id="action-001",
            tool_name="low-risk-tool",
            output=output,
            context={}
        )

        assert result.decision == PolicyDecision.DENY
        patterns = result.metadata["sensitive_patterns"]
        assert "api_key" in patterns
        assert "password" in patterns
        assert "token" in patterns
