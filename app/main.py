"""FastAPI application: lifespan wiring, feed routes, and entrypoint."""

from __future__ import annotations

import logging
import warnings
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import PlainTextResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import Settings, get_settings
from .feed_store import FEED_TYPES, FeedStore
from .logging_config import configure_logging
from .qradar_client import QRadarClient
from .scheduler import SyncService

logger = logging.getLogger("qradar.main")

# Feed type -> served filename.
_FEED_FILES = {
    "ip": "ip.txt",
    "hash": "hash.txt",
    "domain": "domain.txt",
    "url": "url.txt",
}

_bearer = HTTPBearer(auto_error=False)


def _suppress_insecure_warnings(settings: Settings) -> None:
    """Quiet per-request TLS warnings, logging the posture once instead."""
    if settings.qradar_verify_ssl:
        return
    logger.warning(
        "QRadar TLS verification is DISABLED (QRADAR_VERIFY_SSL=false). "
        "Self-signed certificate warnings are suppressed for the rest of "
        "this run."
    )
    try:  # urllib3 is an indirect dependency; suppress only if present.
        import urllib3  # type: ignore

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:  # noqa: BLE001 - optional dependency
        pass
    warnings.filterwarnings("ignore", message="Unverified HTTPS request")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    _suppress_insecure_warnings(settings)

    if not settings.auth_enabled:
        reason = (
            "REQUIRE_AUTH=false" if not settings.require_auth else "API_KEY empty"
        )
        logger.warning(
            "Feed authentication is DISABLED (%s): feeds, metrics and "
            "/admin/sync are reachable without a token. Only expose this on a "
            "trusted network.",
            reason,
        )

    store = FeedStore()
    client = QRadarClient(
        base_url=settings.qradar_base_url,
        token=settings.qradar_api_token,
        verify_ssl=settings.qradar_verify_ssl,
        api_version=settings.qradar_api_version,
    )
    sync_service = SyncService(settings, store, client)

    app.state.store = store
    app.state.client = client
    app.state.sync_service = sync_service

    sync_service.start()

    if settings.initial_sync_on_startup:
        # Fire-and-forget so startup never blocks on an unreachable QRadar
        # (the feed service must come up and serve empty feeds regardless).
        sync_service.trigger_now()
        logger.info("Initial sync triggered on startup")

    logger.info(
        "Service ready",
        extra={"port": settings.service_port},
    )
    try:
        yield
    finally:
        sync_service.shutdown()
        await client.close()
        logger.info("Service shut down")


def _require_api_key(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """Validate the ``Authorization: Bearer <API_KEY>`` header.

    Becomes a no-op when authentication is disabled (``REQUIRE_AUTH=false`` or
    an empty ``API_KEY``), allowing unauthenticated access to the feeds.
    """
    settings: Settings = request.app.state.settings
    if not settings.auth_enabled:
        return
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if credentials.credentials != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    app = FastAPI(
        title="QRadar IOC Exporter",
        version="1.0.0",
        description=(
            "Serves QRadar Reference Set contents as Fortigate-compatible "
            "External Block List feeds."
        ),
        lifespan=lifespan,
    )
    app.state.settings = settings

    async def _feed_response(request: Request, feed_type: str) -> PlainTextResponse:
        store: FeedStore = request.app.state.store
        entries = await store.get(feed_type)
        last_sync = store.last_sync
        body = "\n".join(entries)
        if body:
            body += "\n"  # trailing newline per EBL convention
        headers = {
            "X-Entry-Count": str(len(entries)),
            "X-Last-Sync": last_sync.isoformat() if last_sync else "never",
            "Cache-Control": "no-cache",
        }
        return PlainTextResponse(
            content=body,
            media_type="text/plain; charset=utf-8",
            headers=headers,
        )

    # --- Feed endpoints (one registration per type) -----------------------
    def _make_feed_route(feed_type: str):
        async def _route(request: Request) -> PlainTextResponse:
            return await _feed_response(request, feed_type)

        return _route

    for feed_type, filename in _FEED_FILES.items():
        app.add_api_route(
            f"/feeds/{filename}",
            _make_feed_route(feed_type),
            methods=["GET"],
            response_class=PlainTextResponse,
            dependencies=[Depends(_require_api_key)],
            summary=f"{feed_type} feed",
            tags=["feeds"],
        )

    # --- Health (unauthenticated for container/orchestrator probes) --------
    @app.get("/health", tags=["ops"])
    async def health(request: Request) -> dict[str, object]:
        store: FeedStore = request.app.state.store
        stats = await store.get_stats()
        return {
            "status": "ok",
            "last_sync": stats["last_sync"],
            "counts": stats["counts"],
        }

    # --- Metrics ----------------------------------------------------------
    @app.get("/metrics", dependencies=[Depends(_require_api_key)], tags=["ops"])
    async def metrics(request: Request) -> dict[str, object]:
        store: FeedStore = request.app.state.store
        stats = await store.get_stats()
        return {
            "last_sync": stats["last_sync"],
            "last_sync_duration_ms": stats["last_sync_duration_ms"],
            "sync_count": stats["sync_count"],
            "error_count": stats["error_count"],
            "counts": stats["counts"],
        }

    # --- Admin: trigger immediate sync ------------------------------------
    @app.post(
        "/admin/sync",
        dependencies=[Depends(_require_api_key)],
        tags=["admin"],
    )
    async def admin_sync(request: Request) -> dict[str, str]:
        sync_service: SyncService = request.app.state.sync_service
        sync_service.trigger_now()
        return {"status": "started", "message": "Sync triggered"}

    return app


# Module-level app for `uvicorn app.main:app` and the container CMD.
app = create_app()


def main() -> None:
    """Run the service over HTTPS (self-signed) or plain HTTP.

    HTTPS is the default. Set ``ENABLE_TLS=false`` to serve plain HTTP — useful
    when a downstream consumer (e.g. Fortigate) cannot validate the self-signed
    certificate, or when TLS is terminated by an upstream proxy/load balancer.
    """
    import uvicorn

    settings = get_settings()
    configure_logging(settings.log_level, settings.log_dir)

    ssl_kwargs: dict[str, str] = {}
    if settings.enable_tls:
        from .tls import ensure_certificate

        cert_path, key_path = ensure_certificate(settings.cert_dir)
        ssl_kwargs = {"ssl_certfile": cert_path, "ssl_keyfile": key_path}
    else:
        logger.warning(
            "TLS is DISABLED (ENABLE_TLS=false): serving plain HTTP. The feed "
            "API key travels in cleartext — only do this on a trusted network "
            "or behind a TLS-terminating proxy.",
            extra={"scheme": "http", "port": settings.service_port},
        )

    uvicorn.run(
        app,
        host="0.0.0.0",  # noqa: S104 - bind all interfaces inside container
        port=settings.service_port,
        log_config=None,  # keep our JSON logging configuration
        access_log=True,
        **ssl_kwargs,
    )


if __name__ == "__main__":
    main()
