"""
RBAC 单元测试。

测试 RBAC 评估引擎的各项功能。
"""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from src.security.rbac.evaluator import RBACEvaluator, RBACManager
from src.security.rbac.models import (
    AuthorizationDecision,
    AuthorizationRequest,
    Operation,
    Resource,
    ResourceType,
    RoleType,
    Subject,
    SubjectType,
)
from src.security.rbac.storage import InMemoryAuthorizationStorage


@pytest.fixture
def storage():
    """创建存储实例."""
    return InMemoryAuthorizationStorage()


@pytest.fixture
def evaluator(storage):
    """创建评估器实例."""
    return RBACEvaluator(storage)


@pytest.fixture
def manager(evaluator, storage):
    """创建管理器实例."""
    return RBACManager(evaluator, storage)


class TestRBACModels:
    """测试 RBAC 数据模型."""
    
    def test_subject_creation(self):
        """测试创建主体."""
        subject = Subject(
            subject_id="user_001",
            subject_type=SubjectType.USER,
            organization_id="org_001",
            roles=frozenset([RoleType.DEVELOPER]),
        )
        
        assert subject.subject_id == "user_001"
        assert subject.subject_type == SubjectType.USER
        assert subject.organization_id == "org_001"
        assert RoleType.DEVELOPER in subject.roles
    
    def test_subject_immutability(self):
        """测试主体不可变性."""
        subject = Subject(
            subject_id="user_001",
            subject_type=SubjectType.USER,
            organization_id="org_001",
        )
        
        with pytest.raises(ValidationError):  # frozen=True 会抛出异常
            subject.subject_id = "user_002"
    
    def test_resource_creation(self):
        """测试创建资源."""
        resource = Resource(
            resource_id="repo_001",
            resource_type=ResourceType.REPOSITORY,
            organization_id="org_001",
            project_id="proj_001",
            repository_id="repo_001",
            sensitivity_level=2,
        )
        
        assert resource.resource_id == "repo_001"
        assert resource.resource_type == ResourceType.REPOSITORY
        assert resource.sensitivity_level == 2
    
    def test_authorization_request_timestamp(self):
        """测试授权请求自动添加时间戳."""
        subject = Subject(
            subject_id="user_001",
            subject_type=SubjectType.USER,
            organization_id="org_001",
        )
        resource = Resource(
            resource_id="repo_001",
            resource_type=ResourceType.REPOSITORY,
            organization_id="org_001",
        )
        
        request = AuthorizationRequest(
            request_id="req_001",
            subject=subject,
            resource=resource,
            operation=Operation.READ,
        )
        
        assert request.timestamp is not None
        assert isinstance(request.timestamp, datetime)


class TestRBACStorage:
    """测试 RBAC 存储功能."""
    
    @pytest.mark.asyncio
    async def test_assign_role(self, storage):
        """测试分配角色."""
        result = await storage.assign_role("user_001", RoleType.DEVELOPER)
        assert result is True
        
        roles = await storage.get_subject_roles("user_001")
        assert RoleType.DEVELOPER in roles
    
    @pytest.mark.asyncio
    async def test_revoke_role(self, storage):
        """测试撤销角色."""
        await storage.assign_role("user_001", RoleType.DEVELOPER)
        result = await storage.revoke_role("user_001", RoleType.DEVELOPER)
        
        assert result is True
        roles = await storage.get_subject_roles("user_001")
        assert RoleType.DEVELOPER not in roles
    
    @pytest.mark.asyncio
    async def test_get_role_definition(self, storage):
        """测试获取角色定义."""
        role = await storage.get_role_definition(RoleType.DEVELOPER)
        
        assert role is not None
        assert role.role_type == RoleType.DEVELOPER
        assert (ResourceType.REPOSITORY, Operation.READ) in role.permissions
    
    @pytest.mark.asyncio
    async def test_add_resource_denial(self, storage):
        """测试添加显式拒绝规则."""
        result = await storage.add_resource_denial("repo_001", "user_001", "READ")
        assert result is True
        
        denials = await storage.get_resource_denials("repo_001")
        assert ("user_001", "READ") in denials
    
    @pytest.mark.asyncio
    async def test_multiple_roles(self, storage):
        """测试主体拥有多个角色."""
        await storage.assign_role("user_001", RoleType.DEVELOPER)
        await storage.assign_role("user_001", RoleType.SECURITY_AUDITOR)
        
        roles = await storage.get_subject_roles("user_001")
        assert len(roles) == 2
        assert RoleType.DEVELOPER in roles
        assert RoleType.SECURITY_AUDITOR in roles


