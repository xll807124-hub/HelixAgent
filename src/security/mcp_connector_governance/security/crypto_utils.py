"""
Shared X.509 / signature primitives for the verifiers.

Every function raises VerificationError on failure so callers can fail closed.
"""

from datetime import UTC, datetime

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa


class VerificationError(Exception):
    """Raised when a certificate or signature check fails."""


def load_chain(pem: str) -> list[x509.Certificate]:
    """Parse one or more PEM certificates (leaf first)."""
    try:
        certs = x509.load_pem_x509_certificates(pem.encode("utf-8"))
    except ValueError as exc:
        raise VerificationError(f"Invalid certificate PEM: {exc}") from exc
    if not certs:
        raise VerificationError("No certificate found in PEM")
    return certs


def check_validity(cert: x509.Certificate, now: datetime | None = None) -> None:
    """Reject certificates outside their validity window."""
    now = now or datetime.now(UTC)
    if not (cert.not_valid_before_utc <= now <= cert.not_valid_after_utc):
        raise VerificationError(
            f"Certificate not valid at {now.isoformat()}: "
            f"{cert.subject.rfc4514_string()}"
        )


def _require_ca(cert: x509.Certificate) -> None:
    """Issuing certificates must carry BasicConstraints CA=true."""
    try:
        constraints = cert.extensions.get_extension_for_class(
            x509.BasicConstraints
        ).value
    except x509.ExtensionNotFound:
        constraints = None
    if constraints is None or not constraints.ca:
        raise VerificationError(
            f"Issuer is not a CA certificate: {cert.subject.rfc4514_string()}"
        )


def verify_chain(
    chain: list[x509.Certificate],
    trusted_roots: list[x509.Certificate],
    now: datetime | None = None,
) -> x509.Certificate:
    """
    Verify chain[0] (leaf) up to one of trusted_roots.

    Each certificate must be in its validity window, each issuer must be a CA,
    and each link must be signed by the next. Returns the matched root.
    """
    if not trusted_roots:
        raise VerificationError("No trusted root certificates configured")

    for cert in chain:
        check_validity(cert, now)

    # Link every certificate in the supplied chain to the next one.
    for child, parent in zip(chain, chain[1:], strict=False):
        _require_ca(parent)
        try:
            child.verify_directly_issued_by(parent)
        except (ValueError, TypeError, InvalidSignature) as exc:
            raise VerificationError(
                f"Chain link invalid: {child.subject.rfc4514_string()}: {exc}"
            ) from exc

    # The last certificate must be issued by (or be) a trusted root.
    top = chain[-1]
    for root in trusted_roots:
        check_validity(root, now)
        if top == root:
            return root
        try:
            _require_ca(root)
            top.verify_directly_issued_by(root)
            return root
        except (VerificationError, ValueError, TypeError, InvalidSignature):
            continue
    raise VerificationError("Certificate chain does not lead to a trusted root")


def verify_signature_with_cert(
    cert: x509.Certificate,
    artifact: bytes,
    signature: bytes,
) -> None:
    """Verify `signature` over `artifact` using the certificate's public key."""
    key = cert.public_key()
    try:
        if isinstance(key, rsa.RSAPublicKey):
            key.verify(signature, artifact, padding.PKCS1v15(), hashes.SHA256())
        elif isinstance(key, ec.EllipticCurvePublicKey):
            key.verify(signature, artifact, ec.ECDSA(hashes.SHA256()))
        elif isinstance(key, ed25519.Ed25519PublicKey):
            key.verify(signature, artifact)
        else:
            raise VerificationError(f"Unsupported key type: {type(key).__name__}")
    except InvalidSignature as exc:
        raise VerificationError("Signature does not match artifact") from exc


def cert_identity(cert: x509.Certificate) -> str:
    """Prefer an email/URI SAN (Sigstore identity), else the subject DN."""
    try:
        san = cert.extensions.get_extension_for_class(
            x509.SubjectAlternativeName
        ).value
        for name in san.get_values_for_type(x509.RFC822Name):
            return name
        for name in san.get_values_for_type(x509.UniformResourceIdentifier):
            return name
    except x509.ExtensionNotFound:
        pass
    return cert.subject.rfc4514_string()

