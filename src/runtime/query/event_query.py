"""
事件查询服务 - Event Query API

负责：
1. 事件查询与过滤
2. 权限检查和脱敏
3. 分页和排序
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from src.runtime.event_store.envelope import EventEnvelope, DataSensitivity
from .access_control import AccessController, AccessLevel, UserContext
from .redaction_engine import RedactionEngine, SensitivityLevel


@dataclass
class EventQueryRequest:
    """事件查询请求"""
    task_id: str
    page: int = 1
    limit: int = 50
    include_payload: bool = False
    access_level: Optional[AccessLevel] = None  # None = 使用用户最高级别
    occurred_after: Optional[datetime] = None
    occurred_before: Optional[datetime] = None


@dataclass
class RedactedEvent:
    """脱敏后的事件"""
    event_id: str
    event_type: str
    task_id: str
    occurred_at: datetime
    payload: dict[str, Any]
    redaction_info: dict[str, Any]
    access_level_applied: AccessLevel


class EventQueryService:
    """
    事件查询服务
    
    主要职责：
    1. 验证用户权限
    2. 查询事件
    3. 脱敏返回
    """
    
    def __init__(
        self,
        event_store,  # EventStore 实例
        access_controller: Optional[AccessController] = None,
        redaction_engine: Optional[RedactionEngine] = None,
    ):
        """
        初始化查询服务
        
        Args:
            event_store: 事件存储实例
            access_controller: 访问控制器（可选，会创建默认实例）
            redaction_engine: 脱敏引擎（可选，会创建默认实例）
        """
        self.event_store = event_store
        self.access_controller = access_controller or AccessController()
        self.redaction_engine = redaction_engine or RedactionEngine()
    
    def query_events(
        self,
        user: UserContext,
        request: EventQueryRequest,
        task_org_id: str,
        task_project_id: str,
        task_repo_id: str,
    ) -> tuple[list[RedactedEvent], int]:
        """
        查询事件（带权限检查和脱敏）
        
        Args:
            user: 用户上下文
            request: 查询请求
            task_org_id: 任务所属 organization
            task_project_id: 任务所属 project
            task_repo_id: 任务所属 repository
            
        Returns:
            (脱敏后的事件列表, 总数)
            
        Raises:
            PermissionError: 无访问权限
            ValueError: 无效的查询参数
        """
        # 步骤 1：权限检查
        if not self.access_controller.check_event_access(
            user, task_org_id, task_project_id, task_repo_id
        ):
            raise PermissionError(
                f"User {user.user_id} has no access to task in org {task_org_id}"
            )
        
        # 步骤 2：获取用户实际的访问级别
        user_max_level = self.access_controller.get_access_level(user)
        
        # 步骤 3：归一化请求的访问级别
        # 如果请求没有指定 access_level（None），使用用户的最高级别
        if request.access_level is None:
            actual_access_level = user_max_level
        else:
            actual_access_level = self.access_controller.normalize_access_level(
                request.access_level, user_max_level
            )
        
        # 步骤 4：查询原始事件
        try:
            raw_events, total = self.event_store.query(
                task_id=request.task_id,
                page=request.page,
                limit=request.limit,
                occurred_after=request.occurred_after,
                occurred_before=request.occurred_before,
            )
        except Exception as e:
            raise ValueError(f"Failed to query events: {str(e)}")
        
        # 步骤 5：脱敏返回
        # 如果不返回载荷，使用 BASIC 级别避免泄露；否则使用实际访问级别
        if not request.include_payload:
            redaction_access_level = AccessLevel.BASIC
        else:
            redaction_access_level = actual_access_level
        
        redacted_events = []
        for event in raw_events:
            redacted_event = self._redact_event(
                event, redaction_access_level, actual_access_level
            )
            redacted_events.append(redacted_event)
        
        return redacted_events, total
    
    def _redact_event(
        self, 
        event: EventEnvelope, 
        redaction_access_level: AccessLevel,
        user_actual_access_level: AccessLevel,
    ) -> RedactedEvent:
        """
        脱敏单个事件
        
        Args:
            event: 原始事件
            redaction_access_level: 用于脱敏的访问级别
            user_actual_access_level: 用户的实际访问级别（用于返回）
            
        Returns:
            脱敏后的事件
        """
        # 获取数据敏感级别
        data_sensitivity = self._map_data_sensitivity(event.data_classification)
        
        # 脱敏载荷
        redacted_payload, redaction_info = self.redaction_engine.redact_payload(
            event.payload,
            redaction_access_level,
            data_sensitivity,
        )
        
        return RedactedEvent(
            event_id=event.event_id,
            event_type=event.event_type,
            task_id=event.task_id,
            occurred_at=event.occurred_at,
            payload=redacted_payload,
            redaction_info=redaction_info.to_dict(),
            access_level_applied=user_actual_access_level,
        )
    
    @staticmethod
    def _map_data_sensitivity(
        envelope_classification: DataSensitivity,
    ) -> SensitivityLevel:
        """
        将 EventEnvelope 的数据分类映射到脱敏引擎的敏感级别
        
        Args:
            envelope_classification: Event 中的数据分类
            
        Returns:
            脱敏引擎的敏感级别
        """
        mapping = {
            DataSensitivity.PUBLIC: SensitivityLevel.L0,
            DataSensitivity.INTERNAL: SensitivityLevel.L1,
            DataSensitivity.SENSITIVE: SensitivityLevel.L3,
            DataSensitivity.CONFIDENTIAL: SensitivityLevel.L4,
        }
        return mapping.get(envelope_classification, SensitivityLevel.L1)
