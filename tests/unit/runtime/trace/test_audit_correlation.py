"""测试审计关联逻辑。"""
from src.runtime.common.types import ActorRef, ActorType, ResourceRef, ResourceType
from src.runtime.trace.audit_correlation import AuditCorrelation
from src.runtime.trace.context import TraceContext


class TestAuditRecord:
    """测试 AuditRecord（REQ-RT-006 §6）。"""

    def test_create_audit_record(self) -> None:
        """测试创建审计记录。"""
        actor = ActorRef(actor_type=ActorType.USER, actor_id="user-123")
        record = AuditCorrelation.create_audit_record(
            action_type="task.create",
            actor=actor,
            decision="ALLOW",
            task_id="task-456",
        )

        assert record.action_type == "task.create"
        assert record.actor == actor
        assert record.decision == "ALLOW"
        assert record.task_id == "task-456"
        assert record.audit_id is not None
        assert record.timestamp is not None

    def test_audit_record_with_trace_context(self) -> None:
        """测试审计记录包含 TraceContext 关联。"""
        actor = ActorRef(actor_type=ActorType.WORKER, actor_id="worker-001")
        trace_ctx = TraceContext(
            trace_id="0123456789abcdef0123456789abcdef",
            span_id="0123456789abcdef",
            trace_flags=1,
        )

        record = AuditCorrelation.create_audit_record(
            action_type="action.execute",
            actor=actor,
            decision="ALLOW",
            trace_context=trace_ctx,
            action_id="action-789",
        )

        assert record.trace_id == trace_ctx.trace_id
        assert record.span_id == trace_ctx.span_id

    def test_audit_record_without_trace_context(self) -> None:
        """测试审计记录可以不包含 TraceContext（未采样场景）。

        核心原则（REQ-RT-006 §4.3）：
        审计记录独立于 Trace，即使 Trace 未采样也要写入。
        """
        actor = ActorRef(actor_type=ActorType.SYSTEM, actor_id="system")
        record = AuditCorrelation.create_audit_record(
            action_type="policy.deny",
            actor=actor,
            decision="DENY",
            reason="Insufficient permissions",
        )

        assert record.trace_id is None
        assert record.span_id is None
        assert record.reason == "Insufficient permissions"

    def test_audit_record_with_resource(self) -> None:
        """测试审计记录包含资源引用。"""
        actor = ActorRef(actor_type=ActorType.TOOL, actor_id="git-tool")
        resource = ResourceRef(
            resource_type=ResourceType.FILE,
            resource_id="file-001",
            scope="repo:test-repo",
            locator="src/main.py",
        )

        record = AuditCorrelation.create_audit_record(
            action_type="tool.file_read",
            actor=actor,
            decision="ALLOW",
            resource=resource,
            result_status="SUCCESS",
        )

        assert record.resource == resource
        assert record.result_status == "SUCCESS"

    def test_audit_record_with_evidence_refs(self) -> None:
        """测试审计记录包含证据引用。"""
        actor = ActorRef(actor_type=ActorType.WORKER, actor_id="coder-worker")
        evidence_refs = ["evidence-001", "evidence-002"]

        record = AuditCorrelation.create_audit_record(
            action_type="action.complete",
            actor=actor,
            decision="ALLOW",
            evidence_refs=evidence_refs,
        )

        assert record.evidence_refs == evidence_refs

    def test_audit_record_with_policy_version(self) -> None:
        """测试审计记录包含策略版本。"""
        actor = ActorRef(actor_type=ActorType.USER, actor_id="user-123")
        record = AuditCorrelation.create_audit_record(
            action_type="approval.request",
            actor=actor,
            decision="PENDING",
            policy_version="v1.2.0",
        )

        assert record.policy_version == "v1.2.0"
        assert record.decision == "PENDING"

    def test_audit_record_with_metadata(self) -> None:
        """测试审计记录包含元数据。"""
        actor = ActorRef(actor_type=ActorType.SYSTEM, actor_id="kill-switch")
        metadata = {
            "mode": "M3",
            "trigger_reason": "excessive_failures",
        }

        record = AuditCorrelation.create_audit_record(
            action_type="kill_switch.trigger",
            actor=actor,
            decision="DENY",
            metadata=metadata,
        )

        assert record.metadata == metadata

    def test_audit_record_is_frozen(self) -> None:
        """测试 AuditRecord 是不可变的。"""
        actor = ActorRef(actor_type=ActorType.USER, actor_id="user-123")
        record = AuditCorrelation.create_audit_record(
            action_type="task.create",
            actor=actor,
            decision="ALLOW",
        )

        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):  # pydantic frozen
            record.decision = "DENY"  # type: ignore


class TestAuditCorrelation:
    """测试 AuditCorrelation 工具类（REQ-RT-006 §6）。"""

    def test_should_audit_task_operations(self) -> None:
        """测试任务操作需要审计。"""
        assert AuditCorrelation.should_audit("task.create") is True
        assert AuditCorrelation.should_audit("task.cancel") is True
        assert AuditCorrelation.should_audit("task.complete") is True

    def test_should_audit_policy_operations(self) -> None:
        """测试策略操作需要审计。"""
        assert AuditCorrelation.should_audit("policy.decide") is True
        assert AuditCorrelation.should_audit("policy.deny") is True

    def test_should_audit_approval_operations(self) -> None:
        """测试审批操作需要审计。"""
        assert AuditCorrelation.should_audit("approval.request") is True
        assert AuditCorrelation.should_audit("approval.approve") is True
        assert AuditCorrelation.should_audit("approval.reject") is True

    def test_should_audit_action_operations(self) -> None:
        """测试 Action 操作需要审计。"""
        assert AuditCorrelation.should_audit("action.authorize") is True
        assert AuditCorrelation.should_audit("action.deny") is True
        assert AuditCorrelation.should_audit("action.execute") is True

    def test_should_audit_tool_operations(self) -> None:
        """测试工具操作需要审计。"""
        assert AuditCorrelation.should_audit("tool.start") is True
        assert AuditCorrelation.should_audit("tool.complete") is True
        assert AuditCorrelation.should_audit("tool.fail") is True

    def test_should_audit_credential_operations(self) -> None:
        """测试凭据操作需要审计。"""
        assert AuditCorrelation.should_audit("credential.issue") is True
        assert AuditCorrelation.should_audit("credential.revoke") is True

    def test_should_audit_sandbox_operations(self) -> None:
        """测试沙箱操作需要审计。"""
        assert AuditCorrelation.should_audit("sandbox.create") is True
        assert AuditCorrelation.should_audit("sandbox.destroy") is True

    def test_should_audit_kill_switch_operations(self) -> None:
        """测试 Kill Switch 操作需要审计。"""
        assert AuditCorrelation.should_audit("kill_switch.trigger") is True
        assert AuditCorrelation.should_audit("kill_switch.recover") is True

    def test_should_not_audit_internal_operations(self) -> None:
        """测试内部操作不需要审计。"""
        assert AuditCorrelation.should_audit("internal.log") is False
        assert AuditCorrelation.should_audit("debug.trace") is False
        assert AuditCorrelation.should_audit("cache.hit") is False