class TestRBACEvaluator:
    """测试 RBAC 评估引擎."""
    
    @pytest.mark.asyncio
    async def test_default_deny(self, evaluator):
        """测试默认拒绝原则."""
        subject = Subject(
            subject_id="user_001",
            subject_type=SubjectType.USER,
            organization_id="org_001",
        )
        resource = Resource(
            resource_id="repo_001",
            resource_type=ResourceType.REPOSITORY,
            organization_id="org_001",
        )
        
        request = AuthorizationRequest(
            request_id="req_001",
            subject=subject,
            resource=resource,
            operation=Operation.READ,
        )
        
        result = await evaluator.evaluate(request)
        assert result.decision == AuthorizationDecision.DENY
        assert "default deny" in result.reason.lower()
    
    @pytest.mark.asyncio
    async def test_allow_with_role(self, evaluator, storage):
        """测试有角色时允许."""
        await storage.assign_role("user_001", RoleType.DEVELOPER)
        
        subject = Subject(
            subject_id="user_001",
            subject_type=SubjectType.USER,
            organization_id="org_001",
            roles=frozenset([RoleType.DEVELOPER]),
        )
        resource = Resource(
            resource_id="repo_001",
            resource_type=ResourceType.REPOSITORY,
            organization_id="org_001",
        )
        
        request = AuthorizationRequest(
            request_id="req_001",
            subject=subject,
            resource=resource,
            operation=Operation.READ,
        )
        
        result = await evaluator.evaluate(request)
        assert result.decision == AuthorizationDecision.ALLOW
    
    @pytest.mark.asyncio
    async def test_deny_override(self, evaluator, storage):
        """测试拒绝优先原则."""
        await storage.assign_role("user_001", RoleType.DEVELOPER)
        await storage.add_resource_denial("repo_001", "user_001", Operation.READ.value)
        
        subject = Subject(
            subject_id="user_001",
            subject_type=SubjectType.USER,
            organization_id="org_001",
            roles=frozenset([RoleType.DEVELOPER]),
        )
        resource = Resource(
            resource_id="repo_001",
            resource_type=ResourceType.REPOSITORY,
            organization_id="org_001",
        )
        
        request = AuthorizationRequest(
            request_id="req_001",
            subject=subject,
            resource=resource,
            operation=Operation.READ,
        )
        
        result = await evaluator.evaluate(request)
        assert result.decision == AuthorizationDecision.DENY
        assert "explicit denial" in result.reason.lower()
    
    @pytest.mark.asyncio
    async def test_organization_mismatch(self, evaluator, storage):
        """测试组织不匹配时拒绝."""
        await storage.assign_role("user_001", RoleType.DEVELOPER)
        
        subject = Subject(
            subject_id="user_001",
            subject_type=SubjectType.USER,
            organization_id="org_001",
            roles=frozenset([RoleType.DEVELOPER]),
        )
        resource = Resource(
            resource_id="repo_001",
            resource_type=ResourceType.REPOSITORY,
            organization_id="org_002",  # 不同的组织
        )
        
        request = AuthorizationRequest(
            request_id="req_001",
            subject=subject,
            resource=resource,
            operation=Operation.READ,
        )
        
        result = await evaluator.evaluate(request)
        assert result.decision == AuthorizationDecision.DENY
    
    @pytest.mark.asyncio
    async def test_expired_subject(self, evaluator):
        """测试已过期的主体拒绝."""
        expired_time = datetime.now(UTC) - timedelta(hours=1)
        
        subject = Subject(
            subject_id="user_001",
            subject_type=SubjectType.USER,
            organization_id="org_001",
            effective_until=expired_time,
            roles=frozenset([RoleType.DEVELOPER]),
        )
        resource = Resource(
            resource_id="repo_001",
            resource_type=ResourceType.REPOSITORY,
            organization_id="org_001",
        )
        
        request = AuthorizationRequest(
            request_id="req_001",
            subject=subject,
            resource=resource,
            operation=Operation.READ,
        )
        
        result = await evaluator.evaluate(request)
        assert result.decision == AuthorizationDecision.DENY
    
    @pytest.mark.asyncio
    async def test_platform_admin_permission(self, evaluator, storage):
        """测试平台管理员权限."""
        await storage.assign_role("admin_001", RoleType.PLATFORM_ADMIN)
        
        subject = Subject(
            subject_id="admin_001",
            subject_type=SubjectType.USER,
            organization_id="org_001",
            roles=frozenset([RoleType.PLATFORM_ADMIN]),
        )
        resource = Resource(
            resource_id="platform_001",
            resource_type=ResourceType.PLATFORM,
        )
        
        request = AuthorizationRequest(
            request_id="req_001",
            subject=subject,
            resource=resource,
            operation=Operation.MANAGE_POLICIES,
        )
        
        result = await evaluator.evaluate(request)
        assert result.decision == AuthorizationDecision.ALLOW
    
    @pytest.mark.asyncio
    async def test_permission_inheritance(self, evaluator, storage):
        """测试权限继承 (PROJECT_ADMIN -> REPOSITORY)."""
        await storage.assign_role("admin_001", RoleType.PROJECT_ADMIN)
        
        subject = Subject(
            subject_id="admin_001",
            subject_type=SubjectType.USER,
            organization_id="org_001",
            roles=frozenset([RoleType.PROJECT_ADMIN]),
        )
        
        # 访问 REPOSITORY 资源时，PROJECT 权限应该继承
        resource = Resource(
            resource_id="repo_001",
            resource_type=ResourceType.REPOSITORY,
            organization_id="org_001",
            project_id="proj_001",
        )
        
        request = AuthorizationRequest(
            request_id="req_001",
            subject=subject,
            resource=resource,
            operation=Operation.VIEW,
        )
        
        result = await evaluator.evaluate(request)
        # 根据设计，PROJECT_ADMIN 的 VIEW 权限应该继承到 REPOSITORY
        assert result.decision == AuthorizationDecision.ALLOW


