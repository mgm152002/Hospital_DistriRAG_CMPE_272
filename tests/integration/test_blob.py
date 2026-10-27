"""Covers: DP-4."""
import os
import uuid

import pytest

from common.blob.local import LocalBlobStore


def stores(tmp_path):
    out = [("local", LocalBlobStore(str(tmp_path)))]
    if os.environ.get("S3_ENDPOINT_URL"):
        from common.blob.s3 import S3BlobStore
        out.append(("s3", S3BlobStore(bucket="distrirag-test", endpoint_url=os.environ["S3_ENDPOINT_URL"])))
    if os.environ.get("AZURE_CONNECTION_STRING"):
        from common.blob.azure import AzureBlobStore
        out.append(("azure", AzureBlobStore(os.environ["AZURE_CONNECTION_STRING"], "distrirag-test")))
    return out


@pytest.mark.parametrize("kind", ["local", "s3", "azure"])
async def test_blob_roundtrip(kind, tmp_path):
    found = dict(stores(tmp_path))
    if kind not in found:
        pytest.skip(f"{kind} not configured")
    store = found[kind]
    prefix = f"t/{uuid.uuid4()}/"
    await store.put(prefix + "a.txt", b"hello", "text/plain")
    await store.put(prefix + "b.txt", b"world", "text/plain")
    assert await store.get(prefix + "a.txt") == b"hello"
    assert await store.exists(prefix + "a.txt")
    assert sorted(await store.list_prefix(prefix)) == [prefix + "a.txt", prefix + "b.txt"]
    assert await store.delete_prefix(prefix) == 2
    assert not await store.exists(prefix + "a.txt")
