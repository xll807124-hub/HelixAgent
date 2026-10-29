"""
MCP Connector Governance - Authorization Module
授权管理模块：OAuth 2.1、STDIO、API Key（已废弃）认证
"""

from .auth_manager import AuthorizationManager
from .credential_adapter import (
    ApprovalDecision,
    CredentialIssuanceError,
    SEC005CredentialProxyClient,
)

__all__ = [
    "AuthorizationManager",
    "ApprovalDecision",
    "CredentialIssuanceError",
    "SEC005CredentialProxyClient",
]
