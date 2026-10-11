"""
工具端点（src/api/endpoints/tools.py）。

- GET  /api/v1/tools                       列出已注册工具
- POST /api/v1/tools/{name}/invoke          调用工具（受 Policy Gateway 校验）

设计原则（对齐 REQ-SEC-003 / AGENTS.md §7）：
- 模型不能直接执行 Action（必须经 Action 提议 → Policy Gateway → 工具执行）；
  本 API 层模拟 Worker 提议，自动构造 Action 实体供 ActionExecutor 使用。
- 失败时返回 envelope；不回内部栈/规则细节。
- 工具不可写资源限制：本端点仅暴露工具给"已授权用户"（占位），不下放凭据；
  真正工具调用仍受 Policy Gateway 前置校验。

注意：本端点不构造完整 Action 实体（避免触达 REQ-RT-001 冻结契约的字段约束）；
改走 ActionExecutor.execute_action 的封装路径，传入最小必填字段。
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Path, Request

from src.api.deps import (
    get_action_executor,
    get_tool_registry,
)
from src.api.middleware.error_handler import APIError
from src.api.middleware.trace import get_trace_id
from src.api.schemas.common import APIErrorCode, success_response
from src.api.schemas.tool import (
    ToolInvokeRequest,
    ToolInvokeResponse,
    ToolListResponse,
    ToolSummary,
)
from src.runtime.common.types import (
    ResourceRef,
    ResourceType,
    SafeMetadata,
    generate_entity_id,
)
from src.runtime.entities.action import Action, ActionStatus, ActionType
from src.runtime.entities.task import RiskLevel
from src.tools.base import ExecutionContext
from src.tools.executor import ActionExecutor
from src.tools.registry import ToolRegistry

router = APIRouter(prefix="/api/v1/tools", tags=["tools"])


@router.get("", summary="List registered tools")
async def list_tools(
    request: Request,
    tool_registry: ToolRegistry = Depends(get_tool_registry),  # noqa: B008
) -> dict[str, Any]:
    """列出已注册工具（仅暴露 name/description/risk_level/timeout/capabilities）。"""
    trace_id = get_trace_id(request)
    items = [
        ToolSummary(
            name=tool.name,
            description=tool.description,
            risk_level=tool.risk_level.value,
            timeout_seconds=tool.timeout_seconds,
            capabilities=list(tool.capabilities),
        )
        for tool in tool_registry.list_tools()
    ]
    payload = ToolListResponse(items=items, total=len(items))
    return success_response(payload.model_dump(), trace_id=trace_id)


@router.post(
    "/{name}/invoke",
    summary="Invoke a registered tool",
)
async def invoke_tool(
    request: Request,
    body: ToolInvokeRequest,
    name: str = Path(min_length=1, max_length=200),
    tool_registry: ToolRegistry = Depends(get_tool_registry),  # noqa: B008
    executor: ActionExecutor = Depends(get_action_executor),  # noqa: B008
) -> dict[str, Any]:
    """调用工具：经 ActionExecutor（含 Policy Gateway 前置/后置校验）。

    失败语义：
    - 工具不存在 → 404 TOOL_NOT_FOUND
    - Policy 拒绝 → 403 PERMISSION_DENIED
    - 需要审批 → 409 STATE_CONFLICT（API 层不做审批流；上层应轮询 Task 状态）
    - 工具执行异常 → 200 success=False（业务级错误，不视为 HTTP 失败）
    """
    trace_id = get_trace_id(request)
    principal_id = getattr(request.state, "principal_id", "anonymous")

    tool = tool_registry.get_tool(name)
    if tool is None:
        raise APIError(
            status_code=404,
            code=APIErrorCode.TOOL_NOT_FOUND,
            message=f"tool not found: {name}",
        )

    # 组装 ExecutionContext
    task_id = body.task_id or generate_entity_id()
    project_id = body.project_id or "default-project"
    organization_id = getattr(request.app.state, "default_organization_id", "default-org")
    now = datetime.now(UTC)

    context = ExecutionContext(
        trace_id=trace_id,
        action_id=generate_entity_id(),
        user_id=principal_id,
        organization_id=organization_id,
        project_id=project_id,
        task_id=task_id,
        allowed_paths=[],
        read_only=False,
        timeout_seconds=tool.timeout_seconds,
    )

    # 构造最小可用的 Action 实体（满足 REQ-RT-001 §5.4 必填字段）。
    # 注：这里 source_revision 临时填 "unknown" 占位；后续接入 REQ-RT-001 完整事件流时，
    # 由调用方提供真实 commit SHA。
    action = Action(
        schema_version="runtime.action.v1",
        action_id=context.action_id,
        task_id=task_id,
        workflow_id=generate_entity_id(),
        worker_id=generate_entity_id(),
        step_id="api-invoke",
        type=ActionType.ANALYZE if tool.risk_level == RiskLevel.LOW else ActionType.WRITE,
        tool_name=name,
        tool_schema_version="v1",
        arguments=body.params,
        target_resources=[
            ResourceRef(
                resource_type=ResourceType.EXTERNAL_SERVICE,
                resource_id=name,
                scope=f"{organization_id}/{project_id}",
            )
        ],
        source_revision="unknown",  # 占位：API 调用尚未接入真实 source_revision
        risk_level=tool.risk_level,
        requires_approval=False,
        policy_decision_id=None,
        idempotency_key=None,
        expected_observation_schema=None,
        status_projection=ActionStatus.PROPOSED,
        trace_id=trace_id,
        created_at=now,
        updated_at=now,
        proposed_at=now,
        authorized_at=None,
        started_at=None,
        completed_at=None,
        metadata=SafeMetadata(),
    )

    result = await executor.execute_action(action, context)

    response_payload = ToolInvokeResponse(
        tool_name=name,
        success=result.success,
        output=None,
        error=result.error,
        execution_time_ms=0,
        evidence_id=result.evidence.evidence_id if result.evidence else None,
        action_status=(
            result.action.status_projection.value
            if result.action.status_projection is not None
            and hasattr(result.action.status_projection, "value")
            else str(result.action.status_projection)
        ),
    )

    # Policy 拒绝 → 403
    if (
        not result.success
        and result.action.status_projection == ActionStatus.FAILED
        and result.error
        and "Policy check failed" in result.error
    ):
        raise APIError(
            status_code=403,
            code=APIErrorCode.PERMISSION_DENIED,
            message=result.error,
        )

    # 需要审批 → 409
    if (
        not result.success
        and result.action.status_projection == ActionStatus.WAITING_APPROVAL
    ):
        raise APIError(
            status_code=409,
            code=APIErrorCode.STATE_CONFLICT,
            message=result.error or "action requires approval",
        )

    return success_response(response_payload.model_dump(), trace_id=trace_id)