class TestRBACManager:
    """测试 RBAC 管理器."""
    
    @pytest.mark.asyncio
    async def test_assign_role_via_manager(self, manager):
        """测试通过管理器分配角色."""
        result = await manager.assign_role("user_001", RoleType.DEVELOPER)
        assert result is True
    
    @pytest.mark.asyncio
    async def test_revoke_role_via_manager(self, manager):
        """测试通过管理器撤销角色."""
        await manager.assign_role("user_001", RoleType.DEVELOPER)
        result = await manager.revoke_role("user_001", RoleType.DEVELOPER)
        assert result is True
    
    @pytest.mark.asyncio
    async def test_add_denial_via_manager(self, manager):
        """测试通过管理器添加拒绝规则."""
        result = await manager.add_denial("repo_001", "user_001", Operation.READ)
        assert result is True
    
    @pytest.mark.asyncio
    async def test_check_permission_quick_interface(self, manager, storage):
        """测试快速权限检查接口."""
        await storage.assign_role("user_001", RoleType.DEVELOPER)
        
        subject = Subject(
            subject_id="user_001",
            subject_type=SubjectType.USER,
            organization_id="org_001",
            roles=frozenset([RoleType.DEVELOPER]),
        )
        resource = Resource(
            resource_id="repo_001",
            resource_type=ResourceType.REPOSITORY,
            organization_id="org_001",
        )
        
        result = await manager.check_permission(subject, resource, Operation.READ)
        assert result.decision == AuthorizationDecision.ALLOW
