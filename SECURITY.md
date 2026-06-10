# Security Policy

## Reporting a Vulnerability

Please **do not** open a public GitHub issue for security vulnerabilities.

Instead, report privately via GitHub's
[**Private vulnerability reporting**](../../security/advisories/new) (Security →
Advisories → "Report a vulnerability"). Include:

- A description of the issue and its impact.
- Steps to reproduce or a proof of concept.
- Affected version / commit.

You can expect an initial acknowledgement within **5 business days** and a
remediation plan once the report is triaged.

## Supported Versions

The latest commit on the `main` branch is supported. There is no long-term
support branch.

## Operational Security Notes

This service handles threat-intelligence feeds and credentials. When deploying:

- **Change `API_KEY`** from its default and keep `REQUIRE_AUTH=true` unless the
  service is on a fully trusted, isolated network segment.
- **Never commit `.env`** — it contains the QRadar `SEC` token. It is gitignored
  by default; keep it that way and rely on push protection / secret scanning.
- **Prefer TLS.** `ENABLE_TLS=false` serves the API key (when auth is enabled)
  in cleartext; only use it behind a TLS-terminating proxy or on a trusted LAN.
- **QRadar TLS:** set `QRADAR_VERIFY_SSL=true` with a valid CA in production;
  `false` (the default for QRadar's self-signed cert) disables verification.
- Run the container as the provided non-root user and keep the hardening options
  in `docker-compose.yml` (`no-new-privileges`, dropped capabilities,
  read-only root filesystem).
- Rotate the QRadar token and `API_KEY` periodically.
