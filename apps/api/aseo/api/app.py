"""FastAPI application factory."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from aseo.core.config import get_settings
from aseo.core.errors import AppError
from aseo.core.logging import configure_logging, request_id_ctx

log = logging.getLogger("aseo.api")


def _error(status: int, code: str, message: str, details: object = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, "details": details,
                                                               "request_id": request_id_ctx.get()}})


class RateLimiter:
    """Fixed-window limiter (per IP + route class). Uses Redis when reachable so limits hold
    across API replicas; falls back to in-process counters."""

    def __init__(self) -> None:
        self._mem: dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()
        self._redis = None
        try:
            import redis

            r = redis.Redis.from_url(get_settings().redis_url, socket_connect_timeout=0.3, socket_timeout=0.3)
            r.ping()
            self._redis = r
        except Exception:  # noqa: BLE001
            self._redis = None

    def hit(self, key: str, limit: int) -> bool:
        window = int(time.time() // 60)
        k = f"rl:{key}:{window}"
        if self._redis is not None:
            try:
                n = self._redis.incr(k)
                if n == 1:
                    self._redis.expire(k, 70)
                return n <= limit
            except Exception:  # noqa: BLE001, S110 — Redis hiccup: fall back to in-process counters
                pass
        with self._lock:
            self._mem[k] += 1
            if len(self._mem) > 50_000:
                self._mem.clear()
            return self._mem[k] <= limit


def _start_inline_relay() -> None:
    """Inline mode: background thread that drains due outbox events and runs the scheduler."""
    from aseo.agents.workflows import scheduler_tick
    from aseo.services import outbox

    def loop() -> None:
        tick = 0
        while True:
            try:
                outbox.drain()
                if tick % 30 == 0:
                    scheduler_tick()
            except Exception:  # noqa: BLE001
                log.exception("inline relay error")
            tick += 1
            time.sleep(2)

    threading.Thread(target=loop, daemon=True, name="inline-relay").start()


def create_app(*, start_background: bool = True) -> FastAPI:
    settings = get_settings()
    configure_logging()

    import aseo.agents.workflows  # noqa: F401 — registers outbox handlers
    import aseo.services.changes  # noqa: F401
    import aseo.services.crawls  # noqa: F401
    from aseo.api.routes import register

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # noqa: ANN202
        from aseo.core.db import system_session
        from aseo.services import billing
        from aseo.services.crawls import sync_rule_catalogue

        try:
            with system_session() as db:
                sync_rule_catalogue(db)
                billing.ensure_plans(db)
        except Exception:  # noqa: BLE001
            log.exception("startup sync failed (are migrations applied?)")
        if start_background and settings.task_execution == "inline":
            _start_inline_relay()
        yield

    app = FastAPI(
        title=f"{settings.product_name} API",
        version="1.0.0",
        description="Agentic SEO operations API. All routes are under /api/v1. Write endpoints accept an `Idempotency-Key` header. "
                    "Browser sessions use an httpOnly cookie plus the `X-CSRF-Token` header; API clients may use `Authorization: Bearer`.",
        openapi_url=f"{settings.api_prefix}/openapi.json",
        docs_url=f"{settings.api_prefix}/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    limiter = RateLimiter()

    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["content-type", "x-csrf-token", "idempotency-key", "authorization"],
    )

    @app.middleware("http")
    async def context_mw(request: Request, call_next):  # noqa: ANN001, ANN202
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        token = request_id_ctx.set(rid)
        started = time.monotonic()
        ip = request.client.host if request.client else "unknown"
        path = request.url.path
        is_auth = path.startswith(f"{settings.api_prefix}/auth/")
        if path.startswith(settings.api_prefix) and not path.startswith(f"{settings.api_prefix}/webhooks"):
            limit = settings.auth_rate_limit_per_minute if is_auth and request.method == "POST" else settings.rate_limit_per_minute
            if not limiter.hit(f"{ip}:{'auth' if is_auth else 'api'}", limit):
                request_id_ctx.reset(token)
                return _error(429, "rate_limited", "Too many requests. Please slow down.")
        try:
            response = await call_next(request)
        finally:
            request_id_ctx.reset(token)
        response.headers["x-request-id"] = rid
        response.headers["x-content-type-options"] = "nosniff"
        response.headers["x-frame-options"] = "DENY"
        response.headers["referrer-policy"] = "strict-origin-when-cross-origin"
        response.headers["cache-control"] = response.headers.get("cache-control", "no-store")
        log.info(f"{request.method} {path} {response.status_code}",
                 extra={"status": response.status_code, "duration_ms": int((time.monotonic() - started) * 1000)})
        return response

    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError) -> JSONResponse:
        return _error(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [{"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
        return _error(422, "validation_failed", "Request validation failed.", details)

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error")
        return _error(500, "internal_error", "Something went wrong. The error has been logged.")

    register(app, settings.api_prefix)

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
