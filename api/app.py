"""``inventory-api`` application factory."""

from flask import Flask

from api.config import ApiSettings
from api.dependencies import Dependencies, build_dependencies
from api.errors import register_error_handlers
from api.middleware import register_request_context
from api.routes import register_routes
from common.hardening import apply_hardening
from common.structured_logging import configure_logging


def create_app(
    settings: ApiSettings | None = None, *, dependencies: Dependencies | None = None
) -> Flask:
    """Build the application. Tests pass ``dependencies`` with fake adapters."""
    settings = settings or ApiSettings()
    configure_logging(
        level=settings.log_level,
        service_name=settings.service_name,
        project_id=settings.gcp_project_id,
    )

    app = Flask(__name__)
    app.json.sort_keys = False  # type: ignore[attr-defined]
    app.extensions["settings"] = settings
    app.extensions["dependencies"] = dependencies or build_dependencies(settings)

    apply_hardening(app, max_request_bytes=settings.max_request_bytes)
    register_request_context(app)
    register_error_handlers(app)
    register_routes(app)
    return app
