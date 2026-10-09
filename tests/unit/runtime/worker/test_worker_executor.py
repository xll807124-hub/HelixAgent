"""
WorkerExecutor 单元测试

覆盖：
- Worker 启动流程
- Action 提议和队列管理
- Action 执行
- 状态迁移
- 暂停/恢复/审批流程
"""
from unittest.mock import Mock

import pytest

from src.runtime.entities.worker import WorkerStatus
from src.runtime.worker import WorkerExecutor, WorkerStateTransitionError
from src.runtime.worker.worker_executor import WorkerExecutionError
from src.tools.executor import ActionExecutionResult
from tests.helpers.action_factory import create_test_action, create_test_worker


class TestWorkerExecutor:
    """WorkerExecutor 单元测试"""
    
    @pytest.fixture
    def mock_action_executor(self):
        """Mock ActionExecutor"""
        mock = Mock()
        mock.execute = Mock()
        return mock
    
    @pytest.fixture
    def worker(self):
        """创建测试 Worker"""
        return create_test_worker(
            status=WorkerStatus.CREATED
        )
    
    @pytest.fixture
    def executor(self, worker, mock_action_executor):
        """创建 WorkerExecutor 实例"""
        return WorkerExecutor(
            worker=worker,
            action_executor=mock_action_executor
        )
    
    # ----------------------------------------------------------------
    # 启动和初始化测试
    # ----------------------------------------------------------------
    
    def test_initialization(self, executor, worker):
        """测试：初始化状态"""
        assert executor.worker_id == worker.worker_id
        assert executor.current_status == WorkerStatus.CREATED
        assert executor.queue.is_empty()
    
    def test_start_transitions_to_running(self, executor):
        """测试：启动后进入 RUNNING 状态"""
        executor.start()
        
        assert executor.current_status == WorkerStatus.RUNNING
        stats = executor.get_stats()
        assert stats["started_at"] is not None
    
    def test_start_from_ready_goes_to_running(self, mock_action_executor):
        """测试：从 READY 状态启动"""
        worker = create_test_worker(status=WorkerStatus.READY)
        executor = WorkerExecutor(worker, mock_action_executor)
        
        executor.start()
        assert executor.current_status == WorkerStatus.RUNNING
    
    def test_start_already_running_is_idempotent(self, mock_action_executor):
        """测试：已经 RUNNING 的 Worker 启动是幂等的"""
        worker = create_test_worker(status=WorkerStatus.RUNNING)
        executor = WorkerExecutor(worker, mock_action_executor)
        
        # 不应抛出异常
        executor.start()
        assert executor.current_status == WorkerStatus.RUNNING
    
    # ----------------------------------------------------------------
    # Action 提议测试
    # ----------------------------------------------------------------
    
    def test_propose_action_when_running(self, executor):
        """测试：RUNNING 状态可以提议 Action"""
        executor.start()
        
        action = create_test_action(
            worker_id=executor.worker_id
        )
        
        executor.propose_action(action)
        
        assert executor.queue.size() == 1
        assert executor.queue.peek().action_id == action.action_id
        
        stats = executor.get_stats()
        assert stats["actions_proposed"] == 1
    
    def test_propose_action_when_not_running_fails(self, executor):
        """测试：非 RUNNING 状态无法提议 Action"""
        # Worker 处于 CREATED 状态
        action = create_test_action(worker_id=executor.worker_id)
        
        with pytest.raises(WorkerExecutionError, match="无法接收 Action"):
            executor.propose_action(action)
    
    def test_propose_action_with_mismatched_worker_id_fails(self, executor):
        """测试：worker_id 不匹配的 Action 被拒绝"""
        executor.start()
        
        action = create_test_action()  # 生成一个不同的 worker_id
        
        with pytest.raises(WorkerExecutionError, match="不匹配"):
            executor.propose_action(action)
    
    def test_propose_multiple_actions(self, executor):
        """测试：提议多个 Action"""
        executor.start()
        
        action1 = create_test_action(worker_id=executor.worker_id)
        action2 = create_test_action(worker_id=executor.worker_id)
        action3 = create_test_action(worker_id=executor.worker_id)
        
        executor.propose_action(action1)
        executor.propose_action(action2)
        executor.propose_action(action3)
        
        assert executor.queue.size() == 3
        stats = executor.get_stats()
        assert stats["actions_proposed"] == 3
    
    # ----------------------------------------------------------------
    # Action 执行测试
    # ----------------------------------------------------------------
    
    def test_execute_next_action_success(self, executor, mock_action_executor):
        """测试：执行 Action 成功"""
        executor.start()
        
        action = create_test_action(worker_id=executor.worker_id)
        executor.propose_action(action)
        
        # Mock 执行成功
        mock_result = ActionExecutionResult(
            success=True,
            action=action,
            evidence=None
        )
        mock_action_executor.execute.return_value = mock_result
        
        result = executor.execute_next_action()
        
        assert result is not None
        assert result.success is True
        assert executor.queue.is_empty()
        
        stats = executor.get_stats()
        assert stats["actions_completed"] == 1
        assert stats["actions_failed"] == 0
    
    def test_execute_next_action_failure(self, executor, mock_action_executor):
        """测试：执行 Action 失败"""
        executor.start()
        
        action = create_test_action(worker_id=executor.worker_id)
        executor.propose_action(action)
        
        # Mock 执行失败
        mock_result = ActionExecutionResult(
            success=False,
            action=action,
            error="Tool execution failed"
        )
        mock_action_executor.execute.return_value = mock_result
        
        result = executor.execute_next_action()
        
        assert result is not None
        assert result.success is False
        
        stats = executor.get_stats()
        assert stats["actions_completed"] == 0
        assert stats["actions_failed"] == 1
    
    def test_execute_next_action_when_queue_empty(self, executor):
        """测试：队列为空时 execute_next_action 返回 None"""
        executor.start()
        
        result = executor.execute_next_action()
        assert result is None
    
    def test_execute_all_actions(self, executor, mock_action_executor):
        """测试：执行队列中的所有 Action"""
        executor.start()
        
        action1 = create_test_action(worker_id=executor.worker_id)
        action2 = create_test_action(worker_id=executor.worker_id)
        action3 = create_test_action(worker_id=executor.worker_id)
        
        executor.propose_action(action1)
        executor.propose_action(action2)
        executor.propose_action(action3)
        
        # Mock 所有执行成功
        mock_action_executor.execute.return_value = ActionExecutionResult(
            success=True,
            action=Mock(),
            evidence=None
        )
        
        results = executor.execute_all_actions()
        
        assert len(results) == 3
        assert all(r.success for r in results)
        assert executor.queue.is_empty()
        
        stats = executor.get_stats()
        assert stats["actions_completed"] == 3
    
    def test_execute_all_actions_stops_on_failure(self, executor, mock_action_executor):
        """测试：execute_all_actions 在失败时停止"""
        executor.start()
        
        action1 = create_test_action(worker_id=executor.worker_id)
        action2 = create_test_action(worker_id=executor.worker_id)
        action3 = create_test_action(worker_id=executor.worker_id)
        
        executor.propose_action(action1)
        executor.propose_action(action2)
        executor.propose_action(action3)
        
        # 第二个 Action 失败
        call_count = 0
        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                return ActionExecutionResult(success=False, action=Mock(), error="Failed")
            return ActionExecutionResult(success=True, action=Mock())
        
        mock_action_executor.execute.side_effect = side_effect
        
        results = executor.execute_all_actions()
        
        # 只执行了 2 个（第二个失败后停止）
        assert len(results) == 2
        assert results[0].success is True
        assert results[1].success is False
        
        # 第三个 Action 还在队列中
        assert executor.queue.size() == 1
    
    # ----------------------------------------------------------------
    # 状态迁移测试
    # ----------------------------------------------------------------
    
    def test_complete_success(self, executor):
        """测试：完成 Worker"""
        executor.start()
        
        # 队列为空，可以完成
        executor.complete()
        
        assert executor.current_status == WorkerStatus.COMPLETED
        stats = executor.get_stats()
        assert stats["completed_at"] is not None
    
    def test_complete_with_pending_actions_fails(self, executor):
        """测试：有待处理 Action 时无法完成"""
        executor.start()
        
        action = create_test_action(worker_id=executor.worker_id)
        executor.propose_action(action)
        
        with pytest.raises(WorkerStateTransitionError, match="仍有未处理的 Action"):
            executor.complete()
    
    def test_fail_worker(self, executor):
        """测试：标记 Worker 为失败"""
        executor.start()
        
        executor.fail(reason="Execution timeout")
        
        assert executor.current_status == WorkerStatus.FAILED
        stats = executor.get_stats()
        assert stats["completed_at"] is not None
        assert stats["failure_reason"] == "Execution timeout"
    
    def test_cancel_worker(self, executor):
        """测试：取消 Worker"""
        executor.start()
        
        # 添加一些 Action
        executor.propose_action(create_test_action(worker_id=executor.worker_id))
        executor.propose_action(create_test_action(worker_id=executor.worker_id))
        
        executor.cancel()
        
        assert executor.current_status == WorkerStatus.CANCELLED
        assert executor.queue.is_empty()  # 队列被清空
        stats = executor.get_stats()
        assert stats["completed_at"] is not None
    
    # ----------------------------------------------------------------
    # 暂停/恢复测试
    # ----------------------------------------------------------------
    
    def test_pause_and_resume(self, executor):
        """测试：暂停和恢复"""
        executor.start()
        
        action = create_test_action(worker_id=executor.worker_id)
        executor.propose_action(action)
        
        # 暂停
        executor.pause()
        assert executor.current_status == WorkerStatus.PAUSED
        assert executor.queue.is_paused()
        
        # 恢复
        executor.resume()
        assert executor.current_status == WorkerStatus.RUNNING
        assert not executor.queue.is_paused()
    
    def test_execute_action_when_paused_fails(self, executor):
        """测试：暂停状态无法执行 Action"""
        executor.start()
        executor.pause()
        
        action = create_test_action(worker_id=executor.worker_id)
        
        # 暂停状态无法提议
        with pytest.raises(WorkerExecutionError, match="无法接收 Action"):
            executor.propose_action(action)
    
    # ----------------------------------------------------------------
    # 审批流程测试
    # ----------------------------------------------------------------
    
    def test_wait_for_approval(self, executor):
        """测试：进入审批等待状态"""
        executor.start()
        
        executor.wait_for_approval()
        
        assert executor.current_status == WorkerStatus.WAITING_APPROVAL
        assert executor.queue.is_paused()
    
    def test_approval_granted(self, executor):
        """测试：审批通过后恢复"""
        executor.start()
        executor.wait_for_approval()
        
        executor.approval_granted()
        
        assert executor.current_status == WorkerStatus.RUNNING
        assert not executor.queue.is_paused()
    
    # ----------------------------------------------------------------
    # 统计信息测试
    # ----------------------------------------------------------------
    
    def test_get_stats(self, executor, mock_action_executor):
        """测试：获取统计信息"""
        executor.start()
        
        action = create_test_action(worker_id=executor.worker_id)
        executor.propose_action(action)
        
        mock_action_executor.execute.return_value = ActionExecutionResult(
            success=True,
            action=action
        )
        
        executor.execute_next_action()
        
        stats = executor.get_stats()
        
        assert stats["current_status"] == WorkerStatus.RUNNING.value
        assert stats["actions_proposed"] == 1
        assert stats["actions_completed"] == 1
        assert stats["actions_failed"] == 0
        assert stats["started_at"] is not None
        assert "queue_stats" in stats
