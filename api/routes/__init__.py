"""HTTP routes of the API."""

from flask import Flask

from api.routes.events import events_blueprint
from common.health import health_blueprint


def register_routes(app: Flask) -> None:
    app.register_blueprint(health_blueprint)
    app.register_blueprint(events_blueprint)
