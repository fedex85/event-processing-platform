"""Validation of the query string of the read endpoints.

Same philosophy as the event contract: unknown parameters are rejected, errors
name the field and never echo the value, and timestamps must carry a timezone.
"""

from collections.abc import Mapping
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from common.alerts import AlertStatus, AlertType, Severity
from common.errors import RejectedError
from common.events import ErrorItem, IsoTimestamp, NonEmptyStr

DEFAULT_ALERTS_LIMIT = 50
MAX_ALERTS_LIMIT = 500
DEFAULT_TRENDS_LIMIT = 100
MAX_TRENDS_LIMIT = 1000
MAX_OFFSET = 100_000

_ENUM_FIELDS: dict[str, type[StrEnum]] = {
    "alert_type": AlertType,
    "severity": Severity,
    "status": AlertStatus,
}
_TIMESTAMP_HINT = (
    "must be an ISO 8601 timestamp with a timezone (e.g. 2026-11-16T19:40:12Z; "
    "write a '+' offset as %2B in a URL)"
)


class _QueryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    from_: IsoTimestamp | None = Field(default=None, alias="from")
    to: IsoTimestamp | None = None
    offset: int = Field(default=0, ge=0, le=MAX_OFFSET)


class AlertQuery(_QueryModel):
    store_id: NonEmptyStr | None = None
    sku: NonEmptyStr | None = None
    alert_type: AlertType | None = None
    severity: Severity | None = None
    status: AlertStatus | None = None
    limit: int = Field(default=DEFAULT_ALERTS_LIMIT, ge=1, le=MAX_ALERTS_LIMIT)


class TrendQuery(_QueryModel):
    store_id: NonEmptyStr | None = None
    sku: NonEmptyStr | None = None
    limit: int = Field(default=DEFAULT_TRENDS_LIMIT, ge=1, le=MAX_TRENDS_LIMIT)


def _integer_message(field: str, model: type[_QueryModel]) -> str:
    if field == "offset":
        return f"must be an integer between 0 and {MAX_OFFSET}"
    maximum = MAX_ALERTS_LIMIT if model is AlertQuery else MAX_TRENDS_LIMIT
    return f"must be an integer between 1 and {maximum}"


def _to_error_items(exc: ValidationError, model: type[_QueryModel]) -> list[ErrorItem]:
    items: list[ErrorItem] = []
    for error in exc.errors(include_url=False, include_input=False):
        location = error["loc"]
        field = ".".join(str(part) for part in location) if location else "query"
        kind = error["type"]
        if kind == "extra_forbidden":
            message = "unknown parameter"
        elif field in {"limit", "offset"}:
            message = _integer_message(field, model)
        elif field in _ENUM_FIELDS:
            message = "must be one of: " + ", ".join(m.value for m in _ENUM_FIELDS[field])
        elif kind == "string_too_short":
            message = "must not be empty"
        elif kind == "string_too_long":
            message = "must be at most 255 characters"
        elif kind.startswith("datetime") or kind in {"time_delta_parsing", "date_from_datetime"}:
            message = _TIMESTAMP_HINT
        else:
            message = error["msg"].removeprefix("Value error, ")
            if field in {"from", "to"} and "timezone" not in message:
                message = _TIMESTAMP_HINT
        items.append(ErrorItem(field=field, message=message))
    return items


def _flatten(args: Mapping[str, list[str]]) -> tuple[dict[str, str], list[ErrorItem]]:
    flat: dict[str, str] = {}
    errors: list[ErrorItem] = []
    for key, values in args.items():
        if len(values) > 1:
            errors.append(ErrorItem(field=key, message="must be provided only once"))
        else:
            flat[key] = values[0]
    return flat, errors


def _parse[M: _QueryModel](model: type[M], args: Mapping[str, list[str]]) -> M:
    flat, errors = _flatten(args)
    try:
        parsed = model.model_validate(flat)
    except ValidationError as exc:
        raise RejectedError(errors + _to_error_items(exc, model)) from exc
    if errors:
        raise RejectedError(errors)
    return parsed


def parse_alert_query(args: Mapping[str, list[str]]) -> AlertQuery:
    """``args`` is ``request.args.to_dict(flat=False)``."""
    return _parse(AlertQuery, args)


def parse_trend_query(args: Mapping[str, list[str]]) -> TrendQuery:
    return _parse(TrendQuery, args)
