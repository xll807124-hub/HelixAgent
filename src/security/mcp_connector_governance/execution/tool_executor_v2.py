"""
Tool Execution Implementation - Day 3
实际的工具执行 - STDIO、HTTP、隔离执行
"""

import asyncio
import hashlib
import json
import logging
import os
import time
from datetime import datetime
from typing import Any

from ..audit.audit_logger import AuditLogger
from ..authorization.auth_manager import AuthorizationManager
from ..models import Connector, ToolSchema
from ..models.connector import AuthenticationMode, SignatureVerification
from ..policies.policy_engine import PolicyEngine
from ..registry.signature_verifier import check_signature_gate, connector_signing_payload
from ..registry.tool_registry import ToolRegistry
from ..security.signature_verifier import UnifiedSignatureVerifier
from .egress_guard import EgressViolation, build_guarded_resolver, validate_endpoint

logger = logging.getLogger(__name__)

# STDIO 连接器通过该环境变量接收短期令牌
CREDENTIAL_ENV_VAR = "MCP_CONNECTOR_TOKEN"


class ToolExecutionResult:
    """工具执行结果"""

    def __init__(
        self,
        success: bool,
        result: Any = None,
        error: str | None = None,
        execution_time_ms: float = 0.0,
        metadata: dict | None = None,
    ) -> None:
        self.success = success
        self.result = result
        self.error = error
        self.execution_time_ms = execution_time_ms
        self.metadata = metadata or {}
        self.timestamp = datetime.utcnow()

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "result": self.result,
            "error": self.error,
            "execution_time_ms": self.execution_time_ms,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
        }


