"""
Signature Verifier (registry facade)

Cryptographic signature verification for MCP connectors.

This module is a thin adapter over ``security.signature_verifier``
(``UnifiedSignatureVerifier``), which performs the real checks:
- Sigstore OIDC keyless (certificate chain to configured Fulcio roots + signature)
- GPG (trusted keys + gpg binary)
- Internal platform PKI (root CA + registered certificates)

Everything fails closed: missing trust roots, malformed input or any
verification error yields an invalid result. No identity allow-list is
treated as proof of a valid signature.

It also hosts the connector signing payload and the signature gate shared by
the lifecycle manager and the tool executor, so both apply the same rule.
"""

import hashlib
import json
import logging
from datetime import datetime
from typing import Any

from ..models import Connector, SignatureVerification, get_trust_level_config
from ..security.signature_verifier import UnifiedSignatureVerifier

logger = logging.getLogger(__name__)


def connector_signing_payload(connector: Connector) -> bytes:
    """连接器被签名的内容: 配置的规范化 JSON (不含 signature 字段)。"""
    data = connector.config.to_dict()
    data.pop("signature", None)
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


def check_signature_gate(connector: Connector) -> str | None:
    """
    需要签名的信任等级必须有有效且与当前配置一致的签名。

    Returns:
        拒绝原因；None 表示通过（或该信任等级不要求签名）。
    """
    trust = get_trust_level_config(connector.trust_level)
    if not trust.requires_signature:
        return None
    sig = connector.config.signature
    if not sig.is_valid():
        return (
            f"{connector.trust_level.name} connector requires a valid signature "
            f"(status: {sig.verification_status})"
        )
    current = hashlib.sha256(connector_signing_payload(connector)).hexdigest()
    if sig.signature_digest != current:
        return "Connector config changed after signature verification"
    return None


class SignatureVerifier:
    """
    Verifies cryptographic signatures for MCP connectors.

    Delegates to ``UnifiedSignatureVerifier``; configure trust material
    (Fulcio roots, GPG keys, internal root CA) on the wrapped verifier.
    """

    def __init__(self, verifier: UnifiedSignatureVerifier | None = None) -> None:
        """
        Args:
            verifier: Real verifier holding the trust material. A default
                instance has no trusted roots, so every check fails closed.
        """
        self.verifier = verifier or UnifiedSignatureVerifier()

    async def verify(
        self,
        content: str | bytes,
        signature_data: dict[str, Any],
    ) -> SignatureVerification:
        """
        Verify signature for given content.

        Args:
            content: Signed content (canonical connector config, see
                ``connector_signing_payload``)
            signature_data: Signature metadata. ``algorithm`` (or legacy
                ``format``) selects the verifier: sigstore-oidc, gpg or
                internal-pki; ``signature`` is base64.

        Returns:
            SignatureVerification result (``verification_status`` is "valid"
            only when the cryptographic check passed)
        """
        payload = content.encode("utf-8") if isinstance(content, str) else content
        if not isinstance(signature_data, dict):
            return SignatureVerification(
                is_signed=False, verification_status="invalid"
            )

        algorithm = signature_data.get("algorithm") or signature_data.get("format")
        info = dict(signature_data)
        if isinstance(algorithm, str):
            # 兼容旧写法 sigstore_oidc / internal_pki
            info["algorithm"] = algorithm.replace("_", "-")

        result = await self.verifier.verify(payload, info)
        if not result.is_valid:
            logger.warning(
                "Signature verification failed (%s): %s", result.algorithm, result.error
            )
        return SignatureVerification(
            is_signed=True,
            signature_format=result.algorithm,
            signer_identity=result.signer_identity,
            signed_at=datetime.utcnow() if result.is_valid else None,
            verification_status="valid" if result.is_valid else "invalid",
            signature_digest=hashlib.sha256(payload).hexdigest(),
        )


def compute_content_hash(content: dict[str, Any]) -> str:
    """
    Compute canonical hash of connector content.

    Used for signing and verification.

    Args:
        content: Connector configuration dictionary

    Returns:
        SHA256 hex digest
    """
    canonical_json = json.dumps(content, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical_json.encode()).hexdigest()
