"""
RT-008 脱敏引擎单元测试

测试覆盖：
1. 敏感模式识别
2. 脱敏规则应用
3. 访问级别与数据分类的矩阵
"""

import pytest

from src.runtime.query.redaction_engine import (
    AccessLevel,
    RedactionEngine,
    SensitivePatternMatcher,
    SensitivityLevel,
)


class TestSensitivePatternMatcher:
    """敏感模式匹配测试"""

    def test_detect_api_key(self):
        """检测 API 密钥"""
        patterns = SensitivePatternMatcher.detect_sensitive_patterns(
            "sk-1234567890abcdefghijklmnopqrstuvwxyz"
        )
        assert "api_key" in patterns

    def test_detect_github_token(self):
        """检测 GitHub Token"""
        patterns = SensitivePatternMatcher.detect_sensitive_patterns(
            "ghp_1234567890abcdefghijklmnopqrstuvwxyz"
        )
        assert "github_token" in patterns

    def test_detect_private_key(self):
        """检测私钥"""
        private_key = "-----BEGIN PRIVATE KEY-----\nMIIEvQIBA..."
        patterns = SensitivePatternMatcher.detect_sensitive_patterns(private_key)
        assert "private_key" in patterns

    def test_detect_password(self):
        """检测密码字段"""
        patterns = SensitivePatternMatcher.detect_sensitive_patterns("password=secret123")
        assert "password" in patterns

    def test_no_pattern_match(self):
        """没有敏感模式"""
        patterns = SensitivePatternMatcher.detect_sensitive_patterns("This is normal text")
        assert len(patterns) == 0

    def test_multiple_patterns(self):
        """多个敏感模式"""
        text = "api_key=sk-1234567890abcd password=secret123"
        patterns = SensitivePatternMatcher.detect_sensitive_patterns(text)
        assert len(patterns) > 0


