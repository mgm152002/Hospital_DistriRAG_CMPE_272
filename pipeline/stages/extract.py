"""Text extraction with explicit, non-retryable failure codes (RL-6)."""
import io
import pathlib

from pypdf import PdfReader

from pipeline.consumer import PermanentError

MIN_CHARS_PER_PAGE = 20
TEXT_EXTENSIONS = {".txt", ".md", ".markdown"}


def is_markdown(filename: str) -> bool:
    return pathlib.PurePath(filename.lower()).suffix in (".md", ".markdown")


def _pdf_pages(data: bytes) -> list[str]:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise PermanentError("pdf_encrypted", "This PDF is encrypted. Upload an unencrypted copy.")
        pages = [(page.extract_text() or "").replace("\r\n", "\n") for page in reader.pages]
    except PermanentError:
        raise
    except Exception as error:
        raise PermanentError("pdf_malformed", f"This PDF could not be read: {error}") from error
    if not pages:
        raise PermanentError("pdf_malformed", "This PDF has no pages.")
    if sum(len(p.strip()) for p in pages) / len(pages) < MIN_CHARS_PER_PAGE:
        raise PermanentError("pdf_no_text_layer", "This PDF has no text layer (it looks scanned).")
    return pages


def _text_pages(data: bytes) -> list[str]:
    if b"\x00" in data:
        raise PermanentError("invalid_encoding", "The file contains binary data, not UTF-8 text.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise PermanentError("invalid_encoding", "The file is not valid UTF-8 text.") from error
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.split("\f")


def extract_pages(data: bytes, filename: str, content_type: str) -> list[str]:
    """Return the text of each page. Content decides the format (a PDF renamed .txt is still a PDF)."""
    suffix = pathlib.PurePath(filename.lower()).suffix
    if data.startswith(b"%PDF-"):
        pages = _pdf_pages(data)
    elif suffix == ".pdf":
        raise PermanentError("pdf_malformed", "The file is named .pdf but is not a PDF.")
    elif suffix in TEXT_EXTENSIONS:
        pages = _text_pages(data)
    else:
        raise PermanentError("unsupported_type", "Only .txt, .md and text-based .pdf files are supported.")
    if not any(page.strip() for page in pages):
        raise PermanentError("empty_document", "The document has no text.")
    return pages


# ---- handler: version.approved → extract + chunk + plan embed batches -------------------------------------
from common import audit  # noqa: E402
from common.ids import chunk_id  # noqa: E402
from common.models import Stage, VersionStatus  # noqa: E402
from pipeline import events, outbox, repo, streams  # noqa: E402
from pipeline.stages.chunk import split  # noqa: E402

DONE_STAGES = (Stage.EMBED, Stage.FINALIZE)


async def handle_approved(ctx, payload: dict) -> None:
    vid = payload["version_id"]
    async with ctx.pool.connection() as conn, conn.transaction():
        version = await repo.load_version(conn, vid, lock=True)
        if version is None:
            return  # document deleted meanwhile: nothing to do
        if version["status"] not in (VersionStatus.QUEUED, VersionStatus.PROCESSING) or version["stage"] in DONE_STAGES:
            return  # duplicate delivery after the work was committed
        await repo.set_stage(conn, vid, VersionStatus.PROCESSING, Stage.EXTRACT)
        await events.emit(conn, "stage.started", vid, {"stage": "EXTRACT", "consumer": ctx.consumer_name})
    pages = extract_pages(await ctx.blobs.get(version["object_key"]), version["filename"], version["content_type"])
    text_key = f"text/{version['document_id']}/{vid}.txt"
    await ctx.blobs.put(text_key, "\f".join(pages).encode("utf-8"), "text/plain")
    async with ctx.pool.connection() as conn:
        await repo.set_stage(conn, vid, VersionStatus.PROCESSING, Stage.CHUNK)
    s = ctx.settings
    pieces = split(pages, markdown=is_markdown(version["filename"]), size=s.chunk_size, overlap=s.chunk_overlap)
    if not pieces:
        raise PermanentError("empty_document", "The document has no text.")
    batch = s.embed_batch_size
    async with ctx.pool.connection() as conn, conn.transaction():
        async with conn.cursor() as cur:
            await cur.executemany(
                "INSERT INTO document_chunks "
                "(chunk_id, document_id, version_id, chunk_index, page_number, section, text) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (chunk_id) DO NOTHING",
                [(chunk_id(vid, i), version["document_id"], vid, i, p.page, p.section, p.text)
                 for i, p in enumerate(pieces)])
        await conn.execute(
            "UPDATE document_versions SET chunks_total = %s, text_key = %s, stage = %s, updated_at = now() "
            "WHERE version_id = %s", (len(pieces), text_key, Stage.EMBED, vid))
        for number, start in enumerate(range(0, len(pieces), batch)):
            end = min(start + batch, len(pieces)) - 1
            await conn.execute("INSERT INTO embed_batches (version_id, batch_no, chunk_from, chunk_to) "
                               "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING", (vid, number, start, end))
            await outbox.enqueue(conn, streams.EMBED, "batch.ready", f"embed:{vid}:{number}",
                                 {"version_id": vid, "batch_no": number})
        await events.emit(conn, "stage.done", vid, {"stage": "CHUNK", "chunks": len(pieces),
                                                   "consumer": ctx.consumer_name})


async def on_permanent(ctx, payload: dict, error: PermanentError) -> None:
    vid = payload.get("version_id")
    if not vid:
        return
    async with ctx.pool.connection() as conn, conn.transaction():
        await conn.execute(
            "UPDATE document_versions SET status = %s, error_code = %s, error = %s, updated_at = now() "
            "WHERE version_id = %s", (VersionStatus.FAILED, error.code, error.message[:2000], vid))
        await audit.record(conn, "system", "version.failed", vid, {"error_code": error.code})
        await events.emit(conn, "version.failed", vid, {"error_code": error.code, "consumer": ctx.consumer_name})
