"""src/api/schemas 单元测试。"""
from __future__ import annotations

from src.api.schemas.common import APIErrorCode, error_response, success_response
from src.api.schemas.task import TaskCreateRequest, TaskListResponse
from src.api.schemas.tool import ToolInvokeRequest, ToolListResponse, ToolSummary


class TestEnvelope:
    """统一响应 envelope 测试。"""

    def test_success_response_default(self) -> None:
        """成功响应：code=0，data 透传，trace_id 默认空。"""
        r = success_response({"x": 1}, trace_id="abc123")
        assert r["code"] == 0
        assert r["message"] == "ok"
        assert r["data"] == {"x": 1}
        assert r["trace_id"] == "abc123"

    def test_error_response_includes_code(self) -> None:
        """错误响应：code 来自 APIErrorCode。"""
        r = error_response(APIErrorCode.NOT_FOUND, "missing", trace_id="t")
        assert r["code"] == int(APIErrorCode.NOT_FOUND)
        assert r["message"] == "missing"
        assert r["data"] is None

    def test_error_code_ranges_documented(self) -> None:
        """错误码分段：4xxx 业务/参数；5xxx 内部。"""
        assert 40000 < int(APIErrorCode.BUSINESS_VALIDATION) < 50000
        assert 50000 < int(APIErrorCode.INTERNAL_ERROR) < 60000


class TestTaskSchemas:
    """Task schema 单元测试。"""

    def test_create_request_minimal(self) -> None:
        """POST 请求体：最小必填。"""
        req = TaskCreateRequest(
            title="T",
            description="D",
            workflow_template_id="wf",
            workflow_template_version="v1",
            base_revision="0123456789abcdef0123456789abcdef01234567",
        )
        assert req.title == "T"
        assert req.risk_level.value == "LOW"

    def test_create_request_rejects_blank_title(self) -> None:
        """POST 请求体：title 为空应拒。"""
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            TaskCreateRequest(
                title="",
                description="D",
                workflow_template_id="wf",
                workflow_template_version="v1",
                base_revision="0123456789abcdef0123456789abcdef01234567",
            )

    def test_list_response_pagination_fields(self) -> None:
        """列表响应：limit/offset/total 三件套。"""
        resp = TaskListResponse(items=[], total=0, limit=20, offset=0)
        assert resp.limit == 20
        assert resp.offset == 0
        assert resp.total == 0


class TestToolSchemas:
    """Tool schema 单元测试。"""

    def test_tool_summary(self) -> None:
        """ToolSummary 字段必填校验。"""
        t = ToolSummary(
            name="file-read",
            description="Read file",
            risk_level="LOW",
            timeout_seconds=5,
            capabilities=["file", "read"],
        )
        assert t.name == "file-read"
        assert t.risk_level == "LOW"

    def test_invoke_request_forbids_extra(self) -> None:
        """ToolInvokeRequest：extra=forbid（防客户端注入）。"""
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ToolInvokeRequest(
                params={},
                task_id="t1",
                project_id="p1",
                extra_field="forbidden",  # type: ignore[call-arg]
            )

    def test_tool_list_response(self) -> None:
        """ToolListResponse 列表项字段。"""
        resp = ToolListResponse(
            items=[ToolSummary(
                name="x", description="y", risk_level="LOW", timeout_seconds=10
            )],
            total=1,
        )
        assert resp.total == 1
        assert resp.items[0].name == "x"
