"""
Worker 执行器框架（Task 1.1.4）

职责：
- Worker 状态机管理（REQ-RT-002 §7）
- Action 队列处理
- Worker 生命周期控制
- 与 ActionExecutor 集成
"""
from .action_queue import ActionQueue
from .lifecycle import WorkerLifecycle, WorkerStateTransitionError
from .worker_executor import WorkerExecutor

__all__ = [
    "ActionQueue",
    "WorkerLifecycle",
    "WorkerStateTransitionError",
    "WorkerExecutor",
]
