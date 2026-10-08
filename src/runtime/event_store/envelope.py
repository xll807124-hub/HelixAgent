"""
Event Envelope - 事件信封模型

本模块定义统一的事件信封结构，是平台事件事实源的核心数据模型。
所有事件必须通过EventEnvelope封装，确保：
- 不可变事实记录
- 完整的业务坐标（task/workflow/worker/action）
- 可追踪的因果关系和追踪链
- 类型安全的载荷验证
- 内容哈希完整性

设计依据：REQ-RT-003 Event Schema与版本策略
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from ..common.types import (
    ActorRef,
    ensure_utc,
    generate_entity_id,
)

# 类型别名（与 REQ-RT-001 对齐）
EventId = str
TaskId = str
EntityId = str
WorkflowId = str
WorkerId = str
ActionId = str
TraceId = str
SpanId = str


class EventCategory(str, Enum):
    """事件分类"""
    DOMAIN = "DOMAIN"  # 业务事实变化
    LIFECYCLE = "LIFECYCLE"  # 实体生命周期变化
    ACTION = "ACTION"  # Action/工具生命周期
    CONTROL = "CONTROL"  # 人工或系统控制
    OBSERVATION = "OBSERVATION"  # 执行结果和外部观察
    AUDIT = "AUDIT"  # 安全、策略和审计事实
    SYSTEM = "SYSTEM"  # 运行时基础设施事实


class CausationType(str, Enum):
    """因果类型"""
    EVENT = "EVENT"  # 由另一个事件触发
    COMMAND = "COMMAND"  # 由命令触发
    EXTERNAL_CALLBACK = "EXTERNAL_CALLBACK"  # 外部系统回调
    SYSTEM_RECOVERY = "SYSTEM_RECOVERY"  # 系统恢复触发


class DataSensitivity(str, Enum):
    """数据敏感级别"""
    PUBLIC = "PUBLIC"  # L1 公开
    INTERNAL = "INTERNAL"  # L2 内部
    SENSITIVE = "SENSITIVE"  # L3 敏感
    CONFIDENTIAL = "CONFIDENTIAL"  # L4 机密


@dataclass(frozen=True)
class CausationRef:
    """因果引用"""
    causation_type: CausationType
    causation_id: str
    parent_event_id: EventId | None = None
    root_event_id: EventId | None = None

    def __post_init__(self) -> None:
        """验证因果引用"""
        if not self.causation_id or not self.causation_id.strip():
            raise ValueError("causation_id cannot be empty")


@dataclass(frozen=True)
class ProducerRef:
    """生产者引用"""
    producer_type: str  # WORKER / SYSTEM / USER / TOOL / EXTERNAL_PROVIDER
    producer_id: str
    producer_version: str

    def __post_init__(self) -> None:
        """验证生产者"""
        if not self.producer_type or not self.producer_type.strip():
            raise ValueError("producer_type cannot be empty")
        if not self.producer_id or not self.producer_id.strip():
            raise ValueError("producer_id cannot be empty")
        if not self.producer_version or not self.producer_version.strip():
            raise ValueError("producer_version cannot be empty")


@dataclass(frozen=True)
class ContentRef:
    """内容引用（大型载荷的对象存储引用）"""
    content_type: str  # DIFF / LOG / ARTIFACT / EVIDENCE / MODEL_OUTPUT
    storage_url: str
    content_hash: str
    size_bytes: int

    def __post_init__(self) -> None:
        """验证内容引用"""
        if not self.content_type or not self.content_type.strip():
            raise ValueError("content_type cannot be empty")
        if not self.storage_url or not self.storage_url.strip():
            raise ValueError("storage_url cannot be empty")
        if not self.content_hash or not self.content_hash.strip():
            raise ValueError("content_hash cannot be empty")
        if self.size_bytes < 0:
            raise ValueError("size_bytes must be non-negative")


@dataclass
class EventEnvelope:
    """
    事件信封 - 统一事件结构
    
    所有事件必须包含完整的元数据和业务坐标，确保可追溯、可回放、可审计。
    
    核心字段：
    - event_id: 事件唯一标识（UUIDv7）
    - event_type: 事件类型（如 TaskCreated, ActionProposed）
    - task_id: 所属任务
    - trace_id: 追踪标识
    - sequence: 单调递增序列（由存储层分配）
    - payload: 事件载荷（类型化JSON）
    
    不变量：
    - 事件一旦创建不可修改
    - event_id全局唯一
    - 同一task_id内sequence单调递增
    - payload必须符合payload_schema
    """
    
    # === 元数据 ===
    schema_version: str = "runtime.event-envelope.v1"
    event_id: EventId = field(default_factory=generate_entity_id)
    event_type: str = ""
    event_type_version: str = "v1"
    event_category: EventCategory = EventCategory.DOMAIN
    
    # === 业务坐标（必填） ===
    task_id: TaskId = field(default_factory=generate_entity_id)
    organization_id: EntityId = field(default_factory=generate_entity_id)
    project_id: EntityId = field(default_factory=generate_entity_id)
    repository_id: EntityId = field(default_factory=generate_entity_id)
    
    # === 业务坐标（可选，按层级） ===
    workflow_id: WorkflowId | None = None
    worker_id: WorkerId | None = None
    action_id: ActionId | None = None
    step_id: str | None = None
    attempt: int = 1
    
    # === 追踪 ===
    trace_id: TraceId = field(default_factory=generate_entity_id)
    span_id: SpanId | None = None
    parent_span_id: SpanId | None = None
    source_revision: str | None = None
    
    # === 执行者 ===
    actor: ActorRef = field(default_factory=lambda: ActorRef(
        actor_type="SYSTEM",
        actor_id="runtime"
    ))
    
    # === 时序 ===
    occurred_at: datetime = field(default_factory=lambda: ensure_utc(datetime.now(UTC)))
    recorded_at: datetime | None = None  # 由存储层设置
    sequence: int = 0  # 由存储层分配
    
    # === 因果 ===
    causation: CausationRef = field(default_factory=lambda: CausationRef(
        causation_type=CausationType.COMMAND,
        causation_id="init"
    ))
    correlation_id: str = field(default_factory=generate_entity_id)
    idempotency_key: str | None = None
    
    # === 载荷 ===
    payload_schema: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    
    # === 安全 ===
    data_classification: DataSensitivity = DataSensitivity.INTERNAL
    content_refs: list[ContentRef] = field(default_factory=list)
    redaction_applied: bool = False
    
    # === 生产者 ===
    producer: ProducerRef = field(default_factory=lambda: ProducerRef(
        producer_type="SYSTEM",
        producer_id="runtime",
        producer_version="v0.1.0"
    ))
    
    # === 扩展元数据 ===
    extensions: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """验证事件信封"""
        # 验证必填字段
        if not self.event_type or not self.event_type.strip():
            raise ValueError("event_type cannot be empty")
        if not self.payload_schema or not self.payload_schema.strip():
            raise ValueError("payload_schema cannot be empty")
        
        # 验证时间
        if not isinstance(self.occurred_at, datetime):
            raise ValueError("occurred_at must be datetime")
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware (UTC)")
        
        # 验证attempt
        if self.attempt < 1:
            raise ValueError("attempt must be >= 1")
        
        # 验证sequence（存储前为0）
        if self.sequence < 0:
            raise ValueError("sequence must be non-negative")

    def compute_content_hash(self) -> str:
        """
        计算事件内容哈希
        
        用于完整性验证和去重检测。
        哈希包含：event_id + event_type + task_id + payload
        
        Returns:
            SHA-256哈希（十六进制）
        """
        content = {
            "event_id": str(self.event_id),
            "event_type": self.event_type,
            "event_type_version": self.event_type_version,
            "task_id": str(self.task_id),
            "occurred_at": self.occurred_at.isoformat(),
            "payload": self.payload,
        }
        
        # 规范化JSON（排序key）
        canonical_json = json.dumps(content, sort_keys=True, ensure_ascii=False)
        
        # 计算SHA-256
        return hashlib.sha256(canonical_json.encode('utf-8')).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        """
        转换为字典（用于序列化）
        
        Returns:
            包含所有字段的字典
        """
        return {
            "schema_version": self.schema_version,
            "event_id": str(self.event_id),
            "event_type": self.event_type,
            "event_type_version": self.event_type_version,
            "event_category": self.event_category.value,
            "task_id": str(self.task_id),
            "organization_id": str(self.organization_id),
            "project_id": str(self.project_id),
            "repository_id": str(self.repository_id),
            "workflow_id": str(self.workflow_id) if self.workflow_id else None,
            "worker_id": str(self.worker_id) if self.worker_id else None,
            "action_id": str(self.action_id) if self.action_id else None,
            "step_id": self.step_id,
            "attempt": self.attempt,
            "trace_id": str(self.trace_id),
            "span_id": str(self.span_id) if self.span_id else None,
            "parent_span_id": str(self.parent_span_id) if self.parent_span_id else None,
            "source_revision": self.source_revision,
            "actor": {
                "actor_type": self.actor.actor_type,
                "actor_id": self.actor.actor_id,
            },
            "occurred_at": self.occurred_at.isoformat(),
            "recorded_at": self.recorded_at.isoformat() if self.recorded_at else None,
            "sequence": self.sequence,
            "causation": {
                "causation_type": self.causation.causation_type.value,
                "causation_id": self.causation.causation_id,
                "parent_event_id": (
                    str(self.causation.parent_event_id)
                    if self.causation.parent_event_id
                    else None
                ),
                "root_event_id": (
                    str(self.causation.root_event_id)
                    if self.causation.root_event_id
                    else None
                ),
            },
            "correlation_id": self.correlation_id,
            "idempotency_key": self.idempotency_key,
            "payload_schema": self.payload_schema,
            "payload": self.payload,
            "data_classification": self.data_classification.value,
            "content_refs": [
                {
                    "content_type": ref.content_type,
                    "storage_url": ref.storage_url,
                    "content_hash": ref.content_hash,
                    "size_bytes": ref.size_bytes,
                }
                for ref in self.content_refs
            ],
            "redaction_applied": self.redaction_applied,
            "producer": {
                "producer_type": self.producer.producer_type,
                "producer_id": self.producer.producer_id,
                "producer_version": self.producer.producer_version,
            },
            "extensions": self.extensions,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EventEnvelope":
        """
        从字典创建事件信封（用于反序列化）
        
        Args:
            data: 字典数据
            
        Returns:
            EventEnvelope实例
        """
        # 解析时间（to_dict 使用 isoformat 输出，标准库 fromisoformat 可无损还原）
        occurred_at = datetime.fromisoformat(data["occurred_at"])
        recorded_at = (
            datetime.fromisoformat(data["recorded_at"]) if data.get("recorded_at") else None
        )
        
        # 解析因果
        causation_data = data["causation"]
        causation = CausationRef(
            causation_type=CausationType(causation_data["causation_type"]),
            causation_id=causation_data["causation_id"],
            parent_event_id=causation_data.get("parent_event_id"),
            root_event_id=causation_data.get("root_event_id"),
        )
        
        # 解析生产者
        producer_data = data["producer"]
        producer = ProducerRef(
            producer_type=producer_data["producer_type"],
            producer_id=producer_data["producer_id"],
            producer_version=producer_data["producer_version"],
        )
        
        # 解析内容引用
        content_refs = [
            ContentRef(
                content_type=ref["content_type"],
                storage_url=ref["storage_url"],
                content_hash=ref["content_hash"],
                size_bytes=ref["size_bytes"],
            )
            for ref in data.get("content_refs", [])
        ]
        
        # 解析执行者
        actor_data = data["actor"]
        actor = ActorRef(
            actor_type=actor_data["actor_type"],
            actor_id=actor_data["actor_id"],
        )
        
        return cls(
            schema_version=data.get("schema_version", "runtime.event-envelope.v1"),
            event_id=data["event_id"],
            event_type=data["event_type"],
            event_type_version=data["event_type_version"],
            event_category=EventCategory(data["event_category"]),
            task_id=data["task_id"],
            organization_id=data["organization_id"],
            project_id=data["project_id"],
            repository_id=data["repository_id"],
            workflow_id=data.get("workflow_id"),
            worker_id=data.get("worker_id"),
            action_id=data.get("action_id"),
            step_id=data.get("step_id"),
            attempt=data.get("attempt", 1),
            trace_id=data["trace_id"],
            span_id=data.get("span_id"),
            parent_span_id=data.get("parent_span_id"),
            source_revision=data.get("source_revision"),
            actor=actor,
            occurred_at=occurred_at,
            recorded_at=recorded_at,
            sequence=data.get("sequence", 0),
            causation=causation,
            correlation_id=data["correlation_id"],
            idempotency_key=data.get("idempotency_key"),
            payload_schema=data["payload_schema"],
            payload=data["payload"],
            data_classification=DataSensitivity(data.get("data_classification", "INTERNAL")),
            content_refs=content_refs,
            redaction_applied=data.get("redaction_applied", False),
            producer=producer,
            extensions=data.get("extensions", {}),
        )
