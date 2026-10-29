"""
Signature Verification
签名验证 - Sigstore OIDC、GPG、内部 PKI

All verifiers fail closed: if trust material is missing or a check cannot be
performed, the result is invalid.
"""

import base64
import binascii
import logging
import shutil
import subprocess
import tempfile
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509 import Certificate

from .crypto_utils import (
    VerificationError,
    cert_identity,
    load_chain,
    verify_chain,
    verify_signature_with_cert,
)

logger = logging.getLogger(__name__)

# Async callable: (artifact_bytes, entry_uuid) -> bool. Supplied by the caller
# so the verifier never makes network calls on its own.
RekorLookup = Callable[[bytes, str], Awaitable[bool]]


class SignatureAlgorithm(Enum):
    """签名算法"""

    SIGSTORE_OIDC = "sigstore-oidc"
    GPG = "gpg"
    INTERNAL_PKI = "internal-pki"
    ED25519 = "ed25519"


class VerificationResult:
    """签名验证结果"""

    def __init__(
        self,
        is_valid: bool,
        algorithm: str,
        signer_identity: str | None = None,
        verified_at: datetime | None = None,
        certificate_chain: list | None = None,
        error: str | None = None,
    ) -> None:
        self.is_valid = is_valid
        self.algorithm = algorithm
        self.signer_identity = signer_identity
        self.verified_at = verified_at
        self.certificate_chain = certificate_chain or []
        self.error = error

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "algorithm": self.algorithm,
            "signer_identity": self.signer_identity,
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
            "certificate_count": len(self.certificate_chain),
            "error": self.error,
        }


def _ok(
    algorithm: SignatureAlgorithm, identity: str, chain: list | None = None
) -> VerificationResult:
    return VerificationResult(
        is_valid=True,
        algorithm=algorithm.value,
        signer_identity=identity,
        verified_at=datetime.now(UTC),
        certificate_chain=chain,
    )


def _fail(algorithm: SignatureAlgorithm, error: str) -> VerificationResult:
    return VerificationResult(is_valid=False, algorithm=algorithm.value, error=error)


class SigstoreVerifier:
    """
    Sigstore keyless verification.

    Checks: leaf/chain validity -> chain to a configured Fulcio root ->
    artifact signature -> optional Rekor lookup (caller-supplied).
    Without trusted roots every verification fails.
    """

    def __init__(
        self,
        rekor_url: str = "https://rekor.sigstore.dev",
        trusted_roots_pem: list[str] | None = None,
        rekor_lookup: RekorLookup | None = None,
        require_rekor: bool = False,
    ) -> None:
        self.rekor_url = rekor_url
        self.rekor_lookup = rekor_lookup
        self.require_rekor = require_rekor
        self._roots: list[Certificate] = []
        for pem in trusted_roots_pem or []:
            self.add_trusted_root(pem)

    def add_trusted_root(self, pem: str) -> None:
        self._roots.extend(load_chain(pem))

    async def verify_signature(
        self,
        artifact_bytes: bytes,
        signature: bytes,
        certificate_pem: str,
        entry_uuid: str | None = None,
    ) -> VerificationResult:
        alg = SignatureAlgorithm.SIGSTORE_OIDC
        try:
            chain = load_chain(certificate_pem)
            verify_chain(chain, self._roots)
            verify_signature_with_cert(chain[0], artifact_bytes, signature)
        except VerificationError as exc:
            return _fail(alg, str(exc))
        except Exception as exc:  # fail closed on anything unexpected
            logger.error("Sigstore verification error: %s", exc, exc_info=True)
            return _fail(alg, f"Verification error: {exc}")

        if entry_uuid or self.require_rekor:
            if not entry_uuid:
                return _fail(alg, "Rekor entry required but not provided")
            if self.rekor_lookup is None:
                return _fail(alg, "Rekor lookup not configured")
            try:
                if not await self.rekor_lookup(artifact_bytes, entry_uuid):
                    return _fail(alg, f"Rekor entry not verified: {entry_uuid}")
            except Exception as exc:
                return _fail(alg, f"Rekor lookup failed: {exc}")

        return _ok(
            alg,
            cert_identity(chain[0]),
            [c.public_bytes(_PEM()).decode() for c in chain],
        )


def _PEM() -> Encoding:
    return Encoding.PEM


