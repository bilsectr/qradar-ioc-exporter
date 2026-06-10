# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-06-10

### Added
- Async QRadar Reference Data client with automatic pagination and retry/
  exponential backoff.
- Periodic sync (APScheduler) of four reference sets (IP / hash / domain / URL)
  into a thread-safe in-memory store; fail-open so feeds stay available when
  QRadar is unreachable.
- Fortigate-compatible plain-text feed endpoints (`/feeds/*.txt`) plus
  `/health`, `/metrics` and `/admin/sync`.
- `ENABLE_TLS` toggle: self-signed HTTPS by default, or plain HTTP for
  consumers that cannot validate the certificate.
- `REQUIRE_AUTH` toggle: optional `Authorization: Bearer <API_KEY>` on the
  feed/metrics/admin endpoints (constant-time key comparison).
- Structured JSON logging to stdout and a rotating file; secrets are never
  logged.
- Container image (multi-arch amd64/arm64) with non-root user, read-only root
  filesystem, dropped capabilities and `no-new-privileges`.

### Security / CI
- CI: ruff (lint + format), pytest, hadolint, Trivy image scan (SARIF),
  gitleaks secret scan, CodeQL.
- Automated GHCR image publishing: Trivy gate before push, SBOM + provenance
  attestations, keyless cosign signing.
- Dependabot (pip / docker / github-actions) with auto-merge for patch & minor
  updates.

[Unreleased]: https://github.com/bilsectr/qradar-ioc-exporter/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/bilsectr/qradar-ioc-exporter/releases/tag/v1.0.0
