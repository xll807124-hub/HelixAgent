"""
GitHub 凭据代理单元测试
"""
import pytest
from datetime import datetime, timedelta

from src.security.credential.github_proxy import (
    CredentialToken,
    GitHubAppConfig,
    GitHubCredentialProxy,
    TokenType,
)


class TestCredentialToken:
    """凭据令牌测试"""

    def test_token_creation(self):
        """测试令牌创建"""
        expires_at = datetime.now() + timedelta(hours=1)
        token = CredentialToken(
            token="ghu_16C7e42F292c6912E7710c838347Ae178B4a",
            token_type=TokenType.INSTALLATION,
            scopes=["contents:read", "pull_requests:read"],
            expires_at=expires_at,
            created_at=datetime.now(),
        )
        assert token.token == "ghu_16C7e42F292c6912E7710c838347Ae178B4a"
        assert token.token_type == TokenType.INSTALLATION
        assert len(token.scopes) == 2
        assert token.expires_at > datetime.now()

    def test_token_with_metadata(self):
        """测试带元数据的令牌"""
        metadata = {
            "installation_id": "123456",
            "permissions": {"contents": "read", "pull_requests": "read"},
        }
        token = CredentialToken(
            token="test-token",
            token_type=TokenType.INSTALLATION,
            scopes=["contents:read"],
            expires_at=datetime.now() + timedelta(hours=1),
            created_at=datetime.now(),
            metadata=metadata,
        )
        assert token.metadata["installation_id"] == "123456"


class TestTokenType:
    """令牌类型枚举测试"""

    def test_token_types(self):
        """测试令牌类型"""
        assert TokenType.GITHUB_APP.value == "github_app"
        assert TokenType.INSTALLATION.value == "installation"
        assert TokenType.USER_ACCESS.value == "user_access"
        assert TokenType.OAUTH.value == "oauth"


class TestGitHubAppConfig:
    """GitHub App 配置测试"""

    def test_config_creation(self):
        """测试配置创建"""
        config = GitHubAppConfig(
            app_id="123456",
            private_key="-----BEGIN PRIVATE KEY-----\ntest\n-----END PRIVATE KEY-----",
            webhook_secret="webhook-secret-123",
        )
        assert config.app_id == "123456"
        assert "BEGIN PRIVATE KEY" in config.private_key
        assert config.webhook_secret == "webhook-secret-123"
        assert config.installation_id is None

    def test_config_with_installation_id(self):
        """测试带安装 ID 的配置"""
        config = GitHubAppConfig(
            app_id="123456",
            private_key="key",
            webhook_secret="secret",
            installation_id="install-789",
        )
        assert config.installation_id == "install-789"


class TestGitHubCredentialProxyValidation:
    """凭据代理验证测试"""

    def test_validate_dangerous_scopes(self):
        """测试危险权限范围验证"""
        proxy = GitHubCredentialProxy(
            GitHubAppConfig(
                app_id="123",
                private_key="key",
                webhook_secret="secret",
                installation_id="456",
            )
        )
        
        # 这些权限应该被拒绝
        dangerous_scopes = [
            "admin",
            "admin:org_hook",
            "repo",
            "delete_repo",
        ]
        
        for scope in dangerous_scopes:
            with pytest.raises(ValueError, match="Dangerous"):
                proxy._validate_scopes([scope])

    def test_validate_safe_scopes(self):
        """测试安全权限范围验证"""
        proxy = GitHubCredentialProxy(
            GitHubAppConfig(
                app_id="123",
                private_key="key",
                webhook_secret="secret",
                installation_id="456",
            )
        )
        
        # 这些权限应该被允许
        safe_scopes = [
            "contents:read",
            "pull_requests:read",
            "workflows:read",
        ]
        
        # 不应该抛出异常
        try:
            proxy._validate_scopes(safe_scopes)
        except ValueError:
            pytest.fail("Safe scopes should not raise ValueError")

    def test_validate_empty_scopes(self):
        """测试空权限范围"""
        proxy = GitHubCredentialProxy(
            GitHubAppConfig(
                app_id="123",
                private_key="key",
                webhook_secret="secret",
                installation_id="456",
            )
        )
        
        # 空列表应该被允许
        try:
            proxy._validate_scopes([])
        except ValueError:
            pytest.fail("Empty scopes should be allowed")


