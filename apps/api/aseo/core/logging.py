"""Structured JSON logging with secret redaction."""

from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
import time

request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

_SECRET_PATTERNS = [
    re.compile(r"(?i)(authorization|api[_-]?key|token|secret|password|cookie)(\"?\s*[:=]\s*\"?)([^\s\",}]+)"),
    re.compile(r"sk-ant-[A-Za-z0-9_\-]+"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"shpat_[A-Za-z0-9]+"),
]


def redact(value: str) -> str:
    out = value
    for pat in _SECRET_PATTERNS:
        if pat.groups >= 3:
            out = pat.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", out)
        else:
            out = pat.sub("[REDACTED]", out)
    return out


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": redact(record.getMessage()),
            "request_id": request_id_ctx.get(),
        }
        for key in ("tenant_id", "site_id", "job", "event", "duration_ms", "status"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
