"""
ReAct Loop 单元测试

测试覆盖：
1. 状态转移
2. 迭代执行
3. 超时和预算约束
4. Checkpoint 序列化/恢复
5. 异常处理
"""
import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.runtime.common.types import generate_entity_id
from src.runtime.entities.action import ActionType
from src.runtime.trace.context import TraceContext
from src.workers.react_loop import (
    Observation,
    Reasoning,
    ReActLoop,
    ReActLoopCheckpoint,
    ReActLoopConfig,
    ReActLoopState,
    ReActLoopTimeoutError,
    ReActLoopBudgetExceededError,
    ReActLoopIterationError,
)


@pytest.fixture
def trace_context():
    """创建测试用 TraceContext"""
    return TraceContext(
        trace_id="a" * 32,
        span_id="b" * 16,
    )


@pytest.fixture
def valid_config():
    """创建有效的 ReActLoopConfig"""
    return ReActLoopConfig(
        max_iterations=5,
        timeout_seconds=60,
        max_tokens=1000,
        max_cost_cents=100,
    )


@pytest.fixture
def mock_callbacks():
    """创建模拟的 observer/reasoner/actor 回调"""
    observation = Observation(
        iteration=1,
        context_summary="Test context",
        available_tools=["file-read", "git-clone"],
        remaining_budget={"tokens": 800, "time_seconds": 50},
    )
    
    reasoning = Reasoning(
        iteration=1,
        thought="Let me analyze this step",
        next_action_type=ActionType.ANALYZE,
        next_tool_name="file-read",
        next_tool_args={"path": "/test"},
        confidence=0.9,
        reasoning_time_ms=100,
        should_continue=True,  # 第 1 轮继续，让 actor 执行
    )

    stop_reasoning = Reasoning(
        iteration=2,
        thought="Done",
        next_action_type=ActionType.REPORT,
        confidence=0.9,
        reasoning_time_ms=100,
        should_continue=False,
        termination_reason="Analysis complete",
    )
    
    action_result = MagicMock()
    action_result.success = True
    action_result.action = None  # 可选
    action_result.evidence = None  # 可选
    action_result.metadata = {}
    
    return {
        "observer": AsyncMock(return_value=observation),
        "reasoner": AsyncMock(side_effect=[reasoning, stop_reasoning]),
        "actor": AsyncMock(return_value=action_result),
    }


# ===== 状态转移测试 =====

@pytest.mark.asyncio
async def test_loop_basic_execution(valid_config, trace_context, mock_callbacks):
    """测试：基本执行流程（INITIALIZING → OBSERVING → REASONING → ACTING → COMPLETE）"""
    loop = ReActLoop(
        loop_id=generate_entity_id(),
        worker_id="worker-test-001",
        task_id="task-test-001",
        config=valid_config,
        observer=mock_callbacks["observer"],
        reasoner=mock_callbacks["reasoner"],
        actor=mock_callbacks["actor"],
        trace_context=trace_context,
    )
    
    assert loop.state == ReActLoopState.INITIALIZING
    
    result = await loop.run()
    
    assert result.final_state == ReActLoopState.COMPLETE
    assert result.succeeded is True
    assert result.iteration_count == 2
    assert result.termination_reason == "Analysis complete"
    assert mock_callbacks["observer"].call_count == 2
    assert mock_callbacks["reasoner"].call_count == 2
    # 第 2 轮 reasoner 决定停止，因此 actor 只执行 1 次
    assert mock_callbacks["actor"].call_count == 1


@pytest.mark.asyncio
async def test_loop_multi_iteration(valid_config, trace_context):
    """测试：多轮迭代"""
    observations = [
        Observation(
            iteration=i,
            context_summary=f"Round {i}",
            available_tools=["file-read"],
            remaining_budget={"tokens": 1000 - i * 100},
        )
        for i in range(1, 4)
    ]
    
    reasonings = [
        Reasoning(
            iteration=i,
            next_action_type=ActionType.ANALYZE,
            next_tool_name="file-read",
            confidence=0.9,
            reasoning_time_ms=50,
            should_continue=(i < 3),  # 第 3 轮停止
            termination_reason="Done" if i == 3 else None,
        )
        for i in range(1, 4)
    ]
    
    observer = AsyncMock(side_effect=observations)
    reasoner = AsyncMock(side_effect=reasonings)
    actor_result = MagicMock()
    actor_result.success = True
    actor_result.metadata = {}
    actor = AsyncMock(return_value=actor_result)
    
    loop = ReActLoop(
        loop_id=generate_entity_id(),
        worker_id="worker-test-001",
        task_id="task-test-001",
        config=valid_config,
        observer=observer,
        reasoner=reasoner,
        actor=actor,
        trace_context=trace_context,
    )
    
    result = await loop.run()
    
    assert result.iteration_count == 3
    assert result.final_state == ReActLoopState.COMPLETE
    assert len(result.all_observations) == 3


