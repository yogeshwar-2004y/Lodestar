"""Object storage for page snapshots and reports.

LocalStorage writes under SNAPSHOT_DIR (dev, single host). For pilots, point
STORAGE_BACKEND=s3 at any S3-compatible bucket (AWS S3, MinIO, R2) — see docs/operations.
"""

from __future__ import annotations

import os
from pathlib import Path

from aseo.core.config import get_settings


class LocalStorage:
    def __init__(self, root: str) -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if not str(p).startswith(str(self.root.resolve())):
            raise ValueError("invalid storage key")
        return p

    def put(self, key: str, data: bytes) -> str:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.write_bytes(data)
        return key

    def get(self, key: str) -> bytes | None:
        p = self._path(key)
        return p.read_bytes() if p.exists() else None

    def delete_prefix(self, prefix: str) -> int:
        base = self._path(prefix)
        count = 0
        if base.exists():
            for f in sorted(base.rglob("*"), reverse=True):
                if f.is_file():
                    f.unlink()
                    count += 1
                else:
                    f.rmdir()
        return count


class S3Storage:  # pragma: no cover - requires credentials
    def __init__(self) -> None:
        import boto3  # optional dependency

        self.bucket = os.environ["S3_BUCKET"]
        self.client = boto3.client("s3", endpoint_url=os.environ.get("S3_ENDPOINT_URL"))

    def put(self, key: str, data: bytes) -> str:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ServerSideEncryption="AES256")
        return key

    def get(self, key: str) -> bytes | None:
        try:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except self.client.exceptions.NoSuchKey:
            return None

    def delete_prefix(self, prefix: str) -> int:
        n = 0
        for page in self.client.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                self.client.delete_object(Bucket=self.bucket, Key=obj["Key"])
                n += 1
        return n


def get_storage() -> LocalStorage | S3Storage:
    if os.environ.get("STORAGE_BACKEND") == "s3":
        return S3Storage()
    return LocalStorage(get_settings().snapshot_dir)