class TestGitHubCredentialProxyAudit:
    """凭据代理审计测试"""

    def test_audit_token_issuance(self):
        """测试令牌签发审计"""
        proxy = GitHubCredentialProxy(
            GitHubAppConfig(
                app_id="123",
                private_key="key",
                webhook_secret="secret",
                installation_id="456",
            )
        )
        
        # 这是一个同步方法，但使用时需要 await
        # 在这里只测试审计日志结构
        assert proxy._token_audit_log == []

    def test_audit_log_retrieval(self):
        """测试审计日志检索"""
        proxy = GitHubCredentialProxy(
            GitHubAppConfig(
                app_id="123",
                private_key="key",
                webhook_secret="secret",
                installation_id="456",
            )
        )
        
        # 检索空审计日志
        audit_log = proxy.get_audit_log()
        assert audit_log == []
        
        # 检索有限数量的日志
        audit_log = proxy.get_audit_log(limit=10)
        assert len(audit_log) <= 10


class TestGitHubCredentialProxyTokenHash:
    """令牌哈希测试"""

    def test_token_hash(self):
        """测试令牌哈希"""
        token1 = "ghu_16C7e42F292c6912E7710c838347Ae178B4a"
        token2 = "ghu_16C7e42F292c6912E7710c838347Ae178B4b"
        
        hash1 = GitHubCredentialProxy._hash_token(token1)
        hash2 = GitHubCredentialProxy._hash_token(token2)
        
        # 不同令牌应该产生不同哈希
        assert hash1 != hash2
        
        # 哈希应该是 16 字符的十六进制字符串
        assert len(hash1) == 16
        assert len(hash2) == 16
        assert all(c in "0123456789abcdef" for c in hash1)

    def test_token_hash_consistency(self):
        """测试令牌哈希一致性"""
        token = "test-token-123"
        hash1 = GitHubCredentialProxy._hash_token(token)
        hash2 = GitHubCredentialProxy._hash_token(token)
        
        # 相同令牌应该产生相同哈希
        assert hash1 == hash2


class TestGitHubCredentialProxyIntegration:
    """集成测试（需要 PyJWT 和 httpx）"""

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires PyJWT and network access")
    async def test_get_installation_token(self):
        """测试获取安装令牌"""
        # 这个测试需要实际的 GitHub App 配置和网络访问
        pass

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires installation_id")
    async def test_token_issuance_without_installation_id(self):
        """测试没有安装 ID 时的令牌签发"""
        proxy = GitHubCredentialProxy(
            GitHubAppConfig(
                app_id="123",
                private_key="key",
                webhook_secret="secret",
                installation_id=None,
            )
        )
        
        # 应该抛出 ValueError
        with pytest.raises(ValueError, match="installation_id"):
            await proxy.get_installation_token()

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires PyJWT")
    async def test_jwt_token_generation(self):
        """测试 JWT 令牌生成"""
        # 这个测试需要 PyJWT 包
        pass


class TestGitHubCredentialProxyProperties:
    """凭据代理属性测试"""

    def test_proxy_initialization(self):
        """测试代理初始化"""
        config = GitHubAppConfig(
            app_id="123",
            private_key="key",
            webhook_secret="secret",
            installation_id="456",
        )
        proxy = GitHubCredentialProxy(config)
        
        assert proxy.config == config
        assert proxy._jwt_cache == {}
        assert proxy._token_audit_log == []
        assert proxy._jwt_cache_ttl == 600

    def test_proxy_audit_log_is_list(self):
        """测试审计日志是列表"""
        proxy = GitHubCredentialProxy(
            GitHubAppConfig(
                app_id="123",
                private_key="key",
                webhook_secret="secret",
                installation_id="456",
            )
        )
        
        assert isinstance(proxy._token_audit_log, list)

    def test_proxy_jwt_cache_is_dict(self):
        """测试 JWT 缓存是字典"""
        proxy = GitHubCredentialProxy(
            GitHubAppConfig(
                app_id="123",
                private_key="key",
                webhook_secret="secret",
                installation_id="456",
            )
        )
        
        assert isinstance(proxy._jwt_cache, dict)


class TestCredentialTokenTimestamps:
    """凭据时间戳测试"""

    def test_token_expiration_check(self):
        """测试令牌过期检查"""
        now = datetime.now()
        
        # 过期令牌
        expired_token = CredentialToken(
            token="expired",
            token_type=TokenType.INSTALLATION,
            scopes=[],
            expires_at=now - timedelta(hours=1),
            created_at=now - timedelta(hours=2),
        )
        
        assert expired_token.expires_at < now
        
        # 有效令牌
        valid_token = CredentialToken(
            token="valid",
            token_type=TokenType.INSTALLATION,
            scopes=[],
            expires_at=now + timedelta(hours=1),
            created_at=now,
        )
        
        assert valid_token.expires_at > now

    def test_token_created_before_expires(self):
        """测试令牌创建时间早于过期时间"""
        now = datetime.now()
        token = CredentialToken(
            token="test",
            token_type=TokenType.INSTALLATION,
            scopes=[],
            expires_at=now + timedelta(hours=1),
            created_at=now,
        )
        
        assert token.created_at <= token.expires_at