@pytest.mark.asyncio
async def test_loop_early_termination(valid_config, trace_context):
    """测试：Agent 决定提前终止"""
    observation = Observation(
        iteration=1,
        context_summary="Ready to stop",
        remaining_budget={"tokens": 800},
    )
    
    reasoning = Reasoning(
        iteration=1,
        next_action_type=ActionType.REPORT,
        confidence=0.95,
        reasoning_time_ms=50,
        should_continue=False,  # Agent 决定停止
        termination_reason="Goal achieved",
    )
    
    observer = AsyncMock(return_value=observation)
    reasoner = AsyncMock(return_value=reasoning)
    actor_result = MagicMock()
    actor_result.success = True
    actor_result.metadata = {}
    actor = AsyncMock(return_value=actor_result)
    
    loop = ReActLoop(
        loop_id=generate_entity_id(),
        worker_id="worker-test-001",
        task_id="task-test-001",
        config=valid_config,
        observer=observer,
        reasoner=reasoner,
        actor=actor,
        trace_context=trace_context,
    )
    
    result = await loop.run()
    
    assert result.iteration_count == 1
    assert result.final_state == ReActLoopState.COMPLETE
    assert result.termination_reason == "Goal achieved"


# ===== 约束条件测试 =====

@pytest.mark.asyncio
async def test_loop_max_iteration_limit(trace_context):
    """测试：超过最大迭代数限制"""
    config = ReActLoopConfig(max_iterations=2, timeout_seconds=60)
    
    observation = Observation(
        iteration=1,
        context_summary="Test",
        remaining_budget={"tokens": 1000},
    )
    
    reasoning = Reasoning(
        iteration=1,
        next_action_type=ActionType.ANALYZE,
        confidence=0.9,
        reasoning_time_ms=50,
        should_continue=True,  # 想继续，但会超过限制
    )
    
    observer = AsyncMock(return_value=observation)
    reasoner = AsyncMock(return_value=reasoning)
    actor_result = MagicMock()
    actor_result.success = True
    actor_result.metadata = {}
    actor = AsyncMock(return_value=actor_result)
    
    loop = ReActLoop(
        loop_id=generate_entity_id(),
        worker_id="worker-test-001",
        task_id="task-test-001",
        config=config,
        observer=observer,
        reasoner=reasoner,
        actor=actor,
        trace_context=trace_context,
    )
    
    result = await loop.run()
    
    assert result.final_state == ReActLoopState.COMPLETE
    assert "Max iterations" in result.termination_reason


@pytest.mark.asyncio
async def test_loop_timeout(trace_context):
    """测试：执行超时"""
    config = ReActLoopConfig(max_iterations=10, timeout_seconds=1)  # 1 秒超时
    
    async def slow_observer(ctx):
        await asyncio.sleep(5)  # 远超 1 秒，应被 deadline 中断
        return Observation(
            iteration=1,
            context_summary="Too late",
            remaining_budget={"tokens": 1000},
        )
    
    reasoner = AsyncMock()
    actor = AsyncMock()
    
    loop = ReActLoop(
        loop_id=generate_entity_id(),
        worker_id="worker-test-001",
        task_id="task-test-001",
        config=config,
        observer=slow_observer,
        reasoner=reasoner,
        actor=actor,
        trace_context=trace_context,
    )
    
    result = await loop.run()
    
    # deadline 在回调内部生效：约 1 秒被中断，而不是等满 5 秒
    assert result.final_state == ReActLoopState.COMPLETE
    assert result.termination_reason == "Timeout"
    assert 900 <= result.total_execution_time_ms < 3000
    reasoner.assert_not_called()
    actor.assert_not_called()


