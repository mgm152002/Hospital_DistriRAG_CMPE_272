import asyncio
import pathlib
import shutil


class LocalBlobStore:
    def __init__(self, root: str) -> None:
        self.root = pathlib.Path(root)

    def _path(self, key: str) -> pathlib.Path:
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents and path != self.root.resolve():
            raise ValueError(f"key escapes the blob root: {key}")
        return path

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)

        def write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
        await asyncio.to_thread(write)

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._path(key).read_bytes)

    async def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    async def age_seconds(self, key: str) -> float:
        import time
        return time.time() - self._path(key).stat().st_mtime

    async def list_prefix(self, prefix: str) -> list[str]:
        base = self._path(prefix.rstrip("/")) if prefix.strip("/") else self.root
        if not base.exists():
            return []
        return sorted(str(p.relative_to(self.root)) for p in base.rglob("*") if p.is_file())

    async def delete_prefix(self, prefix: str) -> int:
        keys = await self.list_prefix(prefix)
        base = self._path(prefix.rstrip("/"))
        if base.exists():
            await asyncio.to_thread(shutil.rmtree, base, True)
        return len(keys)
