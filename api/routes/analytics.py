"""Read endpoints: alerts and stock trends."""

import logging
from typing import Any

from flask import Blueprint, Response, jsonify, request

from api.dependencies import get_dependencies
from api.middleware.guard import authenticate_and_rate_limit
from api.query_params import parse_alert_query, parse_trend_query
from api.repositories.base import AlertRecord, TrendRecord
from api.services.analytics import Window
from common.events import format_timestamp

logger = logging.getLogger(__name__)

analytics_blueprint = Blueprint("analytics", __name__, url_prefix="/v1")
analytics_blueprint.before_request(authenticate_and_rate_limit)


@analytics_blueprint.get("/alerts")
def list_alerts() -> Response:
    query = parse_alert_query(request.args.to_dict(flat=False))
    page = get_dependencies().analytics.list_alerts(query)
    logger.info("alerts_listed", extra={"returned": len(page.items), "has_more": page.has_more})
    return jsonify(
        {
            "items": [_alert_json(alert) for alert in page.items],
            "pagination": _pagination_json(page.limit, page.offset, len(page.items), page.has_more),
            "window": _window_json(page.window),
        }
    )


@analytics_blueprint.get("/metrics/stock-trends")
def stock_trends() -> Response:
    query = parse_trend_query(request.args.to_dict(flat=False))
    page = get_dependencies().analytics.stock_trends(query)
    logger.info("trends_listed", extra={"returned": len(page.items), "has_more": page.has_more})
    return jsonify(
        {
            "granularity": "hour",
            "items": [_trend_json(trend) for trend in page.items],
            "pagination": _pagination_json(page.limit, page.offset, len(page.items), page.has_more),
            "window": _window_json(page.window),
        }
    )


def _alert_json(alert: AlertRecord) -> dict[str, Any]:
    return {
        "alert_id": alert.alert_id,
        "event_id": alert.event_id,
        "store_id": alert.store_id,
        "sku": alert.sku,
        "alert_type": alert.alert_type,
        "severity": alert.severity,
        "detected_at": format_timestamp(alert.detected_at),
        "details": alert.details,
        "status": alert.status,
    }


def _trend_json(trend: TrendRecord) -> dict[str, Any]:
    return {
        "hour": format_timestamp(trend.hour_start),
        "store_id": trend.store_id,
        "sku": trend.sku,
        "units_sold": trend.units_sold,
        "units_restocked": trend.units_restocked,
        "avg_stock": None if trend.avg_stock is None else round(trend.avg_stock, 2),
        "event_count": trend.event_count,
        "stock_variation": trend.stock_variation,
    }


def _pagination_json(limit: int, offset: int, returned: int, has_more: bool) -> dict[str, Any]:
    return {"limit": limit, "offset": offset, "returned": returned, "has_more": has_more}


def _window_json(window: Window) -> dict[str, Any]:
    return {
        "from": format_timestamp(window.start),
        "to": None if window.end is None else format_timestamp(window.end),
    }
