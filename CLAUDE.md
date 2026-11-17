# CLAUDE.md

Real-Time Inventory Event Platform: two Flask services on Cloud Run (`api/`, `processor/`) connected by Pub/Sub, with BigQuery as the analytical store. Shared code is in `common/`.

## Commands

Run from the repository root with `make` (Linux, macOS, WSL, Git Bash). Override the virtualenv with `VENV=...`.

| Task | Command |
|---|---|
| Install | `make install` |
| Run API | `make run-api` (port 8080) |
| Run processor | `make run-processor` (port 8081) |
| Tests | `make test` (or `.venv/bin/python -m pytest api/tests/test_health.py -k name`) |
| Lint + format check | `make lint` |
| Auto-fix | `make format` |
| Type check | `make typecheck` |
| Everything CI runs | `make check` |
| Docker images | `make docker-api`, `make docker-processor` |
| Simulator | `python -m simulator.store_simulator --api-key <key>` |

`make check` must pass (ruff, mypy strict, pytest) before a phase is considered done.

## Architecture rules

- BigQuery SQL on the read path (`api/repositories/bigquery.py`) uses query parameters only; never interpolate client input. Table names come from validated settings. The view lives in `infra/sql/v_stock_trends.sql` and `api/tests/test_trends_view_sql.py` keeps it in step with the code.

- `api/` and `processor/` never import each other. Anything both need goes in `common/`.
- Layers inside a service: `routes` / `consumers` (entry) -> `services` (use cases) -> `domain` / `rules` (pure logic, no I/O) and `publishers` / `repositories` (adapters for Pub/Sub and BigQuery).
- Google Cloud clients are injected into services, never created inside them, so tests use fakes (`api/tests/fakes.py`, `processor/tests/fakes.py`). Each service's `dependencies.py` builds the real wiring and `create_app(settings, dependencies=...)` accepts a test one.
- Build apps only through `create_app(settings)`; do not create module-level Flask apps.
- Configuration comes from environment variables through `pydantic-settings` (`common/settings.py` and each service's `config.py`). Do not hardcode project ids, regions, URLs or credentials.
- Errors: raise `AppError` / `RejectedError` from `common/errors.py`. The global handlers turn them into JSON; never return stack traces.
- Logs: use `logging.getLogger(__name__)` and `extra={...}`; bind correlation fields with `bind_context(event_id=..., store_id=..., sku=...)`.

## Constraints

- Python 3.12, Flask, Gunicorn, Pydantic v2, Pub/Sub, BigQuery, Terraform.
- Do not add Django, FastAPI, Celery, Redis, Kafka or a relational database as primary storage.
- Do not use `insert_rows_json` without error handling and retries (the only call site is `processor/repositories/bigquery.py`, which classifies errors and retries transient ones).
- Processor write order is fixed: alerts first, event last. The event row is what marks a message as processed; do not reorder.
- No secrets in the repository. `.env` is git-ignored.
- Keep dependencies minimal; justify new ones.

## Working agreement

The project is built in phases (see `README.md`). Finish one phase, run `make check`, report files changed, commands, risks and the next phase, and wait for confirmation before continuing. Every endpoint needs tests and every business rule needs unit tests, using fixtures and factories (`api/tests/factories.py`, `processor/tests/factories.py`).

Infrastructure is Terraform in `infra/` (modules under `infra/modules/`). Check it with `cd infra && terraform fmt -recursive && terraform init -backend=false && terraform validate`; `common/tests/test_terraform_structure.py` checks module inputs and references without Terraform. Never put secrets or service account keys in Terraform; the API-keys secret value is added by hand.

BigQuery table schemas live in `infra/schemas/*.json` (single source of truth for Terraform); a test checks they match what the repository writes.
