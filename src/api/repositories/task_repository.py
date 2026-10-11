"""
Task 仓储 facade（src/api/repositories/task_repository.py）。

封装 InMemoryProjectionStorage + TaskProjector，给 API 层提供：
- create_task: 创建 Task（生成 EntityId、TraceId、写入初始投影）
- get_task: 查询 Task 投影
- list_tasks: 列表 + 强制分页
- cancel_task: 取消 Task（仅 CREATED/EXECUTING 可取消；状态机约束由 REQ-RT-002 定义）

设计原则：
- 不引入 SQLAlchemy/Redis；本任务使用内存存储，便于本地演示与单测。
- 状态机不变量（哪些状态可取消）由 REQ-RT-002 冻结；本模块仅做现状投影写入，
  真正的事件溯源与跨 Projector 影响待 T-3 (SEC-009) 与 T-5 (OBS) 时接入。
"""
from __future__ import annotations

from datetime import UTC, datetime

from pydantic import ValidationError as PydanticValidationError

from src.api.schemas.task import TaskCreateRequest
from src.runtime.common.types import (
    Budget,
    SafeMetadata,
    generate_entity_id,
    generate_trace_id,
)
from src.runtime.entities.task import (
    AgentTask,
    SourceReference,
)
from src.runtime.projection.in_memory_storage import InMemoryProjectionStorage
from src.runtime.projection.models import TaskProjection
from src.runtime.projection.task_projector import TaskProjector

# 可取消的 Task 状态集合（与 REQ-RT-002 对齐）
# TaskStatus 枚举值：CREATED / EXECUTING / PAUSED 可取消；COMPLETED/CANCELLED/FAILED 终态
_CANCELLABLE_STATUSES: frozenset[str] = frozenset(
    {
        "CREATED",
        "AUTHORIZING",
        "PLANNING",
        "WAITING_APPROVAL",
        "PREPARING_WORKSPACE",
        "EXECUTING",
        "VALIDATING",
        "CREATING_PR",
        "WAITING_REVIEW",
        "PAUSED",
    }
)


class TaskNotFoundError(LookupError):
    """Task 不存在。"""

    def __init__(self, task_id: str) -> None:
        super().__init__(f"task not found: {task_id}")
        self.task_id = task_id


class TaskAlreadyTerminalError(RuntimeError):
    """Task 已处于终态，无法取消。"""

    def __init__(self, task_id: str, current_status: str) -> None:
        super().__init__(
            f"task {task_id} already terminal (status={current_status})"
        )
        self.task_id = task_id
        self.current_status = current_status


