"""Covers: FR-1, RL-6 (at the door)."""
import pytest

from documents.validation import UploadError, validate_upload
from tests.fixtures.make_docs import text_pdf

MAX = 10 * 1024 * 1024


def code(filename, data, content_type=None):
    with pytest.raises(UploadError) as caught:
        validate_upload(filename, content_type, data, MAX)
    return caught.value.code, caught.value.status


def test_upload_filename_variants():
    """Review Focus 2: case, missing extension, wrong content type, traversal."""
    assert validate_upload("POLICY.PDF", None, text_pdf(["Hand hygiene."]), MAX)[0] == "pdf"
    assert validate_upload("notes.md", "application/octet-stream", b"# Hi\ntext", MAX)[0] == "md"
    assert validate_upload("../../evil name.txt", "text/plain", b"hello", MAX)[0] == "txt"
    assert code("noextension", b"hello") == ("unsupported_type", 400)


def test_reject_types_and_size():
    assert code("a.docx", b"PK\x03\x04") == ("unsupported_type", 400)
    assert code("a.png", b"\x89PNG") == ("unsupported_type", 400)
    assert code("a.pdf", b"not a pdf") == ("pdf_malformed", 400)
    assert code("a.md", b"\x00\x01binary") == ("invalid_encoding", 400)
    assert code("big.txt", b"x" * (MAX + 1)) == ("too_large", 413)
    assert code("empty.txt", b"") == ("empty_document", 400)


def test_pdf_named_txt_is_pdf():
    assert validate_upload("policy.txt", "text/plain", text_pdf(["Gloves."]), MAX)[0] == "pdf"


def test_sha256_returned():
    assert validate_upload("a.txt", None, b"abc", MAX)[1].startswith("ba7816bf")
