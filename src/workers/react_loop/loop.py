"""
ReAct Loop 核心执行器

职责：
1. 管理循环状态机（INITIALIZING → OBSERVING → REASONING → ACTING → COMPLETE）
2. 协调 observe/reason/act 三个回调
3. 追踪资源预算和 Evidence
4. 与 Checkpoint 集成支持故障恢复

对齐：
- REQ-RT-002 状态机与迁移约束
- REQ-RT-005 Checkpoint Protocol
- REQ-RT-006 Trace 传播
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Callable

from src.runtime.common.types import ensure_utc, generate_entity_id
from src.runtime.entities.action import Action, ActionType
from src.runtime.entities.evidence import Evidence
from src.runtime.trace.context import TraceContext

from .exceptions import (
    ReActLoopBudgetExceededError,
    ReActLoopCancelledException,
    ReActLoopCheckpointError,
    ReActLoopIterationError,
    ReActLoopStateError,
    ReActLoopTimeoutError,
)
from .models import (
    Observation,
    ReActLoopCheckpoint,
    ReActLoopConfig,
    ReActLoopResult,
    ReActLoopState,
    Reasoning,
)


class ReActLoop:
    """ReAct 循环执行器
    
    使用方式：
        config = ReActLoopConfig(max_iterations=10, timeout_seconds=300)
        loop = ReActLoop(
            loop_id=generate_entity_id(),
            worker_id=worker.worker_id,
            task_id=task.task_id,
            config=config,
            observer=async_observer_fn,
            reasoner=async_reasoner_fn,
            actor=async_actor_fn,
            trace_context=trace_context,
        )
        result = await loop.run()
    """
    
    def __init__(
        self,
        loop_id: str,
        worker_id: str,
        task_id: str,
        config: ReActLoopConfig,
        observer: Callable[[dict[str, Any]], Observation],
        reasoner: Callable[[Observation], Reasoning],
        actor: Callable[[Reasoning], Any],
        trace_context: TraceContext,
    ):
        """初始化 ReAct Loop
        
        Args:
            loop_id: 循环实例唯一 ID
            worker_id: 关联的 Worker ID
            task_id: 关联的 Task ID
            config: 循环配置（迭代限制、超时、预算）
            observer: 异步观察函数，返回 Observation
            reasoner: 异步推理函数，返回 Reasoning
            actor: 异步执行函数，返回 ActionExecutionResult
            trace_context: Trace 上下文
        """
        self.loop_id = loop_id
        self.worker_id = worker_id
        self.task_id = task_id
        self.config = config
        self._observer = observer
        self._reasoner = reasoner
        self._actor = actor
        self._trace_context = trace_context
        
        # 状态
        self._state = ReActLoopState.INITIALIZING
        self._current_iteration = 0
        
        # 历史记录
        self._observations: list[Observation] = []
        self._reasonings: list[Reasoning] = []
        self._actions: list[Action] = []
        self._evidences: list[Evidence] = []
        
        # 资源追踪
        self._start_time: datetime | None = None
        self._total_time_ms = 0
        self._total_tokens_consumed = 0
        self._total_cost_cents = 0
        
        # 终止信息
        self._termination_reason = ""
        self._error_message: str | None = None
        self._cancelled = False
    
    @property
    def state(self) -> ReActLoopState:
        """获取当前状态"""
        return self._state
    
    @property
    def current_iteration(self) -> int:
        """获取当前迭代轮数"""
        return self._current_iteration
    
    def _remaining_seconds(self) -> float:
        """剩余可用时间（秒）"""
        if self._start_time is None:
            return float(self.config.timeout_seconds)
        elapsed = (ensure_utc(datetime.now(timezone.utc)) - self._start_time).total_seconds()
        return self.config.timeout_seconds - elapsed

    def _check_timeout(self) -> None:
        """检查是否超时"""
        if self._remaining_seconds() <= 0:
            raise ReActLoopTimeoutError(
                f"Loop timeout (configured: {self.config.timeout_seconds}s)"
            )

    async def _call_with_deadline(self, fn: Callable, arg: Any) -> Any:
        """在剩余时间内调用回调；超时则中断并抛 ReActLoopTimeoutError"""
        remaining = self._remaining_seconds()
        if remaining <= 0:
            raise ReActLoopTimeoutError(
                f"Loop timeout (configured: {self.config.timeout_seconds}s)"
            )
        try:
            return await asyncio.wait_for(fn(arg), timeout=remaining)
        except asyncio.TimeoutError as e:
            raise ReActLoopTimeoutError(
                f"Loop timeout (configured: {self.config.timeout_seconds}s)"
            ) from e
    
    def _check_budget(self, reasoning: Reasoning | None = None) -> None:
        """检查预算是否超支"""
        # 检查 Token 预算
        if self.config.max_tokens is not None:
            if self._total_tokens_consumed > self.config.max_tokens:
                raise ReActLoopBudgetExceededError(
                    f"Token budget exceeded: {self._total_tokens_consumed} > {self.config.max_tokens}"
                )
        
        # 检查成本预算
        if self.config.max_cost_cents is not None:
            if self._total_cost_cents > self.config.max_cost_cents:
                raise ReActLoopBudgetExceededError(
                    f"Cost budget exceeded: {self._total_cost_cents} > {self.config.max_cost_cents} cents"
                )
    
    def _check_iteration_limit(self) -> None:
        """检查迭代限制"""
        if self._current_iteration >= self.config.max_iterations:
            raise ReActLoopBudgetExceededError(
                f"Max iterations exceeded: {self._current_iteration} >= {self.config.max_iterations}"
            )
    
    def _build_context_for_observation(self) -> dict[str, Any]:
        """为观察回调构建上下文
        
        Returns:
            包含已执行 Action 和 Evidence 的上下文
        """
        return {
            "iteration": self._current_iteration,
            "last_action": self._actions[-1] if self._actions else None,
            "last_evidence": self._evidences[-1] if self._evidences else None,
            "all_actions": self._actions,
            "all_evidences": self._evidences,
            "budget": {
                "tokens": self.config.max_tokens,
                "time_seconds": self.config.timeout_seconds,
                "cost_cents": self.config.max_cost_cents,
            },
            "consumed": {
                "tokens": self._total_tokens_consumed,
                "time_ms": self._total_time_ms,
                "cost_cents": self._total_cost_cents,
            },
        }
    
    async def _run_iteration(self) -> bool:
        """执行一次完整的 Observe → Reason → Act 迭代
        
        Returns:
            True 表示应该继续循环，False 表示应该结束
            
        Raises:
            ReActLoopTimeoutError: 如果超时
            ReActLoopBudgetExceededError: 如果预算超支
            ReActLoopIterationError: 如果迭代失败
        """
        try:
            # 检查约束（在计数前检查，保证恰好执行 max_iterations 轮）
            self._check_timeout()
            self._check_iteration_limit()
            self._current_iteration += 1
            
            # ===== OBSERVING =====
            self._state = ReActLoopState.OBSERVING
            context = self._build_context_for_observation()
            observation = await self._call_with_deadline(self._observer, context)
            self._observations.append(observation)
            
            # ===== REASONING =====
            self._state = ReActLoopState.REASONING
            reasoning = await self._call_with_deadline(self._reasoner, observation)
            self._reasonings.append(reasoning)
            
            # 检查推理预算消耗
            self._total_tokens_consumed += reasoning.metadata.get("tokens_used", 0)
            self._total_cost_cents += reasoning.metadata.get("cost_cents", 0)
            self._check_budget(reasoning)
            
            # 检查是否应该继续
            if not reasoning.should_continue:
                self._termination_reason = reasoning.termination_reason or "Agent decided to stop"
                return False
            
            # ===== ACTING =====
            self._state = ReActLoopState.ACTING
            action_result = await self._call_with_deadline(self._actor, reasoning)
            
            # 记录 Action 和 Evidence（仅记录真实的实体，忽略 None / 缺失）
            action = getattr(action_result, "action", None)
            if isinstance(action, Action):
                self._actions.append(action)
            evidence = getattr(action_result, "evidence", None)
            if isinstance(evidence, Evidence):
                self._evidences.append(evidence)
            
            # 更新资源消耗
            metadata = getattr(action_result, "metadata", None)
            if isinstance(metadata, dict):
                self._total_tokens_consumed += metadata.get("tokens_used", 0)
                self._total_cost_cents += metadata.get("cost_cents", 0)
                self._check_budget()
            
            return True
            
        except ReActLoopTimeoutError:
            self._termination_reason = "Timeout"
            return False
        except ReActLoopBudgetExceededError as e:
            self._termination_reason = str(e)
            return False
        except Exception as e:
            self._error_message = str(e)
            raise ReActLoopIterationError(f"Iteration {self._current_iteration} failed: {e}") from e
    
    async def run(self) -> ReActLoopResult:
        """执行 ReAct 循环
        
        Returns:
            ReActLoopResult - 包含最终状态、所有 Action/Evidence、统计信息
            
        Raises:
            ReActLoopCancelledException: 如果循环被取消
            ReActLoopTimeoutError: 如果总超时
            ReActLoopIterationError: 如果某次迭代失败
        """
        self._start_time = ensure_utc(datetime.now(timezone.utc))
        self._state = ReActLoopState.INITIALIZING
        
        try:
            # 循环主体
            while True:
                if self._cancelled:
                    raise ReActLoopCancelledException("Loop was cancelled")
                
                should_continue = await self._run_iteration()
                
                if not should_continue:
                    break
            
            # 成功完成
            self._state = ReActLoopState.COMPLETE
            self._total_time_ms = int(
                (ensure_utc(datetime.now(timezone.utc)) - self._start_time).total_seconds() * 1000
            )
            
            return ReActLoopResult(
                loop_id=self.loop_id,
                worker_id=self.worker_id,
                task_id=self.task_id,
                final_state=self._state,
                termination_reason=self._termination_reason or "Completed successfully",
                succeeded=True,
                error_message=None,
                iteration_count=self._current_iteration,
                all_observations=self._observations,
                all_reasonings=self._reasonings,
                all_actions=self._actions,
                all_evidences=self._evidences,
                final_artifacts=[],  # 由 Coder Worker 填充
                total_execution_time_ms=self._total_time_ms,
                total_tokens_consumed=self._total_tokens_consumed or None,
                total_cost_cents=self._total_cost_cents or None,
            )
            
        except Exception as e:
            if isinstance(e, ReActLoopCancelledException):
                self._state = ReActLoopState.CANCELLED
                self._termination_reason = "Cancelled by user"
            else:
                self._state = ReActLoopState.FAILED
            self._error_message = str(e)
            self._total_time_ms = int(
                (ensure_utc(datetime.now(timezone.utc)) - self._start_time).total_seconds() * 1000
            )
            
            return ReActLoopResult(
                loop_id=self.loop_id,
                worker_id=self.worker_id,
                task_id=self.task_id,
                final_state=self._state,
                termination_reason=self._termination_reason or "Failed",
                succeeded=False,
                error_message=self._error_message,
                iteration_count=self._current_iteration,
                all_observations=self._observations,
                all_reasonings=self._reasonings,
                all_actions=self._actions,
                all_evidences=self._evidences,
                final_artifacts=[],
                total_execution_time_ms=self._total_time_ms,
                total_tokens_consumed=self._total_tokens_consumed or None,
                total_cost_cents=self._total_cost_cents or None,
            )
    
    def cancel(self) -> None:
        """请求取消循环（在下一轮迭代开始前生效）"""
        self._cancelled = True
        self._termination_reason = "Cancelled by user"
    
    def to_checkpoint(self) -> ReActLoopCheckpoint:
        """转换为 Checkpoint 格式（用于故障恢复）"""
        return ReActLoopCheckpoint(
            loop_id=self.loop_id,
            worker_id=self.worker_id,
            task_id=self.task_id,
            current_state=self._state,
            current_iteration=self._current_iteration,
            observations=self._observations,
            reasonings=self._reasonings,
            actions=self._actions,
            evidences=self._evidences,
            total_iterations_completed=self._current_iteration,
            total_time_ms=self._total_time_ms,
            total_tokens_consumed=self._total_tokens_consumed or None,
            total_cost_cents=self._total_cost_cents or None,
        )
    
    @classmethod
    def from_checkpoint(
        cls,
        checkpoint: ReActLoopCheckpoint,
        observer: Callable,
        reasoner: Callable,
        actor: Callable,
        trace_context: TraceContext,
        config: ReActLoopConfig | None = None,
    ) -> ReActLoop:
        """从 Checkpoint 恢复循环实例"""
        loop = cls(
            loop_id=checkpoint.loop_id,
            worker_id=checkpoint.worker_id,
            task_id=checkpoint.task_id,
            config=config or ReActLoopConfig(),
            observer=observer,
            reasoner=reasoner,
            actor=actor,
            trace_context=trace_context,
        )
        
        # 恢复状态
        loop._state = checkpoint.current_state
        loop._current_iteration = checkpoint.current_iteration
        loop._observations = checkpoint.observations
        loop._reasonings = checkpoint.reasonings
        loop._actions = checkpoint.actions
        loop._evidences = checkpoint.evidences
        loop._total_time_ms = checkpoint.total_time_ms
        loop._total_tokens_consumed = checkpoint.total_tokens_consumed or 0
        loop._total_cost_cents = checkpoint.total_cost_cents or 0
        
        return loop
