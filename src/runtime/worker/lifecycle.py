"""
Worker 生命周期管理（Task 1.1.4）

对齐设计文档：
- REQ-RT-002 §7 - Worker 状态机与迁移约束
"""
from __future__ import annotations

from ..entities.worker import Worker, WorkerStatus


class WorkerStateTransitionError(Exception):
    """Worker 状态迁移错误"""
    pass


class WorkerLifecycle:
    """
    Worker 生命周期管理器
    
    职责：
    1. 封装状态迁移验证逻辑（REQ-RT-002 §7）
    2. 提供状态转换前置检查
    3. 确保状态机约束得到遵守
    """
    
    # 合法的状态迁移映射（REQ-RT-002 §7.1）
    VALID_TRANSITIONS: dict[WorkerStatus, set[WorkerStatus]] = {
        WorkerStatus.CREATED: {WorkerStatus.READY},
        WorkerStatus.READY: {WorkerStatus.RUNNING, WorkerStatus.CANCELLED},
        WorkerStatus.RUNNING: {
            WorkerStatus.WAITING_APPROVAL,
            WorkerStatus.PAUSED,
            WorkerStatus.COMPLETED,
            WorkerStatus.FAILED,
            WorkerStatus.CANCELLED,
        },
        WorkerStatus.WAITING_APPROVAL: {
            WorkerStatus.RUNNING,
            WorkerStatus.FAILED,
            WorkerStatus.CANCELLED,
        },
        WorkerStatus.PAUSED: {
            WorkerStatus.RUNNING,
            WorkerStatus.CANCELLED,
        },
        # 终态：无法迁移
        WorkerStatus.COMPLETED: set(),
        WorkerStatus.FAILED: set(),
        WorkerStatus.CANCELLED: set(),
    }
    
    # 终态集合
    TERMINAL_STATES = {
        WorkerStatus.COMPLETED,
        WorkerStatus.FAILED,
        WorkerStatus.CANCELLED,
    }
    
    @classmethod
    def validate_transition(
        cls,
        current_status: WorkerStatus,
        target_status: WorkerStatus
    ) -> None:
        """
        验证状态迁移是否合法
        
        Args:
            current_status: 当前状态
            target_status: 目标状态
            
        Raises:
            WorkerStateTransitionError: 状态迁移不合法
        """
        # 检查是否从终态迁移
        if current_status in cls.TERMINAL_STATES:
            raise WorkerStateTransitionError(
                f"无法从终态 {current_status.value} 迁移到 {target_status.value}"
            )
        
        # 检查目标状态是否合法
        valid_targets = cls.VALID_TRANSITIONS.get(current_status, set())
        if target_status not in valid_targets:
            raise WorkerStateTransitionError(
                f"非法状态迁移：{current_status.value} -> {target_status.value}。"
                f"合法目标状态：{[s.value for s in valid_targets]}"
            )
    
    @classmethod
    def can_accept_actions(cls, status: WorkerStatus) -> bool:
        """
        检查当前状态是否可以接收新的 Action 提议
        
        Args:
            status: Worker 当前状态
            
        Returns:
            是否可以接收 Action
        """
        return status == WorkerStatus.RUNNING
    
    @classmethod
    def is_terminal(cls, status: WorkerStatus) -> bool:
        """
        检查状态是否为终态
        
        Args:
            status: Worker 状态
            
        Returns:
            是否为终态
        """
        return status in cls.TERMINAL_STATES
    
    @classmethod
    def validate_ready_transition(cls, worker: Worker) -> None:
        """
        验证 CREATED -> READY 迁移的前置条件（REQ-RT-002 §7.2）
        
        Args:
            worker: Worker 实体
            
        Raises:
            WorkerStateTransitionError: 前置条件不满足
        """
        # 基本字段校验（大部分已由 Worker Pydantic 模型保证）
        if not worker.worker_id:
            raise WorkerStateTransitionError("worker_id 不能为空")
        
        if not worker.workflow_id:
            raise WorkerStateTransitionError("workflow_id 不能为空")
        
        if not worker.task_id:
            raise WorkerStateTransitionError("task_id 不能为空")
        
        if not worker.step_id:
            raise WorkerStateTransitionError("step_id 不能为空")
        
        if worker.attempt < 1:
            raise WorkerStateTransitionError(f"attempt 必须 >= 1，当前值：{worker.attempt}")
        
        if not worker.source_revision:
            raise WorkerStateTransitionError("source_revision 必须已确定")
        
        # REQ-RT-002 §7.2：工具和资源能力已声明
        # 注：允许空列表，表示该 Worker 不需要工具
        
        # REQ-RT-002 §7.2：Worker 预算已分配
        if worker.budget is None:
            raise WorkerStateTransitionError("Worker 预算必须已分配")
    
    @classmethod
    def validate_running_transition(cls, worker: Worker) -> None:
        """
        验证 READY -> RUNNING 迁移的前置条件（REQ-RT-002 §7.3）
        
        Args:
            worker: Worker 实体
            
        Raises:
            WorkerStateTransitionError: 前置条件不满足
        """
        # REQ-RT-002 §7.3：Worker 资源通过授权
        # 注：实际授权检查由 Policy Gateway 负责，此处只做基本校验
        
        # REQ-RT-002 §7.3：执行环境已创建
        # 注：实际环境创建由 Sandbox 负责，此处预留扩展点
        pass
    
    @classmethod
    def validate_completed_transition(
        cls,
        worker: Worker,
        has_pending_actions: bool
    ) -> None:
        """
        验证 RUNNING -> COMPLETED 迁移的前置条件（REQ-RT-002 §7.6）
        
        Args:
            worker: Worker 实体
            has_pending_actions: 是否有未处理的 Action
            
        Raises:
            WorkerStateTransitionError: 前置条件不满足
        """
        # REQ-RT-002 §7.6：没有未处理 Action
        if has_pending_actions:
            raise WorkerStateTransitionError(
                "Worker 仍有未处理的 Action，无法标记为 COMPLETED"
            )
        
        # REQ-RT-002 §7.6：所需 Artifact 或 Evidence 已生成
        # 注：实际验证需要查询 Evidence 存储，此处简化处理
