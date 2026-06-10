FROM python:3.14-slim

# Keep Python lean and unbuffered for container logging.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Apply the latest OS security patches: the base image lags behind Debian's
# security repo for freshly disclosed CVEs (e.g. openssl). Intentional full
# upgrade, so DL3005 is suppressed.
# hadolint ignore=DL3005
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first for layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code.
COPY app/ ./app/

# Create a non-root user and writable runtime directories.
RUN useradd -r -u 1001 appuser && \
    mkdir -p /app/certs /app/logs && \
    chown -R appuser:appuser /app

USER appuser

EXPOSE 8443

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=15s \
    CMD ["python", "-m", "app.healthcheck"]

CMD ["python", "-m", "app.main"]
