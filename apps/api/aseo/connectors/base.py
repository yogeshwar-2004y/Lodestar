"""Typed website-connector interface.

Each connector reports which actions it supports, how it writes (direct vs pull request),
the preconditions/permissions involved, and whether rollback is supported. Unsupported
writes remain recommendations — the change service refuses to execute them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from aseo.core.errors import ConnectorError


@dataclass
class ConnectorContext:
    site_id: str
    site_base_url: str
    site_host: str
    connector_id: str | None
    provider: str
    mode: str  # live | fixture
    config: dict[str, Any]
    secrets: dict[str, str] = field(default_factory=dict, repr=False)  # never logged


@dataclass
class Capability:
    action_type: str
    supported: bool
    write_mode: str = "none"  # direct | pull_request | none
    rollback_supported: bool = False
    preconditions: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    notes: str | None = None


@dataclass
class ResourceState:
    ref: dict[str, Any]  # {"type": "post", "id": 12, "url": "..."}
    fields: dict[str, Any]  # {"meta_description": "...", "title": "..."}
    version: str | None
    url: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class PreparedPatch:
    ref: dict[str, Any]
    before: dict[str, Any]
    after: dict[str, Any]
    resource_version: str | None
    warnings: list[str] = field(default_factory=list)
    preview: dict[str, Any] = field(default_factory=dict)


@dataclass
class ApplyResult:
    applied: bool
    live: bool  # False when the change is not live yet (e.g. PR opened, awaiting deploy)
    resource_version: str | None
    previous: dict[str, Any]
    response: dict[str, Any] = field(default_factory=dict)  # sanitized connector response
    external_url: str | None = None


@dataclass
class VerifyResult:
    verified: bool
    pending: bool  # True when waiting on something external (merge/deploy/cache)
    method: str
    expected: dict[str, Any]
    observed: dict[str, Any]
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class RollbackResult:
    restored: bool
    requires_human: bool
    message: str
    response: dict[str, Any] = field(default_factory=dict)
    resource_version: str | None = None


class StaleResourceError(ConnectorError):
    code = "stale_resource_version"
    status_code = 409


@runtime_checkable
class WebsiteConnector(Protocol):
    provider: str

    async def verify_ownership(self, ctx: ConnectorContext) -> dict[str, Any]: ...
    async def capabilities(self, ctx: ConnectorContext) -> list[Capability]: ...
    async def discover_pages(self, ctx: ConnectorContext) -> list[str]: ...
    async def read_resource(self, ctx: ConnectorContext, url: str) -> ResourceState: ...
    async def prepare_patch(self, ctx: ConnectorContext, url: str, action_type: str, after: dict[str, Any]) -> PreparedPatch: ...
    async def apply_patch(self, ctx: ConnectorContext, patch: dict[str, Any], *, expected_version: str | None, change_ref: str) -> ApplyResult: ...
    async def verify_patch(self, ctx: ConnectorContext, patch: dict[str, Any], apply: dict[str, Any]) -> VerifyResult: ...
    async def rollback(self, ctx: ConnectorContext, patch: dict[str, Any], snapshot: dict[str, Any], *, current_version: str | None, change_ref: str) -> RollbackResult: ...


FIELD_FOR_ACTION = {"meta_description": "meta_description", "title": "title"}


def unsupported(action: str, notes: str) -> Capability:
    return Capability(action_type=action, supported=False, notes=notes)
