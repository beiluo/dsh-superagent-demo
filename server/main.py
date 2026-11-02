"""ASGI entry point: ``uvicorn server.main:app``."""

from .app import create_app

app = create_app()
