"""
测试辅助工具：创建有效的 Action 和 Worker 实体
"""
import uuid
from datetime import UTC, datetime

from src.runtime.common.types import Budget, ResourceRef, ResourceType
from src.runtime.entities.action import Action, ActionStatus, ActionType
from src.runtime.entities.task import RiskLevel
from src.runtime.entities.worker import Worker, WorkerStatus, WorkerType


def create_test_action(
    action_id: str | None = None,
    task_id: str | None = None,
    workflow_id: str | None = None,
    worker_id: str | None = None,
    step_id: str = "step-001",
    tool_name: str = "file-read",
    parameters: dict | None = None,
    status: ActionStatus = ActionStatus.PROPOSED,
    risk_level: RiskLevel = RiskLevel.LOW,
    trace_id: str | None = None,
    target_resources: list[ResourceRef] | None = None,
    action_type: ActionType = ActionType.READ,
    **kwargs
) -> Action:
    """
    创建有效的测试 Action 实体
    
    自动处理所有必填字段和格式要求：
    - 自动生成符合 UUID 格式的 ID
    - 自动生成符合格式的 trace_id
    - 自动填充必填的 target_resources
    - 自动设置时间戳
    """
    now = datetime.now(UTC)

    # 生成符合 UUID 格式的 ID
    action_id = action_id or str(uuid.uuid4())
    task_id = task_id or str(uuid.uuid4())
    workflow_id = workflow_id or str(uuid.uuid4())
    worker_id = worker_id or str(uuid.uuid4())

    # 生成符合格式的 trace_id (32位十六进制)
    trace_id = trace_id or uuid.uuid4().hex

    # 默认 target_resources
    if target_resources is None:
        target_resources = [
            ResourceRef(
                resource_type=ResourceType.FILE,
                resource_id=str(uuid.uuid4()),
                scope="repository://test-repo",
                locator="/test/file.txt"
            )
        ]

    # 根据 status 设置时间戳
    timestamps = {
        "created_at": now,
        "updated_at": now,
        "proposed_at": now,
        "authorized_at": None,
        "started_at": None,
        "completed_at": None,
    }

    if status == ActionStatus.AUTHORIZED:
        timestamps["authorized_at"] = now
    elif status in [ActionStatus.EXECUTING]:
        timestamps["authorized_at"] = now
        timestamps["started_at"] = now
    elif status in [ActionStatus.SUCCEEDED, ActionStatus.FAILED]:
        timestamps["authorized_at"] = now
        timestamps["started_at"] = now
        timestamps["completed_at"] = now

    return Action(
        action_id=action_id,
        task_id=task_id,
        workflow_id=workflow_id,
        worker_id=worker_id,
        step_id=step_id,
        type=action_type,
        tool_name=tool_name,
        tool_schema_version="v1.0.0",
        arguments=parameters or {},
        target_resources=target_resources,
        risk_level=risk_level,
        status_projection=status,
        trace_id=trace_id,
        **timestamps,
        **kwargs
    )


def create_test_worker(
    worker_id: str | None = None,
    task_id: str | None = None,
    workflow_id: str | None = None,
    step_id: str = "step-001",
    worker_type: WorkerType = WorkerType.CODER,
    status: WorkerStatus = WorkerStatus.CREATED,
    attempt: int = 1,
    trace_id: str | None = None,
    allowed_tools: list[str] | None = None,
    allowed_resources: list[ResourceRef] | None = None,
    **kwargs
) -> Worker:
    """
    创建有效的测试 Worker 实体
    
    自动处理所有必填字段和格式要求：
    - 自动生成符合 UUID 格式的 ID
    - 自动生成符合格式的 trace_id
    - 自动设置时间戳和预算
    """
    now = datetime.now(UTC)
    
    # 生成符合 UUID 格式的 ID
    worker_id = worker_id or str(uuid.uuid4())
    task_id = task_id or str(uuid.uuid4())
    workflow_id = workflow_id or str(uuid.uuid4())
    
    # 生成符合格式的 trace_id (32位十六进制)
    trace_id = trace_id or uuid.uuid4().hex
    
    # 默认工具和资源
    if allowed_tools is None:
        allowed_tools = ["file-read", "file-write"]
    
    if allowed_resources is None:
        allowed_resources = []
    
    # 根据 status 设置时间戳
    timestamps = {
        "created_at": now,
        "updated_at": now,
        "started_at": None,
        "completed_at": None,
    }
    
    if status in [WorkerStatus.RUNNING, WorkerStatus.WAITING_APPROVAL, WorkerStatus.PAUSED]:
        timestamps["started_at"] = now
    elif status in [WorkerStatus.COMPLETED, WorkerStatus.FAILED, WorkerStatus.CANCELLED]:
        timestamps["started_at"] = now
        timestamps["completed_at"] = now
    
    return Worker(
        worker_id=worker_id,
        task_id=task_id,
        workflow_id=workflow_id,
        step_id=step_id,
        worker_type=worker_type,
        attempt=attempt,
        allowed_tools=allowed_tools,
        allowed_resources=allowed_resources,
        agent_profile_id="default-agent",
        agent_profile_version="v1.0.0",
        toolset_id="default-toolset",
        toolset_version="v1.0.0",
        source_revision="abc123def456",  # 具体 commit SHA
        budget=Budget(),
        status_projection=status,
        trace_id=trace_id,
        **timestamps,
        **kwargs
    )
