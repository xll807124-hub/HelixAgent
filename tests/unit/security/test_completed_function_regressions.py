"""Regression cases for the completed API, policy and tool execution paths."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from src.api.config import get_settings
from src.api.main import create_app
from src.runtime.entities.action import ActionStatus
from src.runtime.entities.evidence import EvidenceResult
from src.security.policy_gateway import SimplifiedPolicyGateway
from src.security.policy_gateway.gateway_v2 import (
    ApprovalMatrix,
    PolicyDecision,
    PolicyGateway,
    PolicyRequest,
    RiskLevel,
)
from src.security.prompt_injection.policy_gateway import (
    PromptInjectionPolicyDecision,
    PromptInjectionPolicyGateway,
)
from src.security.rbac.models import (
    AuthorizationDecision,
    AuthorizationResult,
    Operation,
    Resource,
    ResourceType,
    Subject,
    SubjectType,
)
from src.tools.base import ExecutionContext, ToolResult
from src.tools.executor import ActionExecutor
from src.tools.file.read import FileReadTool
from src.tools.file.search import FileSearchTool
from src.tools.registry import ToolRegistry
from src.tools.shell.safe_shell import SafeShellTool
from src.tools.test.pytest_runner import PytestRunnerTool
from tests.helpers import create_test_action


@pytest.fixture
def context(tmp_path):
    return ExecutionContext(
        trace_id="a" * 32,
        action_id="action-1",
        task_id="task-1",
        user_id="user-1",
        organization_id="org-1",
        project_id="project-1",
        allowed_paths=[str(tmp_path)],
    )


def policy_request():
    return PolicyRequest(
        request_id="request-1",
        action_id="action-1",
        action_name="read",
        operation=Operation.READ,
        resource_id="repo-1",
        risk_level=RiskLevel.LOW,
        rbac_result=AuthorizationResult(
            request_id="rbac-1",
            decision=AuthorizationDecision.ALLOW,
            subject=Subject(
                subject_id="user-1",
                subject_type=SubjectType.USER,
                organization_id="org-1",
            ),
            resource=Resource(
                resource_id="repo-1",
                resource_type=ResourceType.REPOSITORY,
                organization_id="org-1",
            ),
            operation=Operation.READ,
        ),
    )


@pytest.mark.asyncio
async def test_cached_allow_cannot_override_new_rbac_denial():
    gateway = PolicyGateway()
    request = policy_request()
    assert (await gateway.evaluate(request)).decision == PolicyDecision.ALLOW
    denied = request.model_copy(
        update={
            "rbac_result": request.rbac_result.model_copy(
                update={
                    "decision": AuthorizationDecision.DENY,
                }
            ),
        }
    )
    assert (await gateway.evaluate(denied)).decision == PolicyDecision.DENY


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"operation": Operation.CREATE_COMMIT},
        {"resource_id": "another-repo"},
    ],
)
async def test_authorization_must_match_requested_operation_and_resource(changes):
    result = await PolicyGateway().evaluate(policy_request().model_copy(update=changes))
    assert result.decision == PolicyDecision.DENY


@pytest.mark.asyncio
async def test_unknown_rbac_decision_is_denied():
    request = policy_request()
    auth = request.rbac_result.model_copy(update={"decision": AuthorizationDecision.UNKNOWN})
    result = await PolicyGateway().evaluate(request.model_copy(update={"rbac_result": auth}))
    assert result.decision == PolicyDecision.DENY


@pytest.mark.asyncio
async def test_cached_allow_cannot_override_higher_risk():
    gateway = PolicyGateway()
    request = policy_request()
    await gateway.evaluate(request)
    dangerous = request.model_copy(update={"risk_level": RiskLevel.CRITICAL})
    result = await gateway.evaluate(dangerous)
    assert result.decision == PolicyDecision.ESCALATE_TO_APPROVAL


@pytest.mark.asyncio
async def test_cached_allow_cannot_override_policy_change():
    gateway = PolicyGateway()
    request = policy_request()
    await gateway.evaluate(request)
    gateway.approval_matrix.operation_overrides[Operation.READ] = True
    assert (await gateway.evaluate(request)).requires_approval


@pytest.mark.parametrize("operation", [Operation.CREATE_BRANCH, Operation.CREATE_COMMIT])
def test_critical_risk_always_requires_approval(operation):
    assert ApprovalMatrix().requires_approval(operation, RiskLevel.CRITICAL)


@pytest.mark.asyncio
@pytest.mark.parametrize("expired_field", ["subject", "authorization"])
async def test_expired_authorization_is_denied(expired_field):
    request = policy_request()
    expired = datetime.now(UTC) - timedelta(seconds=1)
    if expired_field == "subject":
        auth = request.rbac_result.model_copy(
            update={
                "subject": request.rbac_result.subject.model_copy(
                    update={"effective_until": expired}
                ),
            }
        )
    else:
        auth = request.rbac_result.model_copy(update={"effective_until": expired})
    result = await PolicyGateway().evaluate(request.model_copy(update={"rbac_result": auth}))
    assert result.decision == PolicyDecision.DENY


@pytest.mark.asyncio
async def test_cache_hit_keeps_current_request_id_and_audit():
    gateway = PolicyGateway()
    request = policy_request()
    await gateway.evaluate(request)
    next_request = request.model_copy(update={"request_id": "request-2"})
    result = await gateway.evaluate(next_request)
    assert result.request_id == "request-2"
    assert [event.request_id for event in gateway.get_audit_log()] == [
        "request-1",
        "request-2",
    ]


@pytest.mark.parametrize("role", ["viewer", "developer", "", "unknown"])
def test_prompt_injection_high_risk_override_requires_admin(role):
    gateway = PromptInjectionPolicyGateway()
    rejected = gateway.evaluate("high", 0.95, ["attack"], [], "reject")
    result = gateway.evaluate_kill_switch_override(rejected, "user-1", role, "reason")
    assert result.decision == PromptInjectionPolicyDecision.REJECT


@pytest.mark.parametrize("actor,reason", [("", "reason"), ("admin", " ")])
def test_prompt_injection_override_requires_auditable_identity_and_reason(actor, reason):
    gateway = PromptInjectionPolicyGateway()
    rejected = gateway.evaluate("high", 0.95, [], [], "reject")
    result = gateway.evaluate_kill_switch_override(rejected, actor, "admin", reason)
    assert result.decision == PromptInjectionPolicyDecision.REJECT


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["tests failed", None])
async def test_failed_tool_result_never_becomes_success(context, tmp_path, monkeypatch, failure):
    tool = FileReadTool()
    registry = ToolRegistry()
    registry.register(tool)
    monkeypatch.setattr(
        tool,
        "execute",
        AsyncMock(
            return_value=ToolResult(
                success=False,
                output={"failed": 1},
                error=failure,
            )
        ),
    )
    action = create_test_action(
        tool_name="file-read",
        parameters={"file_path": str(tmp_path / "test.txt")},
    )
    result = await ActionExecutor(registry, SimplifiedPolicyGateway(registry)).execute_action(
        action,
        context,
    )
    assert not result.success
    assert result.action.status_projection == ActionStatus.FAILED
    assert result.evidence.result == EvidenceResult.FAILED


@pytest.mark.asyncio
@pytest.mark.parametrize("escape", ["prefix", "parent"])
async def test_shell_rejects_directory_boundary_escape(context, tmp_path, escape):
    outside = str(tmp_path) + "-outside" if escape == "prefix" else str(tmp_path / "..")
    result = await SafeShellTool().validate_input({"command": "echo ok", "cwd": outside}, context)
    assert not result.valid


@pytest.mark.asyncio
async def test_shell_rechecks_validation_before_spawning(context, tmp_path, monkeypatch):
    def forbidden_spawn(*args, **kwargs):
        pytest.fail("invalid command reached subprocess.run")

    monkeypatch.setattr("src.tools.shell.safe_shell.subprocess.run", forbidden_spawn)
    result = await SafeShellTool().execute(
        {"command": "unapproved-command", "cwd": str(tmp_path)}, context
    )
    assert not result.success


@pytest.mark.asyncio
async def test_test_runner_rejects_out_of_scope_path(context):
    result = await PytestRunnerTool().validate_input({"test_path": str(Path.cwd())}, context)
    assert not result.valid


@pytest.mark.asyncio
async def test_test_runner_accepts_relative_path_and_current_interpreter(
    context, tmp_path, monkeypatch
):
    import subprocess
    import sys

    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "test_ok.py").write_text("def test_ok(): assert True\n")
    monkeypatch.chdir(tmp_path)
    calls = []

    def run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        assert cmd[0] == sys.executable
        target = Path(kwargs["cwd"]) / cmd[3]
        assert target.exists(), "relative test path was resolved twice"
        return subprocess.CompletedProcess(cmd, 0, "1 passed in 0.01s\n", "")

    monkeypatch.setattr("src.tools.test.pytest_runner.subprocess.run", run)
    result = await PytestRunnerTool().execute({"test_path": "suite/test_ok.py"}, context)
    assert result.success, result.error
    assert calls


@pytest.mark.asyncio
async def test_content_search_does_not_follow_file_symlink_outside_root(context, tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    private_dir = tmp_path / "private"
    private_dir.mkdir()
    private = private_dir / "private.txt"
    private.write_text("private-marker")
    link = root / "innocent.txt"
    try:
        link.symlink_to(private)
    except OSError:
        import sys

        if sys.platform != "win32":
            pytest.skip("symlink creation unavailable")
        import _winapi

        _winapi.CreateJunction(str(private_dir), str(root / "directory-link"))
    result = await FileSearchTool().execute(
        {
            "search_path": str(root),
            "pattern": "private-marker",
            "search_type": "content",
        },
        context.model_copy(update={"allowed_paths": [str(root)]}),
    )
    assert result.success
    assert result.output["results"] == []


@pytest.mark.asyncio
async def test_content_search_rejects_resolved_target_escape(context, tmp_path, monkeypatch):
    """Exercise target checking even on Windows hosts without symlink privileges."""
    root = tmp_path / "workspace"
    root.mkdir()
    candidate = root / "innocent.txt"
    candidate.write_text("private-marker")
    original_resolve = Path.resolve

    def resolve(path, *args, **kwargs):
        if path == candidate:
            return tmp_path / "outside.txt"
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    result = await FileSearchTool().execute(
        {
            "search_path": str(root),
            "pattern": "private-marker",
            "search_type": "content",
        },
        context.model_copy(update={"allowed_paths": [str(root)]}),
    )
    assert result.output["results"] == []


def test_api_rejects_unregistered_bearer_token(monkeypatch):
    monkeypatch.setenv("AI_API_AUTH_REQUIRED", "true")
    monkeypatch.setenv(
        "AI_API_AUTH_TOKENS",
        '{"configured-test-token": "00000000-0000-0000-0000-000000000010"}',
    )
    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as client:
            response = client.get("/api/v1/tasks", headers={"Authorization": "Bearer forged-token"})
            assert response.status_code == 401
    finally:
        get_settings.cache_clear()


def test_api_without_configured_tokens_fails_closed(monkeypatch):
    monkeypatch.setenv("AI_API_AUTH_REQUIRED", "true")
    monkeypatch.setenv("AI_API_AUTH_TOKENS", "{}")
    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as client:
            response = client.get("/api/v1/tasks", headers={"Authorization": "Bearer anything"})
            assert response.status_code == 503
            assert client.get("/health").status_code == 200
    finally:
        get_settings.cache_clear()


def test_api_search_requires_server_configured_workspace(monkeypatch, tmp_path):
    (tmp_path / "private.txt").write_text("private-marker")
    monkeypatch.setenv("AI_API_AUTH_REQUIRED", "true")
    monkeypatch.setenv(
        "AI_API_AUTH_TOKENS",
        '{"configured-test-token": "00000000-0000-0000-0000-000000000010"}',
    )
    monkeypatch.setenv("AI_API_TOOL_ALLOWED_PATHS", "[]")
    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as client:
            response = client.post(
                "/api/v1/tools/file-search/invoke",
                json={
                    "params": {
                        "search_path": str(tmp_path),
                        "pattern": "private-marker",
                        "search_type": "content",
                    }
                },
                headers={"Authorization": "Bearer configured-test-token"},
            )
            assert response.status_code == 503
    finally:
        get_settings.cache_clear()
