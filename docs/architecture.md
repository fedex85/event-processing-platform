# Architecture

## Overview

```text
Store / simulator ──POST /v1/events──▶ inventory-api ──publish──▶ Pub/Sub (stock-events)
                                                                      │ push
                                                                      ▼
                                                            inventory-processor
                                                              │            │
                                                              ▼            ▼
                                                  BigQuery stock_events   BigQuery stock_alerts
```

Two independently deployed Cloud Run services share only the event contract (`common/events.py`).

## Layers

Each service separates entry points from use cases and from infrastructure:

| Layer | Folders | Rule |
|---|---|---|
| Entry | `routes/`, `consumers/` | Translate HTTP / Pub/Sub into calls to services; no business logic |
| Application | `services/` | One use case per class; receive adapters through the constructor |
| Domain | `domain/`, `rules/` | Pure Python, no I/O, trivially unit-testable |
| Adapters | `publishers/`, `repositories/` | The only code that talks to Pub/Sub or BigQuery, behind small interfaces |

`api/dependencies.py` builds the object graph. `create_app(settings, dependencies=...)` accepts a prebuilt graph, which is how tests run the real routes against a fake publisher.

## Ingestion flow (`inventory-api`)

1. `before_request` on the events blueprint: API key check, then rate limit (so unauthenticated traffic never consumes a client's quota).
2. Validate the body with `StockEvent` (strict, see below).
3. `IngestionService.ingest_many` skips ids it published recently, publishes the rest in one call and reports an outcome per event.
4. `202` once Pub/Sub has confirmed the messages. Nothing heavier runs in the request.

### The Pub/Sub message

`data` is the JSON of `IngestedStockEvent`: the validated event plus `ingested_at` (UTC). `occurred_at` and `ingested_at` are ISO 8601 with `Z`.

| Attribute | Purpose |
|---|---|
| `event_id`, `store_id`, `sku`, `event_type` | Filtering and logging without decoding the body |
| `trace_id` | Carries the request's trace into the processor's logs |
| `schema_version` | `"1"`; lets the processor handle future formats |

## Processing flow (`inventory-processor`)

```text
Pub/Sub push ──▶ POST /internal/pubsub
                   1. parse the push envelope (base64 data, attributes, deliveryAttempt)
                   2. validate the event with IngestedStockEvent
                   3. one BigQuery query: is event_id already stored? + max stock in the last window
                   4. duplicate        ─▶ log, 204
                   5. evaluate rules   ─▶ alerts
                   6. write alerts, then write the event      (the event row is the commit marker)
                   7. 204
```

### Answers Pub/Sub understands

| Situation | Response | Effect |
|---|---|---|
| Processed, or an ignored duplicate | `204` | Message acknowledged |
| Bad envelope, bad base64, unsupported `schema_version`, invalid event | `400` | Retried until the subscription's dead-letter policy moves it to the DLQ |
| BigQuery transient failure after in-process retries | `503` | Redelivered with backoff |
| BigQuery rejected the write (schema, permissions) | `500` | Redelivered, then dead-lettered; needs a human |
| Unexpected exception | `500` | Same, logged with stack trace |

Responses never echo message content or BigQuery error text.

### Why alerts are written before the event

A redelivered message counts as a duplicate only if its event row exists. Writing the event last makes every partial failure recoverable:

- failure before the event is stored: nothing marks the message as done, so the retry redoes everything;
- failure while storing the event: alerts may already exist, and the retry writes the same alerts again with the same `alert_id` (`uuid5(event_id, alert_type)`, also used as BigQuery `insertId`), so no second alert appears.

### Rules

Only `STOCK_UPDATED` events are judged, because for `SALE` and `RESTOCK` the quantity is a number of units moved, not a stock level.

| Alert | Condition | Severity |
|---|---|---|
| `OUT_OF_STOCK` | `quantity == 0` | CRITICAL |
| `LOW_STOCK` | `0 < quantity <= LOW_STOCK_THRESHOLD` (0 is left to `OUT_OF_STOCK`) | MEDIUM |
| `RAPID_STOCK_DROP` | drop strictly greater than `RAPID_DROP_RATIO` from the baseline, baseline at least `RAPID_DROP_MIN_BASELINE` | HIGH |

The rapid-drop baseline is the higher of the event's own `previous_quantity` and the highest `STOCK_UPDATED` quantity of the same store and SKU in the previous `RAPID_DROP_WINDOW_MINUTES`. Using the maximum catches a slow slide made of several small updates. `alerts.details` records the baseline, its source and the ratio.

Rules are pure functions in `processor/rules/`; thresholds come from settings.

### BigQuery access

One query answers both the duplicate check and the history. It filters on `occurred_at` (partition pruning) and on `store_id`, `sku` (clustering), over a window that ends at the event's own `occurred_at`, so a resent duplicate falls inside it. Values are query parameters; table names are validated at start-up because they are part of the SQL.

Writes use `insert_rows_json` with `insertId`. Transient failures (HTTP 408/429/5xx, timeouts, and row errors `backendError`/`internalError`) are retried with exponential backoff and full jitter; anything else fails immediately.

| Limitation | Consequence |
|---|---|
| `insertId` deduplication is best effort | Two instances handling the same duplicate at the same moment can both insert. `v_stock_trends` and the alerts query deduplicate (by `event_id` and `alert_id`) |
| Duplicate detection is scoped to the same store, SKU and `occurred_at` | An event id reused with different content is treated as a new event |
| Streaming-buffer rows cannot be `UPDATE`d or `DELETE`d for a while | The pipeline only appends |
| Duplicate and history lookups cost one query per message | Acceptable at this scale; revisit if volume grows |

The adapter is behind `EventRepository` / `AlertRepository`, so a Storage Write API implementation can replace it without touching the domain.

## Cross-cutting concerns

- **Configuration:** `pydantic-settings`, environment variables only. Deployed environments fail fast when required values are missing (`GCP_PROJECT_ID`, `API_KEYS`, `PUBSUB_TOPIC_ID`).
- **Logging:** one JSON object per line, Cloud Logging field names, correlation fields (`trace_id`, `event_id`, `store_id`, `sku`, `client_id`) from a context variable. Health checks log at DEBUG.
- **Tracing:** `X-Cloud-Trace-Context` is honored; otherwise a trace id is generated. The id is returned in `X-Trace-Id` and forwarded as a Pub/Sub attribute.
- **Errors:** global handlers turn every failure into JSON. Validation failures never echo the rejected values; broker errors stay in the logs.

## Decisions

| Decision | Reason |
|---|---|
| Shared `common/` package | One definition of the event contract and of logging/error behavior |
| Strict validation (no type coercion, timezone required, 255-character limit on text fields) | A silently coerced value corrupts analytics later; the limit also keeps values inside Pub/Sub attribute limits |
| Batch: valid events are published even if others are invalid (`207`) | One bad event should not make a store lose the other 99 |
| An id is remembered only after Pub/Sub confirms it | A failed publish can always be retried; the API never reports "duplicate" for something that was not published |
| Idempotency and rate limiting held in memory, per process (worker) | Without Redis there is no shared state. Both are optimizations: the processor deduplicates by `event_id` in BigQuery, and `max-instances` bounds the total request rate |
| Log-only publisher in local development | Lets the API and simulator run with no Google Cloud; refused outside `ENVIRONMENT=local` by configuration validation |
| Publish and wait for confirmation before answering | `202` means "Pub/Sub has it", which is what makes the system safe to retry |

## Read side (`inventory-api`)

`GET /v1/alerts` and `GET /v1/metrics/stock-trends` read BigQuery through the same ports-and-adapters layout as the rest: routes parse the query string (`api/query_params.py`), `AnalyticsService` resolves the time window and pagination, and an `AnalyticsRepository` port is implemented by `BigQueryAnalyticsRepository` (production) and `EmptyAnalyticsRepository` (local runs without a project). The shared BigQuery gateway and retry helper live in `common/` and are used by both services.

| Decision | Reason |
|---|---|
| Every query has a lower time bound (defaults: alerts 7 days, trends 24 hours) | `stock_events` is partitioned by `DATE(occurred_at)` and `stock_alerts` by `DATE(detected_at)`: a bound limits the bytes scanned and the cost |
| Client values are only ever query parameters | No string interpolation; table names come from validated settings |
| `has_more` instead of a total | A count would scan the whole window on every call |
| Fetch `limit + 1` rows | Detects another page without a second query |
| Alerts deduplicated with `QUALIFY ROW_NUMBER() ... PARTITION BY alert_id` | `insertId` deduplication is best effort |
| Trends view deduplicates by `(event_id, occurred_at)` | Duplicates share both; keeps partition pruning possible |
| Few retries, short timeout (read path is synchronous) | A caller is waiting; a 503 with `Retry-After` is better than a slow answer |
| Reads share the API-key rate limit | A key cannot bypass the limit by using GET |

Known risk: partition pruning through the view is not guaranteed. Check it with `bq query --dry_run` (see the runbook) and, if the bytes processed are too high, replace the view with a table function.

## Infrastructure (Terraform)

One root module (`infra/`) composes small modules; each environment is the same code with its own project and `tfvars`.

| Module | Creates |
|---|---|
| `apis` | Enables the Google APIs the platform uses |
| `service_accounts` | Runtime accounts for the API, the processor and the Pub/Sub push subscription, with `bigquery.jobUser` |
| `artifact_registry` | Docker repository with cleanup policies |
| `secrets` | The API-keys secret (container only, no value) and its reader |
| `bigquery` | Dataset, `stock_events` (partitioned by `occurred_at`) and `stock_alerts` (partitioned by `detected_at`), both clustered by `store_id, sku`, the `v_stock_trends` view, and dataset-level grants |
| `cloud_run_service` | A Cloud Run service (used for the API and the processor) |
| `pubsub` | Topic, push subscription with OIDC, retry backoff, dead-letter topic and pull subscription, agent grants |
| `github_wif` | Workload Identity Federation for GitHub Actions and the deployer account (optional) |
| `monitoring` | Alert policies: dead-letter messages, processor backlog, 5xx per service; optional email channel |

| Decision | Reason |
|---|---|
| The processor is not publicly invokable; only the push subscription's service account has `run.invoker`, and Pub/Sub signs an OIDC token for it | The processor has no authentication of its own |
| Terraform creates the services with a placeholder image and ignores later image changes | The images do not exist before the first deployment, and CI owns every release after that. Infrastructure and releases change independently |
| The secret's value is added by hand | Keeps the keys out of Terraform state and the repository |
| Least-privilege IAM at dataset, topic, secret and repository level | The API can read but not write BigQuery; the processor can append but cannot publish |
| Dead-letter after 5 attempts with 10 s to 600 s backoff, 7-day retention | A transient outage is retried for about an hour; a message that can never succeed stops blocking and stays inspectable |
| `ack_deadline` 60 s, request timeout 60 s | A worst-case run (three BigQuery operations with retries) fits |
| Cloud Run concurrency 16 | Matches gunicorn's 2 workers x 8 threads |
| `max_instances` per service | Bounds the cost of a traffic spike and the write pressure on BigQuery |
| One GCP project, one state prefix and one set of GitHub environment variables per environment | Staging mistakes cannot touch production |
| Workload Identity Federation restricted to the repository (and environment) | No long-lived service account keys exist |

Known limit: none of this has been applied to a real project yet. Run `terraform plan` and review it before the first apply.

## Planned

A shared rate-limit and idempotency store, alert cooldown, the remaining rules (sales spike, store without data) and a Storage Write API adapter are outside the current scope.
