"""
RBAC (Role-Based Access Control) 模块。

实现用户、组织、项目、仓库、路径和操作的统一授权模型。
"""

from src.security.rbac.models import (
    SubjectType,
    ResourceType,
    Operation,
    RoleType,
    AuthorizationDecision,
    Subject,
    Resource,
    Role,
    AuthorizationRequest,
    AuthorizationResult,
)
from src.security.rbac.evaluator import RBACEvaluator
from src.security.rbac.storage import AuthorizationStorage, InMemoryAuthorizationStorage

__all__ = [
    "SubjectType",
    "ResourceType",
    "Operation",
    "RoleType",
    "AuthorizationDecision",
    "Subject",
    "Resource",
    "Role",
    "AuthorizationRequest",
    "AuthorizationResult",
    "RBACEvaluator",
    "AuthorizationStorage",
    "InMemoryAuthorizationStorage",
]
