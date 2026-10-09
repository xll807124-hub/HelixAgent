"""
CheckpointManager 单元测试

测试检查点管理器的核心功能：
- 保存和加载检查点
- 检查点验证和哈希校验
- 查找有效检查点（fallback机制）
- 检查点失效标记
"""

import hashlib
import json
from datetime import UTC, datetime

import pytest

from src.runtime.checkpoint.manager import (
    CheckpointManager,
    InMemoryCheckpointStorage,
)
from src.runtime.checkpoint.models import (
    CheckpointReason,
    CheckpointStatus,
    WorkflowCheckpoint,
)


def compute_checkpoint_hash(checkpoint_dict: dict) -> str:
    """计算检查点哈希（与manager.py中的实现一致）"""
    content = json.dumps(checkpoint_dict, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def create_valid_checkpoint(
    checkpoint_id: str,
    workflow_id: str,
    task_id: str,
    sequence: int,
) -> WorkflowCheckpoint:
    """创建一个具有正确哈希的检查点"""
    # 直接使用对象创建
    checkpoint = WorkflowCheckpoint(
        checkpoint_id=checkpoint_id,
        workflow_id=workflow_id,
        task_id=task_id,
        organization_id="org_001",
        project_id="proj_001",
        repository_id="repo_001",
        created_at=datetime.now(UTC),
        created_by="system",
        source_event_sequence=sequence,
        source_event_id=f"evt_{sequence}",
        source_event_hash=f"evt_hash_{sequence}",
        event_stream_partition="default",
        checkpoint_reason=CheckpointReason.RUNNING,
        checkpoint_status=CheckpointStatus.CREATED,
        content_hash=f"content_hash_{checkpoint_id}",
        checkpoint_hash="placeholder",  # 临时占位符
        runtime_contract_version="v1.0.0",
        workflow_template_id="tpl_001",
        workflow_template_version="v1.0.0",
        agent_profile_version="v1.0.0",
        toolset_version="v1.0.0",
        state_snapshot_ref=f"state_ref_{checkpoint_id}",
        budget_snapshot_ref=f"budget_ref_{checkpoint_id}",
        resource_snapshot_ref=f"resource_ref_{checkpoint_id}",
    )

    # 计算正确的哈希
    checkpoint_dict = checkpoint.model_dump(mode="json")
    checkpoint_dict.pop("checkpoint_hash")
    checkpoint_hash = compute_checkpoint_hash(checkpoint_dict)

    # 使用model_copy更新哈希
    return checkpoint.model_copy(update={"checkpoint_hash": checkpoint_hash})


class TestInMemoryCheckpointStorage:
    """测试内存检查点存储"""

    def test_store_and_retrieve_checkpoint(self):
        """测试存储和检索检查点"""
        storage = InMemoryCheckpointStorage()

        checkpoint = create_valid_checkpoint(
            checkpoint_id="ckpt_001",
            workflow_id="wf_001",
            task_id="task_001",
            sequence=100,
        )

        # 存储检查点
        storage.store(checkpoint)

        # 检索检查点
        loaded = storage.retrieve(checkpoint.checkpoint_id)
        assert loaded is not None
        assert loaded.checkpoint_id == "ckpt_001"
        assert loaded.workflow_id == "wf_001"

    def test_retrieve_nonexistent_checkpoint(self):
        """测试检索不存在的检查点"""
        storage = InMemoryCheckpointStorage()
        loaded = storage.retrieve("nonexistent")
        assert loaded is None

    def test_list_by_workflow(self):
        """测试按workflow_id列出检查点"""
        storage = InMemoryCheckpointStorage()

        # 创建多个检查点
        for i in range(3):
            checkpoint = create_valid_checkpoint(
                checkpoint_id=f"ckpt_{i:03d}",
                workflow_id="wf_001",
                task_id="task_001",
                sequence=100 + i,
            )
            storage.store(checkpoint)

        # 列出检查点
        checkpoints = storage.list_by_workflow("wf_001")
        assert len(checkpoints) == 3
        # 按创建时间降序排列
        assert checkpoints[0].checkpoint_id == "ckpt_002"


class TestCheckpointManager:
    """测试 CheckpointManager"""

    @pytest.fixture
    def storage(self):
        """创建内存存储"""
        return InMemoryCheckpointStorage()

    @pytest.fixture
    def manager(self, storage):
        """创建 CheckpointManager"""
        return CheckpointManager(storage)

    def test_save_checkpoint(self, manager, storage):
        """测试保存检查点"""
        checkpoint = create_valid_checkpoint(
            checkpoint_id="ckpt_001",
            workflow_id="wf_001",
            task_id="task_001",
            sequence=100,
        )

        manager.save_checkpoint(checkpoint)

        # 验证已保存
        loaded = storage.retrieve("ckpt_001")
        assert loaded is not None
        assert loaded.checkpoint_id == "ckpt_001"

    def test_find_latest_valid_checkpoint(self, manager, storage):
        """测试查找最新有效检查点"""
        # 创建多个检查点
        for i in range(3):
            checkpoint = create_valid_checkpoint(
                checkpoint_id=f"ckpt_{i:03d}",
                workflow_id="wf_001",
                task_id="task_001",
                sequence=100 + i,
            )
            storage.store(checkpoint)

        # 查找最新检查点
        latest = manager.find_valid_checkpoint("wf_001")
        assert latest is not None
        assert latest.checkpoint_id == "ckpt_002"

    def test_find_valid_checkpoint_no_checkpoints(self, manager):
        """测试查找有效检查点但没有检查点"""
        latest = manager.find_valid_checkpoint("nonexistent_workflow")
        assert latest is None

    def test_list_checkpoints(self, manager, storage):
        """测试列出检查点"""
        # 创建检查点
        checkpoint = create_valid_checkpoint(
            checkpoint_id="ckpt_001",
            workflow_id="wf_001",
            task_id="task_001",
            sequence=100,
        )
        storage.store(checkpoint)

        # 列出检查点
        checkpoints = manager.list_checkpoints("wf_001")
        assert len(checkpoints) == 1
        assert checkpoints[0].checkpoint_id == "ckpt_001"

    def test_verify_checkpoint_invalid_hash(self, manager):
        """测试验证检查点时哈希不匹配"""
        # 创建一个哈希错误的检查点
        checkpoint = create_valid_checkpoint(
            checkpoint_id="ckpt_001",
            workflow_id="wf_001",
            task_id="task_001",
            sequence=100,
        )

        # 篡改哈希
        checkpoint_dict = checkpoint.model_dump()
        checkpoint_dict["checkpoint_hash"] = "invalid_hash"
        invalid_checkpoint = WorkflowCheckpoint(**checkpoint_dict)

        # 验证应该失败
        from src.runtime.checkpoint.manager import CheckpointVerificationError
        with pytest.raises(CheckpointVerificationError):
            manager.verify_checkpoint(invalid_checkpoint)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
