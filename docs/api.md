# API

Base path: `/v1`. All responses are JSON. Every response carries an `X-Trace-Id` header; send `X-Cloud-Trace-Context` to propagate your own trace.

## Authentication

Every endpoint except `GET /v1/health` requires an API key in the `X-API-Key` header. A missing or wrong key returns `401` with `code: "unauthorized"`.

Rate limiting is applied per API key. Over the limit, the API returns `429` with `code: "rate_limited"` and a `Retry-After` header (seconds). A batch counts as one request. The limit is per instance, so it is a safety net rather than an exact quota.

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

Send your own `event_id` so a retry after a timeout cannot create a second event. Without one, the API generates a new id on every request, so a retried request is a new event. The API remembers recent ids per instance only; the processor performs the final deduplication.

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

## Planned

| Endpoint | Phase |
|---|---|
| `GET /v1/alerts` | 4 |
| `GET /v1/metrics/stock-trends` | 4 |