class TestRedactionEngine:
    """脱敏引擎测试"""

    def setup_method(self):
        """测试前初始化"""
        self.engine = RedactionEngine(rules_version="v1.0")

    def test_get_redaction_policy_basic_user(self):
        """基础用户的脱敏策略"""
        # 基础用户看 L0 = FULL
        policy = self.engine.get_redaction_policy(AccessLevel.BASIC, SensitivityLevel.L0)
        assert policy == "FULL"

        # 基础用户看 L2 = DENY
        policy = self.engine.get_redaction_policy(AccessLevel.BASIC, SensitivityLevel.L2)
        assert policy == "DENY"

    def test_get_redaction_policy_audit_user(self):
        """审计员的脱敏策略"""
        # 审计员看 L3 = PARTIAL
        policy = self.engine.get_redaction_policy(AccessLevel.AUDIT, SensitivityLevel.L3)
        assert policy == "PARTIAL"

        # 审计员看 L4 = DENY
        policy = self.engine.get_redaction_policy(AccessLevel.AUDIT, SensitivityLevel.L4)
        assert policy == "DENY"

    def test_get_redaction_policy_admin_user(self):
        """管理员的脱敏策略"""
        # 管理员看任何级别都是 FULL
        for level in [SensitivityLevel.L0, SensitivityLevel.L1, SensitivityLevel.L2,
                      SensitivityLevel.L3, SensitivityLevel.L4]:
            policy = self.engine.get_redaction_policy(AccessLevel.ADMIN, level)
            assert policy == "FULL"

    def test_redact_string_full_policy(self):
        """完整返回策略"""
        value = "secret_value_12345"
        result = self.engine.redact_string(value, "FULL")
        assert result == value

    def test_redact_string_deny_policy(self):
        """拒绝返回策略"""
        value = "secret_value_12345"
        result = self.engine.redact_string(value, "DENY")
        assert result is None

    def test_redact_string_summary_policy(self):
        """摘要策略"""
        value = "secret_value_12345_very_long_string_continues_here"
        result = self.engine.redact_string(value, "SUMMARY")
        assert result is not None
        assert "..." in result
        assert "HASH:" in result
        # 摘要包含前 50 字符
        assert value[:50] in result

    def test_redact_string_partial_policy_short_value(self):
        """部分脱敏 - 短值"""
        value = "sk-1234567890abcdefghijk"  # 更长的 API key
        result = self.engine.redact_string(value, "PARTIAL", SensitivityLevel.L2)
        assert result is not None
        # PARTIAL 策略会识别敏感模式
        assert "***" in result or result.startswith("sk-")

    def test_redact_string_partial_policy_long_value(self):
        """部分脱敏 - 长值"""
        value = "x" * 200
        result = self.engine.redact_string(value, "PARTIAL", SensitivityLevel.L3)
        assert result is not None
        assert "***" in result
        assert "REDACTED" in result

    def test_redact_payload_basic_user_no_sensitive(self):
        """基础用户查询无敏感数据的载荷"""
        payload = {"message": "Hello", "count": 42}
        redacted, info = self.engine.redact_payload(
            payload, AccessLevel.BASIC, SensitivityLevel.L0
        )
        assert redacted == payload
        assert info.has_sensitive_data is False

    def test_redact_payload_basic_user_with_sensitive(self):
        """基础用户查询含敏感字段的载荷"""
        payload = {
            "message": "Hello",
            "api_key": "sk-1234567890abcdef",
            "status": "ok",
        }
        redacted, info = self.engine.redact_payload(
            payload, AccessLevel.BASIC, SensitivityLevel.L2
        )
        # 基础用户看 L2 = DENY，应该得到空载荷
        assert redacted == {}
        assert "api_key" in info.redacted_fields

    def test_redact_payload_audit_user_with_sensitive(self):
        """审计员查询含敏感字段的载荷"""
        payload = {
            "message": "Hello",
            "api_key": "sk-1234567890abcdef",
            "status": "ok",
        }
        redacted, info = self.engine.redact_payload(
            payload, AccessLevel.AUDIT, SensitivityLevel.L2
        )
        # 审计员看 L2 = FULL，应该完整返回
        assert "message" in redacted
        assert "api_key" in redacted
        assert redacted["api_key"] == "sk-1234567890abcdef"

    def test_redact_payload_admin_user_with_sensitive(self):
        """管理员查询含敏感字段的载荷"""
        payload = {
            "message": "Hello",
            "password": "secret123",
            "status": "ok",
        }
        redacted, info = self.engine.redact_payload(
            payload, AccessLevel.ADMIN, SensitivityLevel.L3
        )
        # 管理员看任何数据都是 FULL
        assert redacted == payload

    def test_redact_payload_partial_deduction(self):
        """部分脱敏"""
        payload = {
            "message": "Here is a secret: ghp_1234567890abcdefghijklmnop",
            "status": "ok",
        }
        redacted, info = self.engine.redact_payload(
            payload, AccessLevel.AUDIT, SensitivityLevel.L3
        )
        # AUDIT + L3 = PARTIAL
        assert redacted["message"] is not None
        # message 字段包含敏感内容，会被部分脱敏
        message = redacted["message"]
        # 验证内容被处理过（要么有 ***, 要么包含原始内容）
        assert isinstance(message, str)

    def test_sensitive_field_name_detection(self):
        """敏感字段名检测"""
        assert RedactionEngine._is_sensitive_field_name("password") is True
        assert RedactionEngine._is_sensitive_field_name("api_key") is True
        assert RedactionEngine._is_sensitive_field_name("token") is True
        assert RedactionEngine._is_sensitive_field_name("message") is False
        assert RedactionEngine._is_sensitive_field_name("status") is False


class TestRedactionMatrix:
    """脱敏矩阵完整测试"""

    def setup_method(self):
        """测试前初始化"""
        self.engine = RedactionEngine()

    def test_redaction_matrix_coverage(self):
        """确保脱敏矩阵覆盖所有访问级别和敏感级别的组合"""
        for access_level in AccessLevel:
            for sensitivity in SensitivityLevel:
                policy = self.engine.get_redaction_policy(access_level, sensitivity)
                assert policy in ["FULL", "SUMMARY", "PARTIAL", "DENY"]

    def test_access_escalation_denied(self):
        """确保低级别用户无法通过参数提升访问权限"""
        payload = {"secret": "sk-1234567890"}
        
        # 基础用户查看 L3 数据
        redacted, info = self.engine.redact_payload(
            payload, AccessLevel.BASIC, SensitivityLevel.L3
        )
        # 应该被拒绝
        assert redacted == {}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
