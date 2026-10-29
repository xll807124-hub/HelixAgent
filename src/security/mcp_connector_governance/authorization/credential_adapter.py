"""
SEC-005 Credential Proxy adapter

把 SEC-005 的 PDP/CDP 适配成 ``AuthorizationManager`` 需要的
``CredentialProxyClient.issue_short_lived_credential`` 接口。

设计要点（均为 fail-closed）：
- 授权决策（Policy Gateway / RBAC）必须由调用方通过 ``approval_provider`` 提供；
  适配器自己绝不放行。provider 抛异常或返回非预期结果一律拒绝。
- PDP 拒绝、CDP 不健康、CDP 未返回令牌内容（Model A 代理模式）都抛异常，
  由 ``AuthorizationManager`` 统一转换为"无凭据"。
- 请求 TTL 不超过适配器配置的上限，CDP 还会再按服务类型取更小值。
- 令牌内容只出现在返回值里，不写日志。
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from threading import Event, RLock, Thread
from typing import Any

from ...credential import (
    CapabilityTokenRequest,
    CredentialCDP,
    CredentialPDP,
)

logger = logging.getLogger(__name__)


class CredentialIssuanceError(RuntimeError):
    """SEC-005 未能签发凭据。消息不包含任何凭据内容。"""


@dataclass(frozen=True)
class ApprovalDecision:
    """调用方对一次凭据请求给出的授权结论。"""

    policy_gateway_approved: bool
    rbac_approved: bool
    rbac_scope: list[str] = field(default_factory=list)
    policy_approval_ref: str = ""


# (key_ref, connector_id, org_id) -> ApprovalDecision
ApprovalProvider = Callable[[str, str, str], ApprovalDecision]


class SEC005CredentialProxyClient:
    """Adapter: AuthorizationManager -> SEC-005 PDP/CDP."""

    def __init__(
        self,
        pdp: CredentialPDP,
        cdp: CredentialCDP,
        approval_provider: ApprovalProvider,
        *,
        agent_svid: str,
        worker_id: str,
        task_id: str = "mcp-connector-governance",
        target_service: str = "generic_oauth",
        requested_action: str = "invoke",
        requested_scope: list[str] | None = None,
        max_ttl_seconds: int = 900,
        revoke_timeout_seconds: float = 1.0,
        retry_delay_seconds: float = 0.05,
    ) -> None:
        """
        Args:
            pdp: SEC-005 策略决策点
            cdp: SEC-005 凭据传递点
            approval_provider: 返回 Policy Gateway / RBAC 结论，必填
            agent_svid: 本组件在 SPIRE 中的身份（SPIFFE ID）
            worker_id: 关联的 Worker ID
            task_id: 审计关联的任务 ID
            target_service: CDP 服务类型，决定默认 TTL 与令牌类型
            requested_action: 申请的操作类型
            requested_scope: 申请的作用域，默认只含 requested_action
            max_ttl_seconds: 适配器允许的最大 TTL
        """
        if not callable(approval_provider):
            raise TypeError("approval_provider is required")
        if not agent_svid or not worker_id:
            raise ValueError("agent_svid and worker_id are required")
        if max_ttl_seconds <= 0:
            raise ValueError("max_ttl_seconds must be positive")
        self._pdp = pdp
        self._cdp = cdp
        self._approval_provider = approval_provider
        self._agent_svid = agent_svid
        self._worker_id = worker_id
        self._task_id = task_id
        self._target_service = target_service
        self._requested_action = requested_action
        self._requested_scope = list(requested_scope or [requested_action])
        self._max_ttl_seconds = max_ttl_seconds
        if (not math.isfinite(revoke_timeout_seconds) or revoke_timeout_seconds <= 0
                or not math.isfinite(retry_delay_seconds) or retry_delay_seconds < 0):
            raise ValueError("Invalid revocation timeout/backoff")
        self._revoke_timeout = revoke_timeout_seconds
        self._retry_delay = retry_delay_seconds
        self._lock = RLock()
        self._leases: dict[tuple[str, str], set[str]] = {}
        self._blocked: set[tuple[str, str]] = set()
        self._issuing: dict[tuple[str, str], int] = {}
        self._jobs: dict[str, Event] = {}

    @staticmethod
    def _scope(connector_id: str, org_id: str) -> tuple[str, str]:
        if (not isinstance(connector_id, str) or not connector_id
                or not isinstance(org_id, str) or not org_id):
            raise ValueError("Connector and organization are required")
        return org_id, connector_id

    def issue_short_lived_credential(
        self, *, key_ref: str, connector_id: str, org_id: str, ttl_seconds: int,
    ) -> dict[str, Any]:
        try:
            scope = self._scope(connector_id, org_id)
        except ValueError:
            raise CredentialIssuanceError("Connector and organization are required") from None
        with self._lock:
            if scope in self._blocked:
                raise CredentialIssuanceError("Connector credentials are invalidated")
            self._issuing[scope] = self._issuing.get(scope, 0) + 1
        try:
            result = self._issue_short_lived_credential(
                key_ref=key_ref, connector_id=connector_id, org_id=org_id,
                ttl_seconds=ttl_seconds,
            )
        finally:
            with self._lock:
                self._issuing[scope] -= 1
                stale = scope in self._blocked
            # A late issue is registered before this cleanup; its handle cannot be lost.
            if stale:
                self.revoke_connector_credentials(connector_id, org_id, "late issuance")
        if stale:
            raise CredentialIssuanceError("Credential issuance was invalidated")
        return result

    def get_revocation_status(self, connector_id: str, org_id: str) -> dict[str, Any]:
        scope = self._scope(connector_id, org_id)
        with self._lock:
            pending = len(self._leases.get(scope, set())) + self._issuing.get(scope, 0)
        return {"credential_revocation_status": "partial" if pending else "complete",
                "pending_count": pending, "retryable": bool(pending)}

    def resume_connector_credentials(self, connector_id: str, org_id: str) -> bool:
        scope = self._scope(connector_id, org_id)
        with self._lock:
            if self._leases.get(scope) or self._issuing.get(scope, 0):
                return False
            self._blocked.discard(scope)
            return True

    def revoke_connector_credentials(
        self, connector_id: str, org_id: str, reason: str,
    ) -> dict[str, Any]:
        scope = self._scope(connector_id, org_id)
        with self._lock:
            self._blocked.add(scope)
            handles = list(self._leases.get(scope, set()))
        for token_id in handles:
            self._revoke_handle(scope, token_id)
        return self.get_revocation_status(connector_id, org_id)

    def _revoke_handle(self, scope: tuple[str, str], token_id: str) -> None:
        # Never launch another worker for a timed-out call that is still running.
        # Daemon workers bound caller latency; their handles remain pending until ACK.
        for attempt in range(4):
            with self._lock:
                if token_id not in self._leases.get(scope, set()):
                    return
                event = self._jobs.get(token_id)
                if event is None:
                    if len(self._jobs) >= 8:
                        return  # Bounded work; caller receives partial and can retry.
                    event = Event()
                    self._jobs[token_id] = event
                    Thread(target=self._revoke_worker, args=(scope, token_id, event),
                           daemon=True).start()
            event.wait(self._revoke_timeout)
            if attempt < 3:
                time.sleep(self._retry_delay * (2 ** attempt))

    def _revoke_worker(self, scope: tuple[str, str], token_id: str, event: Event) -> None:
        try:
            self._cdp.revoke_token(token_id, reason="MCP credential invalidation")
            self._pdp.revoke_token(token_id, self._task_id, reason="MCP credential invalidation")
        except Exception as exc:
            logger.error("Credential revocation failed: %s", type(exc).__name__)
        else:
            with self._lock:
                self._leases[scope].discard(token_id)
        finally:
            with self._lock:
                self._jobs.pop(token_id, None)
                event.set()

    def _issue_short_lived_credential(
        self,
        *,
        key_ref: str,
        connector_id: str,
        org_id: str,
        ttl_seconds: int,
    ) -> dict[str, Any]:
        """
        签发短期派生凭据。

        Returns:
            {"token": str, "expires_at": datetime}

        Raises:
            CredentialIssuanceError: 任何导致无法安全签发的情形
        """
        if not key_ref or not connector_id or not org_id:
            raise CredentialIssuanceError("key_ref, connector_id and org_id are required")
        if ttl_seconds <= 0:
            raise CredentialIssuanceError("ttl_seconds must be positive")

        try:
            decision = self._approval_provider(key_ref, connector_id, org_id)
        except Exception as exc:
            raise CredentialIssuanceError(
                f"approval provider failed: {type(exc).__name__}"
            ) from None
        if not isinstance(decision, ApprovalDecision):
            raise CredentialIssuanceError("approval provider returned invalid decision")
        if not decision.policy_approval_ref:
            # CDP 请求必须引用 SEC-003 的审批记录，没有引用就不能签发
            raise CredentialIssuanceError("missing policy approval reference")

        request = CapabilityTokenRequest(
            agent_svid=self._agent_svid,
            task_id=self._task_id,
            worker_id=self._worker_id,
            target_service=self._target_service,
            target_resource=key_ref,
            requested_action=self._requested_action,
            requested_scope=self._requested_scope,
            policy_approval_ref=decision.policy_approval_ref,
            max_ttl_seconds=min(ttl_seconds, self._max_ttl_seconds),
            justification=f"MCP connector {connector_id} (org {org_id})",
        )

        approval = self._pdp.verify_and_approve(
            request,
            policy_gateway_result=decision.policy_gateway_approved,
            rbac_result=decision.rbac_approved,
            rbac_scope=decision.rbac_scope,
        )
        if not approval[0]:
            raise CredentialIssuanceError(f"PDP rejected: {approval[1]}")

        try:
            response = self._cdp.issue_token(
                request,
                approval,
                requested_ttl_seconds=min(ttl_seconds, self._max_ttl_seconds),
            )
        except Exception as exc:
            raise CredentialIssuanceError(f"CDP failed: {type(exc).__name__}") from None

        scope = self._scope(connector_id, org_id)
        with self._lock:
            self._leases.setdefault(scope, set()).add(response.token_id)
        if not response.issued_token:
            # Model A（代理模式）不下发令牌内容，这里无法使用
            self._revoke_handle(scope, response.token_id)
            raise CredentialIssuanceError("CDP returned no token content")
        if not isinstance(response.expires_at, datetime):
            self._revoke_handle(scope, response.token_id)
            raise CredentialIssuanceError("CDP returned invalid expiry")

        return {"token": response.issued_token, "expires_at": response.expires_at}

