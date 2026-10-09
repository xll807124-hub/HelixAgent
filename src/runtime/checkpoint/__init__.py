"""
Checkpoint Protocol Module（REQ-RT-005）

提供 Workflow 级不可变检查点协议，支持崩溃恢复、暂停/恢复、副作用核查。

核心组件：
- WorkflowCheckpoint: 检查点数据模型
- CheckpointBuilder: 检查点构建器
- CheckpointManager: 检查点管理器
- RecoveryCoordinator: 恢复协调器
- SideEffectVerifier: 副作用验证器

使用示例：
    from src.runtime.checkpoint import (
        CheckpointBuilder,
        CheckpointManager,
        RecoveryCoordinator,
        InMemoryCheckpointStorage,
    )

    # 1. 创建检查点
    builder = CheckpointBuilder(event_store, projection_storage)
    checkpoint = builder.build_from_workflow(
        workflow_id, reason=CheckpointReason.BEFORE_RISKY_ACTION
    )

    # 2. 保存检查点
    storage = InMemoryCheckpointStorage()
    manager = CheckpointManager(storage)
    manager.save_checkpoint(checkpoint)

    # 3. 恢复 Workflow
    coordinator = RecoveryCoordinator(manager, event_store, projection_storage, idempotency_manager)
    recovered_checkpoint = coordinator.recover_workflow(workflow_id)
"""

from src.runtime.checkpoint.builder import CheckpointBuilder
from src.runtime.checkpoint.manager import (
    CheckpointManager,
    CheckpointManagerError,
    CheckpointStorage,
    CheckpointVerificationError,
    InMemoryCheckpointStorage,
)
from src.runtime.checkpoint.models import (
    ActionCheckpointRef,
    BudgetSnapshot,
    CheckpointReason,
    CheckpointStatus,
    RecoveryAction,
    ResourceSnapshot,
    SideEffectState,
    StateSnapshot,
    WorkerCheckpointRef,
    WorkflowCheckpoint,
)
from src.runtime.checkpoint.recovery import (
    RecoveryCoordinator,
    RecoveryError,
    SideEffectVerifier,
)

__all__ = [
    # Models
    "WorkflowCheckpoint",
    "StateSnapshot",
    "WorkerCheckpointRef",
    "ActionCheckpointRef",
    "BudgetSnapshot",
    "ResourceSnapshot",
    "CheckpointReason",
    "CheckpointStatus",
    "SideEffectState",
    "RecoveryAction",
    # Builder
    "CheckpointBuilder",
    # Manager
    "CheckpointManager",
    "CheckpointStorage",
    "InMemoryCheckpointStorage",
    "CheckpointManagerError",
    "CheckpointVerificationError",
    # Recovery
    "RecoveryCoordinator",
    "SideEffectVerifier",
    "RecoveryError",
]
