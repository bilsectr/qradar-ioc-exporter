"""Tests for the async QRadar reference-data client."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.qradar_client import QRadarClient, QRadarError

BASE = "https://qradar.test"


@pytest.fixture
async def client():
    c = QRadarClient(BASE, "test-token", verify_ssl=False, api_version="20.0")
    try:
        yield c
    finally:
        await c.close()


def _set_url(name: str) -> str:
    return f"{BASE}/api/reference_data/sets/{name}"


@respx.mock
async def test_fetch_single_page(client: QRadarClient) -> None:
    route = respx.get(_set_url("Set_IP")).mock(
        return_value=httpx.Response(
            200,
            json={
                "number_of_elements": 2,
                "data": [{"value": "1.1.1.1"}, {"value": "2.2.2.2"}],
            },
        )
    )
    values = await client.fetch_reference_set("Set_IP")
    assert values == ["1.1.1.1", "2.2.2.2"]
    assert route.called

    # SEC + Version headers must be sent, token must never be a Bearer.
    request = route.calls.last.request
    assert request.headers["SEC"] == "test-token"
    assert request.headers["Version"] == "20.0"
    assert "authorization" not in request.headers


@respx.mock
async def test_pagination_walks_offsets(client: QRadarClient) -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params.get("offset", 0))
        if offset == 0:
            data = [{"value": "a"}, {"value": "b"}]
        else:
            data = [{"value": "c"}, {"value": "d"}]
        return httpx.Response(
            200, json={"number_of_elements": 4, "data": data}
        )

    respx.get(_set_url("Big")).mock(side_effect=responder)
    values = await client.fetch_reference_set("Big")
    assert values == ["a", "b", "c", "d"]


@respx.mock
async def test_retry_on_5xx_then_success(
    client: QRadarClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.qradar_client.BACKOFF_BASE_SECONDS", 0)
    attempts = {"n": 0}

    def responder(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(503)
        return httpx.Response(
            200, json={"number_of_elements": 1, "data": [{"value": "x"}]}
        )

    respx.get(_set_url("Flaky")).mock(side_effect=responder)
    values = await client.fetch_reference_set("Flaky")
    assert values == ["x"]
    assert attempts["n"] == 2


@respx.mock
async def test_retry_on_connection_error_then_success(
    client: QRadarClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.qradar_client.BACKOFF_BASE_SECONDS", 0)
    attempts = {"n": 0}

    def responder(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise httpx.ConnectError("boom")
        return httpx.Response(
            200, json={"number_of_elements": 1, "data": [{"value": "ok"}]}
        )

    respx.get(_set_url("Conn")).mock(side_effect=responder)
    values = await client.fetch_reference_set("Conn")
    assert values == ["ok"]
    assert attempts["n"] == 2


@respx.mock
async def test_retries_exhausted_raises(
    client: QRadarClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.qradar_client.BACKOFF_BASE_SECONDS", 0)
    route = respx.get(_set_url("Down")).mock(
        return_value=httpx.Response(500)
    )
    with pytest.raises(QRadarError):
        await client.fetch_reference_set("Down")
    assert route.call_count == 3


@respx.mock
async def test_missing_reference_set_raises(client: QRadarClient) -> None:
    respx.get(_set_url("Ghost")).mock(return_value=httpx.Response(404))
    with pytest.raises(QRadarError, match="not found"):
        await client.fetch_reference_set("Ghost")


@respx.mock
async def test_auth_failure_raises(client: QRadarClient) -> None:
    respx.get(_set_url("Secret")).mock(return_value=httpx.Response(403))
    with pytest.raises(QRadarError, match="authoriz|auth"):
        await client.fetch_reference_set("Secret")


@respx.mock
async def test_empty_reference_set_returns_empty_list(
    client: QRadarClient,
) -> None:
    respx.get(_set_url("Empty")).mock(
        return_value=httpx.Response(
            200, json={"number_of_elements": 0, "data": []}
        )
    )
    assert await client.fetch_reference_set("Empty") == []
