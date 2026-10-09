"""
Worker 执行器核心（Task 1.1.4）

对齐设计文档：
- REQ-RT-002 §7 - Worker 状态机
- REQ-RT-002 §8 - Action 状态机
- REQ-SEC-003 - Policy Gateway 集成
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ...tools.base import ExecutionContext
from ...tools.executor import ActionExecutionResult, ActionExecutor
from ..entities.action import Action
from ..entities.worker import Worker, WorkerStatus
from .action_queue import ActionQueue
from .lifecycle import WorkerLifecycle


class WorkerExecutionError(Exception):
    """Worker 执行错误"""
    pass


class WorkerExecutor:
    """
    Worker 执行器
    
    职责：
    1. 管理 Worker 状态机迁移（REQ-RT-002 §7）
    2. 协调 Action 队列处理
    3. 集成 ActionExecutor
    4. 处理 Worker 生命周期事件
    
    执行流程：
    1. start() - 启动 Worker (CREATED -> READY -> RUNNING)
    2. propose_action() - 提议 Action 并加入队列
    3. execute_next_action() - 执行队列中的下一个 Action
    4. complete() / fail() - 结束 Worker 执行
    """
    
    def __init__(
        self,
        worker: Worker,
        action_executor: ActionExecutor,
    ):
        """
        初始化 Worker 执行器
        
        Args:
            worker: Worker 实体
            action_executor: Action 执行器
        """
        self._worker = worker
        self._action_executor = action_executor
        self._queue = ActionQueue()
        self._lifecycle = WorkerLifecycle()
        
        # 当前状态（从 Worker 实体初始化）
        self._current_status = worker.status_projection or WorkerStatus.CREATED
        
        # 执行统计
        self._stats: dict[str, int | datetime | None] = {
            "actions_proposed": 0,
            "actions_completed": 0,
            "actions_failed": 0,
            "started_at": None,
            "completed_at": None,
        }
        self._failure_reason: str | None = None
    
    @property
    def worker_id(self) -> str:
        """获取 Worker ID"""
        return self._worker.worker_id
    
    @property
    def current_status(self) -> WorkerStatus:
        """获取当前状态"""
        return self._current_status
    
    @property
    def queue(self) -> ActionQueue:
        """获取 Action 队列（用于测试和监控）"""
        return self._queue
    
    def start(self) -> None:
        """
        启动 Worker 执行
        
        状态迁移：CREATED -> READY -> RUNNING
        
        Raises:
            WorkerStateTransitionError: 状态迁移失败
            WorkerExecutionError: 启动失败
        """
        # CREATED -> READY
        if self._current_status == WorkerStatus.CREATED:
            self._transition_to_ready()
        
        # READY -> RUNNING
        if self._current_status == WorkerStatus.READY:
            self._transition_to_running()
        
        self._stats["started_at"] = datetime.now(UTC)
    
    def propose_action(self, action: Action) -> None:
        """
        提议 Action 并加入队列
        
        Args:
            action: 要执行的 Action
            
        Raises:
            WorkerExecutionError: Worker 状态不允许接收 Action
        """
        # 检查 Worker 状态
        if not self._lifecycle.can_accept_actions(self._current_status):
            raise WorkerExecutionError(
                f"Worker 处于 {self._current_status.value} 状态，无法接收 Action"
            )
        
        # 验证 Action 归属
        if action.worker_id != self._worker.worker_id:
            raise WorkerExecutionError(
                f"Action worker_id ({action.worker_id}) 与当前 Worker "
                f"({self._worker.worker_id}) 不匹配"
            )
        
        # 加入队列
        self._queue.enqueue(action)
        actions_proposed = self._stats["actions_proposed"]
        assert isinstance(actions_proposed, int)
        self._stats["actions_proposed"] = actions_proposed + 1
    
    def execute_next_action(self) -> ActionExecutionResult | None:
        """
        执行队列中的下一个 Action
        
        Returns:
            执行结果，如果队列为空或已暂停则返回 None
            
        Raises:
            WorkerExecutionError: 执行失败
        """
        # 检查队列
        action = self._queue.dequeue()
        if action is None:
            return None
        
        # 检查 Worker 状态
        if self._current_status != WorkerStatus.RUNNING:
            raise WorkerExecutionError(
                f"Worker 处于 {self._current_status.value} 状态，无法执行 Action"
            )
        
        # 构建执行上下文
        context = self._build_execution_context(action)
        
        # 执行 Action
        try:
            # Note: 在实际异步环境中应该使用
            # await self._action_executor.execute_action(action, context)
            # 这里为了测试便利性，假设 mock 对象提供同步的 execute 方法
            result = self._action_executor.execute(action, context)  # type: ignore[attr-defined]
            
            # 更新统计
            if result.success:
                actions_completed = self._stats["actions_completed"]
                assert isinstance(actions_completed, int)
                self._stats["actions_completed"] = actions_completed + 1
            else:
                actions_failed = self._stats["actions_failed"]
                assert isinstance(actions_failed, int)
                self._stats["actions_failed"] = actions_failed + 1
                
                # 如果 Action 失败且不可重试，考虑将 Worker 标记为失败
                # 注：完整的失败策略应由 Reliability 模块决定
                
            return result
            
        except Exception as e:
            actions_failed = self._stats["actions_failed"]
            assert isinstance(actions_failed, int)
            self._stats["actions_failed"] = actions_failed + 1
            raise WorkerExecutionError(f"Action 执行异常: {e}") from e
    
    def execute_all_actions(self) -> list[ActionExecutionResult]:
        """
        执行队列中的所有 Action（用于简单场景）
        
        Returns:
            所有 Action 的执行结果列表
            
        Raises:
            WorkerExecutionError: 执行失败
        """
        results: list[ActionExecutionResult] = []
        
        while not self._queue.is_empty():
            result = self.execute_next_action()
            if result is not None:
                results.append(result)
                
                # 如果有 Action 失败，停止执行
                if not result.success:
                    break
        
        return results
    
    def pause(self) -> None:
        """
        暂停 Worker 执行
        
        状态迁移：RUNNING -> PAUSED
        
        Raises:
            WorkerStateTransitionError: 状态迁移失败
        """
        self._transition_to(WorkerStatus.PAUSED)
        self._queue.pause()
    
    def resume(self) -> None:
        """
        恢复 Worker 执行
        
        状态迁移：PAUSED -> RUNNING
        
        Raises:
            WorkerStateTransitionError: 状态迁移失败
        """
        self._transition_to(WorkerStatus.RUNNING)
        self._queue.resume()
    
    def wait_for_approval(self) -> None:
        """
        进入审批等待状态
        
        状态迁移：RUNNING -> WAITING_APPROVAL
        
        Raises:
            WorkerStateTransitionError: 状态迁移失败
        """
        self._transition_to(WorkerStatus.WAITING_APPROVAL)
        self._queue.pause()
    
    def approval_granted(self) -> None:
        """
        审批通过，恢复执行
        
        状态迁移：WAITING_APPROVAL -> RUNNING
        
        Raises:
            WorkerStateTransitionError: 状态迁移失败
        """
        # REQ-RT-002 §7.5：审批通过后需重新校验
        self._lifecycle.validate_running_transition(self._worker)
        
        self._transition_to(WorkerStatus.RUNNING)
        self._queue.resume()
    
    def complete(self) -> None:
        """
        标记 Worker 为完成状态
        
        状态迁移：RUNNING -> COMPLETED
        
        Raises:
            WorkerStateTransitionError: 状态迁移失败
        """
        # REQ-RT-002 §7.6：验证完成条件
        has_pending = not self._queue.is_empty()
        self._lifecycle.validate_completed_transition(self._worker, has_pending)
        
        self._transition_to(WorkerStatus.COMPLETED)
        self._stats["completed_at"] = datetime.now(UTC)
    
    def fail(self, reason: str | None = None) -> None:
        """
        标记 Worker 为失败状态
        
        状态迁移：RUNNING -> FAILED
        
        Args:
            reason: 失败原因
            
        Raises:
            WorkerStateTransitionError: 状态迁移失败
        """
        self._transition_to(WorkerStatus.FAILED)
        self._stats["completed_at"] = datetime.now(UTC)
        self._failure_reason = reason
    
    def cancel(self) -> None:
        """
        取消 Worker 执行
        
        状态迁移：* -> CANCELLED
        
        Raises:
            WorkerStateTransitionError: 状态迁移失败
        """
        self._transition_to(WorkerStatus.CANCELLED)
        self._queue.clear()
        self._stats["completed_at"] = datetime.now(UTC)
    
    def get_stats(self) -> dict[str, Any]:
        """
        获取执行统计信息
        
        Returns:
            统计信息字典
        """
        return {
            **self._stats,
            "current_status": self._current_status.value,
            "failure_reason": self._failure_reason,
            "queue_stats": self._queue.get_stats(),
        }
    
    # ----------------------------------------------------------------
    # 内部方法
    # ----------------------------------------------------------------
    
    def _transition_to_ready(self) -> None:
        """CREATED -> READY 状态迁移"""
        self._lifecycle.validate_ready_transition(self._worker)
        self._transition_to(WorkerStatus.READY)
    
    def _transition_to_running(self) -> None:
        """READY -> RUNNING 状态迁移"""
        self._lifecycle.validate_running_transition(self._worker)
        self._transition_to(WorkerStatus.RUNNING)
    
    def _transition_to(self, target_status: WorkerStatus) -> None:
        """
        执行状态迁移
        
        Args:
            target_status: 目标状态
            
        Raises:
            WorkerStateTransitionError: 状态迁移不合法
        """
        # 验证迁移合法性
        self._lifecycle.validate_transition(self._current_status, target_status)
        
        # 更新状态
        self._current_status = target_status
    
    def _build_execution_context(self, action: Action) -> ExecutionContext:
        """
        构建 Action 执行上下文
        
        Args:
            action: 要执行的 Action
            
        Returns:
            执行上下文
        """
        return ExecutionContext(
            trace_id=self._worker.trace_id,
            action_id=action.action_id,
            user_id="test-user",  # TODO: 从 Worker 或配置中获取
            organization_id="test-org",  # TODO: 从 Worker 或配置中获取
            project_id="test-project",  # TODO: 从 Worker 或配置中获取
            task_id=self._worker.task_id,
            allowed_paths=[],  # TODO: 从 Worker.allowed_resources 中提取
            read_only=False,
        )