@pytest.mark.asyncio
async def test_loop_token_budget_exceeded(valid_config, trace_context):
    """测试：Token 预算超支"""
    config = ReActLoopConfig(
        max_iterations=10,
        timeout_seconds=60,
        max_tokens=100,  # 很小的 Token 限制
    )
    
    observation = Observation(
        iteration=1,
        context_summary="Test",
        remaining_budget={"tokens": 50},
    )
    
    reasoning = Reasoning(
        iteration=1,
        next_action_type=ActionType.ANALYZE,
        confidence=0.9,
        reasoning_time_ms=50,
        should_continue=True,
        metadata={"tokens_used": 200},  # 超过 100
    )
    
    observer = AsyncMock(return_value=observation)
    reasoner = AsyncMock(return_value=reasoning)
    actor = AsyncMock()
    
    loop = ReActLoop(
        loop_id=generate_entity_id(),
        worker_id="worker-test-001",
        task_id="task-test-001",
        config=config,
        observer=observer,
        reasoner=reasoner,
        actor=actor,
        trace_context=trace_context,
    )
    
    result = await loop.run()
    
    assert result.final_state == ReActLoopState.COMPLETE
    assert "budget" in result.termination_reason.lower()


# ===== Checkpoint 测试 =====

@pytest.mark.asyncio
async def test_loop_checkpoint_conversion(valid_config, trace_context):
    """测试：Checkpoint 转换"""
    observation = Observation(
        iteration=1,
        context_summary="Test",
        remaining_budget={"tokens": 800},
    )
    
    reasoning = Reasoning(
        iteration=1,
        next_action_type=ActionType.ANALYZE,
        confidence=0.9,
        reasoning_time_ms=50,
        should_continue=False,
    )
    
    observer = AsyncMock(return_value=observation)
    reasoner = AsyncMock(return_value=reasoning)
    actor_result = MagicMock()
    actor_result.success = True
    actor_result.metadata = {}
    actor = AsyncMock(return_value=actor_result)
    
    loop_id = generate_entity_id()
    loop = ReActLoop(
        loop_id=loop_id,
        worker_id="worker-test-001",
        task_id="task-test-001",
        config=valid_config,
        observer=observer,
        reasoner=reasoner,
        actor=actor,
        trace_context=trace_context,
    )
    
    result = await loop.run()
    
    # 转换为 Checkpoint
    checkpoint = loop.to_checkpoint()
    
    assert checkpoint.loop_id == loop_id
    assert checkpoint.current_state == ReActLoopState.COMPLETE
    assert checkpoint.current_iteration == 1
    assert len(checkpoint.observations) == 1
    assert len(checkpoint.reasonings) == 1


@pytest.mark.asyncio
async def test_loop_restore_from_checkpoint(valid_config, trace_context):
    """测试：从 Checkpoint 恢复"""
    # 创建初始循环并执行到某个点
    observation1 = Observation(
        iteration=1,
        context_summary="Round 1",
        remaining_budget={"tokens": 800},
    )
    
    reasoning1 = Reasoning(
        iteration=1,
        next_action_type=ActionType.ANALYZE,
        confidence=0.9,
        reasoning_time_ms=50,
        should_continue=True,
    )
    
    observer = AsyncMock(return_value=observation1)
    reasoner = AsyncMock(return_value=reasoning1)
    actor_result = MagicMock()
    actor_result.success = True
    actor_result.metadata = {}
    actor = AsyncMock(return_value=actor_result)
    
    # 限制为 1 轮，使 checkpoint 恰好在第 1 轮之后生成
    loop = ReActLoop(
        loop_id=generate_entity_id(),
        worker_id="worker-test-001",
        task_id="task-test-001",
        config=ReActLoopConfig(max_iterations=1, timeout_seconds=60),
        observer=observer,
        reasoner=reasoner,
        actor=actor,
        trace_context=trace_context,
    )
    
    result = await loop.run()
    checkpoint = loop.to_checkpoint()
    
    assert result.iteration_count == 1
    
    # 恢复循环
    observation2 = Observation(
        iteration=2,
        context_summary="Round 2",
        last_observation_result="Success from round 1",
        remaining_budget={"tokens": 700},
    )
    
    reasoning2 = Reasoning(
        iteration=2,
        next_action_type=ActionType.REPORT,
        confidence=0.95,
        reasoning_time_ms=60,
        should_continue=False,
        termination_reason="Task complete",
    )
    
    observer2 = AsyncMock(return_value=observation2)
    reasoner2 = AsyncMock(return_value=reasoning2)
    
    recovered_loop = ReActLoop.from_checkpoint(
        checkpoint,
        observer=observer2,
        reasoner=reasoner2,
        actor=actor,
        trace_context=trace_context,
        config=valid_config,
    )
    
    assert recovered_loop.current_iteration == 1  # 恢复后应该已有 1 轮完成
    assert len(recovered_loop._observations) == 1


