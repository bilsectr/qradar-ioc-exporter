"""Async client for the QRadar Reference Data REST API."""

from __future__ import annotations

import asyncio
import logging

import httpx

logger = logging.getLogger("qradar.client")

# QRadar caps page sizes; 5000 is a safe, large value.
PAGE_SIZE = 5000
MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 0.5


class QRadarError(Exception):
    """Raised when a reference set cannot be fetched."""


class QRadarClient:
    """Fetches reference set contents from QRadar.

    A single :class:`httpx.AsyncClient` with connection pooling is reused for
    the lifetime of the client. Call :meth:`close` (or use as an async context
    manager) to release connections.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        verify_ssl: bool = False,
        api_version: str = "20.0",
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._api_version = api_version
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            verify=verify_ssl,
            timeout=timeout,
            headers={
                "SEC": token,
                "Version": api_version,
                "Accept": "application/json",
            },
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )

    async def __aenter__(self) -> QRadarClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    async def _get_with_retry(
        self, path: str, params: dict[str, object]
    ) -> httpx.Response:
        """GET with exponential backoff on 5xx and connection errors.

        4xx responses are returned immediately (no retry) so the caller can
        distinguish e.g. a missing reference set (404) from a transient fault.
        """
        last_exc: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = await self._client.get(path, params=params)
            except (
                httpx.ConnectError,
                httpx.ConnectTimeout,
                httpx.ReadTimeout,
                httpx.RemoteProtocolError,
                httpx.PoolTimeout,
            ) as exc:
                last_exc = exc
                logger.warning(
                    "QRadar request failed (connection)",
                    extra={
                        "path": path,
                        "attempt": attempt,
                        "max_retries": MAX_RETRIES,
                        "error": str(exc),
                    },
                )
            else:
                if response.status_code < 500:
                    return response
                last_exc = QRadarError(
                    f"QRadar returned {response.status_code} for {path}"
                )
                logger.warning(
                    "QRadar request failed (server error)",
                    extra={
                        "path": path,
                        "attempt": attempt,
                        "max_retries": MAX_RETRIES,
                        "status_code": response.status_code,
                    },
                )

            if attempt < MAX_RETRIES:
                await asyncio.sleep(BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))

        raise QRadarError(f"Exhausted {MAX_RETRIES} retries for {path}") from last_exc

    async def fetch_reference_set(self, name: str) -> list[str]:
        """Return every ``value`` string in the named reference set.

        Pages through the set using ``limit``/``offset`` until all elements
        have been retrieved. Raises :class:`QRadarError` on failure (including
        a missing reference set) so the caller can decide whether to continue.
        """
        path = f"/api/reference_data/sets/{name}"
        values: list[str] = []
        offset = 0
        total: int | None = None

        while True:
            params = {
                "fields": "number_of_elements,data",
                "limit": PAGE_SIZE,
                "offset": offset,
            }
            response = await self._get_with_retry(path, params)

            if response.status_code == 404:
                raise QRadarError(f"Reference set not found: {name!r}")
            if response.status_code in (401, 403):
                raise QRadarError(
                    f"Authentication/authorization failed for {name!r} "
                    f"(HTTP {response.status_code})"
                )
            if response.status_code >= 400:
                raise QRadarError(
                    f"Unexpected HTTP {response.status_code} for {name!r}: "
                    f"{response.text[:200]}"
                )

            body = response.json()
            if total is None:
                total = int(body.get("number_of_elements", 0))

            page = body.get("data", []) or []
            for item in page:
                value = item.get("value")
                if value is not None:
                    values.append(str(value))

            offset += len(page)

            # Stop when we've collected everything or the page came back short.
            if not page or offset >= total:
                break

        logger.info(
            "Fetched reference set",
            extra={"refset": name, "entry_count": len(values)},
        )
        return values
