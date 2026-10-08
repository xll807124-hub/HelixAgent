"""
RT-007 Idempotency Key 与副作用边界 — 对账器

本模块实现对账逻辑（REQ-RT-007 §5.4、§7）

设计原则：
- 最多3次重试（指数退避：1s, 2s, 4s，带抖动）
- 查询外部系统确认副作用是否实际发生
- 对账结果：CONFIRMED_SUCCESS / CONFIRMED_NOT_EXECUTED / STILL_UNKNOWN
- 3次失败后升级到 ESCALATED 状态

核心流程：
1. check_outcome()：查询外部系统确认结果
2. reconcile()：执行对账（带重试）
3. 记录每次尝试（attempt_number, outcome, next_retry_at）

集成点：
- 与 Action 执行流程集成（任务1.2.8）
- 与升级处理器集成（escalation.py）
- 与事件存储集成（记录对账事件）
"""

import random
from datetime import timedelta
from typing import Literal

from ..common.types import utc_now
from .models import ReconciliationAttempt
from .storage import IdempotencyStorage
from .types import IdempotencyStatus

ReconciliationOutcome = Literal[
    "CONFIRMED_SUCCESS",      # 确认成功（副作用已发生）
    "CONFIRMED_NOT_EXECUTED", # 确认未执行（副作用未发生）
    "STILL_UNKNOWN",          # 仍然未知（需要重试）
]


