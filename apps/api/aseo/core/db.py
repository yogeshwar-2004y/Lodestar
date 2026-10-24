"""Database engine/session management with tenant-scoped row level security.

Every transaction sets two transaction-local GUCs that PostgreSQL RLS policies read:

* ``app.tenant_id`` — the tenant the current request/job acts for.
* ``app.bypass_rls`` — 'on' only for explicitly-marked system work (outbox dispatch,
  scheduler, migrations). Never set from request input.

Service-layer checks still scope every query by tenant; RLS is defence in depth.
"""

from __future__ import annotations

import contextlib
import contextvars
import uuid
from collections.abc import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from aseo.core.config import get_settings

_tenant_ctx: contextvars.ContextVar[uuid.UUID | None] = contextvars.ContextVar("tenant", default=None)
_bypass_ctx: contextvars.ContextVar[bool] = contextvars.ContextVar("bypass_rls", default=False)

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(settings.app_database_url, pool_pre_ping=True, pool_size=10, max_overflow=10,
                                connect_args={"options": "-c timezone=utc"})
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, autoflush=False)
    return _engine


def reset_engine() -> None:
    """Used by tests after changing settings."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def session_factory() -> sessionmaker[Session]:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


@event.listens_for(Session, "after_begin")
def _apply_tenant_guc(session: Session, transaction, connection) -> None:  # noqa: ANN001
    if connection.dialect.name != "postgresql":
        return
    tenant = session.info.get("tenant_id") or _tenant_ctx.get()
    bypass = session.info.get("bypass_rls", _bypass_ctx.get())
    connection.execute(
        text("select set_config('app.tenant_id', :t, true), set_config('app.bypass_rls', :b, true)"),
        {"t": str(tenant) if tenant else "", "b": "on" if bypass else "off"},
    )


def new_session(tenant_id: uuid.UUID | None = None, *, system: bool = False) -> Session:
    session = session_factory()()
    if tenant_id:
        session.info["tenant_id"] = tenant_id
    if system:
        session.info["bypass_rls"] = True
    return session


def set_session_tenant(session: Session, tenant_id: uuid.UUID) -> None:
    """Bind the tenant for the session and refresh the GUC for any open transaction."""
    session.info["tenant_id"] = tenant_id
    if session.in_transaction() and session.bind is not None and session.bind.dialect.name == "postgresql":
        session.execute(text("select set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})


@contextlib.contextmanager
def system_session() -> Iterator[Session]:
    """Session for trusted background/system work that must see all tenants."""
    session = new_session(system=True)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextlib.contextmanager
def tenant_session(tenant_id: uuid.UUID) -> Iterator[Session]:
    session = new_session(tenant_id)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
