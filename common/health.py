"""Health endpoint shared by both services."""

from flask import Blueprint, Response, current_app, jsonify

HEALTH_PATH = "/v1/health"

health_blueprint = Blueprint("health", __name__)


@health_blueprint.get(HEALTH_PATH)
def health() -> tuple[Response, int]:
    settings = current_app.extensions["settings"]
    return jsonify({"status": "ok", "service": settings.service_name}), 200
