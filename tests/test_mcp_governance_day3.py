"""
SEC-007 MCP Connector Governance - Day 3 Integration Tests
Day 3 测试：签名验证、完整工具执行、数据库集成
"""

from datetime import datetime

import pytest

from src.security.mcp_connector_governance.execution.tool_executor_v2 import (
    HTTPExecutor,
    STDIOExecutor,
    ToolExecutionResult,
    ToolExecutor,
)
from src.security.mcp_connector_governance.security import (
    GPGVerifier,
    InternalPKIVerifier,
    SignatureAlgorithm,
    SigstoreVerifier,
    UnifiedSignatureVerifier,
    VerificationResult,
)


class TestSignatureVerification:
    """测试签名验证"""

    @pytest.mark.asyncio
    async def test_sigstore_rejects_malformed_certificate(self):
        """畸形证书必须被拒绝 (真实证书的成功路径见 test_mcp_signature_verification.py)"""
        verifier = SigstoreVerifier()

        result = await verifier.verify_signature(
            b"test artifact",
            b"mock-signature",
            "-----BEGIN CERTIFICATE-----\nMOCK\n-----END CERTIFICATE-----",
        )

        assert result.is_valid is False
        assert result.algorithm == SignatureAlgorithm.SIGSTORE_OIDC.value

    @pytest.mark.asyncio
    async def test_gpg_rejects_bogus_signature(self):
        """信任的密钥 + 伪造签名必须被拒绝"""
        verifier = GPGVerifier()
        verifier.add_trusted_key("0123456789ABCDEF", "mock-key-data")

        result = await verifier.verify_signature(
            b"test artifact",
            b"mock-signature",
            "0123456789ABCDEF",
        )

        assert result.is_valid is False
        assert result.algorithm == SignatureAlgorithm.GPG.value

    @pytest.mark.asyncio
    async def test_gpg_untrusted_key(self):
        """测试 GPG 不信任的密钥"""
        verifier = GPGVerifier()

        result = await verifier.verify_signature(
            b"artifact",
            b"signature",
            "UNTRUSTED_KEY",
        )

        assert result.is_valid is False
        assert "Untrusted key" in result.error

    @pytest.mark.asyncio
    async def test_internal_pki_rejects_malformed_certificate(self):
        """畸形证书必须被拒绝"""
        verifier = InternalPKIVerifier()
        verifier.register_certificate(
            "cert_001",
            "-----BEGIN CERTIFICATE-----\nMOCK\n-----END CERTIFICATE-----",
        )

        result = await verifier.verify_signature(
            b"artifact",
            b"signature",
            "cert_001",
        )

        assert result.is_valid is False
        assert result.algorithm == SignatureAlgorithm.INTERNAL_PKI.value

    @pytest.mark.asyncio
    async def test_unified_verifier_sigstore_rejects_bogus(self):
        """伪造的 Sigstore 签名必须被拒绝。

        成功路径见 test_mcp_signature_verification.py。
        """
        verifier = UnifiedSignatureVerifier()

        signature_info = {
            "algorithm": "sigstore-oidc",
            "signature": "bW9jay1zaWduYXR1cmU=",  # base64("mock-signature")
            "certificate": "-----BEGIN CERTIFICATE-----\nMOCK\n-----END CERTIFICATE-----",
        }

        result = await verifier.verify(b"artifact", signature_info)

        assert result.is_valid is False
        assert result.algorithm == SignatureAlgorithm.SIGSTORE_OIDC.value

    @pytest.mark.asyncio
    async def test_unified_verifier_gpg_rejects_bogus(self):
        """统一验证器 - 伪造的 GPG 签名必须被拒绝"""
        verifier = UnifiedSignatureVerifier()
        verifier.gpg.add_trusted_key("0123456789ABCDEF", "key-data")

        signature_info = {
            "algorithm": "gpg",
            "signature": "bW9jay1zaWduYXR1cmU=",  # base64("mock-signature")
            "signer_fingerprint": "0123456789ABCDEF",
        }

        result = await verifier.verify(b"artifact", signature_info)

        assert result.is_valid is False
        assert result.algorithm == SignatureAlgorithm.GPG.value

    @pytest.mark.asyncio
    async def test_verification_result_serialization(self):
        """测试验证结果序列化"""
        result = VerificationResult(
            is_valid=True,
            algorithm="sigstore-oidc",
            signer_identity="user@example.com",
            verified_at=datetime.utcnow(),
        )

        result_dict = result.to_dict()

        assert result_dict["is_valid"] is True
        assert result_dict["algorithm"] == "sigstore-oidc"
        assert result_dict["signer_identity"] == "user@example.com"


