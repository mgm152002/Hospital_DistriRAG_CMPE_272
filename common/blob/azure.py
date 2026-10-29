import asyncio
from typing import Any


class AzureBlobStore:
    """Azure Blob Storage (or Azurite in tests)."""

    def __init__(self, connection_string: str, container: str) -> None:
        from azure.storage.blob import BlobServiceClient
        service = BlobServiceClient.from_connection_string(connection_string)
        self.container: Any = service.get_container_client(container)
        self._ready = False

    def _ensure(self) -> None:
        if not self._ready:
            if not self.container.exists():
                self.container.create_container()
            self._ready = True

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        from azure.storage.blob import ContentSettings

        def run() -> None:
            self._ensure()
            self.container.upload_blob(key, data, overwrite=True,
                                       content_settings=ContentSettings(content_type=content_type))
        await asyncio.to_thread(run)

    async def get(self, key: str) -> bytes:
        def run() -> bytes:
            self._ensure()
            return self.container.download_blob(key).readall()
        return await asyncio.to_thread(run)

    async def exists(self, key: str) -> bool:
        def run() -> bool:
            self._ensure()
            return self.container.get_blob_client(key).exists()
        return await asyncio.to_thread(run)

    async def list_prefix(self, prefix: str) -> list[str]:
        def run() -> list[str]:
            self._ensure()
            return sorted(b.name for b in self.container.list_blobs(name_starts_with=prefix))
        return await asyncio.to_thread(run)

    async def delete_prefix(self, prefix: str) -> int:
        keys = await self.list_prefix(prefix)

        def run() -> None:
            for key in keys:
                self.container.delete_blob(key)
        await asyncio.to_thread(run)
        return len(keys)
