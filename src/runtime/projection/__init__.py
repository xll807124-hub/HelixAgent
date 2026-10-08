"""
Runtime 状态投影模块（REQ-RT-004）

该模块实现事件驱动的状态投影机制，将不可变事件流转换为可查询的实体当前状态。

核心原则：
1. 事件是唯一事实源，投影状态只服务查询
2. 投影永远不能反向修改事件
3. 支持从零重建并保证一致性
4. 投影过程禁止触发外部副作用

子模块：
- checkpoint: 投影消费者进度记录
- models: 投影状态模型（Task/Workflow/Worker/Action Projection）
- projector: 投影器基类与事件应用逻辑
- task_projector: Task 投影器实现
- workflow_projector: Workflow 投影器实现
- worker_projector: Worker 投影器实现
- action_projector: Action 投影器实现
- storage: 存储接口抽象
- in_memory_storage: 内存存储实现（测试用）
- rebuilder: 从零重建机制和健康监控
"""

from .action_projector import ActionProjector
from .checkpoint import ProjectionCheckpoint, ProjectionStatus
from .in_memory_storage import InMemoryProjectionStorage
from .models import (
    ActionProjection,
    TaskProjection,
    WorkerProjection,
    WorkflowProjection,
)
from .projector import (
    BaseProjector,
    EventApplicationResponse,
    EventApplicationResult,
)
from .rebuilder import (
    ProjectionHealthMonitor,
    ProjectionRebuilder,
    RebuildResult,
)
from .storage import ProjectionStorage
from .task_projector import TaskProjector
from .worker_projector import WorkerProjector
from .workflow_projector import WorkflowProjector

__all__ = [
    # Checkpoint
    "ProjectionCheckpoint",
    "ProjectionStatus",
    # Models
    "TaskProjection",
    "WorkflowProjection",
    "WorkerProjection",
    "ActionProjection",
    # Projector Base
    "BaseProjector",
    "EventApplicationResult",
    "EventApplicationResponse",
    # Projector Implementations
    "TaskProjector",
    "WorkflowProjector",
    "WorkerProjector",
    "ActionProjector",
    # Storage
    "ProjectionStorage",
    "InMemoryProjectionStorage",
    # Rebuilder
    "ProjectionRebuilder",
    "ProjectionHealthMonitor",
    "RebuildResult",
]
