"""
SEC-007 signature verification tests using real X.509 certificates.

Certificates are generated in-process with `cryptography`; nothing is mocked.
"""

import base64
from datetime import UTC, datetime, timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from src.security.mcp_connector_governance.security import (
    GPGVerifier,
    InternalPKIVerifier,
    SigstoreVerifier,
    UnifiedSignatureVerifier,
)

ARTIFACT = b"connector-binary-v1"


def _name(cn: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _make_cert(
    subject_cn, issuer_cn, key, signer_key, *, ca, not_before=None, not_after=None, email=None
):
    now = datetime.now(UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(_name(subject_cn))
        .issuer_name(_name(issuer_cn))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before or now - timedelta(hours=1))
        .not_valid_after(not_after or now + timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
    )
    if email:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.RFC822Name(email)]), critical=False
        )
    return builder.sign(signer_key, hashes.SHA256())


def _pem(*certs) -> str:
    return "".join(c.public_bytes(serialization.Encoding.PEM).decode() for c in certs)


def _sign(key, data: bytes) -> bytes:
    return key.sign(data, ec.ECDSA(hashes.SHA256()))


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


@pytest.fixture
def pki():
    """A root CA and a leaf signed by it."""
    root_key, leaf_key = (
        ec.generate_private_key(ec.SECP256R1()),
        ec.generate_private_key(ec.SECP256R1()),
    )
    root = _make_cert("Test Root", "Test Root", root_key, root_key, ca=True)
    leaf = _make_cert("leaf", "Test Root", leaf_key, root_key, ca=False, email="dev@example.com")
    return {"root_key": root_key, "leaf_key": leaf_key, "root": root, "leaf": leaf}


class TestSigstore:
    @pytest.mark.asyncio
    async def test_valid_chain_and_signature(self, pki):
        v = SigstoreVerifier(trusted_roots_pem=[_pem(pki["root"])])
        sig = _sign(pki["leaf_key"], ARTIFACT)
        r = await v.verify_signature(ARTIFACT, sig, _pem(pki["leaf"]))
        assert r.is_valid is True
        assert r.signer_identity == "dev@example.com"

    @pytest.mark.asyncio
    async def test_no_trusted_roots_fails_closed(self, pki):
        v = SigstoreVerifier()
        sig = _sign(pki["leaf_key"], ARTIFACT)
        r = await v.verify_signature(ARTIFACT, sig, _pem(pki["leaf"]))
        assert r.is_valid is False

    @pytest.mark.asyncio
    async def test_tampered_artifact_rejected(self, pki):
        v = SigstoreVerifier(trusted_roots_pem=[_pem(pki["root"])])
        sig = _sign(pki["leaf_key"], ARTIFACT)
        r = await v.verify_signature(b"tampered", sig, _pem(pki["leaf"]))
        assert r.is_valid is False

    @pytest.mark.asyncio
    async def test_wrong_signing_key_rejected(self, pki):
        v = SigstoreVerifier(trusted_roots_pem=[_pem(pki["root"])])
        other = ec.generate_private_key(ec.SECP256R1())
        r = await v.verify_signature(ARTIFACT, _sign(other, ARTIFACT), _pem(pki["leaf"]))
        assert r.is_valid is False

    @pytest.mark.asyncio
    async def test_untrusted_root_rejected(self, pki):
        rogue_key = ec.generate_private_key(ec.SECP256R1())
        rogue_root = _make_cert("Rogue", "Rogue", rogue_key, rogue_key, ca=True)
        v = SigstoreVerifier(trusted_roots_pem=[_pem(rogue_root)])
        sig = _sign(pki["leaf_key"], ARTIFACT)
        r = await v.verify_signature(ARTIFACT, sig, _pem(pki["leaf"]))
        assert r.is_valid is False

    @pytest.mark.asyncio
    async def test_expired_leaf_rejected(self, pki):
        now = datetime.now(UTC)
        expired = _make_cert(
            "leaf",
            "Test Root",
            pki["leaf_key"],
            pki["root_key"],
            ca=False,
            not_before=now - timedelta(days=2),
            not_after=now - timedelta(days=1),
        )
        v = SigstoreVerifier(trusted_roots_pem=[_pem(pki["root"])])
        sig = _sign(pki["leaf_key"], ARTIFACT)
        r = await v.verify_signature(ARTIFACT, sig, _pem(expired))
        assert r.is_valid is False

    @pytest.mark.asyncio
    async def test_garbage_certificate_rejected(self):
        r = await SigstoreVerifier().verify_signature(ARTIFACT, b"sig", "not a cert")
        assert r.is_valid is False

    @pytest.mark.asyncio
    async def test_rekor_entry_without_lookup_fails(self, pki):
        v = SigstoreVerifier(trusted_roots_pem=[_pem(pki["root"])])
        sig = _sign(pki["leaf_key"], ARTIFACT)
        r = await v.verify_signature(ARTIFACT, sig, _pem(pki["leaf"]), entry_uuid="abc")
        assert r.is_valid is False

    @pytest.mark.asyncio
    async def test_rekor_lookup_result_is_honoured(self, pki):
        async def lookup_ok(_artifact, _uuid):
            return True

        async def lookup_bad(_artifact, _uuid):
            return False

        sig = _sign(pki["leaf_key"], ARTIFACT)
        roots = [_pem(pki["root"])]
        ok = SigstoreVerifier(trusted_roots_pem=roots, rekor_lookup=lookup_ok)
        bad = SigstoreVerifier(trusted_roots_pem=roots, rekor_lookup=lookup_bad)
        assert (await ok.verify_signature(ARTIFACT, sig, _pem(pki["leaf"]), "abc")).is_valid
        assert not (await bad.verify_signature(ARTIFACT, sig, _pem(pki["leaf"]), "abc")).is_valid


