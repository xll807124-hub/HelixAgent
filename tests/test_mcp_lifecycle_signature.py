"""SEC-007 AC1/AC5: 注册表签名验证委托真实验证器 + 生命周期签名闸门（fail-closed）"""

import base64
from datetime import UTC, datetime, timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from src.security.mcp_connector_governance.lifecycle import LifecycleManager
from src.security.mcp_connector_governance.models import (
    AuthConfig,
    AuthenticationMode,
    Connector,
    ConnectorConfig,
    ConnectorIdentity,
    ConnectorLifecycleState,
    ConnectorStatus,
    SignatureVerification,
    TransportConfig,
    TransportType,
    TrustLevel,
)
from src.security.mcp_connector_governance.registry import ConnectorRegistry
from src.security.mcp_connector_governance.registry.signature_verifier import (
    SignatureVerifier,
    check_signature_gate,
    connector_signing_payload,
)
from src.security.mcp_connector_governance.security import UnifiedSignatureVerifier

S = ConnectorLifecycleState


def _name(cn):
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _cert(subject, issuer, key, signer_key, ca):
    now = datetime.now(UTC)
    return (
        x509.CertificateBuilder()
        .subject_name(_name(subject))
        .issuer_name(_name(issuer))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(hours=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
        .sign(signer_key, hashes.SHA256())
    )


def _pem(cert):
    return cert.public_bytes(serialization.Encoding.PEM).decode()


@pytest.fixture
def pki():
    root_key = ec.generate_private_key(ec.SECP256R1())
    leaf_key = ec.generate_private_key(ec.SECP256R1())
    root = _cert("Root", "Root", root_key, root_key, True)
    leaf = _cert("leaf", "Root", leaf_key, root_key, False)
    return {"leaf_key": leaf_key, "root": root, "leaf": leaf}


@pytest.fixture
def verifier(pki):
    unified = UnifiedSignatureVerifier()
    unified.internal_pki.set_root_ca(_pem(pki["root"]))
    unified.internal_pki.register_certificate("c1", _pem(pki["leaf"]))
    return SignatureVerifier(unified)


def _sig_info(pki, payload: bytes, cert_id="c1") -> dict:
    sig = pki["leaf_key"].sign(payload, ec.ECDSA(hashes.SHA256()))
    return {
        "algorithm": "internal-pki",
        "signature": base64.b64encode(sig).decode(),
        "certificate_id": cert_id,
    }


def _connector(trust=TrustLevel.L2_ORG_VERIFIED, state=S.PENDING_APPROVAL, cid="conn_1"):
    config = ConnectorConfig(
        identity=ConnectorIdentity(
            connector_id=cid,
            organization_id="org_1",
            namespace="ns",
            display_name="Test",
            version="1.0.0",
        ),
        trust_level=trust,
        transport=TransportConfig(type=TransportType.HTTP, endpoint="https://c.example.com"),
        auth=AuthConfig(mode=AuthenticationMode.NONE),
        signature=SignatureVerification(is_signed=False),
    )
    return Connector(config=config, status=ConnectorStatus(connector_id=cid, lifecycle_state=state))


async def _sign(connector, verifier, pki):
    payload = connector_signing_payload(connector)
    connector.config.signature = await verifier.verify(payload, _sig_info(pki, payload))


def _manager(connector):
    registry = ConnectorRegistry()
    registry.register(connector)
    return LifecycleManager(registry)


class TestRegistrySignatureVerifier:
    @pytest.mark.asyncio
    async def test_valid_signature(self, verifier, pki):
        payload = b"config-v1"
        result = await verifier.verify(payload, _sig_info(pki, payload))
        assert result.verification_status == "valid"
        assert result.is_valid() is True
        assert result.signature_format == "internal-pki"

    @pytest.mark.asyncio
    async def test_legacy_format_key_and_underscore_name(self, verifier, pki):
        payload = b"config-v1"
        info = _sig_info(pki, payload)
        info.pop("algorithm")
        info["format"] = "internal_pki"
        assert (await verifier.verify(payload, info)).is_valid() is True

    @pytest.mark.asyncio
    async def test_str_content_accepted(self, verifier, pki):
        info = _sig_info(pki, b"text-content")
        assert (await verifier.verify("text-content", info)).is_valid() is True

    @pytest.mark.asyncio
    async def test_tampered_content_rejected(self, verifier, pki):
        info = _sig_info(pki, b"original")
        assert (await verifier.verify(b"tampered", info)).is_valid() is False

    @pytest.mark.asyncio
    async def test_default_verifier_has_no_trust_roots(self, pki):
        payload = b"x"
        result = await SignatureVerifier().verify(payload, _sig_info(pki, payload))
        assert result.is_valid() is False
        assert result.verification_status == "invalid"

    @pytest.mark.asyncio
    async def test_trusted_signer_name_alone_is_not_enough(self, verifier):
        # 旧实现只要身份在白名单里就判 valid；现在必须有密码学证明
        info = {"algorithm": "internal-pki", "signature": base64.b64encode(b"junk").decode(),
                "certificate_id": "c1"}
        assert (await verifier.verify(b"x", info)).is_valid() is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad", [None, "str", 5, [], {}, {"algorithm": "rot13"}])
    async def test_malformed_signature_data(self, verifier, bad):
        assert (await verifier.verify(b"x", bad)).is_valid() is False

    @pytest.mark.asyncio
    async def test_unknown_certificate_id(self, verifier, pki):
        info = _sig_info(pki, b"x", cert_id="nope")
        assert (await verifier.verify(b"x", info)).is_valid() is False


class TestLifecycleSignatureGate:
    def test_unsigned_l2_cannot_become_approved(self):
        conn = _connector()
        mgr = _manager(conn)
        assert mgr.transition_to("conn_1", S.APPROVED_INACTIVE, "approve") is False
        assert conn.lifecycle_state == S.PENDING_APPROVAL

    @pytest.mark.asyncio
    async def test_signed_l2_can_become_approved_and_active(self, verifier, pki):
        conn = _connector()
        await _sign(conn, verifier, pki)
        mgr = _manager(conn)
        assert mgr.transition_to("conn_1", S.APPROVED_INACTIVE, "approve") is True
        assert mgr.activate("conn_1", "admin") is True
        assert conn.lifecycle_state == S.ACTIVE

    @pytest.mark.asyncio
    async def test_invalid_signature_blocks(self, verifier, pki):
        conn = _connector()
        payload = connector_signing_payload(conn)
        conn.config.signature = await verifier.verify(payload, _sig_info(pki, b"other"))
        mgr = _manager(conn)
        assert mgr.transition_to("conn_1", S.APPROVED_INACTIVE, "approve") is False

    @pytest.mark.asyncio
    async def test_config_changed_after_signing_blocks(self, verifier, pki):
        conn = _connector()
        await _sign(conn, verifier, pki)
        conn.config.description = "changed after signing"
        mgr = _manager(conn)
        assert mgr.transition_to("conn_1", S.APPROVED_INACTIVE, "approve") is False
        assert "changed" in check_signature_gate(conn)

    @pytest.mark.asyncio
    async def test_resume_from_paused_requires_signature_still_valid(self, verifier, pki):
        conn = _connector(state=S.ACTIVE)
        await _sign(conn, verifier, pki)
        mgr = _manager(conn)
        assert mgr.pause("conn_1", "maintenance", "admin") is True
        conn.config.description = "tampered while paused"
        assert mgr.resume("conn_1", "admin") is False
        assert conn.lifecycle_state == S.PAUSED

    def test_l3_does_not_require_signature(self):
        conn = _connector(trust=TrustLevel.L3_RESTRICTED_CONDITIONAL)
        mgr = _manager(conn)
        assert mgr.transition_to("conn_1", S.APPROVED_INACTIVE, "approve") is True

    def test_blocking_transitions_never_gated(self):
        conn = _connector(state=S.ACTIVE)  # 未签名的 L2
        mgr = _manager(conn)
        assert mgr.revoke("conn_1", "incident", "sec") is True
        assert conn.lifecycle_state == S.REVOKED

    def test_blocked_attempt_is_audited(self):
        conn = _connector()
        mgr = _manager(conn)
        mgr.transition_to("conn_1", S.APPROVED_INACTIVE, "approve", triggered_by="admin")
        history = mgr.get_transition_history("conn_1")
        assert history[-1]["reason"].startswith("Blocked by signature gate")
        assert history[-1]["old_state"] == history[-1]["new_state"] == S.PENDING_APPROVAL.value
