"""``inventory-processor`` application factory."""

from flask import Flask

from common.errors import register_error_handlers
from common.health import HEALTH_PATH, health_blueprint
from common.request_context import register_request_context
from common.structured_logging import configure_logging
from processor.config import ProcessorSettings
from processor.consumers import register_consumers
from processor.dependencies import Dependencies, build_dependencies


def create_app(
    settings: ProcessorSettings | None = None, *, dependencies: Dependencies | None = None
) -> Flask:
    """Build the application. Tests pass ``dependencies`` with fake repositories."""
    settings = settings or ProcessorSettings()
    configure_logging(
        level=settings.log_level,
        service_name=settings.service_name,
        project_id=settings.gcp_project_id,
    )

    app = Flask(__name__)
    app.json.sort_keys = False  # type: ignore[attr-defined]
    app.extensions["settings"] = settings
    app.extensions["dependencies"] = dependencies or build_dependencies(settings)

    register_request_context(app, quiet_paths=frozenset({HEALTH_PATH}))
    register_error_handlers(app)
    app.register_blueprint(health_blueprint)
    register_consumers(app)
    return app
