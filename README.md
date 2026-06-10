# QRadar IOC Exporter

Bridge **IBM QRadar Reference Sets** to **Fortigate External Block Lists (EBL)**.

QRadar stores threat indicators (IPs, file hashes, domains, URLs) in Reference
Sets, often with a configured TTL. Fortigate firewalls can consume an
**External Block List** — a plain-text file served over HTTP(S), one indicator
per line — but they cannot speak the QRadar REST API directly.

This service polls QRadar Reference Sets on a schedule and re-serves their
contents as Fortigate-compatible plain-text feeds over HTTPS on port `8443`.

---

## 1. Overview & Architecture

```
            poll (SEC token, HTTPS)             serve (Bearer token, HTTPS)
  ┌───────────────┐   every N seconds   ┌──────────────────────┐   GET *.txt   ┌───────────────┐
  │               │ ──────────────────► │                      │ ◄──────────── │               │
  │  IBM QRadar   │   GET /api/         │  qradar-ioc-exporter │               │   Fortigate   │
  │   Console     │   reference_data/   │                      │ ────────────► │   (EBL/Feed)  │
  │               │   sets/{name}       │  ┌────────────────┐  │   text/plain  │               │
  └───────────────┘ ◄────────────────── │  │  FeedStore     │  │               └───────────────┘
                       data: [values]   │  │  (in-memory)   │  │
                                        │  └────────────────┘  │
                                        │  APScheduler (async) │
                                        │  FastAPI + uvicorn   │
                                        │  self-signed TLS     │
                                        └──────────────────────┘

  Flow:
   1. APScheduler fires sync_all_feeds() every SYNC_INTERVAL_SECONDS.
   2. QRadarClient fetches all four reference sets concurrently (paginated, retried).
   3. Successful results replace the in-memory FeedStore; failed sets keep prior data.
   4. Fortigate (or curl) pulls /feeds/<type>.txt with a Bearer token over HTTPS.
```

**Design properties**

- **Fully async** — httpx, FastAPI, APScheduler `AsyncIOScheduler`; no blocking
  calls on the event loop.
- **Fail-open feed service** — the API starts and serves (empty) feeds even if
  QRadar is unreachable at startup. A failing reference set never crashes the
  sync or overwrites previously-good data with nothing.
- **No nginx** — a self-signed certificate is generated at first startup and
  uvicorn terminates TLS directly. TLS can be turned off (`ENABLE_TLS=false`)
  to serve plain HTTP when a consumer can't validate the self-signed cert.
- **Structured JSON logs** to stdout and a rotating `logs/app.log`; secrets are
  never serialised.

---

## 2. Prerequisites

