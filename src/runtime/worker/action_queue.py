"""
Action 队列管理（Task 1.1.4）

对齐设计文档：
- REQ-RT-002 §8 - Action 状态机
- 提供 FIFO 队列，支持暂停/恢复
"""
from __future__ import annotations

from collections import deque
from typing import Any

from ..entities.action import Action


class ActionQueue:
    """
    Action 队列管理器
    
    职责：
    1. FIFO 队列管理 Action
    2. 支持队列暂停/恢复（用于 WAITING_APPROVAL）
    3. 提供队列统计信息
    
    线程安全：当前实现为单线程同步版本
    """
    
    def __init__(self) -> None:
        """初始化队列"""
        self._queue: deque[Action] = deque()
        self._paused = False
        self._total_enqueued = 0
        self._total_dequeued = 0
    
    def enqueue(self, action: Action) -> None:
        """
        将 Action 加入队列
        
        Args:
            action: 要加入队列的 Action
        """
        self._queue.append(action)
        self._total_enqueued += 1
    
    def dequeue(self) -> Action | None:
        """
        从队列取出下一个 Action
        
        Returns:
            下一个 Action，如果队列为空或已暂停则返回 None
        """
        if self._paused or not self._queue:
            return None
        
        action = self._queue.popleft()
        self._total_dequeued += 1
        return action
    
    def peek(self) -> Action | None:
        """
        查看队列头部 Action（不移除）
        
        Returns:
            队列头部的 Action，如果队列为空则返回 None
        """
        return self._queue[0] if self._queue else None
    
    def is_empty(self) -> bool:
        """
        检查队列是否为空
        
        Returns:
            队列是否为空
        """
        return len(self._queue) == 0
    
    def pause(self) -> None:
        """暂停队列处理"""
        self._paused = True
    
    def resume(self) -> None:
        """恢复队列处理"""
        self._paused = False
    
    def is_paused(self) -> bool:
        """
        检查队列是否已暂停
        
        Returns:
            队列是否已暂停
        """
        return self._paused
    
    def size(self) -> int:
        """
        获取当前队列长度
        
        Returns:
            队列中 Action 数量
        """
        return len(self._queue)
    
    def clear(self) -> None:
        """清空队列（用于取消场景）"""
        self._queue.clear()
    
    def get_stats(self) -> dict[str, Any]:
        """
        获取队列统计信息
        
        Returns:
            包含统计数据的字典
        """
        return {
            "current_size": len(self._queue),
            "is_paused": self._paused,
            "total_enqueued": self._total_enqueued,
            "total_dequeued": self._total_dequeued,
            "pending": self._total_enqueued - self._total_dequeued,
        }
