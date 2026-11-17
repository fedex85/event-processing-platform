# Real-Time Inventory Event Platform

An event-driven platform that ingests stock changes from stores, processes them asynchronously and turns them into alerts and trends. It is a portfolio project built to show production-minded backend work: API design, asynchronous processing, spike absorption, idempotency, observability and cloud-native deployment on Google Cloud.

> **Status: Phase 3 of 5 (processing).** The API ingests and publishes events; the processor consumes them from Pub/Sub, deduplicates them by `event_id`, applies the alert rules and writes events and alerts to BigQuery. Analytics queries and infrastructure land in the next phases.

## Architecture

```text
Store / simulator
      │  POST /v1/events
      ▼
inventory-api (Cloud Run)  ── validates, authenticates, publishes
      │
      ▼
Pub/Sub topic: stock-events  ── absorbs traffic spikes, retries, dead-letter queue
      │  push subscription
      ▼
inventory-processor (Cloud Run)
      ├── BigQuery: stock_events
      ├── BigQuery: stock_alerts
      └── alerts (log / webhook)
```

The API answers `202 Accepted` once the event is published; it never runs business logic. Everything heavier happens in the processor, so a burst of traffic queues up in Pub/Sub instead of overloading anything.

| Service | Responsibility |
|---|---|
| `api/` | REST ingestion and queries: validation, API-key auth, publishing, alerts and trends endpoints |
| `processor/` | Pub/Sub push consumer: deduplication, BigQuery writes, alert rules |
| `common/` | Code both services share: event contract, structured logging, error handling, health |

Each service keeps a light hexagonal layout: entry points (`routes`, `consumers`) call `services`, which use `domain` logic and reach Google Cloud only through small adapters (`publishers`, `repositories`) that are injected, so tests never need Google Cloud.

## Roadmap

| Phase | Scope | State |
|---|---|---|
| 1 | Foundations: structure, config, logging, errors, health, validation, Docker | Done |
| 2 | Ingestion: `POST /v1/events`, `:batch`, API keys, Pub/Sub publishing, idempotency, rate limiting, simulator | Done |
| 3 | Processing: push endpoint, BigQuery writes, deduplication, retries, DLQ-ready errors, alert rules | Done (BigQuery adapter not yet run against a real project) |
| 4 | Analytics: `GET /v1/alerts`, `GET /v1/metrics/stock-trends`, `v_stock_trends` view | Next |
| 5 | Infrastructure: Terraform, CI/CD, runbook | |

## Getting started

Requirements: Python 3.12 and `make` (Linux, macOS, WSL or Git Bash). [`uv`](https://docs.astral.sh/uv/) is used when installed.

```bash
cp .env.example .env
make install          # creates .venv and installs the project with dev tools
make check            # ruff + mypy + pytest
make run-api          # http://localhost:8080/v1/health
make run-processor    # http://localhost:8081/v1/health
```

Send simulated traffic (with `PUBSUB_TOPIC_ID` empty the API only logs the events, so no Google Cloud is needed; the processor needs Pub/Sub to receive anything, so locally it is exercised through its tests or by posting a push envelope, see [`docs/runbook.md`](docs/runbook.md)):

```bash
python -m simulator.store_simulator --api-key local-dev-key-change-me --events 200
python -m simulator.store_simulator --api-key local-dev-key-change-me --events 5000 --batch-size 100 --rate 0
```

On Windows PowerShell, run the underlying commands directly: create a virtualenv with `py -3.12 -m venv`, `pip install -e ".[dev]"`, then `ruff`, `mypy`, `pytest` and `python -m flask --app "api.app:create_app" run`.

If the repository lives in a OneDrive or Dropbox folder, keep the virtualenv outside it: `make install VENV=$HOME/.venvs/inventory` and pass the same `VENV` to the other targets.

Docker images are built from the repository root:

```bash
make docker-api
make docker-processor
docker run --rm -p 8080:8080 inventory-api:local
```

## API

| Endpoint | Purpose |
|---|---|
| `GET /v1/health` | Liveness check (no key needed) |
| `POST /v1/events` | Ingest one event; `202` once Pub/Sub has confirmed it |
| `POST /v1/events:batch` | Ingest up to 100 events; valid ones are published even if others are rejected (`207`) |
| `POST /internal/pubsub` | (processor) Pub/Sub push endpoint; not for clients, protected by Cloud Run IAM |

Requests carry an `X-API-Key` header. Details, status codes and examples are in [`docs/api.md`](docs/api.md).

## Configuration

Settings come from environment variables (see [`.env.example`](.env.example)). Nothing about a project, region, URL or credential is hardcoded. Outside `ENVIRONMENT=local` the services refuse to start without `GCP_PROJECT_ID` (and, for the API, `API_KEYS`).

## Event contract

```json
{
  "event_id": "evt_01J5Z8K9Q2M7",
  "store_id": "store_014",
  "sku": "SKU-88231",
  "event_type": "STOCK_UPDATED",
  "quantity": 3,
  "previous_quantity": 18,
  "unit": "units",
  "occurred_at": "2026-11-16T19:40:12Z",
  "source": "pos-system",
  "metadata": { "region": "asturias", "channel": "physical_store" }
}
```

Validation is strict: integers must be real integers, `occurred_at` must be an ISO 8601 timestamp that includes a timezone, and unknown fields are rejected. Invalid payloads get `400` with the problems listed per field:

```json
{
  "status": "rejected",
  "errors": [
    { "field": "quantity", "message": "must be an integer greater than or equal to 0" }
  ]
}
```

## Technical decisions

- **Two services, one repository.** The API stays fast and stateless; the processor scales on Pub/Sub delivery. Shared code lives in `common/` so the contract cannot drift between them.
- **Structured JSON logs** using Cloud Logging's field names, with `trace_id`, `event_id`, `store_id` and `sku` attached to every line through a context variable.
- **Errors are always JSON.** Unexpected exceptions are logged with a stack trace but never returned to the client.
- **Timestamps without a timezone are rejected** rather than guessed, because a wrong guess silently corrupts hourly aggregations.
- **`202` means Pub/Sub has the event.** The API waits for the broker's confirmation, so a client can retry safely; it never reports success for an event that was not published.
- **Per-instance idempotency and rate limiting** (no Redis): both are optimizations in front of Pub/Sub. The processor deduplicates by `event_id` in BigQuery, so they cannot cause data loss or duplicates downstream.
- **The event row is the commit marker.** The processor writes alerts first and the event last, so a failure at any point is repaired by Pub/Sub's redelivery. Alerts have deterministic ids, so a retry never creates a second alert.
- **Poison messages get `400`, storage trouble gets `503`.** Pub/Sub's dead-letter policy (Phase 5) moves a message aside after N failed deliveries; nothing is silently dropped.
- **`insert_rows_json` instead of the Storage Write API**, with `insertId`, retries and a documented trade-off (see `processor/repositories/bigquery.py`). The adapter sits behind a port, so a Storage Write API adapter can replace it later.

More detail in [`docs/architecture.md`](docs/architecture.md) and [`docs/api.md`](docs/api.md).
