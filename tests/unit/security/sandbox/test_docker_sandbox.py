"""
Docker 沙箱隔离单元测试
"""

import os
import sys
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from src.security.sandbox.docker_sandbox import (
    ContainerConfig,
    ContainerResult,
    ContainerState,
    DockerSandbox,
    NetworkPolicy,
)


class TestContainerConfig:
    """容器配置测试"""

    def test_config_defaults(self):
        """测试配置默认值"""
        config = ContainerConfig(
            image="python:3.11",
            name="test-container",
        )
        assert config.image == "python:3.11"
        assert config.name == "test-container"
        assert config.working_dir == "/workspace"
        assert config.cpu_limit == "2"
        assert config.memory_limit == "4g"
        assert config.timeout_seconds == 900
        assert config.network_mode == "none"

    def test_config_custom_values(self):
        """测试自定义配置"""
        config = ContainerConfig(
            image="ubuntu:22.04",
            name="custom-container",
            cpu_limit="1",
            memory_limit="2g",
            timeout_seconds=300,
        )
        assert config.cpu_limit == "1"
        assert config.memory_limit == "2g"
        assert config.timeout_seconds == 300

    def test_config_with_environment(self):
        """测试环境变量配置"""
        env = {"DEBUG": "true", "API_KEY": "secret"}
        config = ContainerConfig(
            image="python:3.11",
            name="env-container",
            environment=env,
        )
        assert config.environment == env

    def test_config_with_volumes(self):
        """测试卷挂载配置"""
        volumes = {"/host/path": "/container/path"}
        config = ContainerConfig(
            image="python:3.11",
            name="volume-container",
            volumes=volumes,
        )
        assert config.volumes == volumes


class TestContainerResult:
    """容器结果测试"""

    def test_result_creation(self):
        """测试结果创建"""
        result = ContainerResult(
            container_id="abc123",
            exit_code=0,
            stdout="output",
            stderr="",
            duration_seconds=1.5,
            state=ContainerState.EXITED,
        )
        assert result.container_id == "abc123"
        assert result.exit_code == 0
        assert result.stdout == "output"
        assert result.duration_seconds == 1.5
        assert result.state == ContainerState.EXITED

    def test_result_with_error(self):
        """测试包含错误的结果"""
        result = ContainerResult(
            container_id="def456",
            exit_code=1,
            stdout="",
            stderr="error message",
            duration_seconds=0.5,
            state=ContainerState.EXITED,
        )
        assert result.exit_code == 1
        assert "error" in result.stderr


class TestContainerState:
    """容器状态枚举测试"""

    def test_state_values(self):
        """测试状态值"""
        assert ContainerState.CREATED.value == "created"
        assert ContainerState.RUNNING.value == "running"
        assert ContainerState.PAUSED.value == "paused"
        assert ContainerState.STOPPED.value == "stopped"
        assert ContainerState.EXITED.value == "exited"
        assert ContainerState.DEAD.value == "dead"


class TestNetworkPolicy:
    """网络策略测试"""

    def test_default_policy(self):
        """测试默认网络策略"""
        policy = NetworkPolicy()
        assert policy.allow_outbound is False
        assert policy.allowed_hosts is None
        assert policy.allowed_ports is None

    def test_policy_with_allowed_hosts(self):
        """测试允许主机列表"""
        policy = NetworkPolicy(
            allow_outbound=True,
            allowed_hosts=["github.com", "api.github.com"],
        )
        assert policy.allow_outbound is True
        assert len(policy.allowed_hosts) == 2

    def test_policy_with_allowed_ports(self):
        """测试允许端口列表"""
        policy = NetworkPolicy(
            allow_outbound=True,
            allowed_ports=[443, 80],
        )
        assert policy.allowed_ports == [443, 80]


class TestDockerSandboxResourceParsing:
    """资源限制解析测试"""

    def test_parse_cpu_limit(self):
        """测试 CPU 限制解析"""
        assert DockerSandbox._parse_cpu_limit("1") == 1.0
        assert DockerSandbox._parse_cpu_limit("2") == 2.0
        assert DockerSandbox._parse_cpu_limit("0.5") == 0.5

    def test_parse_memory_limit(self):
        """测试内存限制解析"""
        # 字节
        assert DockerSandbox._parse_memory_limit("1024b") == 1024
        
        # 千字节
        assert DockerSandbox._parse_memory_limit("1k") == 1024
        
        # 兆字节
        assert DockerSandbox._parse_memory_limit("512m") == 512 * 1024 * 1024
        
        # 吉字节
        assert DockerSandbox._parse_memory_limit("1g") == 1024 * 1024 * 1024
        assert DockerSandbox._parse_memory_limit("4g") == 4 * 1024 * 1024 * 1024

    def test_parse_memory_limit_float(self):
        """测试浮点数内存限制"""
        assert DockerSandbox._parse_memory_limit("2.5g") == int(2.5 * 1024 * 1024 * 1024)
        assert DockerSandbox._parse_memory_limit("512.5m") == int(512.5 * 1024 * 1024)


