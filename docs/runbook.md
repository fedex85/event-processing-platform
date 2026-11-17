# Runbook

How to run, deploy and operate the platform. Cloud steps use `$PROJECT` for the GCP project of the environment and `$REGION` for its region (`europe-southwest1` by default).

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

Terraform creates the view (`infra/modules/bigquery`). `infra/sql/v_stock_trends.sql` is the view's query, with `${project_id}` and `${dataset}` placeholders that Terraform fills in. To apply it by hand, wrap it in a `CREATE OR REPLACE VIEW` statement:

```bash
{
  echo "CREATE OR REPLACE VIEW \`$PROJECT.inventory_analytics.v_stock_trends\` AS"
  sed -e "s/\${project_id}/$PROJECT/g" -e "s/\${dataset}/inventory_analytics/g" infra/sql/v_stock_trends.sql
} | bq query --use_legacy_sql=false
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

## Deploy

The infrastructure is Terraform (`infra/`); the images are built and deployed by GitHub Actions. Use one GCP project per environment (`staging`, `prod`), each with its own state and its own `environments/<name>.tfvars`.

### One-time setup of an environment

1. Create the project, link billing and sign in: `gcloud auth application-default login`.
2. Create the state bucket (versioned, private). Terraform cannot create the bucket that stores its own state:

   ```bash
   gcloud storage buckets create "gs://$PROJECT-tfstate" --project "$PROJECT" \
     --location "$REGION" --uniform-bucket-level-access --public-access-prevention
   gcloud storage buckets update "gs://$PROJECT-tfstate" --versioning
   ```

3. Configure and initialise:

   ```bash
   cd infra
   cp environments/staging.tfvars.example environments/staging.tfvars   # edit the values
   terraform init -backend-config="bucket=$PROJECT-tfstate" -backend-config="prefix=staging"
   ```

4. Create the API-keys secret first. Cloud Run refuses to start a revision whose secret has no version, and the key itself must never pass through Terraform state:

   ```bash
   terraform apply -var-file=environments/staging.tfvars -target=module.secrets
   python -c "import secrets; print(secrets.token_urlsafe(32))" | \
     gcloud secrets versions add inventory-api-keys --data-file=- --project "$PROJECT"
   ```

   Several keys go in one version separated by commas. Each needs at least 24 characters.

5. Apply everything: `terraform plan -var-file=environments/staging.tfvars`, review, then `terraform apply -var-file=environments/staging.tfvars`. The first apply runs a placeholder image; the first CI deployment replaces it.

   If it fails with a message that the Pub/Sub service account does not exist, run `gcloud beta services identity create --service=pubsub.googleapis.com --project "$PROJECT"` and apply again.

6. In GitHub, create the environments `staging` and `production` (add required reviewers to `production`) and set these variables on each, from `terraform output`:

   | Variable | Value |
   |---|---|
   | `GCP_PROJECT_ID` | the environment's project |
   | `GCP_REGION` | `$REGION` |
   | `GCP_WORKLOAD_IDENTITY_PROVIDER` | `github_workload_identity_provider` output |
   | `GCP_DEPLOYER_SERVICE_ACCOUNT` | `github_deployer_service_account` output |

   No secrets are needed: GitHub Actions authenticates to Google with its own OIDC token (Workload Identity Federation), restricted to this repository and environment.

### Deploying

- **Staging** deploys by itself when CI passes on `main`: the workflow builds both images, tags them with the commit, deploys the processor, then the API, and calls `/v1/health`.
- **Production** is manual: Actions, Deploy, Run workflow, choose `production` and a tag or commit. The job waits for the approval configured on the `production` environment.

Infrastructure changes are applied by hand with `terraform plan` / `apply`; the workflows only deploy images.

### Roll back

Send traffic to the previous revision (instant, no build):

```bash
gcloud run revisions list --service inventory-api --region "$REGION" --project "$PROJECT"
gcloud run services update-traffic inventory-api --region "$REGION" --project "$PROJECT" \
  --to-revisions <previous-revision>=100
```

Do the same for `inventory-processor` if needed. To redeploy an older commit instead, run the Deploy workflow with that ref.

### Check the Terraform code without cloud access

```bash
cd infra && terraform fmt -recursive && terraform init -backend=false && terraform validate
```

CI runs the same commands. `pytest` also runs structural checks on the Terraform files.

## Dead-letter queue

After `MAX_DELIVERY_ATTEMPTS` (5) failed deliveries Pub/Sub moves a message to `stock-events-dlq`, and an alert fires when it holds messages. The `stock-events-dlq-pull` subscription keeps them for 7 days.

Inspect without removing them:

```bash
gcloud pubsub subscriptions pull stock-events-dlq-pull --project "$PROJECT" --limit 5 --format json
```

`message.data` is base64 of the event. Find why it failed (the processor's logs carry the `message_id`; a `400` means a malformed message, a `500` a storage problem), then:

- **Fixed the cause and the event is valid:** republish it to the main topic. Replays are safe because the processor ignores `event_id`s it already stored.

  ```bash
  gcloud pubsub subscriptions pull stock-events-dlq-pull --project "$PROJECT" --auto-ack --limit 50 --format json \
    | jq -r '.[].message.data' | while read -r data; do
        gcloud pubsub topics publish stock-events --project "$PROJECT" \
          --message "$(echo "$data" | base64 -d)" --attribute schema_version=1
      done
  ```

- **The message is garbage:** acknowledge it (`--auto-ack`) to discard it.

## Rotate API keys

1. Add a version containing the old and the new key: `echo "old-key,new-key" | gcloud secrets versions add inventory-api-keys --data-file=- --project "$PROJECT"`.
2. Start a new revision so instances re-read the secret: `gcloud run services update inventory-api --region "$REGION" --project "$PROJECT" --update-env-vars KEYS_ROTATED_AT=$(date +%s)`.
3. Move clients to the new key, then repeat with only the new key.
