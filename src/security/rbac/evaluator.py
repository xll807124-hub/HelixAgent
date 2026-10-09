"""
RBAC 评估引擎。

实现权限评估逻辑，包括拒绝优先、层级继承等规则。
"""

from datetime import UTC, datetime

from src.security.rbac.models import (
    AuthorizationDecision,
    AuthorizationRequest,
    AuthorizationResult,
    Operation,
    Resource,
    ResourceType,
    RoleType,
    Subject,
)
from src.security.rbac.storage import AuthorizationStorage


class RBACEvaluator:
    """RBAC 评估引擎。
    
    基于 Role-Based Access Control 的权限评估实现。
    
    核心设计原则:
    1. 未明确允许即拒绝 (default deny)
    2. 拒绝规则优先于允许规则 (deny override)
    3. 权限继承按资源层级向下
    4. 组织管理员不自动获得内容读取权
    5. Agent 权限 ≤ min(用户权限, 组织策略, 任务范围)
    """
    
    def __init__(self, storage: AuthorizationStorage):
        """初始化评估引擎。
        
        Args:
            storage: 权限存储实现
        """
        self.storage = storage
    
    async def evaluate(self, request: AuthorizationRequest) -> AuthorizationResult:
        """评估授权请求。
        
        Args:
            request: 授权请求
            
        Returns:
            授权结果
        """
        # 1. 检查主体有效性
        if not await self._is_subject_valid(request.subject):
            return AuthorizationResult(
                request_id=request.request_id,
                decision=AuthorizationDecision.DENY,
                subject=request.subject,
                resource=request.resource,
                operation=request.operation,
                reason="Subject is not valid or has expired",
            )
        
        # 2. 检查显式拒绝 (deny override)
        if await self._has_denial(
            request.resource.resource_id, request.subject.subject_id, request.operation
        ):
            return AuthorizationResult(
                request_id=request.request_id,
                decision=AuthorizationDecision.DENY,
                subject=request.subject,
                resource=request.resource,
                operation=request.operation,
                reason="Explicit denial rule applied",
            )
        
        # 3. 检查组织归属 (fail-closed)
        if not await self._check_organization_membership(request.subject, request.resource):
            return AuthorizationResult(
                request_id=request.request_id,
                decision=AuthorizationDecision.DENY,
                subject=request.subject,
                resource=request.resource,
                operation=request.operation,
                reason="Organization membership check failed",
            )
        
        # 4. 检查主体权限
        if await self._has_permission(request.subject, request.resource, request.operation):
            return AuthorizationResult(
                request_id=request.request_id,
                decision=AuthorizationDecision.ALLOW,
                subject=request.subject,
                resource=request.resource,
                operation=request.operation,
                reason="Permission granted by role",
            )
        
        # 5. 默认拒绝
        return AuthorizationResult(
            request_id=request.request_id,
            decision=AuthorizationDecision.DENY,
            subject=request.subject,
            resource=request.resource,
            operation=request.operation,
            reason="No applicable permission found (default deny)",
        )
    
    async def _is_subject_valid(self, subject: Subject) -> bool:
        """检查主体有效性。
        
        Args:
            subject: 主体
            
        Returns:
            主体是否有效
        """
        # 检查主体是否已过期
        if subject.effective_until is not None:
            if datetime.now(UTC) > subject.effective_until:
                return False
        
        return True
    
    async def _check_organization_membership(
        self,
        subject: Subject,
        resource: Resource,
    ) -> bool:
        """检查主体和资源的组织归属。
        
        fail-closed 原则: 无法验证时拒绝。
        
        Args:
            subject: 主体
            resource: 资源
            
        Returns:
            是否同属一个组织
        """
        # 平台级资源无需检查组织归属
        if resource.resource_type == ResourceType.PLATFORM:
            return True
        
        # 其他资源必须验证组织归属
        if resource.organization_id is None:
            return False
        
        if subject.organization_id != resource.organization_id:
            return False
        
        return True
    
    async def _has_denial(
        self,
        resource_id: str,
        subject_id: str,
        operation: Operation,
    ) -> bool:
        """检查是否有显式拒绝规则。
        
        Args:
            resource_id: 资源 ID
            subject_id: 主体 ID
            operation: 操作
            
        Returns:
            是否有拒绝规则
        """
        denials = await self.storage.get_resource_denials(resource_id)
        return (subject_id, operation.value) in denials
    
    async def _has_permission(
        self,
        subject: Subject,
        resource: Resource,
        operation: Operation,
    ) -> bool:
        """检查主体是否有权限。
        
        根据主体的角色和资源类型判断是否有权限。
        
        Args:
            subject: 主体
            resource: 资源
            operation: 操作
            
        Returns:
            是否有权限
        """
        # 遍历主体的所有角色
        for role_type in subject.roles:
            role_def = await self.storage.get_role_definition(role_type)
            if role_def is None:
                continue
            
            # 检查角色是否有权限
            if (resource.resource_type, operation) in role_def.permissions:
                return True
            
            # 检查继承权限
            # 例: PROJECT_ADMIN 的项目权限可以继承到仓库
            if await self._has_inherited_permission(role_type, resource.resource_type, operation):
                return True
        
        return False
    
    async def _has_inherited_permission(
        self,
        role_type: RoleType,
        resource_type: ResourceType,
        operation: Operation,
    ) -> bool:
        """检查是否有继承权限。
        
        根据资源层级关系判断权限是否继承。
        
        Args:
            role_type: 角色类型
            resource_type: 资源类型
            operation: 操作
            
        Returns:
            是否有继承权限
        """
        role_def = await self.storage.get_role_definition(role_type)
        if role_def is None:
            return False
        
        # 定义权限继承关系
        # PROJECT_ADMIN: PROJECT -> REPOSITORY/PATH
        if role_type == RoleType.PROJECT_ADMIN:
            if resource_type in [ResourceType.REPOSITORY, ResourceType.PATH]:
                parent_permission = (ResourceType.PROJECT, operation)
                if parent_permission in role_def.permissions:
                    return True
        
        # ORG_ADMIN: ORGANIZATION -> PROJECT/REPOSITORY
        elif role_type == RoleType.ORG_ADMIN:
            if resource_type in [ResourceType.PROJECT, ResourceType.REPOSITORY]:
                parent_permission = (ResourceType.ORGANIZATION, operation)
                if parent_permission in role_def.permissions:
                    return True
        
        # PLATFORM_ADMIN: PLATFORM -> all
        elif role_type == RoleType.PLATFORM_ADMIN:
            parent_permission = (ResourceType.PLATFORM, operation)
            if parent_permission in role_def.permissions:
                return True
        
        return False


