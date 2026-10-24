"""Secret storage. Connector credentials are stored *by reference*: the database holds a
``connector_secret_refs`` row with a backend + opaque reference; the secret material lives
in the secret backend. The local backend encrypts with Fernet into the ``secret_blobs``
table (dev/pilot); the AWS backend uses Secrets Manager (configure SECRETS_BACKEND=aws)."""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from aseo.core.config import get_settings


def _fernet() -> Fernet:
    settings = get_settings()
    key = settings.secrets_encryption_key
    if not key:
        # Derive a stable dev key from SECRET_KEY. Production requires an explicit key
        # (enforced in Settings).
        key = base64.urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode()).digest()).decode()
    return Fernet(key.encode())


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:  # pragma: no cover - indicates key rotation problem
        raise RuntimeError("secret could not be decrypted (key rotated?)") from exc