class STDIOExecutor:
    """STDIO 传输的工具执行器"""

    def __init__(self, timeout_seconds: int = 30) -> None:
        """初始化 STDIO 执行器"""
        self.timeout_seconds = timeout_seconds

    async def execute(
        self,
        connector_path: str,
        tool_name: str,
        parameters: dict[str, Any],
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> ToolExecutionResult:
        """
        通过 STDIO 执行工具

        Args:
            connector_path: 连接器可执行文件路径
            tool_name: 工具名称
            parameters: 工具参数
            args: 命令行参数
            env: 额外环境变量 (叠加到当前环境之上)

        Returns:
            执行结果
        """
        start_time = time.time()

        try:
            # 构建 MCP 请求
            request = {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": parameters,
                },
                "id": "1",
            }

            # 启动连接器进程
            process = await asyncio.create_subprocess_exec(
                connector_path,
                *(args or []),
                env={**os.environ, **(env or {})} if env else None,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # 发送请求
            request_json = json.dumps(request).encode() + b"\n"

            try:
                stdout_data, stderr_data = await asyncio.wait_for(
                    process.communicate(input=request_json),
                    timeout=self.timeout_seconds,
                )
            except TimeoutError:
                process.kill()
                await process.wait()

                execution_time_ms = (time.time() - start_time) * 1000
                return ToolExecutionResult(
                    success=False,
                    error="Execution timeout",
                    execution_time_ms=execution_time_ms,
                )

            # 解析响应
            if process.returncode != 0:
                stderr_text = stderr_data.decode(errors="replace")
                execution_time_ms = (time.time() - start_time) * 1000

                return ToolExecutionResult(
                    success=False,
                    error=f"Process failed: {stderr_text}",
                    execution_time_ms=execution_time_ms,
                )

            # 解析 JSON 响应
            response_text = stdout_data.decode().strip()
            response = json.loads(response_text)

            execution_time_ms = (time.time() - start_time) * 1000

            if "error" in response:
                return ToolExecutionResult(
                    success=False,
                    error=response["error"].get("message", "Unknown error"),
                    execution_time_ms=execution_time_ms,
                )

            return ToolExecutionResult(
                success=True,
                result=response.get("result"),
                execution_time_ms=execution_time_ms,
                metadata={
                    "tool": tool_name,
                    "process_id": process.pid,
                },
            )

        except Exception as e:
            execution_time_ms = (time.time() - start_time) * 1000
            logger.error(f"STDIO execution error: {str(e)}", exc_info=True)

            return ToolExecutionResult(
                success=False,
                error=f"Execution error: {str(e)}",
                execution_time_ms=execution_time_ms,
            )


class HTTPExecutor:
    """HTTP 传输的工具执行器"""

    def __init__(self, timeout_seconds: int = 30, allow_private_networks: bool = False) -> None:
        """
        初始化 HTTP 执行器。

        allow_private_networks: 默认 False (严格: 仅 https + 公网地址)。
        True 仅用于本地开发和测试。
        """
        self.timeout_seconds = timeout_seconds
        self.allow_private_networks = allow_private_networks

    async def execute(
        self,
        connector_url: str,
        tool_name: str,
        parameters: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> ToolExecutionResult:
        """
        通过 HTTP 执行工具

        Args:
            connector_url: 连接器 URL (e.g. http://localhost:8000)
            tool_name: 工具名称
            parameters: 工具参数
            headers: HTTP 头

        Returns:
            执行结果
        """
        start_time = time.time()

        try:
            import aiohttp
        except ImportError:
            execution_time_ms = (time.time() - start_time) * 1000
            return ToolExecutionResult(
                success=False,
                error="aiohttp not installed",
                execution_time_ms=execution_time_ms,
            )

        # 出口校验 (SSRF): 在任何网络活动和凭据发送之前
        try:
            validate_endpoint(connector_url, self.allow_private_networks)
        except EgressViolation as exc:
            return ToolExecutionResult(
                success=False,
                error=f"Egress blocked: {exc}",
                execution_time_ms=(time.time() - start_time) * 1000,
                metadata={"blocked_by": "egress"},
            )

        try:
            # 构建请求
            request = {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": parameters,
                },
                "id": "1",
            }

            request_headers = dict(headers or {})
            request_headers["Content-Type"] = "application/json"

            # 连接时校验解析结果, 防 DNS 重绑定; 不跟随重定向, 防跳转到内网
            connector = aiohttp.TCPConnector(
                resolver=build_guarded_resolver(self.allow_private_networks),
                use_dns_cache=False,
            )
            async with aiohttp.ClientSession(connector=connector) as session:
                try:
                    async with session.post(
                        f"{connector_url}/mcp/tools/call",
                        json=request,
                        headers=request_headers,
                        timeout=aiohttp.ClientTimeout(total=self.timeout_seconds),
                        allow_redirects=False,
                    ) as resp:
                        if 300 <= resp.status < 400:
                            return ToolExecutionResult(
                                success=False,
                                error=f"Egress blocked: redirect (HTTP {resp.status}) not followed",
                                execution_time_ms=(time.time() - start_time) * 1000,
                                metadata={"blocked_by": "egress"},
                            )

                        response_text = await resp.text()
                        response = json.loads(response_text)

                        execution_time_ms = (time.time() - start_time) * 1000

                        if resp.status != 200:
                            return ToolExecutionResult(
                                success=False,
                                error=f"HTTP {resp.status}: {response_text}",
                                execution_time_ms=execution_time_ms,
                            )

                        if "error" in response:
                            return ToolExecutionResult(
                                success=False,
                                error=response["error"].get("message", "Unknown error"),
                                execution_time_ms=execution_time_ms,
                            )

                        return ToolExecutionResult(
                            success=True,
                            result=response.get("result"),
                            execution_time_ms=execution_time_ms,
                            metadata={
                                "tool": tool_name,
                                "status_code": resp.status,
                            },
                        )

                except TimeoutError:
                    execution_time_ms = (time.time() - start_time) * 1000
                    return ToolExecutionResult(
                        success=False,
                        error="HTTP request timeout",
                        execution_time_ms=execution_time_ms,
                    )

        except EgressViolation as e:
            return ToolExecutionResult(
                success=False,
                error=f"Egress blocked: {e}",
                execution_time_ms=(time.time() - start_time) * 1000,
                metadata={"blocked_by": "egress"},
            )
        except Exception as e:
            execution_time_ms = (time.time() - start_time) * 1000
            logger.error(f"HTTP execution error: {str(e)}", exc_info=True)

            return ToolExecutionResult(
                success=False,
                error=f"Execution error: {str(e)}",
                execution_time_ms=execution_time_ms,
            )


class ToolExecutor:
    """
    统一工具执行器

    流程: 签名闸门 -> 策略检查 -> 凭据准备 -> 配额扣减 -> 传输层执行 -> 失败退款 -> 审计
    任何一步无法确认时一律拒绝 (fail-closed)。

    凭据只注入传输层 (HTTP Authorization 头 / STDIO 子进程环境变量),
    不会出现在返回结果、元数据或审计中, 也不会进入模型上下文。
    """

    def __init__(
        self,
        policy_engine: PolicyEngine,
        timeout_seconds: int = 30,
        signature_verifier: UnifiedSignatureVerifier | None = None,
        audit_logger: AuditLogger | None = None,
        authorization_manager: AuthorizationManager | None = None,
        allow_private_networks: bool = False,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        """
        allow_private_networks: 默认 False, HTTP/SSE 出口仅允许 https + 公网地址。
        只应在本地开发和测试中设为 True。
        """
        self.policy_engine = policy_engine
        self.tool_registry = tool_registry
        # 需要认证的连接器必须配置 authorization_manager, 否则拒绝调用
        self.authorization_manager = authorization_manager
        self.stdio_executor = STDIOExecutor(timeout_seconds)
        self.http_executor = HTTPExecutor(timeout_seconds, allow_private_networks)
        self.signature_verifier = signature_verifier or UnifiedSignatureVerifier()
        self.audit_logger = audit_logger or AuditLogger()

    @staticmethod
    def signing_payload(connector: Connector) -> bytes:
        """连接器被签名的内容: 配置的规范化 JSON (不含 signature 字段)。"""
        return connector_signing_payload(connector)

    async def verify_connector_signature(
        self, connector: Connector, signature_info: dict[str, Any]
    ) -> bool:
        """
        验证连接器签名并把结果记录到 connector.config.signature。

        signature_info 的格式由 UnifiedSignatureVerifier 定义
        (algorithm / signature / certificate 等)。
        """
        payload = self.signing_payload(connector)
        result = await self.signature_verifier.verify(payload, signature_info)
        status = "valid" if result.is_valid else "invalid"
        connector.config.signature = SignatureVerification(
            is_signed=True,
            signature_format=result.algorithm,
            signer_identity=result.signer_identity,
            signed_at=datetime.utcnow() if result.is_valid else None,
            verification_status=status,
            signature_digest=hashlib.sha256(payload).hexdigest(),
        )
        self.audit_logger.log_signature_verification(
            connector.connector_id, status, result.algorithm, result.signer_identity
        )
        return result.is_valid

    def _signature_gate(self, connector: Connector) -> str | None:
        """需要签名的信任等级必须有有效且与当前配置一致的签名; 返回拒绝原因或 None。"""
        return check_signature_gate(connector)

    async def execute_tool(
        self,
        org_id: str,
        user_id: str,
        connector: Connector,
        tool: ToolSchema,
        parameters: dict[str, Any],
    ) -> ToolExecutionResult:
        """执行工具; 任何前置检查失败都不会触达连接器。"""
        start = time.time()
        connector_id = connector.connector_id

        def elapsed_ms() -> float:
            return (time.time() - start) * 1000

        def denied(reason: str, blocked_by: str) -> ToolExecutionResult:
            self.audit_logger.log_policy_decision(
                connector_id,
                tool.tool_name,
                user_id,
                org_id,
                "denied",
                reason,
                blocked_by,
            )
            return ToolExecutionResult(
                success=False,
                error=reason,
                execution_time_ms=elapsed_ms(),
                metadata={"blocked_by": blocked_by},
            )

        # Step 1: 签名闸门
        reason = self._signature_gate(connector)
        if reason:
            return denied(f"Signature check failed: {reason}", "signature")

        # Step 2: 策略检查 (黑名单 / 组织白名单 / 配额余量)
        decision = self.policy_engine.evaluate_tool_invocation(org_id, connector, tool, parameters)
        if not decision.allowed:
            return denied(f"Policy denied: {decision.reason}", decision.blocked_by or "policy")

        governance = self.tool_registry.governance if self.tool_registry is not None else None
        grant = governance.check_call(org_id, connector, tool) if governance is not None else None
        if grant is None:
            return denied("Tool definition is not approved", "tool_approval")

        # A state can become ACTIVE again while credential work is awaiting a thread.
        generation = connector.status.credential_generation
        manager = self.authorization_manager
        credential_generation = (manager.get_credential_generation(connector_id, org_id)
                                 if isinstance(manager, AuthorizationManager) else None)
        # Step 3: 准备凭据 (在扣配额之前, 失败不消耗配额)
        injection, cred_error = await self._prepare_injection(connector, org_id, user_id)
        if cred_error:
            return denied(cred_error, "credentials")

        # 凭据刷新在线程中等待时可能发生停用；在扣配额及交给传输前复核。
        # 不回显未知状态对象，也不把旧的发现结果或预检结论当作当前许可。
        if (not connector.status.is_callable()
                or generation != connector.status.credential_generation):
            return denied("Connector is no longer callable", "lifecycle")
        if (isinstance(manager, AuthorizationManager) and credential_generation
                != manager.get_credential_generation(connector_id, org_id)):
            return denied("Credential generation changed", "credentials")
        if governance is None or not governance.revalidate(grant, connector, tool):
            return denied("Tool approval changed", "tool_approval")

        # Step 4: 扣减配额
        if not self.policy_engine.consume_quota_for_invocation(org_id, connector, tool):
            return denied("Insufficient quota", "quota")

        # Step 5: 执行; 失败 (含执行器返回的失败结果) 一律退款
        try:
            result = await self._execute(connector, tool, parameters, injection)
        except Exception as exc:
            logger.error("Tool execution error: %s", exc, exc_info=True)
            result = ToolExecutionResult(
                success=False,
                error=f"Execution error: {exc}",
                execution_time_ms=elapsed_ms(),
            )

        if not result.success:
            self.policy_engine.refund_quota_for_failed_invocation(org_id, connector, tool)

        self._audit(org_id, user_id, connector, tool, result, decision.quota_cost)
        return result

    async def _prepare_injection(
        self, connector: Connector, org_id: str, user_id: str
    ) -> tuple[str | None, str | None]:
        """
        准备要注入传输层的令牌。

        返回 (token, error)。无需认证时返回 (None, None);
        需要认证但无法取得可注入的凭据时返回错误, 调用方必须拒绝。
        错误信息不包含凭据内容。
        """
        mode = connector.config.auth.mode
        if mode == AuthenticationMode.NONE:
            return None, None

        if self.authorization_manager is None:
            return (
                None,
                f"Credentials required ({mode.value}) but no authorization manager configured",
            )

        try:
            # prepare_credentials 可能做同步 HTTP (令牌刷新), 放到线程里避免阻塞事件循环
            credentials = await asyncio.to_thread(
                self.authorization_manager.prepare_credentials, connector, org_id, user_id
            )
        except Exception as exc:
            logger.error("Credential preparation failed: %s", type(exc).__name__)
            return None, "Credential preparation failed"

        if credentials is None:
            return None, "Credentials unavailable"

        token = credentials.get("access_token") or credentials.get("token")
        if not token:
            # 例如 mTLS 只有证书指纹, 当前传输层不支持客户端证书绑定
            return None, f"Auth mode '{mode.value}' cannot be injected by this transport"
        return str(token), None

    async def _execute(
        self,
        connector: Connector,
        tool: ToolSchema,
        parameters: dict[str, Any],
        token: str | None = None,
    ) -> ToolExecutionResult:
        """按传输类型分发; 缺少地址/命令时直接失败, 不使用默认值。"""
        transport = connector.config.transport
        kind = transport.type.value

        if kind == "stdio":
            if not transport.command:
                return ToolExecutionResult(success=False, error="STDIO connector has no command")
            env = dict(transport.env)
            if token:
                env[CREDENTIAL_ENV_VAR] = token
            return await self.stdio_executor.execute(
                connector_path=transport.command,
                tool_name=tool.tool_name,
                parameters=parameters,
                args=transport.args,
                env=env,
            )

        if kind in ("http", "sse"):
            if not transport.endpoint:
                return ToolExecutionResult(success=False, error=f"{kind} connector has no endpoint")
            return await self.http_executor.execute(
                connector_url=transport.endpoint.rstrip("/"),
                tool_name=tool.tool_name,
                parameters=parameters,
                headers={"Authorization": f"Bearer {token}"} if token else None,
            )

        return ToolExecutionResult(success=False, error=f"Unsupported transport type: {kind}")

    def _audit(
        self,
        org_id: str,
        user_id: str,
        connector: Connector,
        tool: ToolSchema,
        result: ToolExecutionResult,
        quota_cost: float,
    ) -> None:
        """写入审计; 审计失败只记日志, 不影响已完成的执行结果。"""
        try:
            self.audit_logger.log_tool_invocation(
                connector_id=connector.connector_id,
                tool_name=tool.tool_name,
                user_id=user_id,
                org_id=org_id,
                result="success" if result.success else "failed",
                execution_time_ms=result.execution_time_ms,
                quota_cost=quota_cost,
            )
        except Exception as exc:
            logger.error("Audit logging error: %s", type(exc).__name__)
