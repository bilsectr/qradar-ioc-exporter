"""Tests for configuration helpers."""

from __future__ import annotations

from app.config import Settings


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def test_scheme_https_when_tls_enabled() -> None:
    assert _settings(enable_tls=True).scheme == "https"


def test_scheme_http_when_tls_disabled() -> None:
    assert _settings(enable_tls=False).scheme == "http"


def test_tls_enabled_by_default() -> None:
    assert _settings().enable_tls is True
    assert _settings().scheme == "https"


def test_host_scheme_is_stripped() -> None:
    assert _settings(qradar_host="https://10.0.0.5/").qradar_host == "10.0.0.5"
    assert _settings(qradar_host="http://qradar.lan").qradar_host == "qradar.lan"


def test_auth_enabled_by_default() -> None:
    assert _settings().auth_enabled is True


def test_auth_disabled_when_require_auth_false() -> None:
    assert _settings(require_auth=False).auth_enabled is False


def test_auth_disabled_when_api_key_empty() -> None:
    assert _settings(api_key="").auth_enabled is False
    assert _settings(api_key="   ").auth_enabled is False
