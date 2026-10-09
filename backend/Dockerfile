# syntax=docker/dockerfile:1
# ---- build stage: compile wheels once --------------------------------------
FROM python:3.12-slim AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /build
COPY requirements.lock ./
# Optional: behind a TLS-intercepting proxy pass its CA:  docker build --secret id=ca_bundle,src=/path/ca.pem ...
RUN --mount=type=secret,id=ca_bundle,required=false \
    if [ -f /run/secrets/ca_bundle ]; then export PIP_CERT=/run/secrets/ca_bundle; fi; \
    pip wheel --wheel-dir /wheels -r requirements.lock

# ---- runtime stage ----------------------------------------------------------
FROM python:3.12-slim AS runtime
# FORWARDED_ALLOW_IPS: X-Forwarded-For is honoured only from private networks (the nginx container), so a client reaching
# the API directly cannot spoof its IP for per-IP rate limits.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    STORAGE_DIR=/data/resumes \
    FORWARDED_ALLOW_IPS=127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16
WORKDIR /app
COPY --from=builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels /wheels/* && rm -rf /wheels \
    && groupadd --system app && useradd --system --gid app --home /app app \
    && mkdir -p /data/resumes && chown -R app:app /data
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app app ./app
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=4).status == 200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--proxy-headers"]