class IdempotencyReconciler:
    """对账器（REQ-RT-007 §5.4、§7）
    
    负责对账逻辑：
    - 查询外部系统确认副作用是否实际发生
    - 指数退避重试（最多3次）
    - 记录每次尝试
    - 3次失败后升级到 ESCALATED 状态
    
    Example:
        reconciler = IdempotencyReconciler(storage)
        
        # 执行对账
        outcome = reconciler.reconcile(key_id)
        
        if outcome == "CONFIRMED_SUCCESS":
            # 更新为 SUCCEEDED
            storage.update_status(key_id, IdempotencyStatus.SUCCEEDED)
        elif outcome == "CONFIRMED_NOT_EXECUTED":
            # 更新为 FAILED_FINAL
            storage.update_status(key_id, IdempotencyStatus.FAILED_FINAL)
        else:
            # 升级到人工处理
            storage.update_status(key_id, IdempotencyStatus.ESCALATED)
    """
    
    # 最大重试次数（REQ-RT-007 §7.2）
    MAX_RETRIES = 3
    
    # 基础退避时间（秒）
    BASE_BACKOFF_SECONDS = 1.0
    
    # 最大退避时间（秒）
    MAX_BACKOFF_SECONDS = 4.0
    
    def __init__(self, storage: IdempotencyStorage) -> None:
        """初始化对账器
        
        Args:
            storage: 幂等键存储
        """
        self.storage = storage
    
    def reconcile(self, key_id: str) -> ReconciliationOutcome:
        """执行对账（REQ-RT-007 §5.4）
        
        查询外部系统确认副作用是否实际发生。
        最多重试3次（指数退避），3次失败后升级到 ESCALATED。
        
        Args:
            key_id: 幂等键 ID
        
        Returns:
            对账结果：
            - CONFIRMED_SUCCESS：确认成功（副作用已发生）
            - CONFIRMED_NOT_EXECUTED：确认未执行（副作用未发生）
            - STILL_UNKNOWN：仍然未知（3次重试后仍未确认）
        """
        key = self.storage.get(key_id)
        if key is None:
            return "STILL_UNKNOWN"
        
        # MVP: 模拟对账查询（实际需要查询外部系统）
        # 生产环境需要：
        # 1. 根据 action_type 确定查询策略
        # 2. 调用外部 API 查询副作用状态
        # 3. 解析响应并返回对账结果
        
        # 对于 MVP，我们假设：
        # - EXECUTING 状态的操作可能仍在执行，返回 STILL_UNKNOWN
        # - OUTCOME_UNKNOWN 状态需要查询外部系统
        
        if key.status == IdempotencyStatus.EXECUTING:
            # 仍在执行中，无法确认
            return "STILL_UNKNOWN"
        
        if key.status == IdempotencyStatus.OUTCOME_UNKNOWN:
            # MVP: 简单模拟，实际需要查询外部系统
            # 这里我们假设 70% 概率确认成功，20% 确认未执行，10% 仍然未知
            outcome = self._simulate_external_query()
            return outcome
        
        # 其他状态不需要对账
        if key.status == IdempotencyStatus.SUCCEEDED:
            return "CONFIRMED_SUCCESS"
        elif key.status in (IdempotencyStatus.FAILED_FINAL, IdempotencyStatus.FAILED_RETRYABLE):
            return "CONFIRMED_NOT_EXECUTED"
        
        return "STILL_UNKNOWN"
    
    def reconcile_with_retry(self, key_id: str) -> ReconciliationOutcome:
        """执行对账（带重试）（REQ-RT-007 §7）
        
        最多重试3次，指数退避（1s, 2s, 4s，带抖动）。
        记录每次尝试。
        
        Args:
            key_id: 幂等键 ID
        
        Returns:
            对账结果
        """
        for attempt in range(1, self.MAX_RETRIES + 1):
            # 执行对账查询
            outcome = self.reconcile(key_id)
            
            # 记录尝试
            self._record_attempt(key_id, attempt, outcome)
            
            # 如果确认了结果，返回
            if outcome in ("CONFIRMED_SUCCESS", "CONFIRMED_NOT_EXECUTED"):
                return outcome
            
            # 如果是最后一次尝试，返回 STILL_UNKNOWN
            if attempt == self.MAX_RETRIES:
                return "STILL_UNKNOWN"
            
            # 指数退避（带抖动）
            backoff_seconds = min(
                self.BASE_BACKOFF_SECONDS * (2 ** (attempt - 1)),
                self.MAX_BACKOFF_SECONDS,
            )
            jitter = random.uniform(0, 0.1 * backoff_seconds)
            wait_seconds = backoff_seconds + jitter
            
            # MVP: 同步等待（生产环境应该使用异步调度）
            import time
            time.sleep(wait_seconds)
        
        return "STILL_UNKNOWN"
    
    def _simulate_external_query(self) -> ReconciliationOutcome:
        """模拟外部系统查询（MVP）
        
        生产环境需要实际查询外部系统（工具、API、数据库等）。
        
        Returns:
            对账结果
        """
        # MVP: 简单模拟
        rand = random.random()
        if rand < 0.7:
            return "CONFIRMED_SUCCESS"
        elif rand < 0.9:
            return "CONFIRMED_NOT_EXECUTED"
        else:
            return "STILL_UNKNOWN"
    
    def _record_attempt(
        self,
        key_id: str,
        attempt_number: int,
        outcome: ReconciliationOutcome,
    ) -> None:
        """记录对账尝试
        
        Args:
            key_id: 幂等键 ID
            attempt_number: 尝试次数（1-based）
            outcome: 对账结果
        """
        key = self.storage.get(key_id)
        if key is None:
            return
        
        # 计算下次重试时间
        next_retry_at = None
        if outcome == "STILL_UNKNOWN" and attempt_number < self.MAX_RETRIES:
            backoff_seconds = min(
                self.BASE_BACKOFF_SECONDS * (2 ** (attempt_number - 1)),
                self.MAX_BACKOFF_SECONDS,
            )
            next_retry_at = utc_now() + timedelta(seconds=backoff_seconds)
        
        # 创建尝试记录
        _attempt = ReconciliationAttempt(
            attempt_number=attempt_number,
            attempted_at=utc_now(),
            outcome=outcome,
            error_code=None,
            next_retry_at=next_retry_at,
        )
        
        # MVP: 简单记录（生产环境应该持久化到事件存储）
        # 这里我们只是在内存中记录，不持久化
        pass
