"""Container healthcheck: probe /health using the configured scheme/port.

Run as ``python -m app.healthcheck``. Exits 0 if the service answers 200,
1 otherwise. Reads ``ENABLE_TLS`` and ``SERVICE_PORT`` from the environment so
the probe automatically follows http vs https.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

from .config import get_settings


def main() -> int:
    settings = get_settings()
    url = f"{settings.scheme}://localhost:{settings.service_port}/health"

    # For HTTPS, validate against our own self-signed certificate (its SAN
    # includes localhost / 127.0.0.1) instead of disabling verification. For
    # plain HTTP this value is ignored by httpx.
    verify: str | bool = True
    if settings.enable_tls:
        cert = Path(settings.cert_dir) / "server.crt"
        if cert.exists():
            verify = str(cert)

    try:
        response = httpx.get(url, verify=verify, timeout=5)
    except Exception as exc:  # noqa: BLE001 - any failure is unhealthy
        print(f"healthcheck failed: {exc}", file=sys.stderr)
        return 1
    return 0 if response.status_code == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
