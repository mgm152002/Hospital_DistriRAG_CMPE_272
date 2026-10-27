import asyncio
from typing import Any


class S3BlobStore:
    """AWS S3, MinIO or SeaweedFS (boto3, run in a thread)."""

    def __init__(self, bucket: str, endpoint_url: str | None = None) -> None:
        import boto3
        self.bucket = bucket
        self.client: Any = boto3.client("s3", endpoint_url=endpoint_url)
        self._ready = False

    def _ensure(self) -> None:
        if self._ready:
            return
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except Exception:
            self.client.create_bucket(Bucket=self.bucket)
        self._ready = True

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        def run() -> None:
            self._ensure()
            self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)
        await asyncio.to_thread(run)

    async def get(self, key: str) -> bytes:
        def run() -> bytes:
            self._ensure()
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        return await asyncio.to_thread(run)

    async def exists(self, key: str) -> bool:
        def run() -> bool:
            self._ensure()
            try:
                self.client.head_object(Bucket=self.bucket, Key=key)
                return True
            except Exception:
                return False
        return await asyncio.to_thread(run)

    async def list_prefix(self, prefix: str) -> list[str]:
        def run() -> list[str]:
            self._ensure()
            keys: list[str] = []
            for page in self.client.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=prefix):
                keys += [item["Key"] for item in page.get("Contents", [])]
            return sorted(keys)
        return await asyncio.to_thread(run)

    async def delete_prefix(self, prefix: str) -> int:
        keys = await self.list_prefix(prefix)

        def run() -> None:
            for start in range(0, len(keys), 1000):
                batch = [{"Key": k} for k in keys[start:start + 1000]]
                self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": batch})
        if keys:
            await asyncio.to_thread(run)
        return len(keys)
