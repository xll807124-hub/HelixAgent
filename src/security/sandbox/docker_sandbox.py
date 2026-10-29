"""
Docker 沙箱隔离实现

对齐设计文档：REQ-SEC-004 沙箱隔离
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ContainerState(str, Enum):
    """容器状态"""
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    EXITED = "exited"
    DEAD = "dead"


@dataclass
class ContainerConfig:
    """容器配置"""
    image: str                           # Docker 镜像
    name: str                            # 容器名称
    command: list[str] | None = None     # 执行命令
    working_dir: str = "/workspace"      # 工作目录
    cpu_limit: str = "2"                 # CPU 限制（核数）
    memory_limit: str = "4g"             # 内存限制
    timeout_seconds: int = 900           # 执行超时（15 分钟）
    environment: dict[str, str] | None = None  # 环境变量
    volumes: dict[str, str] | None = None      # 卷挂载 {host: container}
    network_mode: str = "none"           # 默认禁止网络


@dataclass
class ContainerResult:
    """容器执行结果"""
    container_id: str
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    state: ContainerState


@dataclass
class NetworkPolicy:
    """网络策略"""
    allow_outbound: bool = False         # 允许出站连接
    allowed_hosts: list[str] | None = None  # 允许连接的主机列表
    allowed_ports: list[int] | None = None  # 允许连接的端口


class DockerSandbox:
    """
    Docker 沙箱隔离管理器
    
    职责：
    1. 创建和管理隔离容器
    2. 设置资源限制（CPU、内存、磁盘）
    3. 配置网络隔离
    4. 处理容器生命周期
    5. 清理和防逃逸
    """

    def __init__(self, docker_url: str = "unix:///var/run/docker.sock"):
        """
        初始化沙箱管理器
        
        Args:
            docker_url: Docker daemon 连接 URL
        """
        self.docker_url = docker_url
        self._client = None
        self._containers: dict[str, dict] = {}

    @property
    def client(self) -> Any:
        """延迟导入 Docker 客户端"""
        if self._client is None:
            try:
                import docker
                self._client = docker.DockerClient(base_url=self.docker_url)
            except ImportError as e:
                raise RuntimeError("docker package not installed") from e
        return self._client

    async def run_command(
        self,
        config: ContainerConfig,
        network_policy: NetworkPolicy | None = None,
    ) -> ContainerResult:
        """
        在隔离容器中执行命令
        
        Args:
            config: 容器配置
            network_policy: 网络策略
            
        Returns:
            ContainerResult: 执行结果
        """
        container = None
        try:
            # 构建容器参数
            container_kwargs = self._build_container_kwargs(config, network_policy)

            # 参数校验完成后才访问 Docker。
            await self._ensure_image(config.image)

            # 创建容器
            container = self.client.containers.create(**container_kwargs)
            logger.info(f"Created container: {container.id[:12]}")

            # 记录容器信息
            self._containers[container.id] = {
                "created_at": datetime.now().isoformat(),
                "config": asdict(config),
            }

            # 启动容器
            start_time = datetime.now()
            container.start()
            logger.info(f"Started container: {container.id[:12]}")

            # 等待容器完成或超时
            result = await self._wait_for_completion(container, config.timeout_seconds)

            # 计算执行时间
            duration = (datetime.now() - start_time).total_seconds()

            return ContainerResult(
                container_id=container.id[:12],
                exit_code=result["StatusCode"],
                stdout=result.get("stdout", ""),
                stderr=result.get("stderr", ""),
                duration_seconds=duration,
                state=ContainerState.EXITED,
            )

        except Exception as e:
            logger.error(f"Container execution failed: {e}")
            raise

        finally:
            # 清理容器
            if container:
                await self._cleanup_container(container)

    async def _ensure_image(self, image: str) -> None:
        """确保镜像已拉取"""
        try:
            self.client.images.get(image)
            logger.info(f"Image exists: {image}")
        except Exception:
            logger.info(f"Pulling image: {image}")
            self.client.images.pull(image)

    def _build_container_kwargs(
        self,
        config: ContainerConfig,
        network_policy: NetworkPolicy | None,
    ) -> dict[str, Any]:
        """构建容器创建参数"""
        if config.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        cpu_limit = self._parse_cpu_limit(config.cpu_limit)
        memory_limit = self._parse_memory_limit(config.memory_limit)
        if cpu_limit <= 0 or memory_limit <= 0:
            raise ValueError("CPU and memory limits must be positive")
        network_mode = "none"
        if network_policy and network_policy.allow_outbound:
            if network_policy.allowed_hosts or network_policy.allowed_ports:
                raise NotImplementedError("Docker backend cannot enforce egress allowlists")
            if config.network_mode not in ("none", "bridge"):
                raise ValueError("Only none or bridge network modes are supported")
            network_mode = config.network_mode
        kwargs = {
            "image": config.image,
            "name": config.name,
            "command": config.command,
            "working_dir": config.working_dir,
            "environment": config.environment or {},
            "volumes": {
                host: {"bind": target, "mode": "rw"}
                for host, target in (config.volumes or {}).items()
            },
            "network_mode": network_mode,
            # containers.create 使用高层 SDK 参数，由 SDK 生成 HostConfig。
            "nano_cpus": int(cpu_limit * 1_000_000_000),
            "mem_limit": memory_limit,
            "memswap_limit": memory_limit,
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges:true"],
            "detach": True,
            "stdin_open": False,
        }
        return kwargs

    async def _wait_for_completion(
        self,
        container: Any,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        """等待容器完成执行"""
        import asyncio
        import time

        start_time = time.monotonic()

        while time.monotonic() - start_time < timeout_seconds:
            # 检查容器状态
            container.reload()
            state = container.attrs["State"]
            if state["Status"] in ["exited", "dead"]:
                # 获取输出
                stdout = container.logs(stdout=True, stderr=False)
                stderr = container.logs(stdout=False, stderr=True)
                return {
                    "StatusCode": state.get("ExitCode", 1),
                    "stdout": stdout.decode("utf-8", errors="replace") if stdout else "",
                    "stderr": stderr.decode("utf-8", errors="replace") if stderr else "",
                }

            await asyncio.sleep(0.5)

        # 超时：强制终止容器
        logger.warning(f"Container timeout after {timeout_seconds}s")
        container.kill()
        return {
            "StatusCode": 124,  # Timeout exit code
            "stdout": "",
            "stderr": f"Container execution timed out after {timeout_seconds}s",
        }

    async def _cleanup_container(self, container: Any) -> None:
        """清理容器"""
        try:
            container.remove(force=True)
            self._containers.pop(container.id, None)
            logger.info(f"Cleaned up container: {container.id[:12]}")
        except Exception as e:
            logger.error(f"Cleanup failed: {e}")
            raise

    @staticmethod
    def _parse_cpu_limit(cpu_str: str) -> float:
        """解析 CPU 限制字符串"""
        # "2" -> 2.0, "0.5" -> 0.5
        return float(cpu_str)

    @staticmethod
    def _parse_memory_limit(mem_str: str) -> int:
        """解析内存限制字符串"""
        # "4g" -> 4294967296, "512m" -> 536870912
        multipliers = {"b": 1, "k": 1024, "m": 1024**2, "g": 1024**3}
        value = float(mem_str[:-1])
        unit = mem_str[-1].lower()
        return int(value * multipliers.get(unit, 1))

    async def check_sandbox_escape(self, container_id: str) -> bool:
        """
        检测是否存在沙箱逃逸迹象
        
        Returns:
            True if escape detected, False otherwise
        """
        raise NotImplementedError("Sandbox escape detection requires a host monitoring backend")
