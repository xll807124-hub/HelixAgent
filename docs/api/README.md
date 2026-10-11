# API Layer (src/api/)

> 本目录是后端 HTTP API 入口层（Stage 1.5）。与前端 Web 控制台、外部系统集成方对接。

## 设计原则
- 统一响应 envelope：`{code, message, data, trace_id}`（对齐 Cursor 后端 + Anthropic 错误结构）
- 错误码分段：4xxx 业务/参数，403xx 鉴权，404xx 资源，409xx 状态冲突，422xx schema，5xxx 内部
- Fail Secure：未授权一律 401（不暴露资源存在性）
- Fail Fast：启动期 `lifespan` 初始化所有共享组件
- 不暴露内部细节：5xx 不回栈/不回内部消息，只回 `trace_id` 给客户端排查

## 端点一览（MVP）

| 方法 | 路径 | 用途 | 鉴权 |
|---|---|---|---|
| GET | `/health` | 存活探针 | 否（白名单） |
| GET | `/ready` | 就绪探针（检查 tool_registry/policy_gateway/task_repository） | 否（白名单） |
| GET | `/api/v1/tools` | 列出已注册工具 | 是 |
| POST | `/api/v1/tools/{name}/invoke` | 调用工具（经 Policy Gateway 校验） | 是 |
| POST | `/api/v1/tasks` | 创建 Task | 是 |
| GET | `/api/v1/tasks` | 列表（强制 limit/offset 分页） | 是 |
| GET | `/api/v1/tasks/{id}` | 查询单个 Task 详情 | 是 |
| DELETE | `/api/v1/tasks/{id}` | 取消 Task（仅可取消状态可取消） | 是 |
| GET | `/openapi.json` | OpenAPI 3.0 规范 | 否 |
| GET | `/docs` | Swagger UI | 否 |

## 启动方式

```bash
# 开发模式（自动 reload）
uvicorn src.api.main:app --reload --host 127.0.0.1 --port 8000

# 生产模式
uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --workers 4
```

环境变量（可选，均有默认值；前缀 `AI_API_`）：

| 变量 | 默认 | 说明 |
|---|---|---|
| `AI_API_HOST` | `127.0.0.1` | 监听地址 |
| `AI_API_PORT` | `8000` | 监听端口 |
| `AI_API_WORKERS` | `1` | uvicorn worker 数 |
| `AI_API_RELOAD` | `False` | dev reload 开关 |
| `AI_API_CORS_ORIGINS` | `` | 逗号分隔白名单 |
| `AI_API_AUTH_REQUIRED` | `True` | 是否启用 Bearer Token 鉴权 |

## 鉴权

MVP 用 `Authorization: Bearer <token>` 占位实现：
- 缺失/格式错/空 token → 401 UNAUTHENTICATED
- 合法 token → 注入 `request.state.principal_id`（UUID5 派生）和 `request.state.auth_token`
- 真 OAuth/JWT/Scope 校验待 SEC-002 RBAC 接入时替换

## 目录结构

```
src/api/
├── __init__.py
├── main.py                  # FastAPI 工厂 + lifespan
├── config.py                # Pydantic Settings
├── deps.py                  # FastAPI Depends 注入
├── schemas/                 # 请求/响应 schema
│   ├── common.py            # 统一 envelope
│   ├── task.py
│   └── tool.py
├── endpoints/               # 路由
│   ├── health.py
│   ├── tasks.py
│   └── tools.py
├── middleware/              # 中间件
│   ├── auth.py              # Bearer Token（占位）
│   ├── trace.py             # TraceId 注入与回传
│   └── error_handler.py     # 统一异常处理
└── repositories/            # API 友好仓储 facade
    └── task_repository.py
```

## 不在本任务（明确排除）
- SSE/WebSocket 流式
- Webhook 出站
- MCP 连接器 HTTP 端点
- 真实 DB 接入（SQLAlchemy/Alembic）
- OAuth/SSO（占位 bearer token）

## 验收
- 48 个 API 单元测试通过
- 全量测试 1176 passed / 11 skipped
- mypy 0 issues (117 files)
- ruff 0 issues