"""In-app notifications (email delivery is a pluggable P1 adapter; see docs)."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from aseo.models import Notification


def notify(db: Session, tenant_id: uuid.UUID, *, kind: str, title: str, body: str | None = None, link: str | None = None,
           severity: str = "info", user_id: uuid.UUID | None = None) -> Notification:
    n = Notification(tenant_id=tenant_id, user_id=user_id, kind=kind, title=title[:300], body=body, link=link, severity=severity)
    db.add(n)
    db.flush()
    return n
