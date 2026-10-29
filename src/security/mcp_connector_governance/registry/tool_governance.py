"""Single-process definition admission. This is not a user/task invocation PDP."""

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from math import isfinite
from threading import BoundedSemaphore, Event, Thread
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from ..audit import AuditEventType, AuditLogger
from ..models import Connector, ConnectorLifecycleState, ToolSchema
from ..models.tool_schema import as_utc, canonical_digest

if TYPE_CHECKING:
    from .connector_registry import ConnectorRegistry
    from .tool_registry import ToolRegistry


class GovernanceError(ValueError):
    """Safe, stable management error; never includes provider/credential payloads."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ManifestSnapshot:
    org_id: str
    connector_id: str
    connector_revision: str
    manifest_digest: str
    generation: int
    complete: bool
    review_required: bool
    error_code: str | None


@dataclass(frozen=True)
class ToolGrant:
    org_id: str
    connector_id: str
    connector_revision: str
    tool_name: str
    definition_digest: str
    generation: int
    credential_generation: int
    approval_id: str
    actor: str
    approval_ref: str
    valid_until: datetime | None


@dataclass(frozen=True)
class ApprovalRequest:
    operation: str
    snapshot: ManifestSnapshot
    definitions: tuple[tuple[str, str], ...]
    actor: str
    approval_ref: str
    valid_until: datetime | None


@dataclass
class _Manifest:
    revision: str
    digest: str
    initialized: bool = False
    generation: int = 0
    complete: bool = True
    review_required: bool = False
    error_code: str | None = None
    grants: dict[str, ToolGrant] = field(default_factory=dict)
    approval_serial: int = 0


def connector_revision(connector: Connector) -> str:
    data = connector.config.to_dict()
    # Verification timestamps do not alter identity; signer/status/config do.
    data["signature"].pop("signed_at", None)
    return "connector-v1:" + canonical_digest(data)


class ToolGovernance:
    def __init__(
        self,
        tools: "ToolRegistry",
        connectors: "ConnectorRegistry",
        *,
        authorizer: Callable[[ApprovalRequest], bool] | None = None,
        audit_logger: AuditLogger | None = None,
        authorization_timeout: float = 1.0,
    ) -> None:
        if not isfinite(authorization_timeout) or authorization_timeout <= 0:
            raise ValueError("authorization_timeout must be finite and positive")
        self.tools, self.connectors = tools, connectors
        self.authorizer = authorizer
        self.audit_logger = audit_logger or AuditLogger()
        self.authorization_timeout = authorization_timeout
        self._slots = BoundedSemaphore(8)
        self._manifests: dict[tuple[str, str], _Manifest] = {}

    def _owned(self, org_id: str, connector_id: str) -> Connector:
        if not isinstance(org_id, str) or not isinstance(connector_id, str):
            raise GovernanceError("unavailable")
        connector = self.connectors.get(connector_id)
        if not org_id or connector is None or connector.config.identity.organization_id != org_id:
            raise GovernanceError("unavailable")
        return connector

    def _state(self, connector: Connector) -> _Manifest:
        key = (connector.config.identity.organization_id, connector.connector_id)
        if key not in self._manifests:
            definitions = self.tools._provider_tools.get(connector.connector_id, {})
            self._manifests[key] = _Manifest(
                connector_revision(connector),
                self._digest(definitions),
                bool(definitions),
            )
        return self._manifests[key]

    @staticmethod
    def _digest(definitions: dict[str, ToolSchema]) -> str:
        return canonical_digest(
            {name: tool.compute_definition_digest() for name, tool in definitions.items()}
        )

    def _snapshot(self, connector: Connector, state: _Manifest) -> ManifestSnapshot:
        return ManifestSnapshot(
            connector.config.identity.organization_id,
            connector.connector_id,
            state.revision,
            state.digest,
            state.generation,
            state.complete,
            state.review_required,
            state.error_code,
        )

    def _audit(
        self,
        connector: Connector,
        state: _Manifest,
        actor: str,
        action: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        try:
            self.audit_logger.log_event(
                event_type=AuditEventType.TOOL_APPROVED
                if action == "approve"
                else AuditEventType.SCHEMA_CHANGE_DETECTED,
                actor=actor,
                resource_type="connector",
                resource_id=connector.connector_id,
                action=action,
                result="success",
                org_id=connector.config.identity.organization_id,
                metadata={
                    "generation": state.generation,
                    "manifest_digest": state.digest,
                    "connector_revision": state.revision,
                    **(metadata or {}),
                },
            )
            return True
        except Exception:
            state.error_code = "audit_unavailable"
            return False

    def _invalidate(self, connector: Connector, state: _Manifest, actor: str) -> None:
        """Called with lifecycle_lock: block first, then start local credential cleanup."""
        from ..lifecycle.lifecycle_manager import LifecycleManager

        state.generation += 1
        state.review_required = True
        state.grants.clear()
        state.error_code = None
        if connector.status.is_callable():
            LifecycleManager(self.connectors, audit_logger=self.audit_logger).transition_to(
                connector.connector_id,
                ConnectorLifecycleState.PENDING_REVIEW,
                "Tool definition review required",
                actor,
                _defer_credential_cleanup=True,
            )
        self._audit(connector, state, actor, "invalidate")

    def _finish_cleanup(self, connector: Connector, actor: str) -> None:
        from ..lifecycle.lifecycle_manager import LifecycleManager

        LifecycleManager(self.connectors).complete_credential_invalidation(
            connector.connector_id,
            actor,
        )

    def snapshot(self, org_id: str, connector_id: str) -> ManifestSnapshot:
        with self.connectors.lifecycle_lock:
            connector = self._owned(org_id, connector_id)
            state = self._state(connector)
            revision = connector_revision(connector)
            changed = revision != state.revision
            if changed:
                self._invalidate(connector, state, "configuration_change")
                state.revision = revision
        if changed:
            self._finish_cleanup(connector, "configuration_change")
        with self.connectors.lifecycle_lock:
            return self._snapshot(connector, state)

    def _expected(self, expected: ManifestSnapshot) -> tuple[Connector, _Manifest]:
        if not isinstance(expected, ManifestSnapshot):
            raise GovernanceError("invalid_approval")
        connector = self._owned(expected.org_id, expected.connector_id)
        state = self._state(connector)
        if (
            self._snapshot(connector, state) != expected
            or connector_revision(connector) != state.revision
        ):
            raise GovernanceError("stale_snapshot")
        return connector, state

    def synchronize(
        self,
        org_id: str,
        connector_id: str,
        tools: list[ToolSchema],
        *,
        expected_generation: int,
        actor: str,
        complete: bool = True,
    ) -> ManifestSnapshot:
        self.snapshot(org_id, connector_id)
        invalid = False
        with self.connectors.lifecycle_lock:
            connector = self._owned(org_id, connector_id)
            state = self._state(connector)
            if state.generation != expected_generation:
                raise GovernanceError("stale_snapshot")
            if not isinstance(actor, str) or not actor.strip():
                raise GovernanceError("invalid_manifest")
            try:
                if not isinstance(tools, list):
                    raise ValueError("Manifest must be a list")
                definitions = {tool.tool_name: deepcopy(tool) for tool in tools}
                digest = self._digest(definitions)
                if complete is not True or len(definitions) != len(tools):
                    raise ValueError("Incomplete manifest")
            except (ValueError, TypeError, AttributeError, RecursionError):
                invalid = True
                if state.complete:
                    self._invalidate(connector, state, actor)
                state.complete = False
            else:
                if state.initialized and digest != state.digest:
                    self._invalidate(connector, state, actor)
                state.initialized = True
                state.complete = True
                state.digest = digest
                self.tools._replace_local(connector_id, definitions)
                if state.error_code and self._audit(connector, state, actor, "invalidation_retry"):
                    state.error_code = None
        # Revocation IO must never hold the lifecycle or credential-cache locks.
        self._finish_cleanup(connector, actor)
        if invalid:
            raise GovernanceError("invalid_manifest")
        return self.snapshot(org_id, connector_id)

    def mark_dirty(
        self,
        org_id: str,
        connector_id: str,
        *,
        expected_generation: int,
        actor: str,
    ) -> ManifestSnapshot:
        if not isinstance(actor, str) or not actor.strip():
            raise GovernanceError("invalid_manifest")
        try:
            self.synchronize(
                org_id,
                connector_id,
                [],
                expected_generation=expected_generation,
                actor=actor,
                complete=False,
            )
        except GovernanceError as exc:
            if exc.code != "invalid_manifest":
                raise
        return self.snapshot(org_id, connector_id)

    def upsert(self, connector_id: str, tools: list[ToolSchema]) -> None:
        connector = self.connectors.get(connector_id)
        if connector is None:
            raise GovernanceError("unavailable")
        snapshot = self.snapshot(connector.config.identity.organization_id, connector_id)
        with self.connectors.lifecycle_lock:
            definitions = deepcopy(self.tools._provider_tools.get(connector_id, {}))
            # Duplicate names in one batch are ambiguous, even if the last one looks valid.
            try:
                unique = len({tool.tool_name for tool in tools}) == len(tools)
            except (AttributeError, TypeError):
                unique = False
            if unique:
                definitions.update({tool.tool_name: tool for tool in tools})
                tools = list(definitions.values())
        self.synchronize(
            snapshot.org_id,
            connector_id,
            tools,
            expected_generation=snapshot.generation,
            actor="registry",
        )

    def _authorize(self, request: ApprovalRequest) -> None:
        if (
            not isinstance(request.actor, str)
            or not request.actor.strip()
            or not isinstance(request.approval_ref, str)
            or not request.approval_ref.strip()
            or self.authorizer is None
            or not self._slots.acquire(blocking=False)
        ):
            raise GovernanceError("authorization_denied")
        done = Event()
        accepted: list[bool] = []
        authorizer = self.authorizer

        def run() -> None:
            try:
                accepted.append(authorizer(request) is True)
            except Exception:
                accepted.append(False)
            finally:
                self._slots.release()
                done.set()

        try:
            Thread(target=run, daemon=True, name="mcp-definition-approval").start()
        except RuntimeError:
            self._slots.release()
            raise GovernanceError("authorization_denied") from None
        if not done.wait(self.authorization_timeout) or not accepted[0]:
            raise GovernanceError("authorization_denied")

    def approve(
        self,
        snapshot: ManifestSnapshot,
        tool_name: str,
        definition_digest: str,
        *,
        actor: str,
        approval_ref: str,
        valid_until: datetime | None = None,
    ) -> ToolGrant:
        if (
            not isinstance(tool_name, str)
            or not tool_name.strip()
            or not isinstance(definition_digest, str)
            or not definition_digest
        ):
            raise GovernanceError("invalid_approval")
        if valid_until is not None and not isinstance(valid_until, datetime):
            raise GovernanceError("invalid_approval")
        expiry = as_utc(valid_until) if valid_until is not None else None
        with self.connectors.lifecycle_lock:
            connector, state = self._expected(snapshot)
            serial = state.approval_serial
            credential_generation = connector.status.credential_generation
        request = ApprovalRequest(
            "approve", snapshot, ((tool_name, definition_digest),), actor, approval_ref, expiry
        )
        self._authorize(request)
        with self.connectors.lifecycle_lock:
            connector, state = self._expected(snapshot)
            if (
                serial != state.approval_serial
                or credential_generation != connector.status.credential_generation
            ):
                raise GovernanceError("stale_snapshot")
            tool = self.tools.get_tool_for_connector(snapshot.connector_id, tool_name)
            if (
                not state.complete
                or state.error_code
                or tool is None
                or tool.compute_definition_digest() != definition_digest
                or (expiry is not None and datetime.now(UTC) >= expiry)
            ):
                raise GovernanceError("invalid_approval")
            grant = ToolGrant(
                snapshot.org_id,
                snapshot.connector_id,
                state.revision,
                tool_name,
                definition_digest,
                state.generation,
                connector.status.credential_generation,
                uuid4().hex,
                actor,
                approval_ref,
                expiry,
            )
            if not self._audit(
                connector,
                state,
                actor,
                "approve",
                {
                    "approval_id": grant.approval_id,
                    "tool_name": tool_name,
                    "definition_digest": definition_digest,
                    "approval_ref": approval_ref,
                },
            ):
                raise GovernanceError("audit_unavailable")
            self._expected(snapshot)
            state.grants[tool_name] = grant
            state.approval_serial += 1
            return grant

    def _grant(self, connector: Connector, state: _Manifest, tool_name: str) -> ToolGrant | None:
        grant = state.grants.get(tool_name)
        if (
            grant is None
            or not state.complete
            or state.error_code
            or grant.generation != state.generation
            or grant.connector_revision != state.revision
            or (grant.valid_until is not None and datetime.now(UTC) >= grant.valid_until)
        ):
            return None
        return grant

    def get_grant(self, org_id: str, connector_id: str, tool_name: str) -> ToolGrant | None:
        self.snapshot(org_id, connector_id)
        if not isinstance(tool_name, str) or not tool_name.strip():
            return None
        with self.connectors.lifecycle_lock:
            connector = self._owned(org_id, connector_id)
            return self._grant(connector, self._state(connector), tool_name)

    def revoke(self, org_id: str, connector_id: str, tool_name: str, *, actor: str) -> None:
        if (
            not isinstance(actor, str)
            or not actor.strip()
            or not isinstance(tool_name, str)
            or not tool_name.strip()
        ):
            raise GovernanceError("invalid_approval")
        with self.connectors.lifecycle_lock:
            connector = self._owned(org_id, connector_id)
            state = self._state(connector)
            old = state.grants.pop(tool_name, None)
            state.approval_serial += 1
            if not self._audit(
                connector,
                state,
                actor,
                "revoke",
                {
                    "tool_name": tool_name,
                    "approval_id": old.approval_id if old else None,
                },
            ):
                raise GovernanceError("audit_unavailable")

    def complete_review(
        self,
        snapshot: ManifestSnapshot,
        selected_tools: list[str],
        *,
        actor: str,
        approval_ref: str,
    ) -> ManifestSnapshot:
        if not isinstance(selected_tools, list) or any(
            not isinstance(name, str) or not name.strip() for name in selected_tools
        ):
            raise GovernanceError("invalid_approval")
        with self.connectors.lifecycle_lock:
            connector, state = self._expected(snapshot)
            selected = tuple(sorted(set(selected_tools)))
            grants = [self._grant(connector, state, name) for name in selected]
            if not state.complete or state.error_code or any(grant is None for grant in grants):
                raise GovernanceError("invalid_approval")
            definitions = tuple(
                (grant.tool_name, grant.definition_digest) for grant in grants if grant is not None
            )
        self._authorize(
            ApprovalRequest("complete_review", snapshot, definitions, actor, approval_ref, None)
        )
        with self.connectors.lifecycle_lock:
            connector, state = self._expected(snapshot)
            if any(
                self._grant(connector, state, name) != grant
                for name, grant in zip(selected, grants, strict=True)
            ):
                raise GovernanceError("stale_snapshot")
            if not self._audit(
                connector,
                state,
                actor,
                "complete_review",
                {
                    "selected_tools": list(selected),
                    "approval_ref": approval_ref,
                },
            ):
                raise GovernanceError("audit_unavailable")
            self._expected(snapshot)
            state.grants = {name: state.grants[name] for name in selected}
            state.approval_serial += 1
            state.review_required = False
            return self._snapshot(connector, state)

    def can_activate(self, connector: Connector) -> bool:
        """Pure local check: callers may already hold lifecycle_lock."""
        state = self._state(connector)
        return (
            state.complete
            and not state.review_required
            and not state.error_code
            and state.revision == connector_revision(connector)
        )

    def check_call(self, org_id: str, connector: Connector, tool: ToolSchema) -> ToolGrant | None:
        try:
            self.snapshot(org_id, connector.connector_id)
            with self.connectors.lifecycle_lock:
                current = self._owned(org_id, connector.connector_id)
                state = self._state(current)
                registered = self.tools.get_tool_for_connector(current.connector_id, tool.tool_name)
                if (
                    current is not connector
                    or not current.status.is_callable()
                    or not self.can_activate(current)
                    or registered is None
                    or registered.compute_definition_digest() != tool.compute_definition_digest()
                ):
                    return None
                grant = self._grant(current, state, tool.tool_name)
                if grant is None or grant.definition_digest != tool.compute_definition_digest():
                    return None
                return grant
        except (GovernanceError, ValueError, TypeError):
            return None

    def revalidate(self, grant: ToolGrant, connector: Connector, tool: ToolSchema) -> bool:
        return self.check_call(grant.org_id, connector, tool) == grant

    def replace_connector(self, connector: Connector) -> None:
        """Retain stopped state/fences when replacing configuration under the same ID."""
        with self.connectors.lifecycle_lock:
            old = self.connectors.get(connector.connector_id)
            if old is None:
                raise GovernanceError("unavailable")
            if old.config.identity.organization_id != connector.config.identity.organization_id:
                raise GovernanceError("unavailable")
            state = self._state(old)
            self._invalidate(old, state, "registry")
            connector.status = deepcopy(old.status)
            state.revision = connector_revision(connector)
            self.connectors._register_local(connector)
        self._finish_cleanup(connector, "registry")

    def remove_connector(self, connector_id: str) -> None:
        with self.connectors.lifecycle_lock:
            connector = self.connectors.get(connector_id)
            if connector is None:
                return
            state = self._state(connector)
            self._invalidate(connector, state, "registry")
            state.complete = False
            self.tools._replace_local(connector_id, {})
        self._finish_cleanup(connector, "registry")
        with self.connectors.lifecycle_lock:
            if self.connectors.get(connector_id) is connector:
                self.connectors._remove_local(connector_id)