class TestInternalPKI:
    @pytest.mark.asyncio
    async def test_valid(self, pki):
        v = InternalPKIVerifier(root_ca_pem=_pem(pki["root"]))
        v.register_certificate("c1", _pem(pki["leaf"]))
        r = await v.verify_signature(ARTIFACT, _sign(pki["leaf_key"], ARTIFACT), "c1")
        assert r.is_valid is True

    @pytest.mark.asyncio
    async def test_unknown_certificate(self, pki):
        v = InternalPKIVerifier(root_ca_pem=_pem(pki["root"]))
        r = await v.verify_signature(ARTIFACT, b"sig", "missing")
        assert r.is_valid is False

    @pytest.mark.asyncio
    async def test_no_root_ca_fails_closed(self, pki):
        v = InternalPKIVerifier()
        v.register_certificate("c1", _pem(pki["leaf"]))
        r = await v.verify_signature(ARTIFACT, _sign(pki["leaf_key"], ARTIFACT), "c1")
        assert r.is_valid is False

    @pytest.mark.asyncio
    async def test_bad_signature(self, pki):
        v = InternalPKIVerifier(root_ca_pem=_pem(pki["root"]))
        v.register_certificate("c1", _pem(pki["leaf"]))
        r = await v.verify_signature(ARTIFACT, b"\x00" * 70, "c1")
        assert r.is_valid is False


class TestGPG:
    @pytest.mark.asyncio
    async def test_untrusted_key(self):
        r = await GPGVerifier().verify_signature(ARTIFACT, b"sig", "DEADBEEF")
        assert r.is_valid is False
        assert "Untrusted key" in r.error

    @pytest.mark.asyncio
    async def test_missing_binary_fails_closed(self):
        v = GPGVerifier(gpg_binary=None)
        v.gpg_binary = None
        v.add_trusted_key("0123456789ABCDEF", "key-data")
        r = await v.verify_signature(ARTIFACT, b"sig", "0123456789ABCDEF")
        assert r.is_valid is False


class TestUnified:
    @pytest.mark.asyncio
    async def test_sigstore_dispatch(self, pki):
        u = UnifiedSignatureVerifier()
        u.sigstore.add_trusted_root(_pem(pki["root"]))
        info = {
            "algorithm": "sigstore-oidc",
            "signature": _b64(_sign(pki["leaf_key"], ARTIFACT)),
            "certificate": _pem(pki["leaf"]),
        }
        assert (await u.verify(ARTIFACT, info)).is_valid is True

    @pytest.mark.asyncio
    async def test_internal_pki_dispatch(self, pki):
        u = UnifiedSignatureVerifier()
        u.internal_pki.set_root_ca(_pem(pki["root"]))
        u.internal_pki.register_certificate("c1", _pem(pki["leaf"]))
        info = {
            "algorithm": "internal-pki",
            "signature": _b64(_sign(pki["leaf_key"], ARTIFACT)),
            "certificate_id": "c1",
        }
        assert (await u.verify(ARTIFACT, info)).is_valid is True

    @pytest.mark.asyncio
    async def test_unknown_algorithm(self):
        r = await UnifiedSignatureVerifier().verify(
            ARTIFACT, {"algorithm": "rot13", "signature": _b64(b"x")}
        )
        assert r.is_valid is False

    @pytest.mark.asyncio
    async def test_invalid_base64_signature(self):
        r = await UnifiedSignatureVerifier().verify(
            ARTIFACT, {"algorithm": "gpg", "signature": "!!!not-base64"}
        )
        assert r.is_valid is False

    @pytest.mark.asyncio
    async def test_missing_signature_field(self):
        r = await UnifiedSignatureVerifier().verify(ARTIFACT, {"algorithm": "gpg"})
        assert r.is_valid is False
