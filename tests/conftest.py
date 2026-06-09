"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from app.config import Settings


@pytest.fixture
def settings() -> Settings:
    """Settings isolated from any on-disk .env file."""
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        qradar_host="qradar.test",
        qradar_api_token="test-token",
        qradar_verify_ssl=False,
        api_key="test-api-key",
        refset_ip="Set_IP",
        refset_hash="Set_Hash",
        refset_domain="Set_Domain",
        refset_url="Set_URL",
        initial_sync_on_startup=False,
    )
