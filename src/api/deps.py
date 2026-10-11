"""
API 层依赖注入与共享状态（src/api/deps.py）。

通过 FastAPI Depends 提供：
- Tool Registry（已注册的工具集合）
- Policy Gateway（策略网关接口）
- Action Executor（Action 执行器，封装 Policy + Registry）
- Task Repository（API 友好的仓储 facade，封装 InMemoryProjectionStorage）

设计原则：
- 单例懒加载：lifespan 启动期初始化一次，请求期间复用。
- 不引入 SQLAlchemy/Redis：本任务仅本地演示与 Future HTTP 接入；
  持久化层留待 T-3 / T-5 时按 REQ-RT-008 落地。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Depends, Request

from src.runtime.projection.in_memory_storage import InMemoryProjectionStorage
from src.runtime.projection.task_projector import TaskProjector
from src.security.policy_gateway import (
    PolicyGateway,
    SimplifiedPolicyGateway,
)
from src.tools.executor import ActionExecutor
from src.tools.registry import ToolRegistry, get_global_registry

if TYPE_CHECKING:
    from src.api.repositories.task_repository import TaskRepository


def get_tool_registry(request: Request) -> ToolRegistry:
    """从 app.state 取出启动期初始化的 ToolRegistry。"""
    registry: ToolRegistry = request.app.state.tool_registry
    return registry


def get_policy_gateway(request: Request) -> PolicyGateway:
    """从 app.state 取出启动期初始化的 PolicyGateway。"""
    gateway: PolicyGateway = request.app.state.policy_gateway
    return gateway


def get_action_executor(request: Request) -> ActionExecutor:
    """从 app.state 取出启动期初始化的 ActionExecutor。"""
    executor: ActionExecutor = request.app.state.action_executor
    return executor


def get_task_repository(request: Request) -> TaskRepository:
    """从 app.state 取出启动期初始化的 TaskRepository。"""
    repo: TaskRepository = request.app.state.task_repository
    return repo


def get_global_registry_singleton() -> ToolRegistry:
    """备选：从全局单例取 ToolRegistry（用于不依赖 app.state 的场景）。"""
    return get_global_registry()


def get_default_policy_gateway() -> PolicyGateway:
    """备选：默认 Policy Gateway（SimplifiedPolicyGateway）。

    注：SimplifiedPolicyGateway 需要 tool_registry；调用方应传 get_global_registry()。
    """
    return SimplifiedPolicyGateway(tool_registry=get_global_registry())


__all__ = [
    "get_action_executor",
    "get_default_policy_gateway",
    "get_global_registry_singleton",
    "get_policy_gateway",
    "get_task_repository",
    "get_tool_registry",
    # re-export dependencies 让 router 引用方便
    "Depends",
]


# 触达目录结构改造占位：确保 InMemoryProjectionStorage / TaskProjector 被运行时识别，
# 否则本模块独立 import 时 mypy 可能报 unused import（保留为安全引用）。
_ = (InMemoryProjectionStorage, TaskProjector)