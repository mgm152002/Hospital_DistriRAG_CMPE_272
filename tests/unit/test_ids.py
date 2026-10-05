"""Covers: CR-4."""
import uuid

from common.ids import chunk_id


def test_chunk_id_deterministic():
    vid = str(uuid.uuid4())
    assert chunk_id(vid, 3) == chunk_id(vid, 3)
    assert chunk_id(vid, 3) != chunk_id(vid, 4)
    assert chunk_id(vid, 0) != chunk_id(str(uuid.uuid4()), 0)
    assert uuid.UUID(chunk_id(vid, 0)).version == 5
