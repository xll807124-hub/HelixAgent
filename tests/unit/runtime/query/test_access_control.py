"""
RT-008 访问控制单元测试

测试覆盖：
1. 租户隔离
2. 资源访问权限
3. 访问级别映射
4. 权限提升防护
"""

import pytest

from src.runtime.query.access_control import (
    AccessController,
    AccessLevel,
    UserContext,
)


class TestAccessController:
    """访问控制器测试"""

    def setup_method(self):
        """测试前初始化"""
        self.controller = AccessController()

    def test_tenant_isolation_same_org(self):
        """同组织可以访问"""
        user = UserContext(
            user_id="user1",
            organization_id="org1",
            roles=["DEVELOPER"],
        )
        
        can_access = self.controller.check_event_access(
            user, "org1", "proj1", "repo1"
        )
        assert can_access is True

    def test_tenant_isolation_different_org(self):
        """不同组织无法访问（除非是平台管理员）"""
        user = UserContext(
            user_id="user1",
            organization_id="org1",
            roles=["DEVELOPER"],
        )
        
        can_access = self.controller.check_event_access(
            user, "org2", "proj1", "repo1"
        )
        assert can_access is False

    def test_tenant_isolation_platform_admin_can_access_other_org(self):
        """平台管理员可以跨组织访问"""
        user = UserContext(
            user_id="user1",
            organization_id="org1",
            roles=["PLATFORM_ADMIN"],
        )
        
        can_access = self.controller.check_event_access(
            user, "org2", "proj1", "repo1"
        )
        assert can_access is True

    def test_project_access_no_restriction(self):
        """用户没有指定 project 时，可以访问任何 project"""
        user = UserContext(
            user_id="user1",
            organization_id="org1",
            project_id=None,  # 未指定
            roles=["DEVELOPER"],
        )
        
        can_access = self.controller.check_event_access(
            user, "org1", "proj1", "repo1"
        )
        assert can_access is True

    def test_project_access_with_restriction(self):
        """用户指定了 project，只能访问该 project"""
        user = UserContext(
            user_id="user1",
            organization_id="org1",
            project_id="proj1",
            roles=["DEVELOPER"],
        )
        
        # 访问相同 project
        can_access = self.controller.check_event_access(
            user, "org1", "proj1", "repo1"
        )
        assert can_access is True
        
        # 访问不同 project
        can_access = self.controller.check_event_access(
            user, "org1", "proj2", "repo1"
        )
        assert can_access is False

    def test_repository_access_no_restriction(self):
        """用户没有指定 repo 时，可以访问任何 repo"""
        user = UserContext(
            user_id="user1",
            organization_id="org1",
            project_id="proj1",
            repository_id=None,  # 未指定
            roles=["DEVELOPER"],
        )
        
        can_access = self.controller.check_event_access(
            user, "org1", "proj1", "repo1"
        )
        assert can_access is True

    def test_repository_access_with_restriction(self):
        """用户指定了 repo，只能访问该 repo"""
        user = UserContext(
            user_id="user1",
            organization_id="org1",
            project_id="proj1",
            repository_id="repo1",
            roles=["DEVELOPER"],
        )
        
        # 访问相同 repo
        can_access = self.controller.check_event_access(
            user, "org1", "proj1", "repo1"
        )
        assert can_access is True
        
        # 访问不同 repo
        can_access = self.controller.check_event_access(
            user, "org1", "proj1", "repo2"
        )
        assert can_access is False


class TestAccessLevelMapping:
    """访问级别映射测试"""

    def setup_method(self):
        """测试前初始化"""
        self.controller = AccessController()

    def test_platform_admin_access_level(self):
        """平台管理员 = ADMIN 级别"""
        user = UserContext(
            user_id="user1",
            organization_id="org1",
            roles=["PLATFORM_ADMIN"],
        )
        
        level = self.controller.get_access_level(user)
        assert level == AccessLevel.ADMIN

    def test_org_admin_access_level(self):
        """组织管理员 = ADMIN 级别"""
        user = UserContext(
            user_id="user1",
            organization_id="org1",
            roles=["ORG_ADMIN"],
        )
        
        level = self.controller.get_access_level(user)
        assert level == AccessLevel.ADMIN

    def test_security_auditor_access_level(self):
        """安全审计员 = AUDIT 级别"""
        user = UserContext(
            user_id="user1",
            organization_id="org1",
            roles=["SECURITY_AUDITOR"],
        )
        
        level = self.controller.get_access_level(user)
        assert level == AccessLevel.AUDIT

    def test_developer_access_level(self):
        """开发者 = BASIC 级别"""
        user = UserContext(
            user_id="user1",
            organization_id="org1",
            roles=["DEVELOPER"],
        )
        
        level = self.controller.get_access_level(user)
        assert level == AccessLevel.BASIC

    def test_multiple_roles_highest_level(self):
        """多个角色时取最高级别"""
        user = UserContext(
            user_id="user1",
            organization_id="org1",
            roles=["DEVELOPER", "SECURITY_AUDITOR"],
        )
        
        level = self.controller.get_access_level(user)
        assert level == AccessLevel.AUDIT  # AUDIT > BASIC

    def test_multiple_roles_admin_priority(self):
        """包含 ADMIN 角色时优先返回 ADMIN"""
        user = UserContext(
            user_id="user1",
            organization_id="org1",
            roles=["DEVELOPER", "ORG_ADMIN", "SECURITY_AUDITOR"],
        )
        
        level = self.controller.get_access_level(user)
        assert level == AccessLevel.ADMIN

    def test_unknown_role_defaults_to_basic(self):
        """未知角色默认为 BASIC"""
        user = UserContext(
            user_id="user1",
            organization_id="org1",
            roles=["UNKNOWN_ROLE"],
        )
        
        level = self.controller.get_access_level(user)
        assert level == AccessLevel.BASIC


class TestAccessLevelNormalization:
    """访问级别归一化测试"""

    def setup_method(self):
        """测试前初始化"""
        self.controller = AccessController()

    def test_normalize_access_level_same_level(self):
        """请求级别 = 用户级别"""
        result = self.controller.normalize_access_level(
            AccessLevel.BASIC, AccessLevel.BASIC
        )
        assert result == AccessLevel.BASIC

    def test_normalize_access_level_lower_request(self):
        """请求级别 < 用户级别"""
        result = self.controller.normalize_access_level(
            AccessLevel.BASIC, AccessLevel.AUDIT
        )
        assert result == AccessLevel.BASIC

    def test_normalize_access_level_higher_request(self):
        """请求级别 > 用户级别（被降级）"""
        result = self.controller.normalize_access_level(
            AccessLevel.ADMIN, AccessLevel.BASIC
        )
        assert result == AccessLevel.BASIC

    def test_normalize_access_level_no_privilege_escalation(self):
        """用户无法通过请求参数提升权限"""
        result = self.controller.normalize_access_level(
            AccessLevel.AUDIT, AccessLevel.BASIC
        )
        assert result == AccessLevel.BASIC


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