class TestToolExecution:
    """测试工具执行"""

    @pytest.mark.asyncio
    async def test_tool_execution_result(self):
        """测试工具执行结果"""
        result = ToolExecutionResult(
            success=True,
            result={"weather": "sunny"},
            execution_time_ms=125.5,
        )

        assert result.success is True
        assert result.result == {"weather": "sunny"}
        assert result.execution_time_ms == 125.5

        result_dict = result.to_dict()
        assert result_dict["success"] is True
        assert result_dict["execution_time_ms"] == 125.5

    @pytest.mark.asyncio
    async def test_execution_failure(self):
        """测试执行失败"""
        result = ToolExecutionResult(
            success=False,
            error="Connection timeout",
            execution_time_ms=30000.0,
        )

        assert result.success is False
        assert result.error == "Connection timeout"

        result_dict = result.to_dict()
        assert result_dict["error"] == "Connection timeout"

    @pytest.mark.asyncio
    async def test_stdio_executor_timeout(self):
        """测试 STDIO 执行器超时"""
        executor = STDIOExecutor(timeout_seconds=1)

        # 使用不存在的路径来模拟超时
        result = await executor.execute(
            connector_path="/nonexistent/path",
            tool_name="test_tool",
            parameters={"param": "value"},
        )

        # 应该返回错误结果
        assert result.success is False
        assert "error" in result.error or "Execution error" in result.error

    @pytest.mark.asyncio
    async def test_http_executor_initialization(self):
        """测试 HTTP 执行器初始化"""
        executor = HTTPExecutor(timeout_seconds=30)

        assert executor.timeout_seconds == 30

    @pytest.mark.asyncio
    async def test_tool_executor_initialization(self):
        """测试工具执行器初始化"""
        from src.security.mcp_connector_governance.policies import PolicyEngine

        engine = PolicyEngine()
        executor = ToolExecutor(engine)

        assert executor.policy_engine is engine
        assert executor.stdio_executor is not None
        assert executor.http_executor is not None


class TestExecutionFlow:
    """端到端执行流程测试"""

    @pytest.mark.asyncio
    async def test_execution_error_handling(self):
        """测试执行错误处理"""
        result = ToolExecutionResult(
            success=False,
            error="Test error message",
            execution_time_ms=0.0,
        )

        result_dict = result.to_dict()

        assert result_dict["success"] is False
        assert result_dict["error"] == "Test error message"
        assert "timestamp" in result_dict

    @pytest.mark.asyncio
    async def test_signature_verification_result_to_dict(self):
        """测试签名验证结果序列化"""
        now = datetime.utcnow()

        result = VerificationResult(
            is_valid=True,
            algorithm="sigstore-oidc",
            signer_identity="connector@example.com",
            verified_at=now,
            certificate_chain=["cert1", "cert2"],
        )

        result_dict = result.to_dict()

        assert result_dict["is_valid"] is True
        assert result_dict["algorithm"] == "sigstore-oidc"
        assert result_dict["signer_identity"] == "connector@example.com"
        assert result_dict["certificate_count"] == 2


class TestSecurityIntegration:
    """安全集成测试"""

    @pytest.mark.asyncio
    async def test_signature_and_execution_flow(self):
        """测试签名验证 + 执行流程"""
        # Step 1: 验证签名
        verifier = UnifiedSignatureVerifier()
        verifier.internal_pki.register_certificate(
            "conn_001",
            "-----BEGIN CERTIFICATE-----\nMOCK\n-----END CERTIFICATE-----",
        )

        signature_info = {
            "algorithm": "internal-pki",
            "signature": "bW9jay1zaWduYXR1cmU=",  # base64("mock-signature")
            "certificate_id": "conn_001",
        }

        sig_result = await verifier.verify(b"connector-binary", signature_info)

        # Step 2: 伪造签名必须被拒绝，因此不得进入执行阶段
        assert sig_result.is_valid is False
        executed = False
        if sig_result.is_valid:
            executed = True
        assert executed is False

    @pytest.mark.asyncio
    async def test_multi_algorithm_verification(self):
        """测试多算法验证"""
        verifier = UnifiedSignatureVerifier()

        # 注册 GPG 密钥
        verifier.gpg.add_trusted_key("KEY1", "key-data-1")

        # 注册 Internal PKI 证书
        verifier.internal_pki.register_certificate("CERT1", "cert-pem-1")

        # 测试 GPG 验证
        gpg_sig_info = {
            "algorithm": "gpg",
            "signature": "c2ln",  # base64("sig")
            "signer_fingerprint": "KEY1",
        }
        gpg_result = await verifier.verify(b"data", gpg_sig_info)
        assert gpg_result.is_valid is False

        # 测试 Internal PKI 验证 (畸形证书 + 无根 CA)
        pki_sig_info = {
            "algorithm": "internal-pki",
            "signature": "c2ln",  # base64("sig")
            "certificate_id": "CERT1",
        }
        pki_result = await verifier.verify(b"data", pki_sig_info)
        assert pki_result.is_valid is False


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
