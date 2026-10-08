"""
单元测试：ProjectionCheckpoint

测试投影消费者进度记录的核心逻辑。
"""


import pytest

from src.runtime.projection.checkpoint import ProjectionCheckpoint, ProjectionStatus


class TestProjectionCheckpoint:
    """测试 ProjectionCheckpoint 核心功能"""

    def test_initial_state(self):
        """测试初始状态"""
        checkpoint = ProjectionCheckpoint(
            projection_name="task_projection",
            projection_version="v1.0.0",
            partition_key="workflow:wf_test_001",
        )

        assert checkpoint.last_applied_sequence == 0
        assert checkpoint.status == ProjectionStatus.HEALTHY
        assert checkpoint.last_applied_event_id is None
        assert checkpoint.pending_gap_from is None

    def test_can_apply_sequence_next(self):
        """测试可以应用下一个序列"""
        checkpoint = ProjectionCheckpoint(
            projection_name="task_projection",
            projection_version="v1.0.0",
            partition_key="workflow:wf_test_001",
            last_applied_sequence=5,
        )

        can_apply, reason = checkpoint.can_apply_sequence(6)
        assert can_apply is True
        assert "下一个序列" in reason

    def test_can_apply_sequence_duplicate(self):
        """测试重复序列检测"""
        checkpoint = ProjectionCheckpoint(
            projection_name="task_projection",
            projection_version="v1.0.0",
            partition_key="workflow:wf_test_001",
            last_applied_sequence=5,
        )

        can_apply, reason = checkpoint.can_apply_sequence(5)
        assert can_apply is False
        assert "已被应用" in reason

    def test_can_apply_sequence_gap(self):
        """测试序列缺口检测"""
        checkpoint = ProjectionCheckpoint(
            projection_name="task_projection",
            projection_version="v1.0.0",
            partition_key="workflow:wf_test_001",
            last_applied_sequence=5,
        )

        can_apply, reason = checkpoint.can_apply_sequence(10)
        assert can_apply is False
        assert "缺口" in reason
        assert "期望 6" in reason

    def test_mark_gap(self):
        """测试标记序列缺口"""
        checkpoint = ProjectionCheckpoint(
            projection_name="task_projection",
            projection_version="v1.0.0",
            partition_key="workflow:wf_test_001",
            last_applied_sequence=5,
        )

        checkpoint.mark_gap(6, 9)

        assert checkpoint.pending_gap_from == 6
        assert checkpoint.pending_gap_to == 9
        assert checkpoint.status == ProjectionStatus.BLOCKED

    def test_clear_gap(self):
        """测试清除序列缺口"""
        checkpoint = ProjectionCheckpoint(
            projection_name="task_projection",
            projection_version="v1.0.0",
            partition_key="workflow:wf_test_001",
            last_applied_sequence=5,
            pending_gap_from=6,
            pending_gap_to=9,
            status=ProjectionStatus.BLOCKED,
        )

        checkpoint.clear_gap()

        assert checkpoint.pending_gap_from is None
        assert checkpoint.pending_gap_to is None
        assert checkpoint.status == ProjectionStatus.HEALTHY

    def test_advance_sequence(self):
        """测试推进序列"""
        checkpoint = ProjectionCheckpoint(
            projection_name="task_projection",
            projection_version="v1.0.0",
            partition_key="workflow:wf_test_001",
            last_applied_sequence=5,
        )

        checkpoint.advance(
            sequence=6,
            event_id="evt_001",
            event_hash="abc123",
        )

        assert checkpoint.last_applied_sequence == 6
        assert checkpoint.last_applied_event_id == "evt_001"
        assert checkpoint.last_applied_event_hash == "abc123"

    def test_advance_cannot_rollback(self):
        """测试不能回退序列"""
        checkpoint = ProjectionCheckpoint(
            projection_name="task_projection",
            projection_version="v1.0.0",
            partition_key="workflow:wf_test_001",
            last_applied_sequence=10,
        )

        with pytest.raises(ValueError, match="不能回退序列"):
            checkpoint.advance(
                sequence=5,
                event_id="evt_001",
                event_hash="abc123",
            )

    def test_advance_fills_gap(self):
        """测试推进序列自动填补缺口"""
        checkpoint = ProjectionCheckpoint(
            projection_name="task_projection",
            projection_version="v1.0.0",
            partition_key="workflow:wf_test_001",
            last_applied_sequence=5,
            pending_gap_from=6,
            pending_gap_to=9,
            status=ProjectionStatus.BLOCKED,
        )

        # 填补到缺口结束
        checkpoint.advance(
            sequence=10,
            event_id="evt_010",
            event_hash="hash_010",
        )

        # 缺口应该被清除
        assert checkpoint.pending_gap_from is None
        assert checkpoint.pending_gap_to is None
        assert checkpoint.status == ProjectionStatus.HEALTHY

    def test_mark_failed(self):
        """测试标记失败"""
        checkpoint = ProjectionCheckpoint(
            projection_name="task_projection",
            projection_version="v1.0.0",
            partition_key="workflow:wf_test_001",
        )

        checkpoint.mark_failed("error_ref_123")

        assert checkpoint.status == ProjectionStatus.FAILED
        assert checkpoint.failure_ref == "error_ref_123"

    def test_calculate_lag(self):
        """测试计算投影延迟"""
        checkpoint = ProjectionCheckpoint(
            projection_name="task_projection",
            projection_version="v1.0.0",
            partition_key="workflow:wf_test_001",
            last_applied_sequence=100,
        )

        lag = checkpoint.calculate_lag(latest_sequence=150)
        assert lag == 50

        # 测试无延迟
        lag = checkpoint.calculate_lag(latest_sequence=100)
        assert lag == 0

        # 测试不能为负
        lag = checkpoint.calculate_lag(latest_sequence=50)
        assert lag == 0

    def test_blocked_projection_cannot_apply(self):
        """测试被阻塞的投影不能应用事件"""
        checkpoint = ProjectionCheckpoint(
            projection_name="task_projection",
            projection_version="v1.0.0",
            partition_key="workflow:wf_test_001",
            last_applied_sequence=5,
            status=ProjectionStatus.BLOCKED,
            pending_gap_from=6,
            pending_gap_to=9,
        )

        # 尝试应用缺口之外的序列
        can_apply, reason = checkpoint.can_apply_sequence(15)
        assert can_apply is False
        assert "被阻塞" in reason

    def test_failed_projection_cannot_apply(self):
        """测试失败的投影不能应用事件"""
        checkpoint = ProjectionCheckpoint(
            projection_name="task_projection",
            projection_version="v1.0.0",
            partition_key="workflow:wf_test_001",
            status=ProjectionStatus.FAILED,
            failure_ref="unrecoverable_error",
        )

        can_apply, reason = checkpoint.can_apply_sequence(1)
        assert can_apply is False
        assert "FAILED" in reason


class TestProjectionCheckpointEdgeCases:
    """测试边界情况"""

    def test_sequence_zero_is_valid_initial(self):
        """测试序列 0 是有效的初始状态"""
        checkpoint = ProjectionCheckpoint(
            projection_name="task_projection",
            projection_version="v1.0.0",
            partition_key="workflow:wf_test_001",
            last_applied_sequence=0,
        )

        can_apply, _ = checkpoint.can_apply_sequence(1)
        assert can_apply is True

    def test_large_sequence_gap(self):
        """测试大序列缺口"""
        checkpoint = ProjectionCheckpoint(
            projection_name="task_projection",
            projection_version="v1.0.0",
            partition_key="workflow:wf_test_001",
            last_applied_sequence=1,
        )

        can_apply, reason = checkpoint.can_apply_sequence(1000)
        assert can_apply is False
        assert "缺口" in reason

    def test_negative_sequence_rejected(self):
        """测试拒绝负序列（由 Pydantic 校验）"""
        with pytest.raises(ValueError):
            ProjectionCheckpoint(
                projection_name="task_projection",
                projection_version="v1.0.0",
                partition_key="workflow:wf_test_001",
                last_applied_sequence=-1,  # 应该被 ge=0 约束拒绝
            )
