"""
Task 端点（src/api/endpoints/tasks.py）。

- POST   /api/v1/tasks                 创建 Task
- GET    /api/v1/tasks                 列表（分页 + 组织过滤）
- GET    /api/v1/tasks/{task_id}       查询单个 Task
- DELETE /api/v1/tasks/{task_id}       取消 Task（仅可取消状态可取消）

设计原则（AGENTS.md §7）：
- 必填字段校验失败 → 422 INVALID_PARAMS
- 资源不存在 → 404 NOT_FOUND
- 状态冲突（取消已终态）→ 409 STATE_CONFLICT
- 所有写操作走 trace_id 关联（与 REQ-RT-006 对齐）
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Path, Query, Request

from src.api.deps import get_task_repository
from src.api.middleware.error_handler import APIError
from src.api.middleware.trace import get_trace_id
from src.api.repositories.task_repository import (
    TaskAlreadyTerminalError,
    TaskNotFoundError,
    TaskRepository,
)
from src.api.schemas.common import APIErrorCode, success_response
from src.api.schemas.task import (
    TaskCreateRequest,
    TaskListResponse,
    TaskResponse,
)

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


def _to_task_response(entity: Any, projection: Any) -> TaskResponse:
    """将实体 + 投影合并为对外视图。"""
    return TaskResponse(
        task_id=entity.task_id,
        organization_id=entity.organization_id,
        project_id=entity.project_id,
        repository_id=entity.repository_id,
        creator_id=entity.creator_id,
        title=entity.title,
        description=entity.description,
        risk_level=entity.risk_level,
        source_type=entity.source_type,
        workflow_template_id=entity.workflow_template_id,
        workflow_template_version=entity.workflow_template_version,
        workflow_id=entity.workflow_id,
        base_revision=entity.base_revision,
        working_branch=entity.working_branch,
        status=projection.status,
        trace_id=entity.trace_id,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
        started_at=projection.started_at,
        completed_at=projection.completed_at,
    )


@router.post(
    "",
    status_code=201,
    summary="Create a new task",
)
async def create_task(
    request: Request,
    body: TaskCreateRequest,
    repository: TaskRepository = Depends(get_task_repository),  # noqa: B008
) -> dict[str, Any]:
    """创建 Task（返回 201 + envelope）。"""
    trace_id = get_trace_id(request)
    principal_id = getattr(request.state, "principal_id", "anonymous")

    # 占位：MVP 阶段单一组织/项目/仓库；后续接入多租户（SEC-008）时由调用方注入
    organization_id = getattr(
        request.app.state, "default_organization_id", "default-org"
    )
    project_id = getattr(request.app.state, "default_project_id", "default-project")
    repository_id = getattr(request.app.state, "default_repository_id", "default-repo")

    entity = repository.create_task(
        body,
        organization_id=organization_id,
        project_id=project_id,
        repository_id=repository_id,
        creator_id=principal_id,
    )
    projection = repository._storage.load_task_projection(entity.task_id)  # noqa: SLF001
    payload = _to_task_response(entity, projection)
    return success_response(payload.model_dump(), trace_id=trace_id)


@router.get(
    "",
    summary="List tasks (paginated)",
)
async def list_tasks(
    request: Request,
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    organization_id: str | None = Query(default=None, max_length=200),
    repository: TaskRepository = Depends(get_task_repository),  # noqa: B008
) -> dict[str, Any]:
    """分页查询 Task（强制 limit/offset，避免无界查询 REQ-RT-008）。"""
    trace_id = get_trace_id(request)
    page, total = repository.list_tasks(
        limit=limit, offset=offset, organization_id=organization_id
    )

    items: list[TaskResponse] = []
    for projection in page:
        entity, _ = repository.get_task(projection.task_id)
        items.append(_to_task_response(entity, projection))

    payload = TaskListResponse(
        items=items, total=total, limit=limit, offset=offset
    )
    return success_response(payload.model_dump(), trace_id=trace_id)


@router.get(
    "/{task_id}",
    summary="Get task by id",
)
async def get_task(
    request: Request,
    task_id: str = Path(min_length=1, max_length=200),
    repository: TaskRepository = Depends(get_task_repository),  # noqa: B008
) -> dict[str, Any]:
    """查询单个 Task 详情。"""
    trace_id = get_trace_id(request)
    try:
        entity, projection = repository.get_task(task_id)
    except TaskNotFoundError as e:
        raise APIError(
            status_code=404,
            code=APIErrorCode.NOT_FOUND,
            message=f"task not found: {task_id}",
        ) from e
    payload = _to_task_response(entity, projection)
    return success_response(payload.model_dump(), trace_id=trace_id)


@router.delete(
    "/{task_id}",
    summary="Cancel a task",
)
async def cancel_task(
    request: Request,
    task_id: str = Path(min_length=1, max_length=200),
    repository: TaskRepository = Depends(get_task_repository),  # noqa: B008
) -> dict[str, Any]:
    """取消 Task（仅 CREATED / EXECUTING 等可取消状态可取消）。"""
    trace_id = get_trace_id(request)
    principal_id = getattr(request.state, "principal_id", "anonymous")
    try:
        entity = repository.cancel_task(task_id, actor_id=principal_id)
    except TaskNotFoundError as e:
        raise APIError(
            status_code=404,
            code=APIErrorCode.NOT_FOUND,
            message=f"task not found: {task_id}",
        ) from e
    except TaskAlreadyTerminalError as e:
        raise APIError(
            status_code=409,
            code=APIErrorCode.TASK_ALREADY_TERMINAL,
            message=f"task {task_id} already terminal (status={e.current_status})",
        ) from e

    projection = repository._storage.load_task_projection(task_id)  # noqa: SLF001
    payload = _to_task_response(entity, projection)
    return success_response(payload.model_dump(), trace_id=trace_id)