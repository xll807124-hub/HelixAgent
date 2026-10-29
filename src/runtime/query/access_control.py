"""
访问控制模块 - RBAC 与权限检查

负责：
1. 基于 RBAC 的权限检查
2. 访问级别验证
3. 资源隔离验证
"""

from dataclasses import dataclass, field
from enum import Enum


class AccessLevel(str, Enum):
    """用户访问级别"""
    BASIC = "BASIC"         # 基础用户
    AUDIT = "AUDIT"         # 审计员
    ADMIN = "ADMIN"         # 管理员


@dataclass
class UserContext:
    """用户上下文"""
    user_id: str
    organization_id: str
    project_id: str | None = None
    repository_id: str | None = None
    roles: list[str] = field(default_factory=list)


class AccessController:
    """
    访问控制器 - 管理事件查询权限
    """
    
    # 角色到访问级别的映射
    ROLE_TO_ACCESS_LEVEL = {
        "PLATFORM_ADMIN": AccessLevel.ADMIN,
        "ORG_ADMIN": AccessLevel.ADMIN,
        "PROJECT_ADMIN": AccessLevel.ADMIN,
        "SECURITY_AUDITOR": AccessLevel.AUDIT,
        "DEVELOPER": AccessLevel.BASIC,
        "VIEWER": AccessLevel.BASIC,
    }
    
    def __init__(self) -> None:
        pass
    
    def check_event_access(
        self,
        user: UserContext,
        event_org_id: str,
        event_project_id: str,
        event_repo_id: str,
    ) -> bool:
        """
        检查用户是否可以访问事件
        
        规则：
        1. 租户隔离：必须是同一 organization
        2. 资源访问：用户必须有对应 project/repo 的访问权限
        3. 跨组织访问必须是平台管理员
        
        Args:
            user: 用户上下文
            event_org_id: 事件所属 organization
            event_project_id: 事件所属 project
            event_repo_id: 事件所属 repository
            
        Returns:
            是否有访问权限
        """
        # 规则 1：租户隔离（强制）
        if user.organization_id != event_org_id:
            # 除非用户是平台管理员
            if "PLATFORM_ADMIN" not in user.roles:
                return False
        
        # 规则 2：资源访问权限
        # 检查用户是否有该 project 的访问权限
        if not self._has_project_access(user, event_project_id):
            return False
        
        # 规则 3：如果指定了 repo，检查 repo 访问权限
        if event_repo_id and not self._has_repo_access(user, event_project_id, event_repo_id):
            return False
        
        return True
    
    def get_access_level(self, user: UserContext) -> AccessLevel:
        """
        获取用户的访问级别
        
        规则：取用户所有角色中的最高级别
        
        Args:
            user: 用户上下文
            
        Returns:
            用户的访问级别
        """
        max_level = AccessLevel.BASIC
        
        for role in user.roles:
            level = self.ROLE_TO_ACCESS_LEVEL.get(role, AccessLevel.BASIC)
            if level == AccessLevel.ADMIN:
                return AccessLevel.ADMIN
            elif level == AccessLevel.AUDIT and max_level != AccessLevel.ADMIN:
                max_level = AccessLevel.AUDIT
        
        return max_level
    
    def normalize_access_level(
        self,
        requested_level: AccessLevel,
        user_max_level: AccessLevel,
    ) -> AccessLevel:
        """
        归一化访问级别
        
        用户不能请求比自己实际级别更高的访问权限。
        例如：BASIC 用户不能请求 AUDIT 级别
        
        Args:
            requested_level: 用户请求的级别
            user_max_level: 用户实际的最高级别
            
        Returns:
            最终应用的访问级别
        """
        level_hierarchy = {AccessLevel.BASIC: 0, AccessLevel.AUDIT: 1, AccessLevel.ADMIN: 2}
        
        requested_rank = level_hierarchy.get(requested_level, 0)
        user_rank = level_hierarchy.get(user_max_level, 0)
        
        if requested_rank <= user_rank:
            return requested_level
        else:
            return user_max_level
    
    @staticmethod
    def _has_project_access(user: UserContext, project_id: str) -> bool:
        """
        检查用户是否有 project 的访问权限
        
        在完整实现中，这会查询权限数据库。
        这里是简化版本：假设用户总是有权限（后续改进）
        
        Args:
            user: 用户上下文
            project_id: 项目 ID
            
        Returns:
            是否有权限
        """
        # 简化：如果没有设置 project_id，假设有权限
        if not user.project_id:
            return True
        
        # 如果指定了 project_id，必须匹配
        return user.project_id == project_id
    
    @staticmethod
    def _has_repo_access(user: UserContext, project_id: str, repo_id: str) -> bool:
        """
        检查用户是否有 repository 的访问权限
        
        Args:
            user: 用户上下文
            project_id: 项目 ID
            repo_id: 仓库 ID
            
        Returns:
            是否有权限
        """
        # 简化：如果没有设置 repository_id，假设有权限
        if not user.repository_id:
            return True
        
        # 如果指定了 repository_id，必须匹配
        return user.repository_id == repo_id
