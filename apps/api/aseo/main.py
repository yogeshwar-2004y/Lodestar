"""ASGI entrypoint: `uvicorn aseo.main:app`."""

from aseo.api.app import create_app

app = create_app()
