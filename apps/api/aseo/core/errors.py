"""Structured API errors. Every error response has the shape
``{"error": {"code": str, "message": str, "details": object|null, "request_id": str}}``."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, code: str | None = None, details: Any = None, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Unauthorized(AppError):
    status_code = 401
    code = "unauthenticated"


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class ValidationFailed(AppError):
    status_code = 422
    code = "validation_failed"


class RateLimited(AppError):
    status_code = 429
    code = "rate_limited"


class BudgetExceeded(AppError):
    status_code = 402
    code = "budget_exceeded"


class PolicyDenied(AppError):
    status_code = 403
    code = "policy_denied"


class ConnectorError(AppError):
    status_code = 502
    code = "connector_error"

    def __init__(self, message: str, *, retryable: bool = False, **kw: Any):
        super().__init__(message, **kw)
        self.retryable = retryable


class KillSwitchEngaged(AppError):
    status_code = 423
    code = "kill_switch_engaged"
