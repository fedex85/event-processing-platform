# Security notes

What the services do to protect themselves, and what is deliberately left to the platform or to later phases.

## Controls in place

| Area | Control |
|---|---|
| Authentication | `X-API-Key` on every `/v1` endpoint except health. Keys are compared in constant time against every configured key; outside `ENVIRONMENT=local` each key needs at least 24 characters. Logs carry only a 12-character hash of the key |
| Authorization of the processor | `/internal/pubsub` has no application-level auth. Terraform deploys the processor without `allUsers` and grants `run.invoker` only to the push subscription's service account |
| Input validation | Strict Pydantic models, unknown fields rejected, integers and ISO 8601 timestamps strict, strings capped at 255 characters, `metadata` capped at 4096 bytes of plain JSON (no `NaN`) |
| Request size | `MAX_REQUEST_BYTES` (default 1 MiB) answers `413` before the body is buffered; absurdly nested JSON answers `400` |
| SQL injection | Client values are only ever BigQuery query parameters. Project, dataset, table and view names come from settings and are validated at start-up by `common.bigquery.qualified_name` |
| Query cost | `BQ_MAX_BYTES_BILLED` (default 1 GB) makes BigQuery refuse a query that would scan more; the read endpoints also bound their windows and offsets |
| Error handling | Errors never echo input values or internal details; unexpected errors return a generic 500 and the stack trace stays in the logs |
| Logging | Structured JSON; query strings are never logged (only the path); trace ids from headers must be 32 hex characters |
| Responses | `Cache-Control: no-store` and `X-Content-Type-Options: nosniff` |
| Containers | Multi-stage build, non-root user, `.dockerignore` excludes `.env`, tests and docs |
| Deployment identity | GitHub Actions authenticates with Workload Identity Federation (no service account keys), limited to one repository and, when set, one GitHub environment; production needs a reviewer's approval |
| Secrets | None in the repository; `API_KEYS` is a `SecretStr` and is hidden from `repr`. `.gitignore` covers `.env*`, keys and Terraform state |

## Known gaps

| Gap | Impact | Plan |
|---|---|---|
| Rate limit and idempotency memory are per gunicorn worker, so the real limit is `RATE_LIMIT_PER_MINUTE` x workers x instances | A client can exceed the nominal quota | Acceptable as a safety net; a shared store is out of scope for the stack |
| Requests with a wrong API key are not rate limited | Online key guessing is possible | Long keys make it impractical; add Cloud Armor or an API gateway in front for production |
| API keys are shared secrets with no expiry or per-key scopes | A leaked key stays valid until rotated | Rotate through Secret Manager versions; a comma-separated list allows overlap while rotating |
| Dependencies are version-ranged, not locked | Builds are not bit-for-bit reproducible | Dependabot now proposes updates weekly; add a lock file (for example `uv lock`) when network access allows |
| Base image tag is not pinned by digest | Image contents can change between builds | Pin `python:3.12-slim` by digest in the Dockerfiles |
| GitHub Actions are pinned by major version, not by commit SHA | A compromised tag could run in the pipeline | Pin by SHA; Dependabot keeps them current |
| The Terraform and the pipeline have never run against a real project | Mistakes show up on first use | Read `terraform plan` before the first apply; start with staging |
| `insertId` deduplication is best effort | Rare duplicate rows in BigQuery | Reads deduplicate by `event_id` / `alert_id` |
| The BigQuery adapters have not run against a real project | Behaviour in production is unproven | Run the simulator end to end after the first deployment |
