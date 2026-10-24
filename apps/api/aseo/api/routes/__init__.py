from fastapi import FastAPI

from aseo.api.routes import auth, changes, integrations, ops, sites


def register(app: FastAPI, prefix: str) -> None:
    for module in (auth, sites, changes, ops, integrations):
        app.include_router(module.router, prefix=prefix)
