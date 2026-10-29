"""
RT-008 留存策略单元测试

测试覆盖：
1. 热存储期判定
2. 冷存储期判定
3. 法定保留期判定
4. 删除策略
"""

import pytest

from src.runtime.query.retention_policy import (
    EventTypeCategory,
    RetentionPolicies,
    RetentionPolicy,
)


class TestRetentionPolicy:
    """留存策略测试"""

    def test_business_event_in_hot_storage(self):
        """业务事件在热存储期内"""
        policy = RetentionPolicies.BUSINESS_EVENT
        assert policy.is_in_hot_storage(15) is True
        assert policy.is_in_hot_storage(30) is True
        assert policy.is_in_hot_storage(31) is False

    def test_business_event_in_cold_storage(self):
        """业务事件在冷存储期内"""
        policy = RetentionPolicies.BUSINESS_EVENT
        assert policy.is_in_cold_storage(100) is True
        assert policy.is_in_cold_storage(180) is True
        assert policy.is_in_cold_storage(181) is False

    def test_business_event_can_delete_after_cold_storage(self):
        """业务事件超过冷存储期后可以删除"""
        policy = RetentionPolicies.BUSINESS_EVENT
        assert policy.should_delete(181) is True
        assert policy.should_delete(365) is True

    def test_audit_event_never_delete(self):
        """审计事件永久保留（法定保留=None）"""
        policy = RetentionPolicies.AUDIT_EVENT
        assert policy.is_legally_held(1000) is True
        assert policy.should_delete(1000) is False
        assert policy.should_delete(36500) is False

    def test_diagnostic_trace_in_hot_storage(self):
        """诊断 Trace 在热存储期内"""
        policy = RetentionPolicies.DIAGNOSTIC_TRACE
        assert policy.is_in_hot_storage(3) is True
        assert policy.is_in_hot_storage(7) is True
        assert policy.is_in_hot_storage(8) is False

    def test_diagnostic_trace_can_delete(self):
        """诊断 Trace 可以删除"""
        policy = RetentionPolicies.DIAGNOSTIC_TRACE
        assert policy.should_delete(91) is True

    def test_lifecycle_event_retention(self):
        """生命周期事件留存策略"""
        policy = RetentionPolicies.LIFECYCLE_EVENT
        assert policy.is_in_hot_storage(30) is True
        assert policy.is_in_cold_storage(180) is True
        assert policy.should_delete(181) is True

    def test_observation_event_retention(self):
        """观察事件留存策略"""
        policy = RetentionPolicies.OBSERVATION_EVENT
        assert policy.is_in_hot_storage(14) is True
        assert policy.is_in_cold_storage(90) is True
        assert policy.should_delete(91) is True


class TestRetentionPolicies:
    """留存策略集合测试"""

    def test_get_policy_for_business(self):
        """获取业务事件策略"""
        policy = RetentionPolicies.get_policy(EventTypeCategory.BUSINESS)
        assert policy == RetentionPolicies.BUSINESS_EVENT

    def test_get_policy_for_audit(self):
        """获取审计事件策略"""
        policy = RetentionPolicies.get_policy(EventTypeCategory.AUDIT)
        assert policy == RetentionPolicies.AUDIT_EVENT

    def test_get_policy_for_diagnostic(self):
        """获取诊断事件策略"""
        policy = RetentionPolicies.get_policy(EventTypeCategory.DIAGNOSTIC)
        assert policy == RetentionPolicies.DIAGNOSTIC_TRACE

    def test_get_policy_for_lifecycle(self):
        """获取生命周期事件策略"""
        policy = RetentionPolicies.get_policy(EventTypeCategory.LIFECYCLE)
        assert policy == RetentionPolicies.LIFECYCLE_EVENT

    def test_get_policy_for_observation(self):
        """获取观察事件策略"""
        policy = RetentionPolicies.get_policy(EventTypeCategory.OBSERVATION)
        assert policy == RetentionPolicies.OBSERVATION_EVENT

    def test_all_policies_not_empty(self):
        """所有策略集合非空"""
        policies = RetentionPolicies.all_policies()
        assert len(policies) > 0
        assert len(policies) == 5  # 5 个事件类型

    def test_policy_to_dict(self):
        """策略转换为字典"""
        policy = RetentionPolicies.BUSINESS_EVENT
        policy_dict = policy.to_dict()
        
        assert "event_category" in policy_dict
        assert policy_dict["hot_storage_days"] == 30
        assert policy_dict["cold_storage_days"] == 180


class TestRetentionPolicyEdgeCases:
    """留存策略边界情况测试"""

    def test_zero_age_in_hot_storage(self):
        """新事件在热存储期内"""
        policy = RetentionPolicies.BUSINESS_EVENT
        assert policy.is_in_hot_storage(0) is True

    def test_exactly_hot_boundary(self):
        """恰好在热存储期边界"""
        policy = RetentionPolicies.BUSINESS_EVENT
        assert policy.is_in_hot_storage(30) is True
        assert policy.is_in_hot_storage(31) is False

    def test_exactly_cold_boundary(self):
        """恰好在冷存储期边界"""
        policy = RetentionPolicies.BUSINESS_EVENT
        assert policy.is_in_cold_storage(180) is True
        assert policy.is_in_cold_storage(181) is False

    def test_audit_event_permanent_hold(self):
        """审计事件永久保留策略"""
        policy = RetentionPolicies.AUDIT_EVENT
        # 法定保留 = None 表示永久
        assert policy.legal_hold_days is None
        assert policy.is_legally_held(1000000) is True
        assert policy.should_delete(1000000) is False

    def test_custom_policy_with_finite_hold(self):
        """自定义留存策略（有限期法定保留）"""
        policy = RetentionPolicy(
            event_category=EventTypeCategory.BUSINESS,
            hot_storage_days=30,
            cold_storage_days=180,
            legal_hold_days=365,
        )
        
        # 超过冷存储但在法定保留内
        assert policy.is_in_cold_storage(200) is False
        assert policy.is_legally_held(200) is True
        assert policy.should_delete(200) is False
        
        # 超过法定保留
        assert policy.should_delete(366) is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
