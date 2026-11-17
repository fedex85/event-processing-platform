"""Inbound adapters: how messages reach the processor."""

from flask import Flask

from processor.consumers.pubsub import pubsub_blueprint


def register_consumers(app: Flask) -> None:
    app.register_blueprint(pubsub_blueprint)
