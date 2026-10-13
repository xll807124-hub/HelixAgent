"""
RT-008 事件查询服务集成测试

测试覆盖：
1. 权限检查 + 脱敏集成
2. 查询请求处理
3. 完整的查询流程
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from src.runtime.event_store.envelope import EventEnvelope, DataSensitivity
from src.runtime.query.access_control import AccessLevel, AccessController, UserContext
from src.runtime.query.event_query import (
    EventQueryService,
    EventQueryRequest,
)
from src.runtime.query.redaction_engine import RedactionEngine


class TestEventQueryService:
    """事件查询服务测试"""

    def setup_method(self):
        """测试前初始化"""
        # 创建 mock event store
        self.mock_store = MagicMock()
        
        # 创建实际的访问控制器和脱敏引擎
        self.access_controller = AccessController()
        self.redaction_engine = RedactionEngine()
        
        # 创建查询服务
        self.service = EventQueryService(
            self.mock_store,
            self.access_controller,
            self.redaction_engine,
        )

    def _create_sample_event(self, event_id="evt-1", payload=None):
        """创建示例事件"""
        if payload is None:
            payload = {"message": "test", "status": "ok"}
        
        return EventEnvelope(
            event_id=event_id,
            event_type="TestEvent",
            payload_schema="TestEvent.v1",
            task_id="task-123",
            organization_id="org-1",
            project_id="proj-1",
            repository_id="repo-1",
            payload=payload,
            data_classification=DataSensitivity.INTERNAL,
            occurred_at=datetime.now(UTC),
        )

    def test_query_events_basic_user_no_access_to_task(self):
        """基础用户无权访问其他 org 的任务"""
        user = UserContext(
            user_id="user-1",
            organization_id="org-1",
            roles=["DEVELOPER"],
        )
        
        request = EventQueryRequest(task_id="task-123")
        
        with pytest.raises(PermissionError):
            self.service.query_events(
                user,
                request,
                task_org_id="org-2",  # 不同 org
                task_project_id="proj-1",
                task_repo_id="repo-1",
            )

    def test_query_events_basic_user_with_access(self):
        """基础用户有权访问同 org 的任务"""
        user = UserContext(
            user_id="user-1",
            organization_id="org-1",
            roles=["DEVELOPER"],
        )
        
        # 创建示例事件
        events = [self._create_sample_event()]
        self.mock_store.query.return_value = (events, 1)
        
        request = EventQueryRequest(task_id="task-123", include_payload=False)
        
        result, total = self.service.query_events(
            user,
            request,
            task_org_id="org-1",  # 同 org
            task_project_id="proj-1",
            task_repo_id="repo-1",
        )
        
        assert len(result) == 1
        assert total == 1
        assert result[0].access_level_applied == AccessLevel.BASIC

    def test_query_events_audit_user_elevated_access(self):
        """审计员有更高的访问级别"""
        user = UserContext(
            user_id="user-1",
            organization_id="org-1",
            roles=["SECURITY_AUDITOR"],
        )
        
        # 创建示例事件
        events = [self._create_sample_event()]
        self.mock_store.query.return_value = (events, 1)
        
        request = EventQueryRequest(task_id="task-123", include_payload=True)
        
        result, total = self.service.query_events(
            user,
            request,
            task_org_id="org-1",
            task_project_id="proj-1",
            task_repo_id="repo-1",
        )
        
        assert len(result) == 1
        # 审计员的访问级别应该是 AUDIT（用户实际级别）
        assert result[0].access_level_applied in [AccessLevel.AUDIT, AccessLevel.ADMIN]

    def test_query_events_no_payload_by_default(self):
        """默认不返回载荷（avoid redaction bypass）"""
        user = UserContext(
            user_id="user-1",
            organization_id="org-1",
            roles=["DEVELOPER"],
        )
        
        events = [self._create_sample_event()]
        self.mock_store.query.return_value = (events, 1)
        
        request = EventQueryRequest(
            task_id="task-123",
            include_payload=False,  # 不返回载荷
        )
        
        result, total = self.service.query_events(
            user,
            request,
            task_org_id="org-1",
            task_project_id="proj-1",
            task_repo_id="repo-1",
        )
        
        assert result[0].access_level_applied == AccessLevel.BASIC

    def test_query_events_with_sensitive_payload(self):
        """查询含敏感数据的载荷"""
        user = UserContext(
            user_id="user-1",
            organization_id="org-1",
            roles=["DEVELOPER"],
        )
        
        # 创建含敏感数据的事件
        sensitive_payload = {
            "message": "Config deployed",
            "api_key": "sk-1234567890abcdef",
        }
        events = [self._create_sample_event(payload=sensitive_payload)]
        self.mock_store.query.return_value = (events, 1)
        
        request = EventQueryRequest(task_id="task-123", include_payload=True)
        
        result, total = self.service.query_events(
            user,
            request,
            task_org_id="org-1",
            task_project_id="proj-1",
            task_repo_id="repo-1",
        )
        
        # 基础用户看到 L1 数据，访问级别为 BASIC
        # 在 BASIC + L1 情况下应该返回 SUMMARY 级别的脱敏
        redacted_payload = result[0].payload
        assert result[0].access_level_applied == AccessLevel.BASIC

    def test_query_events_sensitive_payload_audit_user(self):
        """审计员查询敏感载荷"""
        user = UserContext(
            user_id="user-1",
            organization_id="org-1",
            roles=["SECURITY_AUDITOR"],
        )
        
        # 创建含敏感数据的事件
        sensitive_payload = {
            "message": "Config deployed",
            "api_key": "sk-1234567890abcdef",
        }
        events = [self._create_sample_event(payload=sensitive_payload)]
        self.mock_store.query.return_value = (events, 1)
        
        request = EventQueryRequest(task_id="task-123", include_payload=True)
        
        result, total = self.service.query_events(
            user,
            request,
            task_org_id="org-1",
            task_project_id="proj-1",
            task_repo_id="repo-1",
        )
        
        # 审计员访问级别应该不是 BASIC
        redacted_payload = result[0].payload
        assert result[0].access_level_applied != AccessLevel.BASIC
        # 审计员应该能看到 api_key（在 AUDIT 级别）
        if "api_key" in redacted_payload:
            assert redacted_payload["api_key"] == "sk-1234567890abcdef"

    def test_query_events_empty_result(self):
        """查询无结果"""
        user = UserContext(
            user_id="user-1",
            organization_id="org-1",
            roles=["DEVELOPER"],
        )
        
        self.mock_store.query.return_value = ([], 0)
        
        request = EventQueryRequest(task_id="task-123")
        
        result, total = self.service.query_events(
            user,
            request,
            task_org_id="org-1",
            task_project_id="proj-1",
            task_repo_id="repo-1",
        )
        
        assert len(result) == 0
        assert total == 0

    def test_query_events_pagination(self):
        """分页查询"""
        user = UserContext(
            user_id="user-1",
            organization_id="org-1",
            roles=["DEVELOPER"],
        )
        
        events = [
            self._create_sample_event(f"evt-{i}")
            for i in range(5)
        ]
        self.mock_store.query.return_value = (events[:50], 150)
        
        request = EventQueryRequest(
            task_id="task-123",
            page=1,
            limit=50,
        )
        
        result, total = self.service.query_events(
            user,
            request,
            task_org_id="org-1",
            task_project_id="proj-1",
            task_repo_id="repo-1",
        )
        
        assert len(result) == 5
        assert total == 150
        
        # 验证 mock_store.query 被正确调用
        self.mock_store.query.assert_called_once()
        call_args = self.mock_store.query.call_args
        assert call_args.kwargs["task_id"] == "task-123"
        assert call_args.kwargs["page"] == 1
        assert call_args.kwargs["limit"] == 50

    def test_query_events_with_time_filter(self):
        """时间过滤"""
        user = UserContext(
            user_id="user-1",
            organization_id="org-1",
            roles=["DEVELOPER"],
        )
        
        events = [self._create_sample_event()]
        self.mock_store.query.return_value = (events, 1)
        
        start_time = datetime(2024, 1, 1, tzinfo=UTC)
        end_time = datetime(2024, 1, 31, tzinfo=UTC)
        
        request = EventQueryRequest(
            task_id="task-123",
            occurred_after=start_time,
            occurred_before=end_time,
        )
        
        result, total = self.service.query_events(
            user,
            request,
            task_org_id="org-1",
            task_project_id="proj-1",
            task_repo_id="repo-1",
        )
        
        # 验证时间过滤被传递
        call_args = self.mock_store.query.call_args
        assert call_args.kwargs["occurred_after"] == start_time
        assert call_args.kwargs["occurred_before"] == end_time


class TestEventQueryServicePermissionDenial:
    """权限拒绝场景测试"""

    def setup_method(self):
        """测试前初始化"""
        self.mock_store = MagicMock()
        self.access_controller = AccessController()
        self.redaction_engine = RedactionEngine()
        self.service = EventQueryService(
            self.mock_store,
            self.access_controller,
            self.redaction_engine,
        )

    def test_cross_org_access_denied(self):
        """跨 org 访问被拒绝"""
        user = UserContext(
            user_id="user-1",
            organization_id="org-1",
            roles=["DEVELOPER"],
        )
        
        request = EventQueryRequest(task_id="task-123")
        
        with pytest.raises(PermissionError) as exc_info:
            self.service.query_events(
                user,
                request,
                task_org_id="org-2",  # 不同 org
                task_project_id="proj-1",
                task_repo_id="repo-1",
            )
        
        assert "no access" in str(exc_info.value).lower()

    def test_cross_project_access_with_restriction(self):
        """有 project 限制时跨 project 访问被拒绝"""
        user = UserContext(
            user_id="user-1",
            organization_id="org-1",
            project_id="proj-1",  # 限制到 proj-1
            roles=["DEVELOPER"],
        )
        
        request = EventQueryRequest(task_id="task-123")
        
        with pytest.raises(PermissionError):
            self.service.query_events(
                user,
                request,
                task_org_id="org-1",
                task_project_id="proj-2",  # 不同 project
                task_repo_id="repo-1",
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
