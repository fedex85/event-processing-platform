# Build from the repository root:
#   docker build -f docker/api.Dockerfile -t inventory-api:local .

# --- Build stage: install the project and its dependencies into a virtualenv ---
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml README.md ./
COPY common ./common
COPY api ./api
RUN pip install ".[api]"

# --- Runtime stage: only the virtualenv, running as a non-root user ---
FROM python:3.12-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

RUN useradd --system --no-create-home --uid 10001 appuser
COPY --from=builder /opt/venv /opt/venv
USER appuser

EXPOSE 8080

# Shell form so ${PORT} (set by Cloud Run) is expanded; exec keeps gunicorn as PID 1.
CMD exec gunicorn "api.app:create_app()" \
    --bind "0.0.0.0:${PORT}" \
    --workers "${WEB_CONCURRENCY:-2}" \
    --threads "${GUNICORN_THREADS:-8}" \
    --timeout 60
