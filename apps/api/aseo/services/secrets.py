"""Secret store abstraction. Connector code asks for secrets by (connector, name) and
never logs, returns via API, sends to AI prompts or writes them to audit events."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from aseo.core.config import get_settings
from aseo.core.crypto import decrypt, encrypt
from aseo.core.security import sha256_hex
from aseo.models import ConnectorSecretRef, SecretBlob
from aseo.models.base import utcnow


def put_secret(db: Session, *, tenant_id: uuid.UUID, connector_id: uuid.UUID, name: str, value: str) -> ConnectorSecretRef:
    settings = get_settings()
    if settings.secrets_backend == "aws":  # pragma: no cover - requires AWS credentials
        raise NotImplementedError(
            "AWS Secrets Manager backend: store the secret with boto3 secretsmanager.create_secret "
            "and save the ARN as ref. See docs/operations/secrets.md."
        )
    existing = db.execute(
        select(ConnectorSecretRef).where(ConnectorSecretRef.connector_id == connector_id, ConnectorSecretRef.name == name)
    ).scalar_one_or_none()
    blob = SecretBlob(tenant_id=tenant_id, ciphertext=encrypt(value))
    db.add(blob)
    db.flush()
    fp = sha256_hex(value)[:8]
    if existing:
        old_blob = db.get(SecretBlob, uuid.UUID(existing.ref))
        if old_blob:
            db.delete(old_blob)
        existing.ref = str(blob.id)
        existing.fingerprint = fp
        existing.rotated_at = utcnow()
        existing.revoked_at = None
        return existing
    ref = ConnectorSecretRef(tenant_id=tenant_id, connector_id=connector_id, name=name, backend="local", ref=str(blob.id), fingerprint=fp)
    db.add(ref)
    db.flush()
    return ref


def get_secret(db: Session, connector_id: uuid.UUID, name: str) -> str | None:
    ref = db.execute(
        select(ConnectorSecretRef).where(
            ConnectorSecretRef.connector_id == connector_id, ConnectorSecretRef.name == name, ConnectorSecretRef.revoked_at.is_(None)
        )
    ).scalar_one_or_none()
    if ref is None:
        return None
    blob = db.get(SecretBlob, uuid.UUID(ref.ref))
    return decrypt(blob.ciphertext) if blob else None


def revoke_secrets(db: Session, connector_id: uuid.UUID) -> int:
    refs = db.execute(select(ConnectorSecretRef).where(ConnectorSecretRef.connector_id == connector_id)).scalars().all()
    for ref in refs:
        blob = db.get(SecretBlob, uuid.UUID(ref.ref))
        if blob:
            db.delete(blob)
        ref.revoked_at = utcnow()
    return len(refs)
