"""
留存策略模块 - 事件留存期限管理

负责：
1. 定义事件类型的留存期限
2. 区分热存储和冷存储
3. 支持法定保留期
"""

from dataclasses import dataclass
from enum import Enum


class EventTypeCategory(str, Enum):
    """事件类型分类"""
    BUSINESS = "BUSINESS"          # 业务事件
    AUDIT = "AUDIT"                # 审计事件（必须永久保留）
    DIAGNOSTIC = "DIAGNOSTIC"      # 诊断事件（可删除）
    LIFECYCLE = "LIFECYCLE"        # 生命周期事件
    OBSERVATION = "OBSERVATION"    # 观察事件


@dataclass
class RetentionPolicy:
    """
    事件留存策略
    
    定义一类事件的热存储/冷存储/法定保留期限
    """
    
    event_category: EventTypeCategory
    """事件类型分类"""
    
    hot_storage_days: int
    """热存储期限（天数）- 可查询期"""
    
    cold_storage_days: int
    """冷存储期限（天数）- 总保留期"""
    
    legal_hold_days: int | None
    """法定保留期限（天数）- None 表示永久保留"""
    
    def is_in_hot_storage(self, age_days: int) -> bool:
        """检查数据是否在热存储期内"""
        return age_days <= self.hot_storage_days
    
    def is_in_cold_storage(self, age_days: int) -> bool:
        """检查数据是否在冷存储期内"""
        return age_days <= self.cold_storage_days
    
    def is_legally_held(self, age_days: int) -> bool:
        """检查数据是否需要法定保留"""
        if self.legal_hold_days is None:
            return True  # 永久保留
        return age_days <= self.legal_hold_days
    
    def should_delete(self, age_days: int) -> bool:
        """
        检查数据是否应该被删除
        
        返回 False 意味着数据必须保留
        """
        # 如果在冷存储期内，不删除
        if self.is_in_cold_storage(age_days):
            return False
        
        # 如果超过冷存储，检查法定保留
        # legal_hold_days=None 表示永久保留
        if self.legal_hold_days is None:
            return False
        
        # 如果有有限的法定保留期
        if age_days <= self.legal_hold_days:
            return False
        
        # 超过冷存储和法定保留，可以删除
        return True
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "event_category": self.event_category.value,
            "hot_storage_days": self.hot_storage_days,
            "cold_storage_days": self.cold_storage_days,
            "legal_hold_days": self.legal_hold_days,
        }


class RetentionPolicies:
    """
    预定义的留存策略集合
    """
    
    # 业务事件：30天热存储，180天冷存储，超过180天可删除（无法定保留）
    BUSINESS_EVENT = RetentionPolicy(
        event_category=EventTypeCategory.BUSINESS,
        hot_storage_days=30,
        cold_storage_days=180,
        legal_hold_days=180,  # 与冷存储期相同 = 无额外法定保留
    )
    
    # 审计事件：30天热存储，永久冷存储和法定保留
    AUDIT_EVENT = RetentionPolicy(
        event_category=EventTypeCategory.AUDIT,
        hot_storage_days=30,
        cold_storage_days=36500,  # 100 年
        legal_hold_days=None,  # 永久
    )
    
    # 诊断 Trace：7天热存储，90天冷存储，超过90天可删除（无法定保留）
    DIAGNOSTIC_TRACE = RetentionPolicy(
        event_category=EventTypeCategory.DIAGNOSTIC,
        hot_storage_days=7,
        cold_storage_days=90,
        legal_hold_days=90,  # 与冷存储期相同 = 无额外法定保留
    )
    
    # 生命周期事件：30天热存储，180天冷存储，超过180天可删除（无法定保留）
    LIFECYCLE_EVENT = RetentionPolicy(
        event_category=EventTypeCategory.LIFECYCLE,
        hot_storage_days=30,
        cold_storage_days=180,
        legal_hold_days=180,  # 与冷存储期相同 = 无额外法定保留
    )
    
    # 观察事件：14天热存储，90天冷存储，超过90天可删除（无法定保留）
    OBSERVATION_EVENT = RetentionPolicy(
        event_category=EventTypeCategory.OBSERVATION,
        hot_storage_days=14,
        cold_storage_days=90,
        legal_hold_days=90,  # 与冷存储期相同 = 无额外法定保留
    )
    
    # 映射表：事件类型 -> 留存策略
    POLICY_MAP = {
        EventTypeCategory.BUSINESS: BUSINESS_EVENT,
        EventTypeCategory.AUDIT: AUDIT_EVENT,
        EventTypeCategory.DIAGNOSTIC: DIAGNOSTIC_TRACE,
        EventTypeCategory.LIFECYCLE: LIFECYCLE_EVENT,
        EventTypeCategory.OBSERVATION: OBSERVATION_EVENT,
    }
    
    @classmethod
    def get_policy(cls, event_category: EventTypeCategory) -> RetentionPolicy:
        """
        获取事件类型的留存策略
        
        Args:
            event_category: 事件类型分类
            
        Returns:
            留存策略
        """
        return cls.POLICY_MAP.get(event_category, cls.BUSINESS_EVENT)
    
    @classmethod
    def all_policies(cls) -> list[RetentionPolicy]:
        """获取所有预定义策略"""
        return list(cls.POLICY_MAP.values())
