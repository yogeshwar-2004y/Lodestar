from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from aseo.api.deps import get_db
from aseo.core.errors import NotFound
from aseo.services import payments

router = APIRouter(tags=["integrations & webhooks"])


@router.post("/webhooks/{provider}", summary="Inbound webhooks (signature-verified, replay-protected)")
async def webhook(provider: str, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    payload = await request.body()
    if provider == "billing":
        sig = request.headers.get("stripe-signature") or request.headers.get("x-lodestar-signature")
        return payments.handle_webhook(db, "billing", payload, sig)
    from aseo.services import platform_webhooks

    if provider in platform_webhooks.HANDLERS:
        return platform_webhooks.HANDLERS[provider](db, request, payload)
    raise NotFound("Unknown webhook provider")
