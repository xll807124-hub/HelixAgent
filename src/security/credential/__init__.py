"""
凭据代理模块

对齐设计文档：REQ-SEC-005 凭据代理
"""
from .github_proxy import (
    CredentialToken,
    GitHubAppConfig,
    GitHubCredentialProxy,
    TokenType,
)

__all__ = [
    "GitHubCredentialProxy",
    "GitHubAppConfig",
    "CredentialToken",
    "TokenType",
]
