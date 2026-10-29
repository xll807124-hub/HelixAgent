"""Docker SDK-shaped fakes verify execution, failure and cleanup contracts."""

import asyncio
from unittest.mock import MagicMock

import pytest

from src.security.sandbox.docker_sandbox import ContainerConfig, DockerSandbox, NetworkPolicy


@pytest.fixture
def sandbox_and_container():
    sandbox = DockerSandbox()
    sandbox._client = MagicMock()
    container = sandbox._client.containers.create.return_value
    container.id = "container-id-for-test"
    container.attrs = {"State": {"Status": "exited", "ExitCode": 7}}
    container.logs.side_effect = lambda *, stdout, stderr: b"output" if stdout else b"error"
    return sandbox, container


@pytest.mark.asyncio
async def test_reads_sdk_state_and_separate_logs_then_removes_container(sandbox_and_container):
    sandbox, container = sandbox_and_container
    result = await sandbox.run_command(ContainerConfig(image="test", name="test"))
    assert result.exit_code == 7
    assert result.stdout == "output"
    assert result.stderr == "error"
    container.remove.assert_called_once_with(force=True)
    assert sandbox._containers == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeError("start failed"), asyncio.CancelledError()])
async def test_failure_or_cancellation_still_removes_container(sandbox_and_container, failure):
    sandbox, container = sandbox_and_container
    container.start.side_effect = failure
    with pytest.raises(type(failure)):
        await sandbox.run_command(ContainerConfig(image="test", name="test"))
    container.remove.assert_called_once_with(force=True)
    assert sandbox._containers == {}


@pytest.mark.asyncio
async def test_timeout_kills_and_cleans_container(sandbox_and_container, monkeypatch):
    sandbox, container = sandbox_and_container
    ticks = iter([0, 2])
    monkeypatch.setattr("time.monotonic", lambda: next(ticks, 2))
    result = await sandbox.run_command(
        ContainerConfig(image="test", name="test", timeout_seconds=1)
    )
    assert result.exit_code == 124
    container.kill.assert_called_once()
    container.remove.assert_called_once_with(force=True)
    assert sandbox._containers == {}


@pytest.mark.asyncio
async def test_cleanup_failure_is_not_reported_as_success(sandbox_and_container):
    sandbox, container = sandbox_and_container
    container.remove.side_effect = RuntimeError("remove failed")
    with pytest.raises(RuntimeError, match="remove failed"):
        await sandbox.run_command(ContainerConfig(image="test", name="test"))
    assert container.id in sandbox._containers


@pytest.mark.parametrize(
    "policy, expected",
    [
        (None, "none"),
        (NetworkPolicy(), "none"),
        (NetworkPolicy(allow_outbound=True), "bridge"),
    ],
)
def test_network_access_requires_explicit_policy(policy, expected):
    config = ContainerConfig(image="test", name="test", network_mode="bridge")
    kwargs = DockerSandbox()._build_container_kwargs(config, policy)
    assert kwargs["network_mode"] == expected


@pytest.mark.parametrize(
    "policy",
    [
        NetworkPolicy(allow_outbound=True, allowed_hosts=["example.com"]),
        NetworkPolicy(allow_outbound=True, allowed_ports=[443]),
    ],
)
def test_unsupported_allowlist_does_not_silently_allow_unrestricted_network(policy):
    with pytest.raises(NotImplementedError, match="allowlists"):
        DockerSandbox()._build_container_kwargs(ContainerConfig(image="test", name="test"), policy)


@pytest.mark.parametrize(
    "options",
    [
        {"cpu_limit": "0"},
        {"cpu_limit": "-1"},
        {"memory_limit": "0g"},
        {"timeout_seconds": 0},
        {"timeout_seconds": -1},
    ],
)
def test_invalid_limits_rejected_without_contacting_docker(options):
    sandbox = DockerSandbox()
    with pytest.raises(ValueError):
        sandbox._build_container_kwargs(ContainerConfig(image="test", name="test", **options), None)
    assert sandbox._client is None


def test_container_arguments_match_docker_sdk_contract():
    containers = pytest.importorskip("docker.models.containers", reason="Install sandbox extra")
    kwargs = DockerSandbox()._build_container_kwargs(
        ContainerConfig(image="test", name="test", volumes={"/host": "/workspace"}), None,
    )
    kwargs["version"] = "1.45"
    request = containers._create_container_args(kwargs)
    assert request["host_config"]["NanoCpus"] == 2_000_000_000
    assert request["host_config"]["NetworkMode"] == "none"
    assert request["host_config"]["Binds"] == ["/host:/workspace:rw"]
