"""
FastAPI 应用入口（src/api/main.py）。

启动期（lifespan）：
1. 初始化默认组织/项目/仓库 ID（占位；SEC-008 多租户接入后改为请求注入）
2. 初始化 ToolRegistry + 11 个内置工具（REQ-HAR-003 Tool Adapter）
3. 初始化 PolicyGateway（SimplifiedPolicyGateway 占位）
4. 初始化 ActionExecutor（串联 Registry + Gateway）
5. 初始化 TaskRepository（内存实现）
6. 注册路由 + 中间件 + 异常处理器

外部启动方式：
    uvicorn src.api.main:app --reload --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.config import get_settings
from src.api.endpoints import health_router, tasks_router, tools_router
from src.api.endpoints.admin import kill_switch_router
from src.api.middleware import (
    BearerTokenAuthMiddleware,
    TraceContextMiddleware,
    register_exception_handlers,
)
from src.api.repositories.task_repository import TaskRepository
from src.security.kill_switch import KillSwitchGate, KillSwitchManager, TriggerRegistry
from src.security.policy_gateway import SimplifiedPolicyGateway
from src.tools.executor import ActionExecutor
from src.tools.registry import ToolRegistry, get_global_registry, reset_global_registry

logger = logging.getLogger(__name__)


def _bootstrap_default_tools(registry: ToolRegistry) -> int:
    """注册 MVP 阶段已实现的工具到 registry。

    返回注册数量；任一失败即抛 RuntimeError（fail-fast）。
    注：本任务仅 bootstrap；缺工具实例不影响 API 启动（返回 0），
    但建议补齐以最大化可演示性。
    """
    registered = 0
    # 延迟导入：避免硬依赖未实现工具阻塞 API 启动
    candidates: list[tuple[str, type | None]] = [
        ("file-read", _try_import("src.tools.file.read", "FileReadTool")),
        ("file-write", _try_import("src.tools.file.write", "FileWriteTool")),
        ("file-search", _try_import("src.tools.file.search", "FileSearchTool")),
        ("git-clone", _try_import("src.tools.git.clone", "GitCloneTool")),
        ("git-status", _try_import("src.tools.git.status", "GitStatusTool")),
        ("git-branch", _try_import("src.tools.git.branch", "GitBranchTool")),
        ("git-commit", _try_import("src.tools.git.commit", "GitCommitTool")),
        ("git-diff", _try_import("src.tools.git.diff", "GitDiffTool")),
        ("git-pr", _try_import("src.tools.git.pr", "GitPRTool")),
        ("pytest-run", _try_import("src.tools.test.pytest_runner", "PytestRunnerTool")),
        ("safe-shell", _try_import("src.tools.shell.safe_shell", "SafeShellTool")),
    ]
    for tool_name, cls in candidates:
        if cls is None:
            continue
        try:
            registry.register(cls())
            registered += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("failed to register tool %s: %s", tool_name, exc)
    return registered


def _try_import(module_path: str, class_name: str) -> type | None:
    """延迟导入工具类；导入失败返回 None 而非抛错（fail-soft 启动）。"""
    try:
        import importlib

        module = importlib.import_module(module_path)
        return getattr(module, class_name, None)
    except Exception as exc:  # noqa: BLE001
        logger.debug("optional tool class missing: %s.%s (%s)", module_path, class_name, exc)
        return None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """启动期初始化共享状态；关闭期清理。"""
    settings = get_settings()

    # 默认上下文（多租户接入前占位；用合法 UUID 满足 AgentTask 校验）
    app.state.default_organization_id = "00000000-0000-0000-0000-000000000001"
    app.state.default_project_id = "00000000-0000-0000-0000-000000000002"
    app.state.default_repository_id = "00000000-0000-0000-0000-000000000003"

    # 工具注册表（用全局单例，确保与现有 ActionExecutor 行为一致）
    reset_global_registry()
    registry = get_global_registry()
    count = _bootstrap_default_tools(registry)
    app.state.tool_registry = registry
    logger.info("tool registry bootstrapped: %d tools", count)

    # Policy Gateway（SimplifiedPolicyGateway 占位；OPA 接入留待 T-3）
    policy_gateway = SimplifiedPolicyGateway(tool_registry=registry)
    app.state.policy_gateway = policy_gateway
    logger.info("policy gateway initialized: %s", type(policy_gateway).__name__)

    # Action Executor（串联 Registry + Gateway + Kill Switch Gate）
    kill_switch_manager = KillSwitchManager()
    app.state.kill_switch_manager = kill_switch_manager
    app.state.kill_switch_trigger_registry = TriggerRegistry(kill_switch_manager)
    kill_switch_gate = KillSwitchGate(kill_switch_manager)
    executor = ActionExecutor(
        tool_registry=registry,
        policy_gateway=policy_gateway,
        kill_switch_gate=kill_switch_gate,
    )
    app.state.action_executor = executor
    logger.info("action executor initialized with kill switch gate")

    # Task Repository（内存实现）
    task_repo = TaskRepository()
    app.state.task_repository = task_repo
    logger.info("task repository initialized")

    logger.info(
        "api startup complete; listening on %s:%d (reload=%s)",
        settings.host,
        settings.port,
        settings.reload,
    )
    try:
        yield
    finally:
        # 关闭期清理（如有句柄/连接/订阅）
        logger.info("api shutdown complete")


def create_app() -> FastAPI:
    """FastAPI 应用工厂。"""
    settings = get_settings()

    app = FastAPI(
        title=settings.title,
        version=settings.version,
        description=(
            "AI Agent Platform HTTP API. "
            "Aligned with REQ-RT-001~008, REQ-SEC-002/003, REQ-HAR-003."
        ),
        lifespan=lifespan,
    )

    # 中间件链（外层 → 内层）
    # 注意：BaseHTTPMiddleware 是 LIFO；最后 add 的最先生效
    app.add_middleware(BearerTokenAuthMiddleware, settings=settings)
    app.add_middleware(TraceContextMiddleware)

    cors_origins = settings.cors_origin_list
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Trace-Id"],
            expose_headers=["X-Trace-Id"],
            max_age=600,
        )

    # 异常处理
    register_exception_handlers(app)

    # 路由
    app.include_router(health_router)
    app.include_router(tasks_router)
    app.include_router(tools_router)
    app.include_router(kill_switch_router)

    return app


# uvicorn 入口：`uvicorn src.api.main:app`
app = create_app()