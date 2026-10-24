"""Deterministic validation of proposed patch values (runs before any policy decision)."""

from __future__ import annotations

import re
from typing import Any

_TAG = re.compile(r"<[^>]+>")
_URL = re.compile(r"https?://", re.I)
_INJECTION_MARKERS = re.compile(r"(ignore (all|previous) instructions|system prompt|as an ai language model)", re.I)

LIMITS = {
    "meta_description": {"hard_min": 25, "hard_max": 300, "soft_min": 70, "soft_max": 160},
    "title": {"hard_min": 5, "hard_max": 120, "soft_min": 30, "soft_max": 60},
}


def validate_value(action_type: str, value: Any, *, before: str | None = None, site_values: list[str] | None = None) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if action_type not in LIMITS:
        return {"passed": False, "errors": [f"No validator for action '{action_type}'"], "warnings": []}
    lim = LIMITS[action_type]
    if not isinstance(value, str):
        return {"passed": False, "errors": ["Value must be text"], "warnings": []}
    text = value.strip()
    if text != value:
        warnings.append("Leading/trailing whitespace will be trimmed by most platforms")
    if "\n" in text or "\r" in text:
        errors.append("Line breaks are not allowed")
    if _TAG.search(text):
        errors.append("HTML tags are not allowed")
    if len(text) < lim["hard_min"]:
        errors.append(f"Too short ({len(text)} chars, minimum {lim['hard_min']})")
    if len(text) > lim["hard_max"]:
        errors.append(f"Too long ({len(text)} chars, maximum {lim['hard_max']})")
    if not errors and not lim["soft_min"] <= len(text) <= lim["soft_max"]:
        warnings.append(f"Length {len(text)} is outside the recommended {lim['soft_min']}-{lim['soft_max']} characters")
    if _URL.search(text):
        warnings.append("Contains a URL")
    if _INJECTION_MARKERS.search(text):
        errors.append("Contains instruction-like text that does not belong in metadata")
    if before is not None and text == (before or "").strip():
        errors.append("New value is identical to the current value")
    if site_values and text.lower() in {v.strip().lower() for v in site_values if v}:
        warnings.append("Duplicates a value already used on another page")
    return {"passed": not errors, "errors": errors, "warnings": warnings, "length": len(text)}
