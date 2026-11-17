# Build from the repository root:
#   docker build -f docker/processor.Dockerfile -t inventory-processor:local .

# --- Build stage: install the project and its dependencies into a virtualenv ---
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml README.md ./
COPY common ./common
COPY processor ./processor
RUN pip install ".[processor]"

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
CMD exec gunicorn "processor.app:create_app()" \
    --bind "0.0.0.0:${PORT}" \
    --workers "${WEB_CONCURRENCY:-2}" \
    --threads "${GUNICORN_THREADS:-8}" \
    --worker-tmp-dir /dev/shm \
    --timeout 60
