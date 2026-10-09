"""Upload validation at the door (FR-1). Pure: no I/O. Content decides the type; the name only guides text files."""
import hashlib
import pathlib

TEXT_SUFFIXES = {".txt": "txt", ".md": "md", ".markdown": "md"}


class UploadError(Exception):
    def __init__(self, code: str, detail: str, status: int = 400) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status = status


def validate_upload(filename: str | None, content_type: str | None, data: bytes, max_bytes: int) -> tuple[str, str]:
    if len(data) > max_bytes:
        raise UploadError("too_large", f"Files must be at most {max_bytes // (1024 * 1024)} MB.", 413)
    if not data.strip():
        raise UploadError("empty_document", "The file is empty.")
    suffix = pathlib.PurePath((filename or "").lower()).suffix
    if data.startswith(b"%PDF-"):
        kind = "pdf"
    elif suffix == ".pdf":
        raise UploadError("pdf_malformed", "The file is named .pdf but is not a PDF.")
    elif suffix in TEXT_SUFFIXES:
        if b"\x00" in data:
            raise UploadError("invalid_encoding", "The file contains binary data, not text.")
        try:
            data.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise UploadError("invalid_encoding", "The file is not valid UTF-8 text.") from error
        kind = TEXT_SUFFIXES[suffix]
    else:
        raise UploadError("unsupported_type", "Only .txt, .md and text-based .pdf files are supported.")
    return kind, hashlib.sha256(data).hexdigest()


CONTENT_TYPES = {"pdf": "application/pdf", "md": "text/markdown", "txt": "text/plain"}
