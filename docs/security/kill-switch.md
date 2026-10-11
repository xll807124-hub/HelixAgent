# Kill Switch (SEC-009)

> 平台级紧急冻结机制。当检测到异常（凭据泄露、Policy 多次违规、异常率突增）时，能在秒级禁用所有新工具调用、阻止 Task 执行、撤销在飞凭据、保留完整审计证据。

## 状态机

```
IDLE ──trigger(scope, reason)──> TRIGGERED ──request_recovery()──> RECOVERING ──confirm_recovery()──> IDLE
       (拒绝所有新工具调用)        (二阶段恢复防误操作)            (回到 IDLE 解除冻结)
```

合法迁移：
- `IDLE → TRIGGERED`（trigger）
- `TRIGGERED → RECOVERING`（request_recovery）
- `RECOVERING → IDLE`（confirm_recovery）

非法迁移一律拒绝（防越权恢复）。

## 作用域

| Scope | 触发范围 | 适用场景 |
|---|---|---|
| `GLOBAL` | 全平台所有工具调用 | 平台级紧急事件 |
| `ORGANIZATION` | 某组织内 | 单租户被攻陷 |
| `PROJECT` | 某项目 | 项目级数据泄露 |
| `REPOSITORY` | 某仓库 | 仓库级污染 |

## 端点（管理面）

所有端点需 `X-Admin-Token` 头（与普通 bearer token 解耦）。

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/admin/kill-switch/status` | 查询当前状态 |
| POST | `/admin/kill-switch/trigger` | 触发（紧急冻结） |
| POST | `/admin/kill-switch/recover` | 阶段 1：进入恢复（返回 `confirm_token`） |
| POST | `/admin/kill-switch/recover/confirm` | 阶段 2：用 `confirm_token` 解除 |
| POST | `/admin/kill-switch/triggers/{name}/enable` | 启用 trigger |
| POST | `/admin/kill-switch/triggers/{name}/disable` | 禁用 trigger |

## 操作流程示例

### 1. 紧急触发

```bash
curl -X POST http://api/admin/kill-switch/trigger \
  -H "X-Admin-Token: $AI_API_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "scope": "GLOBAL",
    "reason": "production credentials leaked via log file",
    "trigger_source": "manual"
  }'
```

**效果**：
- 所有新工具调用立即被拒绝（HTTP 409 + `action blocked by kill switch`）
- 状态进入 `TRIGGERED`
- 审计日志记录 `trigger` 事件

### 2. 查询状态

```bash
curl http://api/admin/kill-switch/status \
  -H "X-Admin-Token: $AI_API_ADMIN_TOKEN"
```

返回：
```json
{
  "state": "TRIGGERED",
  "current_trigger": {
    "event_id": "...",
    "scope": "GLOBAL",
    "reason": "...",
    "triggered_at": "2026-10-11T12:00:00Z",
    ...
  },
  "total_triggers": 1,
  "last_updated_at": "2026-10-11T12:00:00Z"
}
```

### 3. 恢复（两阶段）

```bash
# 阶段 1：请求恢复（返回 confirm_token）
curl -X POST http://api/admin/kill-switch/recover \
  -H "X-Admin-Token: $AI_API_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"reason": "credentials rotated, threat contained"}'
# 响应：{ "data": { "confirm_token": "raw_token_xxx..." } }

# 阶段 2：30 分钟内必须 confirm
curl -X POST http://api/admin/kill-switch/recover/confirm \
  -H "X-Admin-Token: $AI_API_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"confirm_token": "raw_token_xxx..."}'
```

**两阶段设计目的**：防误操作。即使 admin token 泄露，攻击者也无法直接解除冻结，必须再次确认。

## 自动触发器

默认全部 `disable`，避免误触发业务。

### 启用凭据泄露触发器
```bash
curl -X POST http://api/admin/kill-switch/triggers/credential_leak/enable \
  -H "X-Admin-Token: $AI_API_ADMIN_TOKEN"
```

触发条件：5 分钟内 ≥10 次凭据撤销 → 自动 trigger(scope=organization)

### Policy 违规触发器
触发条件：60 秒内 ≥50 次 Policy DENY → 自动 trigger(scope=organization)

### 异常率触发器
MVP 占位：手动 fire；未来接入 Prometheus metrics。

## 与 ActionExecutor 集成

工具执行前由 `ActionExecutor` 调用 `KillSwitchGate.is_blocked(...)`：
- IDLE → 放行
- TRIGGERED/RECOVERING + scope 匹配 → 拒绝，返回 `ActionExecutionResult(success=False, error="action blocked by kill switch: ...")`
- 未启用 gate（`kill_switch_gate=None`）→ 默认放行（fail-open）

## 审计

每次状态变更都触发审计监听器（通过 `manager.add_audit_listener(callback)` 注册）：
- `trigger` 事件
- `recovery_request` 事件
- `recovery_confirm` 事件

MVP 阶段仅写日志；未来接入 OTel spans / 外部 SIEM。

## 环境变量

| 变量 | 说明 |
|---|---|
| `AI_API_ADMIN_TOKEN` | Admin token；未配置时 admin 端点 503 |

## 安全约束

- admin token 用 `hmac.compare_digest` 防时序攻击
- confirm_token 用 SHA-256 哈希存储，明文仅在 recover 响应中返回一次
- 状态机非法迁移一律 RuntimeError
- 二阶段恢复 30 分钟有效期

## 验收

- 43 个 Kill Switch 单元测试通过
- 全量 1219 passed / 11 skipped
- mypy 0 issues (126 files)
- ruff 0 issues