# ===== 异常处理测试 =====

@pytest.mark.asyncio
async def test_loop_observer_exception(valid_config, trace_context):
    """测试：Observer 异常处理"""
    observer = AsyncMock(side_effect=RuntimeError("Observer failed"))
    reasoner = AsyncMock()
    actor = AsyncMock()
    
    loop = ReActLoop(
        loop_id=generate_entity_id(),
        worker_id="worker-test-001",
        task_id="task-test-001",
        config=valid_config,
        observer=observer,
        reasoner=reasoner,
        actor=actor,
        trace_context=trace_context,
    )
    
    result = await loop.run()
    
    assert result.final_state == ReActLoopState.FAILED
    assert result.succeeded is False
    assert "Observer failed" in result.error_message


@pytest.mark.asyncio
async def test_loop_actor_exception(valid_config, trace_context):
    """测试：Actor 异常处理"""
    observation = Observation(
        iteration=1,
        context_summary="Test",
        remaining_budget={"tokens": 800},
    )
    
    reasoning = Reasoning(
        iteration=1,
        next_action_type=ActionType.ANALYZE,
        confidence=0.9,
        reasoning_time_ms=50,
        should_continue=True,
    )
    
    observer = AsyncMock(return_value=observation)
    reasoner = AsyncMock(return_value=reasoning)
    actor = AsyncMock(side_effect=RuntimeError("Actor failed"))
    
    loop = ReActLoop(
        loop_id=generate_entity_id(),
        worker_id="worker-test-001",
        task_id="task-test-001",
        config=valid_config,
        observer=observer,
        reasoner=reasoner,
        actor=actor,
        trace_context=trace_context,
    )
    
    result = await loop.run()
    
    assert result.final_state == ReActLoopState.FAILED
    assert result.succeeded is False


@pytest.mark.asyncio
async def test_loop_cancel(valid_config, trace_context):
    """测试：循环取消"""
    observation = Observation(
        iteration=1,
        context_summary="Test",
        remaining_budget={"tokens": 800},
    )
    
    # 使用会永远返回 True 的 Reasoning 来模拟无限循环
    reasonings = [
        Reasoning(
            iteration=i,
            next_action_type=ActionType.ANALYZE,
            confidence=0.9,
            reasoning_time_ms=50,
            should_continue=True,
        )
        for i in range(1, 100)
    ]
    
    observer = AsyncMock(return_value=observation)
    reasoner = AsyncMock(side_effect=reasonings)
    actor = AsyncMock()
    
    loop = ReActLoop(
        loop_id=generate_entity_id(),
        worker_id="worker-test-001",
        task_id="task-test-001",
        config=valid_config,
        observer=observer,
        reasoner=reasoner,
        actor=actor,
        trace_context=trace_context,
    )
    
    # 在第 2 轮 act 时触发取消：第 2 轮完成后，下一轮开始前应进入 CANCELLED
    actor_result = MagicMock()
    actor_result.metadata = {}
    calls = {"n": 0}

    async def cancelling_actor(reasoning):
        calls["n"] += 1
        if calls["n"] == 2:
            loop.cancel()
        return actor_result

    loop._actor = cancelling_actor

    result = await loop.run()

    assert result.final_state == ReActLoopState.CANCELLED
    assert result.succeeded is False
    assert result.iteration_count == 2
    assert loop.state == ReActLoopState.CANCELLED


@pytest.mark.asyncio
async def test_loop_cancel_before_run(valid_config, trace_context, mock_callbacks):
    """测试：运行前取消，不应执行任何迭代"""
    loop = ReActLoop(
        loop_id=generate_entity_id(),
        worker_id="worker-test-001",
        task_id="task-test-001",
        config=valid_config,
        observer=mock_callbacks["observer"],
        reasoner=mock_callbacks["reasoner"],
        actor=mock_callbacks["actor"],
        trace_context=trace_context,
    )
    loop.cancel()

    result = await loop.run()

    assert result.final_state == ReActLoopState.CANCELLED
    assert result.iteration_count == 0
    mock_callbacks["observer"].assert_not_called()
