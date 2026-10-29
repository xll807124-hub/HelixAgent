"""Sensitive payloads must not escape via short values or nested containers."""

from copy import deepcopy

import pytest

from src.runtime.query.redaction_engine import AccessLevel, RedactionEngine, SensitivityLevel


@pytest.mark.parametrize("access, classification", [
    (AccessLevel.BASIC, SensitivityLevel.L1),
    (AccessLevel.AUDIT, SensitivityLevel.L3),
])
@pytest.mark.parametrize("secret", ["x", "short-password", 12345, ["nested"], {"value": "secret"}])
def test_sensitive_field_is_hidden_regardless_of_value_format(access, classification, secret):
    payload = {"items": [{"password": secret}], "message": "visible"}
    original = deepcopy(payload)
    result, info = RedactionEngine().redact_payload(payload, access, classification)
    assert result == {"items": [{"password": "[REDACTED]"}], "message": "visible"}
    assert info.has_sensitive_data
    assert info.redacted_fields == ["items[0].password"]
    assert payload == original


@pytest.mark.parametrize("access, classification", [
    (AccessLevel.BASIC, SensitivityLevel.L1),
    (AccessLevel.AUDIT, SensitivityLevel.L3),
])
def test_secret_embedded_in_nested_list_is_hidden(access, classification):
    token = "ghp_" + "a" * 36
    result, info = RedactionEngine().redact_payload(
        {"details": [[f"Bearer {token}"]]}, access, classification,
    )
    assert token not in str(result)
    assert info.redacted_fields == ["details[0][0]"]


def test_full_access_preserves_values_and_identifies_nested_sensitive_data():
    payload = {"details": [{"password": "admin-visible"}]}
    result, info = RedactionEngine().redact_payload(
        payload, AccessLevel.ADMIN, SensitivityLevel.L3,
    )
    assert result == payload
    assert info.has_sensitive_data
    assert info.redacted_fields == []
