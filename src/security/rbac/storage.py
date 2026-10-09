"""
RBAC 权限存储接口。

定义权限信息的存储和检索方式。
"""

from abc import ABC, abstractmethod
from typing import Optional, Set, Dict
from src.security.rbac.models import (
    Subject,
    Resource,
    Role,
    RoleType,
    AuthorizationDecision,
)


class AuthorizationStorage(ABC):
    """授权存储基类。
    
    定义权限、角色、主体等信息的存储接口。
    """
    
    @abstractmethod
    async def get_subject_roles(self, subject_id: str) -> Set[RoleType]:
        """获取主体的角色集合。
        
        Args:
            subject_id: 主体 ID
            
        Returns:
            角色集合
        """
        ...
    
    @abstractmethod
    async def get_role_definition(self, role_type: RoleType) -> Optional[Role]:
        """获取角色定义。
        
        Args:
            role_type: 角色类型
            
        Returns:
            角色定义，如果不存在返回 None
        """
        ...
    
    @abstractmethod
    async def assign_role(self, subject_id: str, role: RoleType) -> bool:
        """为主体分配角色。
        
        Args:
            subject_id: 主体 ID
            role: 角色类型
            
        Returns:
            是否成功分配
        """
        ...
    
    @abstractmethod
    async def revoke_role(self, subject_id: str, role: RoleType) -> bool:
        """撤销主体的角色。
        
        Args:
            subject_id: 主体 ID
            role: 角色类型
            
        Returns:
            是否成功撤销
        """
        ...
    
    @abstractmethod
    async def get_resource_denials(self, resource_id: str) -> Set[tuple[str, str]]:
        """获取资源上的显式拒绝规则。
        
        Returns:
            集合形式为 [(subject_id, operation)]
        """
        ...
    
    @abstractmethod
    async def add_resource_denial(self, resource_id: str, subject_id: str, operation: str) -> bool:
        """为资源添加显式拒绝规则。
        
        Args:
            resource_id: 资源 ID
            subject_id: 主体 ID
            operation: 操作
            
        Returns:
            是否成功添加
        """
        ...


class InMemoryAuthorizationStorage(AuthorizationStorage):
    """内存中的授权存储实现。
    
    用于测试和开发环境。
    """
    
    def __init__(self):
        """初始化内存存储."""
        # subject_id -> Set[RoleType]
        self._subject_roles: Dict[str, Set[RoleType]] = {}
        
        # role_type -> Role
        self._role_definitions: Dict[RoleType, Role] = self._init_default_roles()
        
        # resource_id -> Set[(subject_id, operation)]
        self._resource_denials: Dict[str, Set[tuple[str, str]]] = {}
    
    def _init_default_roles(self) -> Dict[RoleType, Role]:
        """初始化默认角色定义."""
        from src.security.rbac.models import (
            RoleType,
            ResourceType,
            Operation,
            Role,
        )
        
        return {
            RoleType.PLATFORM_ADMIN: Role(
                role_type=RoleType.PLATFORM_ADMIN,
                display_name="平台管理员",
                description="管理整个平台的配置和策略",
                permissions=frozenset([
                    (ResourceType.PLATFORM, Operation.MANAGE_POLICIES),
                    (ResourceType.PLATFORM, Operation.MANAGE_MEMBERS),
                    (ResourceType.PLATFORM, Operation.VIEW_AUDIT),
                ]),
            ),
            RoleType.ORG_ADMIN: Role(
                role_type=RoleType.ORG_ADMIN,
                display_name="组织管理员",
                description="管理组织内的成员和资源",
                permissions=frozenset([
                    (ResourceType.ORGANIZATION, Operation.MANAGE_MEMBERS),
                    (ResourceType.ORGANIZATION, Operation.MANAGE_ROLES),
                    (ResourceType.ORGANIZATION, Operation.MANAGE_POLICIES),
                ]),
            ),
            RoleType.PROJECT_ADMIN: Role(
                role_type=RoleType.PROJECT_ADMIN,
                display_name="项目管理员",
                description="管理项目内的资源",
                permissions=frozenset([
                    (ResourceType.PROJECT, Operation.VIEW),
                    (ResourceType.REPOSITORY, Operation.MANAGE_MEMBERS),
                    (ResourceType.REPOSITORY, Operation.MANAGE_POLICIES),
                ]),
            ),
            RoleType.DEVELOPER: Role(
                role_type=RoleType.DEVELOPER,
                display_name="开发者",
                description="可以创建任务和执行工具",
                permissions=frozenset([
                    (ResourceType.REPOSITORY, Operation.READ),
                    (ResourceType.REPOSITORY, Operation.SEARCH),
                    (ResourceType.REPOSITORY, Operation.CREATE_TASK),
                    (ResourceType.REPOSITORY, Operation.CREATE_BRANCH),
                    (ResourceType.REPOSITORY, Operation.CREATE_COMMIT),
                ]),
            ),
            RoleType.SECURITY_AUDITOR: Role(
                role_type=RoleType.SECURITY_AUDITOR,
                display_name="安全审计员",
                description="查看审计和安全信息",
                permissions=frozenset([
                    (ResourceType.PLATFORM, Operation.VIEW_AUDIT),
                    (ResourceType.ORGANIZATION, Operation.VIEW_AUDIT),
                ]),
            ),
        }
    
    async def get_subject_roles(self, subject_id: str) -> Set[RoleType]:
        """获取主体的角色集合."""
        return self._subject_roles.get(subject_id, set()).copy()
    
    async def get_role_definition(self, role_type: RoleType) -> Optional[Role]:
        """获取角色定义."""
        return self._role_definitions.get(role_type)
    
    async def assign_role(self, subject_id: str, role: RoleType) -> bool:
        """为主体分配角色."""
        if subject_id not in self._subject_roles:
            self._subject_roles[subject_id] = set()
        self._subject_roles[subject_id].add(role)
        return True
    
    async def revoke_role(self, subject_id: str, role: RoleType) -> bool:
        """撤销主体的角色."""
        if subject_id in self._subject_roles:
            self._subject_roles[subject_id].discard(role)
            return True
        return False
    
    async def get_resource_denials(self, resource_id: str) -> Set[tuple[str, str]]:
        """获取资源上的显式拒绝规则."""
        return self._resource_denials.get(resource_id, set()).copy()
    
    async def add_resource_denial(self, resource_id: str, subject_id: str, operation: str) -> bool:
        """为资源添加显式拒绝规则."""
        if resource_id not in self._resource_denials:
            self._resource_denials[resource_id] = set()
        self._resource_denials[resource_id].add((subject_id, operation))
        return True
