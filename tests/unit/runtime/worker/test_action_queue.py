"""
ActionQueue 单元测试

覆盖：
- enqueue/dequeue 基本操作
- FIFO 顺序
- 暂停/恢复
- 队列统计
"""

from src.runtime.worker.action_queue import ActionQueue
from tests.helpers.action_factory import create_test_action


class TestActionQueue:
    """ActionQueue 单元测试"""
    
    def test_empty_queue_returns_none_on_dequeue(self):
        """测试：空队列 dequeue 返回 None"""
        queue = ActionQueue()
        
        assert queue.is_empty()
        assert queue.dequeue() is None
    
    def test_enqueue_and_dequeue_single_action(self):
        """测试：入队和出队单个 Action"""
        queue = ActionQueue()
        action = create_test_action()
        
        queue.enqueue(action)
        
        assert not queue.is_empty()
        assert queue.size() == 1
        
        dequeued = queue.dequeue()
        assert dequeued is not None
        assert dequeued.action_id == action.action_id
        assert queue.is_empty()
    
    def test_fifo_order(self):
        """测试：FIFO 顺序保证"""
        queue = ActionQueue()
        
        action1 = create_test_action()
        action2 = create_test_action()
        action3 = create_test_action()
        
        queue.enqueue(action1)
        queue.enqueue(action2)
        queue.enqueue(action3)
        
        assert queue.size() == 3
        
        # 按 FIFO 顺序出队
        assert queue.dequeue().action_id == action1.action_id
        assert queue.dequeue().action_id == action2.action_id
        assert queue.dequeue().action_id == action3.action_id
        assert queue.is_empty()
    
    def test_peek_does_not_remove_action(self):
        """测试：peek 不移除 Action"""
        queue = ActionQueue()
        action = create_test_action()
        
        queue.enqueue(action)
        
        # peek 多次不影响队列
        assert queue.peek().action_id == action.action_id
        assert queue.peek().action_id == action.action_id
        assert queue.size() == 1
        
        # dequeue 才移除
        assert queue.dequeue().action_id == action.action_id
        assert queue.is_empty()
        assert queue.peek() is None
    
    def test_pause_blocks_dequeue(self):
        """测试：暂停后无法 dequeue"""
        queue = ActionQueue()
        action = create_test_action()
        
        queue.enqueue(action)
        queue.pause()
        
        assert queue.is_paused()
        assert not queue.is_empty()
        
        # 暂停状态下 dequeue 返回 None
        assert queue.dequeue() is None
        
        # Action 仍在队列中
        assert queue.size() == 1
    
    def test_resume_allows_dequeue(self):
        """测试：恢复后可以 dequeue"""
        queue = ActionQueue()
        action = create_test_action()
        
        queue.enqueue(action)
        queue.pause()
        
        # 暂停时无法 dequeue
        assert queue.dequeue() is None
        
        # 恢复后可以 dequeue
        queue.resume()
        assert not queue.is_paused()
        assert queue.dequeue().action_id == action.action_id
    
    def test_pause_allows_enqueue(self):
        """测试：暂停状态仍可以 enqueue"""
        queue = ActionQueue()
        
        queue.pause()
        
        action = create_test_action()
        queue.enqueue(action)
        
        assert queue.size() == 1
        assert queue.peek().action_id == action.action_id
    
    def test_clear_empties_queue(self):
        """测试：clear 清空队列"""
        queue = ActionQueue()
        
        queue.enqueue(create_test_action())
        queue.enqueue(create_test_action())
        queue.enqueue(create_test_action())
        
        assert queue.size() == 3
        
        queue.clear()
        
        assert queue.is_empty()
        assert queue.size() == 0
        assert queue.dequeue() is None
    
    def test_get_stats_returns_correct_info(self):
        """测试：统计信息正确"""
        queue = ActionQueue()
        
        # 初始状态
        stats = queue.get_stats()
        assert stats["current_size"] == 0
        assert stats["is_paused"] is False
        assert stats["total_enqueued"] == 0
        assert stats["total_dequeued"] == 0
        assert stats["pending"] == 0
        
        # 入队 3 个
        queue.enqueue(create_test_action())
        queue.enqueue(create_test_action())
        queue.enqueue(create_test_action())
        
        stats = queue.get_stats()
        assert stats["current_size"] == 3
        assert stats["total_enqueued"] == 3
        assert stats["total_dequeued"] == 0
        assert stats["pending"] == 3
        
        # 出队 2 个
        queue.dequeue()
        queue.dequeue()
        
        stats = queue.get_stats()
        assert stats["current_size"] == 1
        assert stats["total_enqueued"] == 3
        assert stats["total_dequeued"] == 2
        assert stats["pending"] == 1
        
        # 暂停
        queue.pause()
        stats = queue.get_stats()
        assert stats["is_paused"] is True
    
    def test_multiple_pause_resume_cycles(self):
        """测试：多次暂停/恢复循环"""
        queue = ActionQueue()
        
        action1 = create_test_action()
        action2 = create_test_action()
        queue.enqueue(action1)
        queue.enqueue(action2)
        
        # 第一次暂停/恢复
        queue.pause()
        assert queue.dequeue() is None
        
        queue.resume()
        assert queue.dequeue().action_id == action1.action_id
        
        # 第二次暂停/恢复
        queue.pause()
        assert queue.dequeue() is None
        
        queue.resume()
        assert queue.dequeue().action_id == action2.action_id
        
        assert queue.is_empty()
