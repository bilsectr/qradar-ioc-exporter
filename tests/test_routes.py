"""Tests for the FastAPI feed, health, metrics and admin routes."""

from __future__ import annotations

import httpx
import pytest
from httpx import ASGITransport

from app.config import Settings
from app.feed_store import FeedStore
from app.main import create_app

AUTH = {"Authorization": "Bearer test-api-key"}


class FakeSyncService:
    """Stand-in for SyncService that records trigger calls."""

    def __init__(self) -> None:
        self.triggered = 0

    def trigger_now(self) -> None:
        self.triggered += 1


@pytest.fixture
async def app_client(settings: Settings):
    app = create_app(settings)

    store = FeedStore()
    await store.update("ip", ["1.1.1.1", "2.2.2.2"])
    await store.update("hash", ["d41d8cd98f00b204e9800998ecf8427e"])
    await store.mark_sync_complete(50.0)

    app.state.store = store
    app.state.sync_service = FakeSyncService()

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, app


async def test_ip_feed_returns_plaintext(app_client) -> None:
    client, _ = app_client
    resp = await client.get("/feeds/ip.txt", headers=AUTH)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "text/plain; charset=utf-8"
    assert resp.text == "1.1.1.1\n2.2.2.2\n"
    assert resp.headers["x-entry-count"] == "2"
    assert resp.headers["x-last-sync"] != "never"


async def test_all_feed_endpoints_reachable(app_client) -> None:
    client, _ = app_client
    for name in ("ip", "hash", "domain", "url"):
        resp = await client.get(f"/feeds/{name}.txt", headers=AUTH)
        assert resp.status_code == 200


async def test_empty_feed_returns_200_not_404(app_client) -> None:
    client, _ = app_client
    resp = await client.get("/feeds/url.txt", headers=AUTH)
    assert resp.status_code == 200
    assert resp.text == ""
    assert resp.headers["x-entry-count"] == "0"


async def test_feed_requires_auth(app_client) -> None:
    client, _ = app_client
    resp = await client.get("/feeds/ip.txt")
    assert resp.status_code == 401


async def test_feed_rejects_wrong_key(app_client) -> None:
    client, _ = app_client
    resp = await client.get("/feeds/ip.txt", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401


async def test_feed_rejects_non_bearer_scheme(app_client) -> None:
    client, _ = app_client
    resp = await client.get(
        "/feeds/ip.txt", headers={"Authorization": "Basic test-api-key"}
    )
    assert resp.status_code == 401


async def test_health_is_public_and_ok(app_client) -> None:
    client, _ = app_client
    resp = await client.get("/health")  # no auth header
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["counts"]["ip"] == 2
    assert body["last_sync"] is not None


async def test_metrics_requires_auth(app_client) -> None:
    client, _ = app_client
    assert (await client.get("/metrics")).status_code == 401
    resp = await client.get("/metrics", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["sync_count"] == 1
    assert body["error_count"] == 0
    assert body["last_sync_duration_ms"] == 50.0


async def test_admin_sync_triggers(app_client) -> None:
    client, app = app_client
    resp = await client.post("/admin/sync", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["status"] == "started"
    assert app.state.sync_service.triggered == 1


async def test_admin_sync_requires_auth(app_client) -> None:
    client, _ = app_client
    resp = await client.post("/admin/sync")
    assert resp.status_code == 401


# --- Auth-disabled mode (REQUIRE_AUTH=false) ------------------------------


@pytest.fixture
async def noauth_client(settings: Settings):
    noauth = settings.model_copy(update={"require_auth": False})
    app = create_app(noauth)

    store = FeedStore()
    await store.update("ip", ["9.9.9.9"])
    app.state.store = store
    app.state.sync_service = FakeSyncService()

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_feed_accessible_without_token_when_auth_disabled(
    noauth_client,
) -> None:
    resp = await noauth_client.get("/feeds/ip.txt")  # no auth header
    assert resp.status_code == 200
    assert resp.text == "9.9.9.9\n"


async def test_metrics_and_admin_open_when_auth_disabled(noauth_client) -> None:
    assert (await noauth_client.get("/metrics")).status_code == 200
    assert (await noauth_client.post("/admin/sync")).status_code == 200