class RBACManager:
    """RBAC 管理器。
    
    提供更高层的权限管理接口。
    """
    
    def __init__(self, evaluator: RBACEvaluator, storage: AuthorizationStorage):
        """初始化管理器。
        
        Args:
            evaluator: RBAC 评估引擎
            storage: 权限存储
        """
        self.evaluator = evaluator
        self.storage = storage
    
    async def assign_role(self, subject_id: str, role: RoleType) -> bool:
        """为主体分配角色。
        
        Args:
            subject_id: 主体 ID
            role: 角色类型
            
        Returns:
            是否成功
        """
        return await self.storage.assign_role(subject_id, role)
    
    async def revoke_role(self, subject_id: str, role: RoleType) -> bool:
        """撤销主体的角色。
        
        Args:
            subject_id: 主体 ID
            role: 角色类型
            
        Returns:
            是否成功
        """
        return await self.storage.revoke_role(subject_id, role)
    
    async def add_denial(self, resource_id: str, subject_id: str, operation: Operation) -> bool:
        """添加显式拒绝规则。
        
        Args:
            resource_id: 资源 ID
            subject_id: 主体 ID
            operation: 操作
            
        Returns:
            是否成功
        """
        return await self.storage.add_resource_denial(resource_id, subject_id, operation.value)
    
    async def check_permission(
        self,
        subject: Subject,
        resource: Resource,
        operation: Operation,
        request_id: str | None = None,
    ) -> AuthorizationResult:
        """检查权限（快速接口）。
        
        Args:
            subject: 主体
            resource: 资源
            operation: 操作
            request_id: 请求 ID (可选)
            
        Returns:
            授权结果
        """
        if request_id is None:
            import uuid
            request_id = str(uuid.uuid4())
        
        request = AuthorizationRequest(
            request_id=request_id,
            subject=subject,
            resource=resource,
            operation=operation,
        )
        
        return await self.evaluator.evaluate(request)
