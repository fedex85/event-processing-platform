"""``POST /internal/pubsub``: receives Pub/Sub push deliveries.

Answers Pub/Sub understands:

* ``204`` - processed (or an ignored duplicate); the message is acknowledged.
* ``400`` - the message itself is bad and can never succeed. Pub/Sub keeps
  redelivering until the subscription's dead-letter policy moves it aside.
* ``503`` / ``500`` - storage trouble; Pub/Sub redelivers with backoff.

Cloud Run's IAM check (the push subscription's service account holds
``run.invoker``) authenticates the caller; this endpoint is never public.
"""

import base64
import binascii
import logging
from typing import Any

from flask import Blueprint, request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from common.errors import AppError, RejectedError
from common.events import IngestedStockEvent, to_error_items
from common.structured_logging import bind_context
from processor.dependencies import get_dependencies
from processor.domain.errors import PermanentStorageError, TransientStorageError

logger = logging.getLogger(__name__)

pubsub_blueprint = Blueprint("pubsub", __name__)

SUPPORTED_SCHEMA_VERSION = "1"


class PubSubMessage(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    data: str
    attributes: dict[str, str] = Field(default_factory=dict)
    message_id: str | None = Field(default=None, alias="messageId")


class PushEnvelope(BaseModel):
    """The JSON body Pub/Sub sends to a push endpoint."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    message: PubSubMessage
    subscription: str | None = None
    delivery_attempt: int | None = Field(default=None, alias="deliveryAttempt")


def _poison(code: str, message: str) -> AppError:
    return AppError(message, status_code=400, code=code)


def parse_envelope(body: Any) -> PushEnvelope:
    if not isinstance(body, dict):
        raise _poison("invalid_envelope", "Request body must be a Pub/Sub push envelope")
    try:
        return PushEnvelope.model_validate(body)
    except ValidationError as exc:
        fields = ", ".join(item.field for item in to_error_items(exc))
        raise _poison("invalid_envelope", f"Invalid Pub/Sub envelope: {fields}") from exc


def decode_event(message: PubSubMessage) -> IngestedStockEvent:
    version = message.attributes.get("schema_version", SUPPORTED_SCHEMA_VERSION)
    if version != SUPPORTED_SCHEMA_VERSION:
        raise _poison("unsupported_schema_version", f"Unsupported schema_version {version!r}")
    try:
        raw = base64.b64decode(message.data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise _poison("invalid_message_data", "Message data is not valid base64") from exc
    try:
        return IngestedStockEvent.model_validate_json(raw)
    except ValidationError as exc:
        # Items name the failing fields but never echo values.
        raise RejectedError(to_error_items(exc)) from exc


@pubsub_blueprint.post("/internal/pubsub")
def receive_message() -> tuple[str, int]:
    envelope = parse_envelope(request.get_json(silent=True))
    bind_context(
        message_id=envelope.message.message_id,
        # The API's trace id; the request's own trace_id keeps coming from Cloud Run.
        origin_trace_id=envelope.message.attributes.get("trace_id"),
        delivery_attempt=None
        if envelope.delivery_attempt is None
        else str(envelope.delivery_attempt),
    )

    event = decode_event(envelope.message)
    try:
        get_dependencies().processor.process(event)
    except TransientStorageError as exc:
        raise AppError(
            "Storage temporarily unavailable; the message will be redelivered",
            status_code=503,
            code="storage_unavailable",
        ) from exc
    except PermanentStorageError as exc:
        raise AppError(
            "Storage rejected the write; check the table schema and permissions",
            status_code=500,
            code="storage_error",
        ) from exc
    return "", 204
