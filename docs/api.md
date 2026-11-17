# API

Base path: `/v1`. All responses are JSON. Every response carries an `X-Trace-Id` header; send `X-Cloud-Trace-Context` to propagate your own trace.

## Authentication

Every endpoint except `GET /v1/health` requires an API key in the `X-API-Key` header. A missing or wrong key returns `401` with `code: "unauthorized"`.

Rate limiting is applied per API key. Over the limit, the API returns `429` with `code: "rate_limited"` and a `Retry-After` header (seconds). A batch counts as one request. The limit is per process (each gunicorn worker of each Cloud Run instance), so it is a safety net rather than an exact quota.

## `GET /v1/health`

```json
{ "status": "ok", "service": "inventory-api" }
```

## `POST /v1/events`

Accepts one stock event (contract in the [README](../README.md#event-contract)) and publishes it to Pub/Sub. The API answers after Pub/Sub confirms the message; it does not wait for processing.

```http
POST /v1/events
Content-Type: application/json
X-API-Key: <key>
```

| Status | Meaning |
|---|---|
| `202` | Published (or already published recently: see below) |
| `400` | Invalid payload or malformed JSON |
| `401` | Missing or invalid API key |
| `415` | Body is not `application/json` |
| `429` | Rate limit exceeded |
| `503` | Pub/Sub did not confirm the message; retry |

Accepted:

```json
{ "status": "accepted", "event_id": "evt_01J5Z8K9Q2M7", "published_at": "2026-11-17T08:30:00.123456Z" }
```

If the same `event_id` was published recently, nothing is published again and the response is still `202`:

```json
{ "status": "accepted", "event_id": "evt_01J5Z8K9Q2M7", "duplicate": true }
```

Rejected:

```json
{
  "status": "rejected",
  "errors": [{ "field": "quantity", "message": "must be an integer greater than or equal to 0" }]
}
```

### Retrying safely

Send your own `event_id` so a retry after a timeout cannot create a second event. Without one, the API generates a new id on every request, so a retried request is a new event. The API remembers recent ids per process only; the processor performs the final deduplication.

## `POST /v1/events:batch`

Accepts up to 100 events (`MAX_BATCH_SIZE`) in one request. Each event is validated on its own: valid ones are published even if others are rejected.

```json
{ "events": [ { "...": "event 1" }, { "...": "event 2" } ] }
```

| Status | `status` | Meaning |
|---|---|---|
| `202` | `accepted` | Every event was published or was a duplicate |
| `207` | `partial` | Some events were rejected as invalid; the rest were accepted |
| `400` | `rejected` | Every event was invalid, or the body is not `{"events": [...]}` with 1 to 100 entries |
| `503` | `error` | At least one valid event could not be published; retry |

```json
{
  "status": "partial",
  "accepted": 1,
  "duplicates": 0,
  "rejected": 1,
  "failed": 0,
  "results": [
    { "index": 0, "status": "accepted", "event_id": "evt_1" },
    {
      "index": 1,
      "status": "rejected",
      "event_id": "evt_2",
      "errors": [{ "field": "quantity", "message": "must be an integer greater than or equal to 0" }]
    }
  ]
}
```

Per-event `status` is `accepted`, `duplicate`, `rejected` (fix the payload) or `failed` (retry it). On `503`, resend the batch: events that were already published come back as `duplicate` when they reach the same instance, and the processor discards any that do not.

## Error format

Besides validation failures above, errors look like:

```json
{ "status": "error", "code": "not_found", "message": "The requested URL was not found on the server." }
```

Unexpected server errors return `500` with `code: "internal_error"` and no details.

## Processor endpoint

`POST /internal/pubsub` belongs to `inventory-processor` and is called only by the Pub/Sub push subscription (Cloud Run IAM authenticates it). It takes the standard push envelope and answers `204` (processed or duplicate), `400` (message can never succeed), `503` (storage temporarily unavailable) or `500`. See [`architecture.md`](architecture.md#processing-flow-inventory-processor).

## `GET /v1/alerts`

Lists alerts written by the processor, newest first.

| Parameter | Meaning |
|---|---|
| `store_id`, `sku` | Exact match |
| `alert_type` | `LOW_STOCK`, `OUT_OF_STOCK` or `RAPID_STOCK_DROP` |
| `severity` | `LOW`, `MEDIUM`, `HIGH` or `CRITICAL` |
| `status` | `OPEN` |
| `from` | Start of the window, inclusive. Default: 7 days ago |
| `to` | End of the window, exclusive. Default: no upper bound |
| `limit` | 1 to 500. Default 50 |
| `offset` | 0 to 100000. Default 0 |

Timestamps are ISO 8601 and must carry a timezone (`2026-11-16T19:40:12Z`). In a URL, write `+` as `%2B`. Unknown or repeated parameters are rejected with `400`.

```http
GET /v1/alerts?store_id=store_014&severity=CRITICAL&limit=20
X-API-Key: <key>
```

```json
{
  "items": [
    {
      "alert_id": "6f0c0d0e-...",
      "event_id": "evt_01J5Z8K9Q2M7",
      "store_id": "store_014",
      "sku": "SKU-88231",
      "alert_type": "OUT_OF_STOCK",
      "severity": "CRITICAL",
      "detected_at": "2026-11-16T19:40:13Z",
      "details": { "quantity": 0 },
      "status": "OPEN"
    }
  ],
  "pagination": { "limit": 20, "offset": 0, "returned": 1, "has_more": false },
  "window": { "from": "2026-11-10T12:30:00Z", "to": null }
}
```

Pagination uses `has_more` instead of a total: counting would make BigQuery scan the whole window on every call. Page with `offset += limit` while `has_more` is true. New alerts arriving between pages can shift results; narrow the window with `from` and `to` for a stable view.

## `GET /v1/metrics/stock-trends`

Hourly aggregates per store and SKU from the `v_stock_trends` view, newest hour first.

| Parameter | Meaning |
|---|---|
| `store_id`, `sku` | Exact match |
| `from` | Start of the window. Floored to the hour so the bucket containing it is included. Default: 24 hours ago |
| `to` | End of the window, exclusive. Default: no upper bound |
| `limit` | 1 to 1000. Default 100 |
| `offset` | 0 to 100000. Default 0 |

The range from `from` to `to` (or to now) cannot exceed 31 days.

```json
{
  "granularity": "hour",
  "items": [
    {
      "hour": "2026-11-16T19:00:00Z",
      "store_id": "store_014",
      "sku": "SKU-88231",
      "units_sold": 12,
      "units_restocked": 40,
      "avg_stock": 22.46,
      "event_count": 9,
      "stock_variation": 28
    }
  ],
  "pagination": { "limit": 100, "offset": 0, "returned": 1, "has_more": false },
  "window": { "from": "2026-11-16T12:30:00Z", "to": null }
}
```

`avg_stock` and `stock_variation` are `null` for hours with sales or restocks but no `STOCK_UPDATED` event. `stock_variation` is the closing stock minus the opening stock of the hour.

### Read endpoint errors

| Status | `code` | Meaning |
|---|---|---|
| `400` | | Invalid parameter (structured `errors` list, as for events) |
| `401` | `unauthorized` | Missing or invalid API key |
| `429` | `rate_limited` | Over the rate limit (reads share the limit with writes) |
| `503` | `analytics_unavailable` | BigQuery temporarily unavailable; honour `Retry-After` |
| `500` | `analytics_error` | Query failed; details are in the logs only |

Without `GCP_PROJECT_ID` (local development) both endpoints answer `200` with an empty `items` list.