| Requirement | Notes |
|-------------|-------|
| Docker + Docker Compose | Recommended deployment path. |
| (or) Python 3.12+ | For running locally without Docker. |
| QRadar Console reachable on 443 | With a **Security Token** (SEC) that can read Reference Data. |
| QRadar Reference Sets created | See [§5](#5-qradar-setup). |
| Fortigate FortiOS 6.2+ | External Block List feature. Bearer auth header support is solid on **7.0+**. |

---

## 3. Quick Start

```bash
# 1. Configure
cp .env.example .env && $EDITOR .env      # set QRADAR_HOST, QRADAR_API_TOKEN, API_KEY

# 2. Build
make build                                 # docker compose build

# 3. Run
make up                                     # docker compose up -d

# 4. Watch it sync
make logs                                   # docker compose logs -f

# 5. Verify
make health                                 # curl -sk https://localhost:8443/health
```

Then fetch a feed (note the Bearer token from `API_KEY`):

```bash
curl -sk -H "Authorization: Bearer changeme-secret-key" \
     https://localhost:8443/feeds/ip.txt
```

---

## 4. Configuration Reference

All configuration is via environment variables (or a `.env` file). Copy
`.env.example` to `.env` and edit.

| Variable | Default | Description |
|----------|---------|-------------|
| `QRADAR_HOST` | `127.0.0.1` | QRadar Console IP or FQDN. Scheme is stripped if you paste a URL. |
| `QRADAR_API_TOKEN` | _(empty)_ | QRadar **SEC** authorization token. |
| `QRADAR_VERIFY_SSL` | `false` | Verify QRadar's TLS cert. Keep `false` for QRadar's default self-signed cert; set `true` with a valid CA. |
| `QRADAR_API_VERSION` | `20.0` | Value sent in the `Version` header. |
| `REFSET_IP` | `Blocked_IPs` | Reference set name for the IP feed. |
| `REFSET_HASH` | `Blocked_Hashes` | Reference set name for the hash feed. |
| `REFSET_DOMAIN` | `Blocked_Domains` | Reference set name for the domain feed. |
| `REFSET_URL` | `Blocked_URLs` | Reference set name for the URL feed. |
| `SYNC_INTERVAL_SECONDS` | `300` | Seconds between QRadar polls (min `10`). |
| `INITIAL_SYNC_ON_STARTUP` | `true` | Run one sync immediately on startup (non-blocking). |
| `SERVICE_PORT` | `8443` | Listen port. |
| `ENABLE_TLS` | `true` | `true` = HTTPS with a self-signed cert. `false` = plain HTTP (see [§6](#6-fortigate-integration)). |
| `LOG_LEVEL` | `INFO` | `DEBUG`/`INFO`/`WARNING`/`ERROR`/`CRITICAL`. |
| `REQUIRE_AUTH` | `true` | Require a Bearer token on feed/metrics/admin endpoints. Set `false` (or leave `API_KEY` empty) to serve feeds **without authentication**. |
| `API_KEY` | `changeme-secret-key` | **Bearer token required to read feeds, metrics and trigger sync** (when `REQUIRE_AUTH=true`). Change this. |

> ⚠️ **Reference set names must match QRadar exactly.** Prefer underscores over
> spaces (`Blocked_IPs`, not `Blocked IPs`) to avoid encoding issues.

---

## 5. QRadar Setup

### 5.1 Create the Reference Sets

In the QRadar Console: **Admin → Reference Set Management → Add**. Create one
set per indicator type, for example:

| Feed | Reference Set name | Element type |
|------|--------------------|--------------|
| IP | `Blocked_IPs` | `IP` |
| Hash | `Blocked_Hashes` | `ALNIC` (alphanumeric) |
| Domain | `Blocked_Domains` | `ALNIC` |
| URL | `Blocked_URLs` | `ALNIC` |

Set a **Time-to-Live** if you want indicators to expire automatically; this
service simply mirrors whatever QRadar currently returns.

### 5.2 API token permissions

Create an **Authorized Service** token under
**Admin → Authorized Services** (or use the **API Token** of a user). The token
only needs **read** access to the Reference Data API:

- Capability: `RESTAPICapabilities` → **READ** on `/api/reference_data/sets`.
- **No write/delete permission is required** — the exporter only reads.

The token is sent to QRadar in the `SEC` header (not as a Bearer token).

### 5.3 Verify by hand

```bash
curl -k -H "SEC: <your-token>" -H "Version: 20.0" \
  "https://<QRADAR_HOST>/api/reference_data/sets/Blocked_IPs?fields=number_of_elements,data"
```

You should get JSON containing `number_of_elements` and a `data` array of
`{"value": ...}` objects.

---

## 6. Fortigate Integration

The exporter serves each indicator type at a stable HTTPS URL. On the Fortigate,
configure an **External Block List (Threat Feed)** connector pointing at the
relevant feed.

**FortiOS UI paths** (exact wording varies by version):

- IP feed → **Security Fabric → External Connectors → Threat Feeds → IP Address**,
  or **Security Profiles → DNS Filter → External IP Block List**.
- Domain feed → **Security Fabric → External Connectors → Threat Feeds → Domain Name**.
- URL feed → **Security Profiles → Web Filter → Static URL Filter → External Block List**,
  or Threat Feeds → **Malware Hash** for the hash feed.

**Feed URL format**

```
https://<HOST>:8443/feeds/ip.txt
https://<HOST>:8443/feeds/domain.txt
https://<HOST>:8443/feeds/url.txt
https://<HOST>:8443/feeds/hash.txt
```

**Authentication.** Every feed endpoint requires
`Authorization: Bearer <API_KEY>`. Configure this in the Fortigate threat-feed
connector's HTTP header settings (FortiOS 7.0+ supports custom request headers /
basic auth on external connectors). Set:

```
Header name:  Authorization
Header value: Bearer <your API_KEY>
```

**TLS — three options.** By default the exporter serves HTTPS with a
*self-signed* certificate, which Fortigate will not trust out of the box. Pick
one:

1. **Plain HTTP (simplest).** Set `ENABLE_TLS=false` and point Fortigate at
   `http://<HOST>:8443/feeds/...`. No certificate to manage. Because the
   `API_KEY` then travels in cleartext, only use this on a trusted/management
   segment or behind a TLS-terminating reverse proxy. This is usually the
   easiest path to get Fortigate reading the feed.
2. **Self-signed, trusted.** Keep HTTPS and import `certs/server.crt` into the
   Fortigate's trusted CA store (or disable cert validation on the connector —
   lab only).
3. **CA-signed (production).** Keep HTTPS and mount your own
   `certs/server.crt` / `certs/server.key` (a real cert) — these are reused if
   present, so no self-signed cert is generated.

**Refresh interval.** Set the Fortigate's feed refresh to be ≥
`SYNC_INTERVAL_SECONDS` so it never polls faster than the exporter updates.

---

## 7. Feed & Endpoint Reference

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/feeds/ip.txt` | Bearer² | Blocked IPs, one per line. |
| `GET` | `/feeds/hash.txt` | Bearer² | Blocked file hashes, one per line. |
| `GET` | `/feeds/domain.txt` | Bearer² | Blocked domains, one per line. |
| `GET` | `/feeds/url.txt` | Bearer² | Blocked URLs, one per line. |
| `GET` | `/health` | none¹ | `{"status":"ok","last_sync":...,"counts":{...}}` |
| `GET` | `/metrics` | Bearer² | Sync stats: duration, counts, sync/error totals. |
| `POST` | `/admin/sync` | Bearer² | Trigger an immediate sync. |

¹ `/health` is intentionally unauthenticated so container/orchestrator probes
(including this image's `HEALTHCHECK`) can reach it without credentials.

² Bearer auth applies only when `REQUIRE_AUTH=true` (default) **and** `API_KEY`
is non-empty. With `REQUIRE_AUTH=false` (or an empty `API_KEY`) these endpoints
are served without authentication — convenient for older FortiOS that can't send
a custom header, but only safe on a trusted network.

**Feed response contract**

- `Content-Type: text/plain; charset=utf-8`
- One entry per line, trailing newline; no comments or headers.
- Empty / not-yet-synced set → **HTTP 200 with an empty body** (never 404).
- Response headers `X-Entry-Count` and `X-Last-Sync` expose freshness.

---

## 8. Troubleshooting

| Symptom | Likely cause & fix |
|---------|--------------------|
| Feed returns **401** | Missing/incorrect `Authorization: Bearer <API_KEY>` header. Confirm `API_KEY` matches on both sides. |
| Logs show **`Reference set not found`** | `REFSET_*` name doesn't match QRadar exactly (case/space/underscore). Verify with the curl in §5.3. |
| Logs show **`Authentication/authorization failed` (401/403)** from QRadar | Bad/expired `QRADAR_API_TOKEN`, or the token lacks Reference Data read capability. |
| Logs show **connection errors / `Exhausted 3 retries`** | QRadar host unreachable, wrong `QRADAR_HOST`, or firewall blocking 443. The service stays up and serves last-known data. |
| **TLS / certificate** errors when QRadar is polled | QRadar uses a self-signed cert → keep `QRADAR_VERIFY_SSL=false` (default), or set `true` only with a valid CA chain. |
| Fortigate can't validate the feed's cert / connector stays "offline" | Self-signed cert isn't trusted. Quickest fix: `ENABLE_TLS=false` and use `http://...`. Otherwise import `certs/server.crt` into Fortigate or use a CA-signed cert (see §6). |
| Feeds are always empty | Check `/metrics` — if `sync_count` is rising but counts are 0, the sets are genuinely empty in QRadar; if `error_count` is rising, inspect the logs. |
| Container unhealthy | `docker compose logs` — the `HEALTHCHECK` curls `/health` over HTTPS; ensure the port mapping and cert generation succeeded. |

Increase visibility with `LOG_LEVEL=DEBUG`.

---

## 9. Development

### Run the test suite

```bash
python -m venv .venv && . .venv/bin/activate     # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
pytest tests/ -v        # or: make test
```

Tests cover the QRadar client (pagination, retry/backoff, 404 & auth errors via
mocked httpx), the thread-safe `FeedStore` (concurrent updates, stats), and all
routes (feeds, auth 401s, empty-feed-is-200, health, metrics, admin).

### Run locally without Docker

```bash
cp .env.example .env        # edit values
pip install -r requirements.txt
python -m app.main          # or: make run
```

This generates `certs/server.{crt,key}` on first run and serves HTTPS on
`SERVICE_PORT`. Trigger a manual sync with `make sync-now`.

### Project layout

```
app/
  config.py          pydantic-settings configuration
  logging_config.py  JSON logging to stdout + rotating file
  feed_store.py      thread-safe in-memory store + stats
  qradar_client.py   async QRadar client (pagination, retry/backoff)
  scheduler.py       APScheduler sync orchestration
  tls.py             self-signed certificate generation
  main.py            FastAPI app, routes, entrypoint
tests/               pytest suite (httpx + respx)
```

### Make targets

```
make build  up  down  logs  test  sync-now  health  install  run  certs  clean
```

---

## License

Provided as-is for internal threat-intelligence integration. Review and harden
(`API_KEY`, certificates, network exposure) before production use.
