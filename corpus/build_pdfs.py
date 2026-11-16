"""Rebuild corpus PDFs from corpus/src/*.txt (run in the dev container: python corpus/build_pdfs.py)."""
import pathlib

from tests.fixtures.make_docs import text_pdf

ROOT = pathlib.Path(__file__).parent
for source in sorted((ROOT / "src").glob("*.txt")):
    (ROOT / f"{source.stem}.pdf").write_bytes(text_pdf([source.read_text(encoding="utf-8")]))
    print("built", source.stem + ".pdf")