class TestDockerSandboxInitialization:
    """Docker 沙箱初始化测试"""

    def test_sandbox_creation(self):
        """测试沙箱创建"""
        sandbox = DockerSandbox()
        assert sandbox.docker_url == "unix:///var/run/docker.sock"
        assert sandbox._containers == {}

    def test_sandbox_with_custom_url(self):
        """测试自定义 Docker URL"""
        custom_url = "tcp://localhost:2375"
        sandbox = DockerSandbox(docker_url=custom_url)
        assert sandbox.docker_url == custom_url

    def test_sandbox_client_lazy_initialization(self, monkeypatch):
        docker_module = MagicMock()
        monkeypatch.setitem(sys.modules, "docker", docker_module)
        sandbox = DockerSandbox()
        assert sandbox._client is None
        docker_module.DockerClient.assert_not_called()
        assert sandbox.client is docker_module.DockerClient.return_value
        assert sandbox.client is docker_module.DockerClient.return_value
        docker_module.DockerClient.assert_called_once_with(base_url=sandbox.docker_url)


class TestDockerSandboxBuildContainerKwargs:
    """容器参数构建测试"""

    def test_build_basic_kwargs(self):
        """测试基础参数构建"""
        sandbox = DockerSandbox()
        config = ContainerConfig(image="python:3.11", name="test", command=["python", "app.py"])
        kwargs = sandbox._build_container_kwargs(config, None)
        assert kwargs["nano_cpus"] == 2_000_000_000
        assert kwargs["mem_limit"] == 4 * 1024**3
        assert kwargs["network_mode"] == "none"
        assert "host_config" not in kwargs
        assert sandbox._client is None

    def test_build_kwargs_with_volumes(self):
        """测试带卷的参数构建"""
        config = ContainerConfig(
            image="ubuntu:22.04",
            name="volume-test",
            volumes={"/host": "/container"},
        )
        assert config.volumes == {"/host": "/container"}

    def test_build_kwargs_with_environment(self):
        """测试带环境变量的参数构建"""
        config = ContainerConfig(
            image="python:3.11",
            name="env-test",
            environment={"VAR1": "value1", "VAR2": "value2"},
        )
        assert len(config.environment) == 2


class TestDockerSandboxEscapeDetection:
    """沙箱逃逸检测测试"""

    @pytest.mark.asyncio
    async def test_unavailable_escape_detection_does_not_report_safe(self):
        sandbox = DockerSandbox()
        with pytest.raises(NotImplementedError, match="host monitoring"):
            await sandbox.check_sandbox_escape("container-id")


@pytest.fixture
def docker_integration_sandbox():
    if os.environ.get("AI_AGENT_RUN_DOCKER_TESTS") != "1":
        pytest.skip("Set AI_AGENT_RUN_DOCKER_TESTS=1 with a running Docker daemon")
    docker = pytest.importorskip("docker", reason="Install project sandbox extra")
    client = docker.from_env(timeout=5)
    try:
        client.ping()
        sandbox = DockerSandbox()
        sandbox._client = client
        yield sandbox
    finally:
        client.close()


@pytest.mark.integration
class TestDockerSandboxIntegration:
    @pytest.mark.asyncio
    async def test_run_command_successful(self, docker_integration_sandbox):
        config = ContainerConfig(
            image=os.environ.get("AI_AGENT_DOCKER_TEST_IMAGE", "python:3.12-alpine"),
            name=f"ai-agent-test-{uuid4().hex}", working_dir="/tmp",
            command=["python", "-c", "print('sandbox-ok')"], timeout_seconds=30,
        )
        result = await docker_integration_sandbox.run_command(config)
        assert result.exit_code == 0
        assert result.stdout.strip() == "sandbox-ok"

    @pytest.mark.asyncio
    async def test_run_command_with_timeout(self, docker_integration_sandbox):
        config = ContainerConfig(
            image=os.environ.get("AI_AGENT_DOCKER_TEST_IMAGE", "python:3.12-alpine"),
            name=f"ai-agent-test-{uuid4().hex}", working_dir="/tmp",
            command=["python", "-c", "import time; time.sleep(60)"], timeout_seconds=1,
        )
        result = await docker_integration_sandbox.run_command(config)
        assert result.exit_code == 124
        assert "timed out" in result.stderr
        assert docker_integration_sandbox._containers == {}

    @pytest.mark.asyncio
    async def test_run_command_cleanup(self, docker_integration_sandbox):
        import docker

        config = ContainerConfig(
            image=os.environ.get("AI_AGENT_DOCKER_TEST_IMAGE", "python:3.12-alpine"),
            name=f"ai-agent-test-{uuid4().hex}", working_dir="/tmp",
            command=["python", "-c", "raise SystemExit(3)"], timeout_seconds=30,
        )
        result = await docker_integration_sandbox.run_command(config)
        assert result.exit_code == 3
        assert docker_integration_sandbox._containers == {}
        with pytest.raises(docker.errors.NotFound):
            docker_integration_sandbox.client.containers.get(config.name)


class TestDockerSandboxProperties:
    """沙箱属性测试"""

    def test_container_config_is_dataclass(self):
        """测试 ContainerConfig 是数据类"""
        config = ContainerConfig(image="test", name="test")
        # 数据类应该有 __dataclass_fields__
        assert hasattr(config, "__dataclass_fields__")

    def test_container_result_is_dataclass(self):
        """测试 ContainerResult 是数据类"""
        result = ContainerResult(
            container_id="id",
            exit_code=0,
            stdout="",
            stderr="",
            duration_seconds=0.0,
            state=ContainerState.EXITED,
        )
        assert hasattr(result, "__dataclass_fields__")

    def test_network_policy_is_dataclass(self):
        """测试 NetworkPolicy 是数据类"""
        policy = NetworkPolicy()
        assert hasattr(policy, "__dataclass_fields__")
