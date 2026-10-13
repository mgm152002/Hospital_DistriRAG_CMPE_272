"""Heading-aware chunking (800 characters, 100 overlap). Pure: no I/O."""
import re
from dataclasses import dataclass

MD_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
PLAIN_HEADING = re.compile(r"^(\d+(\.\d+)*\.?\s+)?[A-Z][A-Za-z0-9 /&(),'-]{2,70}$")


@dataclass(frozen=True)
class Piece:
    page: int
    section: str | None
    text: str


def _windows(text: str, size: int, overlap: int) -> list[str]:
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    out: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            cut = text.rfind(" ", start + size - overlap, end)
            cut = max(cut, text.rfind("\n", start + size - overlap, end))
            if cut > start:
                end = cut
        piece = text[start:end].strip()
        if piece:
            out.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
        while start < len(text) and start > 0 and not text[start - 1].isspace() and text[start].isalnum():
            start += 1
            if start >= end:
                break
    return out


def _blocks_markdown(page: str) -> list[tuple[str | None, str]]:
    stack: list[tuple[int, str]] = []
    blocks: list[tuple[str | None, list[str]]] = [(None, [])]
    for line in page.split("\n"):
        match = MD_HEADING.match(line)
        if match:
            level, title = len(match.group(1)), match.group(2).strip()
            stack = [(lv, t) for lv, t in stack if lv < level] + [(level, title)]
            blocks.append((" > ".join(t for _, t in stack), []))
        else:
            blocks[-1][1].append(line)
    return [(section, "\n".join(lines)) for section, lines in blocks]


def _blocks_plain(page: str, current: str | None) -> tuple[list[tuple[str | None, str]], str | None]:
    blocks: list[tuple[str | None, list[str]]] = [(current, [])]
    for line in page.split("\n"):
        stripped = line.strip()
        if PLAIN_HEADING.match(stripped) and not stripped.endswith(".") and len(stripped.split()) <= 10:
            current = stripped
            blocks.append((current, [line]))
        else:
            blocks[-1][1].append(line)
    return [(section, "\n".join(lines)) for section, lines in blocks], current


def split(pages: list[str], markdown: bool, size: int = 800, overlap: int = 100) -> list[Piece]:
    pieces: list[Piece] = []
    current: str | None = None
    for number, page in enumerate(pages, start=1):
        if markdown:
            blocks = _blocks_markdown(page)
        else:
            blocks, current = _blocks_plain(page, current)
        for section, text in blocks:
            if section and text.strip() == section.strip():
                continue  # a heading with no body of its own carries nothing worth retrieving
            pieces += [Piece(number, section, window) for window in _windows(text, size, overlap)]
    return pieces
