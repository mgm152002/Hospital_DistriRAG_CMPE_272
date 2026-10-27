from dataclasses import dataclass


@dataclass(frozen=True)
class Passage:
    index: int
    chunk_id: str
    document_id: str
    title: str
    version_number: int
    section: str | None
    page: int
    classification: str
    text: str
    score: float
    version_id: str = ""
    category: str = ""

    def card(self) -> dict:
        return {"index": self.index, "chunk_id": self.chunk_id, "document_id": self.document_id,
                "version_id": self.version_id, "title": self.title, "version_number": self.version_number,
                "section": self.section, "page": self.page, "classification": self.classification,
                "category": self.category, "score": self.score, "text": self.text}
