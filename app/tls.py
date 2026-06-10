"""Self-signed TLS certificate generation for the feed server."""

from __future__ import annotations

import datetime
import ipaddress
import logging
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

logger = logging.getLogger("qradar.tls")

COMMON_NAME = "qradar-ioc-exporter"
VALIDITY_DAYS = 3650


def ensure_certificate(cert_dir: str) -> tuple[str, str]:
    """Ensure a self-signed cert/key pair exists in ``cert_dir``.

    If ``server.crt`` and ``server.key`` already exist they are reused.
    Otherwise a new 2048-bit RSA self-signed certificate is generated with
    SANs for ``localhost`` and ``127.0.0.1``.

    Returns ``(cert_path, key_path)``.
    """
    directory = Path(cert_dir)
    directory.mkdir(parents=True, exist_ok=True)
    cert_path = directory / "server.crt"
    key_path = directory / "server.key"

    if cert_path.exists() and key_path.exists():
        logger.info(
            "Using existing TLS certificate",
            extra={"cert_path": str(cert_path)},
        )
        return str(cert_path), str(key_path)

    logger.info("Generating self-signed TLS certificate")

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, COMMON_NAME)])

    now = datetime.datetime.now(datetime.UTC)
    san = x509.SubjectAlternativeName(
        [
            x509.DNSName("localhost"),
            x509.DNSName(COMMON_NAME),
            x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
        ]
    )

    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=VALIDITY_DAYS))
        .add_extension(san, critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))

    # Best-effort lock-down of the private key (no-op semantics on Windows).
    try:
        key_path.chmod(0o600)
    except OSError:  # pragma: no cover - platform dependent
        pass

    logger.info(
        "Self-signed certificate generated",
        extra={"cert_path": str(cert_path), "validity_days": VALIDITY_DAYS},
    )
    return str(cert_path), str(key_path)
