"""SEC-007 AC2: OAuth 令牌 aud/exp/iss 校验测试（fail-closed）"""

import time

import jwt
import pytest

from src.security.mcp_connector_governance.authorization.oauth_handler import (
    OAuth21Handler,
)

SECRET = "unit-test-secret-key-at-least-32-bytes-long!"
AUDIENCE = "https://connector.example.com"
ISSUER = "https://auth.example.com"


def _handler(audience=AUDIENCE) -> OAuth21Handler:
    return OAuth21Handler(
        client_id="client-1",
        authorization_endpoint="https://auth.example.com/authorize",
        token_endpoint="https://auth.example.com/token",
        redirect_uri="https://app.example.com/callback",
        scopes=["read"],
        audience=audience,
    )


def _token(**overrides) -> str:
    claims = {
        "aud": AUDIENCE,
        "iss": ISSUER,
        "exp": int(time.time()) + 3600,
        "sub": "user-1",
    }
    claims.update(overrides)
    # 值为 None 表示删除该 claim
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, SECRET, algorithm="HS256")


class TestAudienceSmoke:
    def test_valid_token_without_signature_check(self):
        assert _handler().validate_token_audience(_token()) is True

    def test_valid_token_with_signature_check(self):
        assert _handler().validate_token_audience(
            _token(), signing_key=SECRET, algorithms=["HS256"]
        ) is True

    def test_valid_token_with_issuer(self):
        assert _handler().validate_token_audience(_token(), issuer=ISSUER) is True

    def test_audience_list_containing_expected(self):
        token = _token(aud=["other", AUDIENCE])
        assert _handler().validate_token_audience(token) is True


class TestAudienceRejections:
    def test_wrong_audience(self):
        assert _handler().validate_token_audience(_token(aud="https://evil.example.com")) is False

    def test_missing_audience_claim(self):
        assert _handler().validate_token_audience(_token(aud=None)) is False

    def test_expired_token(self):
        assert _handler().validate_token_audience(_token(exp=int(time.time()) - 10)) is False

    def test_missing_exp_claim(self):
        assert _handler().validate_token_audience(_token(exp=None)) is False

    def test_wrong_issuer(self):
        assert _handler().validate_token_audience(
            _token(iss="https://evil.example.com"), issuer=ISSUER
        ) is False

    def test_missing_issuer_when_required(self):
        assert _handler().validate_token_audience(_token(iss=None), issuer=ISSUER) is False

    def test_bad_signature(self):
        forged = jwt.encode(
            {"aud": AUDIENCE, "exp": int(time.time()) + 60},
            "a-different-secret-key-that-is-32-bytes!",
            algorithm="HS256",
        )
        assert _handler().validate_token_audience(
            forged, signing_key=SECRET, algorithms=["HS256"]
        ) is False


class TestAudienceFailClosed:
    def test_no_audience_configured(self):
        assert _handler(audience=None).validate_token_audience(_token()) is False

    @pytest.mark.parametrize("bad", ["", "not-a-jwt", "a.b.c", None, 123])
    def test_malformed_or_opaque_token(self, bad):
        assert _handler().validate_token_audience(bad) is False

    def test_alg_none_token_rejected_when_verifying(self):
        unsigned = jwt.encode(
            {"aud": AUDIENCE, "exp": int(time.time()) + 60}, key=None, algorithm="none"
        )
        assert _handler().validate_token_audience(
            unsigned, signing_key=SECRET, algorithms=["HS256"]
        ) is False

    def test_none_algorithm_not_allowed_in_allowlist(self):
        assert _handler().validate_token_audience(
            _token(), signing_key=SECRET, algorithms=["none"]
        ) is False

    def test_signing_key_without_algorithms_rejected(self):
        assert _handler().validate_token_audience(_token(), signing_key=SECRET) is False
