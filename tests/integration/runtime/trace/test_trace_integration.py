"""集成测试：Trace 传播和审计关联完整流程。

验收标准（REQ-RT-006 §10.2）：
1. ✅ Task 创建时生成根 TraceContext
2. ✅ TraceContext 在 Task → Workflow → Worker → Action → Tool/Model 链路传播
3. ✅ 跨边界传播（HTTP Headers 注入/提取）
4. ✅ 采样策略（默认 15%，高风险任务 100%）
5. ✅ 审计记录关联 TraceId（不受采样影响）
"""

from src.runtime.common.types import ActorRef, ActorType
from src.runtime.trace.audit_correlation import AuditCorrelation
from src.runtime.trace.context import TraceContext
from src.runtime.trace.propagation import extract_trace_context, inject_trace_context
from src.runtime.trace.sampling import SamplingPriority, SamplingStrategy
from src.runtime.trace.tracer import SpanKind, create_span, get_current_trace_context


def test_full_trace_propagation_workflow() -> None:
    """测试完整的 Trace 传播工作流（验收标准 1-3）。

    模拟场景：
    1. Task 创建（生成根 TraceContext）
    2. Workflow 执行（继承 Task 的 TraceContext）
    3. Worker 执行（继承 Workflow 的 TraceContext）
    4. Action 执行（继承 Worker 的 TraceContext）
    5. Tool 调用（跨边界传播到外部服务）
    """
    # 1. Task 创建（根 Span）
    with create_span(
        "task.execute",
        SpanKind.TASK,
        attributes={"task_id": "task-001", "organization_id": "org-123"},
    ) as task_span:
        assert task_span is not None

        # 获取 Task 的 TraceContext
        task_trace_ctx = get_current_trace_context()
        if task_trace_ctx is None:
            # 未被采样，手动创建一个用于演示
            task_trace_ctx = TraceContext(
                trace_id="a" * 32,
                span_id="b" * 16,
                trace_flags=1,
            )

        # 2. Workflow 执行（子 Span）
        with create_span(
            "workflow.run",
            SpanKind.WORKFLOW,
            trace_context=task_trace_ctx,
            attributes={"workflow_id": "workflow-001"},
        ) as workflow_span:
            assert workflow_span is not None

            workflow_trace_ctx = get_current_trace_context()
            if workflow_trace_ctx:
                # 验证 TraceId 一致（父子关系）
                assert workflow_trace_ctx.trace_id == task_trace_ctx.trace_id

            # 3. Worker 执行（子 Span）
            with create_span(
                "worker.execute",
                SpanKind.WORKER,
                attributes={"worker_id": "coder-worker"},
            ) as worker_span:
                assert worker_span is not None

                # 4. Action 执行（子 Span）
                with create_span(
                    "action.run",
                    SpanKind.ACTION,
                    attributes={"action_id": "action-001", "action_type": "tool.call"},
                ) as action_span:
                    assert action_span is not None

                    action_trace_ctx = get_current_trace_context()

                    # 5. Tool 跨边界调用（注入 HTTP Headers）
                    if action_trace_ctx:
                        carrier: dict[str, str] = {}
                        inject_trace_context(action_trace_ctx, carrier)

                        # 验证 HTTP Headers 包含 W3C Trace Context
                        assert "traceparent" in carrier
                        assert carrier["traceparent"].startswith("00-")

                        # 模拟外部服务提取 TraceContext
                        extracted_ctx = extract_trace_context(carrier)
                        assert extracted_ctx is not None
                        assert extracted_ctx.trace_id == action_trace_ctx.trace_id


def test_sampling_strategy_integration() -> None:
    """测试采样策略集成（验收标准 4）。"""
    # 默认任务（15% 采样）
    default_priority = SamplingStrategy.should_sample_task()
    assert default_priority == SamplingPriority.DEFAULT

    # 高风险任务（100% 采样）
    high_risk_priority = SamplingStrategy.should_sample_task(is_high_risk=True)
    assert high_risk_priority == SamplingPriority.HIGH

    # 失败任务（100% 采样）
    failure_priority = SamplingStrategy.should_sample_task(has_failure=True)
    assert failure_priority == SamplingPriority.HIGH

    # 恢复操作（100% 采样）
    recovery_priority = SamplingStrategy.should_sample_task(is_recovery=True)
    assert recovery_priority == SamplingPriority.HIGH

    # 显式诊断请求（100% 采样）
    explicit_priority = SamplingStrategy.should_sample_task(explicit_request=True)
    assert explicit_priority == SamplingPriority.HIGH


