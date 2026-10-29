import re
from typing import Protocol

from common.config import Settings

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


class BlobStore(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def exists(self, key: str) -> bool: ...
    async def delete_prefix(self, prefix: str) -> int: ...
    async def list_prefix(self, prefix: str) -> list[str]: ...


def safe_key(*parts: str) -> str:
    """Join key parts; each part loses path separators, '..' and characters outside [A-Za-z0-9._-]."""
    cleaned = []
    for part in parts:
        name = _UNSAFE.sub("_", part.replace("/", "_").replace("\\", "_")).strip("._") or "file"
        cleaned.append(name)
    return "/".join(cleaned)


def make_blob_store(s: Settings) -> BlobStore:
    if s.blob_provider == "s3":
        from common.blob.s3 import S3BlobStore
        return S3BlobStore(bucket=s.s3_bucket, endpoint_url=s.s3_endpoint_url or None)
    if s.blob_provider == "azure":
        from common.blob.azure import AzureBlobStore
        return AzureBlobStore(s.azure_connection_string, s.azure_container)
    from common.blob.local import LocalBlobStore
    return LocalBlobStore(s.blob_root)