class GPGVerifier:
    """
    GPG detached-signature verification via the `gpg` binary.

    Uses a throwaway GNUPGHOME per call containing only the trusted key, and
    requires a VALIDSIG status line for the expected fingerprint. If `gpg` is
    not installed, verification fails.
    """

    def __init__(self, gpg_binary: str | None = None, timeout_seconds: int = 15) -> None:
        self.gpg_binary = gpg_binary or shutil.which("gpg")
        self.timeout_seconds = timeout_seconds
        self.trusted_keys: dict[str, str] = {}  # fingerprint -> armored key

    def add_trusted_key(self, fingerprint: str, key_data: str) -> None:
        self.trusted_keys[fingerprint.replace(" ", "").upper()] = key_data
        logger.info("Added trusted GPG key: %s", fingerprint)

    async def verify_signature(
        self,
        artifact_bytes: bytes,
        signature_bytes: bytes,
        signer_fingerprint: str,
    ) -> VerificationResult:
        import asyncio

        alg = SignatureAlgorithm.GPG
        fpr = signer_fingerprint.replace(" ", "").upper()
        key = self.trusted_keys.get(fpr)
        if key is None:
            return _fail(alg, f"Untrusted key: {signer_fingerprint}")
        if not self.gpg_binary:
            return _fail(alg, "gpg binary not available")
        try:
            ok, detail = await asyncio.to_thread(
                self._run_gpg, artifact_bytes, signature_bytes, key, fpr
            )
        except Exception as exc:
            logger.error("GPG verification error: %s", exc, exc_info=True)
            return _fail(alg, f"Verification error: {exc}")
        return _ok(alg, fpr) if ok else _fail(alg, detail)

    def _run_gpg(self, artifact: bytes, sig: bytes, key: str, fpr: str) -> tuple[bool, str]:
        binary = self.gpg_binary
        if not binary:
            return False, "gpg binary not available"
        with tempfile.TemporaryDirectory() as tmp:
            home, base = Path(tmp) / "home", Path(tmp)
            home.mkdir(mode=0o700)
            (base / "key.asc").write_text(key, encoding="utf-8")
            (base / "data").write_bytes(artifact)
            (base / "data.sig").write_bytes(sig)
            common = [binary, "--homedir", str(home), "--batch", "--no-tty"]
            imp = subprocess.run(
                common + ["--import", str(base / "key.asc")],
                capture_output=True,
                timeout=self.timeout_seconds,
            )
            if imp.returncode != 0:
                return False, "Failed to import trusted key"
            res = subprocess.run(
                common
                + ["--status-fd", "1", "--verify", str(base / "data.sig"), str(base / "data")],
                capture_output=True,
                timeout=self.timeout_seconds,
            )
            for line in res.stdout.decode("utf-8", "replace").splitlines():
                if line.startswith("[GNUPG:] VALIDSIG"):
                    fields = line.split()[2:]
                    if fields and fpr in (fields[0].upper(), fields[-1].upper()):
                        return True, ""
            return False, "GPG signature invalid or signed by a different key"


class InternalPKIVerifier:
    """
    Internal PKI verification for platform-hosted connectors.

    Certificates are registered by ID; the registered certificate must chain to
    the configured root CA and its key must have produced the signature.
    """

    def __init__(self, root_ca_pem: str | None = None) -> None:
        self._roots = load_chain(root_ca_pem) if root_ca_pem else []
        self.certificate_store: dict[str, str] = {}

    def set_root_ca(self, pem: str) -> None:
        self._roots = load_chain(pem)

    def register_certificate(self, certificate_id: str, certificate_pem: str) -> None:
        self.certificate_store[certificate_id] = certificate_pem
        logger.info("Registered certificate: %s", certificate_id)

    async def verify_signature(
        self,
        artifact_bytes: bytes,
        signature_bytes: bytes,
        certificate_id: str,
    ) -> VerificationResult:
        alg = SignatureAlgorithm.INTERNAL_PKI
        pem = self.certificate_store.get(certificate_id)
        if pem is None:
            return _fail(alg, f"Certificate not found: {certificate_id}")
        try:
            chain = load_chain(pem)
            verify_chain(chain, self._roots)
            verify_signature_with_cert(chain[0], artifact_bytes, signature_bytes)
        except VerificationError as exc:
            return _fail(alg, str(exc))
        except Exception as exc:
            logger.error("Internal PKI verification error: %s", exc, exc_info=True)
            return _fail(alg, f"Verification error: {exc}")
        return _ok(alg, certificate_id, [pem])


def _decode_signature(value: Any) -> bytes:
    """Signatures arrive base64-encoded in signature_info."""
    if isinstance(value, bytes):
        return value
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError, TypeError) as exc:
        raise VerificationError(f"Signature is not valid base64: {exc}") from exc


class UnifiedSignatureVerifier:
    """Dispatch to the verifier named by signature_info['algorithm']."""

    def __init__(self) -> None:
        self.sigstore = SigstoreVerifier()
        self.gpg = GPGVerifier()
        self.internal_pki = InternalPKIVerifier()

    async def verify(
        self,
        artifact_bytes: bytes,
        signature_info: dict[str, Any],
    ) -> VerificationResult:
        algorithm = signature_info.get("algorithm", "sigstore-oidc")
        try:
            sig = _decode_signature(signature_info["signature"])
            if algorithm == SignatureAlgorithm.SIGSTORE_OIDC.value:
                return await self.sigstore.verify_signature(
                    artifact_bytes,
                    sig,
                    signature_info.get("certificate", ""),
                    entry_uuid=signature_info.get("rekor_entry"),
                )
            if algorithm == SignatureAlgorithm.GPG.value:
                return await self.gpg.verify_signature(
                    artifact_bytes, sig, signature_info["signer_fingerprint"]
                )
            if algorithm == SignatureAlgorithm.INTERNAL_PKI.value:
                return await self.internal_pki.verify_signature(
                    artifact_bytes, sig, signature_info["certificate_id"]
                )
            return VerificationResult(
                is_valid=False,
                algorithm=algorithm,
                error=f"Unknown algorithm: {algorithm}",
            )
        except (VerificationError, KeyError) as exc:
            return VerificationResult(
                is_valid=False, algorithm=algorithm, error=f"Invalid input: {exc}"
            )
        except Exception as exc:
            logger.error("Signature verification error: %s", exc, exc_info=True)
            return VerificationResult(
                is_valid=False,
                algorithm=algorithm,
                error=f"Verification error: {exc}",
            )
