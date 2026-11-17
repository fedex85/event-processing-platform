# Runbook

Operational procedures are added as the system gains something to operate. Local development, querying alerts and trends, and the read-side IAM are covered; deployment arrives with Phase 5.

## Run locally

```bash
cp .env.example .env
make install
make run-api         # http://localhost:8080/v1/health
make run-processor   # http://localhost:8081/v1/health
```

On Windows PowerShell, run the same commands without `make` (see the README).

With `PUBSUB_TOPIC_ID` empty and `ENVIRONMENT=local`, the API logs each event (`event_logged_not_published`) instead of publishing it.

### Send traffic with the simulator

```bash
python -m simulator.store_simulator --api-key local-dev-key-change-me --events 200
python -m simulator.store_simulator --api-key local-dev-key-change-me --events 5000 --batch-size 100 --rate 0   # a spike
```

Options: `--url`, `--stores`, `--skus`, `--events`, `--batch-size` (1 to 100), `--rate` (events per second, 0 for no limit) and `--seed` for a reproducible run. The key can also come from `SIMULATOR_API_KEY`.

### Use the Pub/Sub emulator

```bash
gcloud beta emulators pubsub start --project=local-project
# in another terminal, once the emulator prints its host:
export PUBSUB_EMULATOR_HOST=localhost:8085
```

Create the topic in the emulator, then set `GCP_PROJECT_ID=local-project` and `PUBSUB_TOPIC_ID=<topic>` in `.env`. The Google client reads `PUBSUB_EMULATOR_HOST` by itself.

### Try the processor without Pub/Sub

With `GCP_PROJECT_ID` empty the processor keeps everything in memory. Post a push envelope by hand (PowerShell shown; `data` is the base64 of the event JSON):

```powershell
$event = '{"event_id":"evt_1","store_id":"store_014","sku":"SKU-1","event_type":"STOCK_UPDATED","quantity":3,"previous_quantity":18,"unit":"units","occurred_at":"2026-11-16T19:40:12Z","source":"manual","ingested_at":"2026-11-16T19:40:13Z"}'
$data = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($event))
$body = @{ message = @{ data = $data; messageId = "1"; attributes = @{ schema_version = "1" } } } | ConvertTo-Json -Depth 4
Invoke-WebRequest http://127.0.0.1:8081/internal/pubsub -Method Post -ContentType application/json -Body $body -UseBasicParsing
```

Expect `204`. Posting it again also returns `204` and logs `duplicate_event_ignored`. The logs show `event_processed` with the alerts raised (`LOW_STOCK` and `RAPID_STOCK_DROP` here). Nothing is persisted in this mode.

## Diagnose a request

Every response includes `X-Trace-Id`. Find the matching log lines by `trace_id`. In Cloud Logging (after deployment), filter on `jsonPayload.trace_id="<trace-id>"`. The same id is a Pub/Sub attribute, so the processor's logs for that event share it.

## Common problems

| Symptom | Cause |
|---|---|
| `GCP_PROJECT_ID is required when ENVIRONMENT is not 'local'` | Set `GCP_PROJECT_ID`, or use `ENVIRONMENT=local` |
| `API_KEYS is required when ENVIRONMENT is not 'local'` | Provide at least one key (from Secret Manager when deployed) |
| `PUBSUB_TOPIC_ID is required when ENVIRONMENT is not 'local'` | Set the topic the API publishes to |
| `401 unauthorized` | Missing or wrong `X-API-Key`; check the log line `authentication_failed` |
| `429 rate_limited` | Honor `Retry-After`; raise `RATE_LIMIT_PER_MINUTE` if the client is legitimate |
| `503 publish_failed` | Pub/Sub did not confirm in `PUBSUB_PUBLISH_TIMEOUT_SECONDS`; look for `event_publish_failed` in the logs (permissions, topic name, quota) |
| Processor `400 invalid_envelope` / `invalid_message_data` / `rejected` | A message that can never be processed. Pub/Sub retries, then dead-letters it. The response lists the failing fields, never their values |
| Processor `503 storage_unavailable` | BigQuery transient failure after retries. Look for `storage_retry` and `bigquery_row_errors` in the logs; Pub/Sub redelivers by itself |
| Processor `500 storage_error` | BigQuery rejected the write (schema drift, missing `roles/bigquery.dataEditor`, wrong dataset or table name). Compare the table with `infra/schemas/*.json` |
| Alerts keep repeating for one SKU | By design in Phase 3: every `STOCK_UPDATED` at or below the threshold raises an alert. A cooldown is planned |

## Query alerts and trends

```powershell
$h = @{ "X-API-Key" = "local-dev-key-change-me" }
Invoke-RestMethod -Headers $h "http://127.0.0.1:8080/v1/alerts?severity=CRITICAL&limit=10"
Invoke-RestMethod -Headers $h "http://127.0.0.1:8080/v1/metrics/stock-trends?store_id=store_014"
```

Without `GCP_PROJECT_ID` both return empty lists: the API does not share memory with the processor. Against a real project they read BigQuery.

### Create or update the view

`infra/sql/v_stock_trends.sql` contains `${project_id}` and `${dataset}` placeholders (Terraform fills them in Phase 5). To apply it by hand:

```bash
sed -e "s/\${project_id}/$PROJECT/g" -e "s/\${dataset}/inventory_analytics/g" \
  infra/sql/v_stock_trends.sql | bq query --use_legacy_sql=false
```

### Check the view prunes partitions

```bash
bq query --use_legacy_sql=false --dry_run \
  "SELECT * FROM \`$PROJECT.inventory_analytics.v_stock_trends\`
   WHERE hour_start >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)"
```

Compare the bytes with a full scan of `stock_events`. If they are similar, pruning does not work through the view: replace it with a table function that takes the window as arguments.

### IAM for the read side

| Service account | Roles |
|---|---|
| `inventory-api` | `roles/bigquery.dataViewer` on the dataset, `roles/bigquery.jobUser` on the project, `roles/pubsub.publisher` on the topic |
| `inventory-processor` | `roles/bigquery.dataEditor` on the dataset, `roles/bigquery.jobUser` on the project |

A query that exceeds `BQ_MAX_BYTES_BILLED` fails with `500 analytics_error` (the log shows the BigQuery reason); narrow the window or raise the cap deliberately.

A `503 analytics_unavailable` that never clears usually means a missing `jobUser` role or a wrong `BQ_DATASET`; check the logs for the BigQuery error reason.

## Planned

Deployment, rollback and dead-letter queue replay are documented in Phase 5 (they depend on the Terraform resources).