class TaskRepository:
    """Task 仓储 facade（内存实现）。"""

    def __init__(self) -> None:
        # 内存投影存储（REQ-RT-004 兼容）
        self._storage = InMemoryProjectionStorage()
        self._projector = TaskProjector(storage=self._storage)
        # 保留 AgentTask 业务实体，便于 GET 详情返回完整字段
        self._entities: dict[str, AgentTask] = {}

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create_task(
        self,
        request: TaskCreateRequest,
        *,
        organization_id: str,
        project_id: str,
        repository_id: str,
        creator_id: str,
    ) -> AgentTask:
        """创建 Task（不触发 Policy Gateway；API 层在调用工具时才走 Policy）。"""

        now = datetime.now(UTC)
        trace_id = generate_trace_id()

        try:
            task = AgentTask(
                schema_version="runtime.task.v1",
                task_id=generate_entity_id(),
                organization_id=organization_id,
                project_id=project_id,
                repository_id=repository_id,
                creator_id=creator_id,
                source_type=request.source_type,
                source_reference=SourceReference(
                    source_type=request.source_type,
                    snapshot_hash=None,
                ),
                title=request.title,
                description=request.description,
                risk_level=request.risk_level,
                workflow_template_id=request.workflow_template_id,
                workflow_template_version=request.workflow_template_version,
                workflow_id=None,
                base_revision=request.base_revision,
                working_branch=request.working_branch,
                working_revision=None,
                budget=Budget(
                    max_total_tokens=request.budget_max_tokens,
                    max_cost_microusd=request.budget_max_cost_microusd,
                ),
                status_projection=None,
                created_at=now,
                updated_at=now,
                started_at=None,
                completed_at=None,
                metadata=SafeMetadata(),
                trace_id=trace_id,
            )
        except PydanticValidationError as exc:
            # 业务层不变量（动态 base_revision / UUID 格式等）失败 → 422
            from src.api.middleware.error_handler import APIError
            from src.api.schemas.common import APIErrorCode

            raise APIError(
                status_code=422,
                code=APIErrorCode.INVALID_PARAMS,
                message=f"task entity validation failed: {exc.errors()[0]['msg']}",
            ) from exc
        self._entities[task.task_id] = task

        # 写入初始投影（TaskCreated 事件路径的简化版，不走事件存储）
        projection = TaskProjection(
            task_id=task.task_id,
            organization_id=task.organization_id,
            project_id=task.project_id,
            repository_id=task.repository_id,
            creator_id=task.creator_id,
            current_workflow_id=None,
            status="CREATED",
            status_reason=None,
            risk_level=task.risk_level.value,
            base_revision=task.base_revision,
            working_revision=None,
            current_step_id=None,
            required_approval_count=0,
            unresolved_failure_count=0,
            artifact_count=0,
            evidence_count=0,
            last_event_id=trace_id,
            last_sequence=1,
            last_event_type="TaskCreated",
            projection_version=self._projector.PROJECTION_VERSION,
            created_at=now,
            updated_at=now,
            started_at=None,
            completed_at=None,
            completion_summary=None,
        )
        # 兼容：InMemoryProjectionStorage.save_task_projection_with_checkpoint 需要 checkpoint
        from src.runtime.projection.checkpoint import ProjectionCheckpoint

        checkpoint = ProjectionCheckpoint(
            projection_name=self._projector.PROJECTION_NAME,
            projection_version=self._projector.PROJECTION_VERSION,
            partition_key=task.task_id,
            last_event_id=trace_id,
            last_sequence=1,
            last_event_hash=trace_id,
        )
        self._storage.save_task_projection_with_checkpoint(
            projection=projection,
            checkpoint=checkpoint,
            event_id=trace_id,
            event_hash=trace_id,
        )
        return task

    def get_task(self, task_id: str) -> tuple[AgentTask, TaskProjection]:
        """获取 Task 实体 + 投影；不存在抛 TaskNotFoundError。"""
        projection = self._storage.load_task_projection(task_id)
        entity = self._entities.get(task_id)
        if projection is None or entity is None:
            raise TaskNotFoundError(task_id)
        return entity, projection

    def list_tasks(
        self,
        *,
        limit: int,
        offset: int,
        organization_id: str | None = None,
    ) -> tuple[list[TaskProjection], int]:
        """分页查询 Task 投影。

        强制 limit ∈ [1, 200]；offset ≥ 0（API 层校验后传入）。
        按 updated_at 倒序；MVP 简单内存排序，足够演示。
        """
        items = sorted(
            self._storage.task_projections.values(),
            key=lambda p: p.updated_at,
            reverse=True,
        )
        if organization_id is not None:
            items = [p for p in items if p.organization_id == organization_id]
        total = len(items)
        page = items[offset : offset + limit]
        return page, total

    def cancel_task(self, task_id: str, *, actor_id: str) -> AgentTask:
        """取消 Task（仅可取消状态可取消；终态抛 TaskAlreadyTerminalError）。

        行为：
        - 终态：抛 TaskAlreadyTerminalError（由 API 层映射为 409）
        - 可取消：将投影 status 改为 CANCELLED + status_reason 记 actor_id
        - 不可达状态：保守抛 409（防御未来枚举扩展）
        """
        projection = self._storage.load_task_projection(task_id)
        if projection is None:
            raise TaskNotFoundError(task_id)

        current = projection.status
        if current not in _CANCELLABLE_STATUSES:
            raise TaskAlreadyTerminalError(task_id, current)

        # 更新投影
        now = datetime.now(UTC)
        projection.status = "CANCELLED"
        projection.status_reason = f"cancelled by {actor_id}"
        projection.completed_at = now
        projection.updated_at = now

        # 同步实体
        entity = self._entities.get(task_id)
        if entity is not None:
            cancelled = entity.model_copy(
                update={
                    "status_projection": entity.status_projection,  # 类型不变；仅投影变更
                    "updated_at": now,
                    "completed_at": now,
                }
            )
            self._entities[task_id] = cancelled

        return entity if entity is not None else self._entities[task_id]  # 不会 None


__all__ = [
    "TaskAlreadyTerminalError",
    "TaskNotFoundError",
    "TaskRepository",
]