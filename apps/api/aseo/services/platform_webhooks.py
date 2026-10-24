"""Platform webhooks (Shopify, GitHub). Populated by connector modules."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

HANDLERS: dict[str, Callable[..., dict[str, Any]]] = {}
