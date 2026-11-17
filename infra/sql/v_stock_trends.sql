-- Hourly stock trends per store and SKU.
--
-- Terraform renders this file with templatefile(); ${project_id} and ${dataset} are
-- template variables, not BigQuery syntax.
--
-- The first CTE drops duplicate events (best-effort insertId deduplication can let a
-- few through). Duplicates share event_id AND occurred_at, so partitioning by both keeps
-- the predicate on occurred_at pushable below the window function.
--
-- Columns:
--   hour_start       start of the hour (UTC) the events fall in, by occurred_at
--   units_sold       sum of quantity of SALE events
--   units_restocked  sum of quantity of RESTOCK events
--   avg_stock        average resulting stock of STOCK_UPDATED events (NULL if none)
--   event_count      number of events of any type
--   stock_variation  closing stock minus opening stock (NULL if no STOCK_UPDATED event):
--                    closing = quantity of the last STOCK_UPDATED of the hour,
--                    opening = previous_quantity of the first one (its own quantity
--                    when previous_quantity is unknown)

CREATE OR REPLACE VIEW `${project_id}.${dataset}.v_stock_trends` AS
WITH events AS (
  SELECT *
  FROM `${project_id}.${dataset}.stock_events`
  WHERE TRUE
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY event_id, occurred_at
    ORDER BY ingested_at
  ) = 1
)
SELECT
  TIMESTAMP_TRUNC(occurred_at, HOUR) AS hour_start,
  store_id,
  sku,
  SUM(IF(event_type = 'SALE', quantity, 0)) AS units_sold,
  SUM(IF(event_type = 'RESTOCK', quantity, 0)) AS units_restocked,
  AVG(IF(event_type = 'STOCK_UPDATED', quantity, NULL)) AS avg_stock,
  COUNT(*) AS event_count,
  ARRAY_AGG(
    IF(event_type = 'STOCK_UPDATED', quantity, NULL)
    IGNORE NULLS ORDER BY occurred_at DESC, event_id DESC LIMIT 1
  )[SAFE_OFFSET(0)]
  - ARRAY_AGG(
    IF(event_type = 'STOCK_UPDATED', COALESCE(previous_quantity, quantity), NULL)
    IGNORE NULLS ORDER BY occurred_at ASC, event_id ASC LIMIT 1
  )[SAFE_OFFSET(0)] AS stock_variation
FROM events
GROUP BY hour_start, store_id, sku;