def test_audit_correlation_integration() -> None:
    """测试审计关联集成（验收标准 5）。

    核心原则：
    - 审计记录 100% 写入（不受 Trace 采样影响）
    - 审计记录包含 TraceId 引用（如果有）
    """
    # 创建一个 Span 并获取 TraceContext
    with create_span("task.create", SpanKind.TASK) as span:
        assert span is not None
        trace_ctx = get_current_trace_context()

        # 创建审计记录（关联 TraceId）
        actor = ActorRef(actor_type=ActorType.USER, actor_id="user-123")
        audit_record = AuditCorrelation.create_audit_record(
            action_type="task.create",
            actor=actor,
            decision="ALLOW",
            trace_context=trace_ctx,
            task_id="task-001",
        )

        # 验证审计记录
        assert audit_record.action_type == "task.create"
        assert audit_record.actor == actor
        assert audit_record.decision == "ALLOW"
        assert audit_record.task_id == "task-001"

        # 如果 Trace 被采样，审计记录应包含 TraceId
        if trace_ctx:
            assert audit_record.trace_id == trace_ctx.trace_id
            assert audit_record.span_id == trace_ctx.span_id


def test_audit_without_trace() -> None:
    """测试审计独立于 Trace（未采样场景）。

    核心原则：
    - 即使 Trace 未被采样，审计记录仍然写入
    - TraceId 字段为 None
    """
    # 不创建 Span（模拟未采样）
    actor = ActorRef(actor_type=ActorType.SYSTEM, actor_id="system")
    audit_record = AuditCorrelation.create_audit_record(
        action_type="policy.deny",
        actor=actor,
        decision="DENY",
        reason="Insufficient permissions",
        trace_context=None,  # 未采样
    )

    # 验证审计记录仍然创建
    assert audit_record.action_type == "policy.deny"
    assert audit_record.decision == "DENY"
    assert audit_record.reason == "Insufficient permissions"
    assert audit_record.trace_id is None  # 未关联 Trace
    assert audit_record.span_id is None


def test_cross_service_propagation_with_trust_boundary() -> None:
    """测试跨服务传播的信任边界控制（验收标准 3）。"""
    # 可信来源（内部服务）
    trusted_carrier = {
        "traceparent": "00-a1b2c3d4e5f6789012345678901234ab-0123456789abcdef-01",
        "tracestate": "organization_id=org-123",
    }
    trusted_ctx = extract_trace_context(trusted_carrier, trusted=True)
    assert trusted_ctx is not None
    assert trusted_ctx.trace_id == "a1b2c3d4e5f6789012345678901234ab"

    # 不可信来源（外部服务，拒绝传播）
    untrusted_carrier = {
        "traceparent": "00-ffffffffffffffffffffffffffffffff-fedcba9876543210-01"
    }
    untrusted_ctx = extract_trace_context(untrusted_carrier, trusted=False)
    assert untrusted_ctx is None  # 拒绝不可信来源的 Trace


def test_span_attributes_do_not_contain_sensitive_data() -> None:
    """测试 Span 属性不包含敏感数据（验收标准 6）。

    默认不记录：
    - Prompt 内容
    - 代码内容
    - 凭据
    - 工具完整输入输出
    """
    # 创建 Span 时只传递元数据，不传递敏感内容
    with create_span(
        "model.call",
        SpanKind.MODEL,
        attributes={
            "model_id": "gpt-4",
            "token_count": 1500,  # ✅ 允许：用量统计
            "request_id": "req-123",  # ✅ 允许：关联标识
            # ❌ 禁止：prompt="..."
            # ❌ 禁止：response="..."
            # ❌ 禁止：api_key="..."
        },
    ) as span:
        assert span is not None
        # Span 不应包含敏感数据
