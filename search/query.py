"""Source-aware hybrid search (FR-8, CR-1, CR-2, CR-7). Permission, approval and version filters live inside the SQL,
so a chunk the user may not read, a pending draft or a superseded version is never even a candidate."""
from dataclasses import asdict, dataclass

from psycopg import AsyncConnection

from common.db import vector_literal
from common.embed.hashing import GENERIC
from common.models import User
from search.abbreviations import expand, lexical_terms
from search.snippet import best_window, query_terms

SQL = """
WITH visible AS (
    SELECT c.chunk_id, c.document_id, c.version_id, c.page_number, c.section, c.text, c.tsv,
           d.title, d.category, d.department, d.classification, v.version_number,
           tsvector_to_array(to_tsvector('english', regexp_replace(coalesce(c.section, ''), '^.* > ', '')))
               AS heading_terms
    FROM document_chunks c
    JOIN documents d ON d.document_id = c.document_id AND d.active_version_id = c.version_id
    JOIN document_versions v ON v.version_id = c.version_id AND v.status = 'READY'
    WHERE d.deleted_at IS NULL AND d.retired_at IS NULL
      AND EXISTS (SELECT 1 FROM document_acl a WHERE a.document_id = d.document_id AND a.group_name = ANY(%(groups)s))
      AND (%(categories)s::text[] IS NULL OR d.category = ANY(%(categories)s))
      AND (%(departments)s::text[] IS NULL OR d.department = ANY(%(departments)s))
),
scored AS (
    SELECT vis.*, 1 - (e.embedding <=> %(vec)s::vector) AS vscore,
           CASE WHEN cardinality(%(terms)s::text[]) = 0 THEN 0
                ELSE (SELECT count(*) FROM unnest(%(terms)s::text[]) AS t(term)
                      WHERE vis.tsv @@ plainto_tsquery('english', t.term))::float
                     / cardinality(%(terms)s::text[]) END AS tscore,
           CASE WHEN cardinality(vis.heading_terms) = 0 THEN NULL
                ELSE (SELECT count(*) FROM unnest(vis.heading_terms) AS h(term)
                      WHERE h.term = ANY(tsvector_to_array(to_tsvector('english', %(query)s))))::float
                     / cardinality(vis.heading_terms) END AS hscore
    FROM visible vis JOIN document_embeddings e ON e.chunk_id = vis.chunk_id
)
SELECT chunk_id::text, document_id::text, title, version_id::text, version_number, category, department,
       classification, section, page_number, text,
       %(vw)s * greatest(vscore, 0) + %(tw)s * (tscore + coalesce(hscore, tscore)) / 2 AS score
FROM scored ORDER BY score DESC LIMIT %(limit)s
"""


@dataclass(frozen=True)
class SearchHit:
    chunk_id: str
    document_id: str
    title: str
    version_id: str
    version_number: int
    category: str
    department: str
    classification: str
    section: str | None
    page: int
    score: float
    snippet: str
    highlights: list[tuple[int, int]]
    text: str

    def public(self) -> dict:
        data = asdict(self)
        data.pop("text")
        return data


async def search(conn: AsyncConnection, embedder, user: User, q: str, categories: list[str] | None = None,
                 departments: list[str] | None = None, top_k: int = 8, text_weight: float = 0.3) -> list[SearchHit]:
    """Hybrid score combines cosine with query-term coverage and nearest-heading coverage.

    The stored full-text index includes inherited title headings. Those make all sections of a named document
    match equally; use half the lexical weight for the nearest heading so the requested section survives
    document diversity. Plain chunks without a heading keep their existing lexical score.
    """
    if not user.groups:
        return []
    expanded = expand(q)
    [vector] = await embedder.embed([expanded])
    terms = query_terms(expanded)
    rows = await (await conn.execute(SQL, {
        "groups": list(user.groups), "categories": categories or None, "departments": departments or None,
        "vec": vector_literal(vector), "terms": [t for t in lexical_terms(q) if t not in GENERIC], "query": expanded,
        "vw": 1 - text_weight, "tw": text_weight,
        "limit": top_k * 4})).fetchall()
    hits: list[SearchHit] = []
    per_doc: dict[str, int] = {}
    for row in rows:
        if per_doc.get(row[1], 0) >= 2:
            continue
        per_doc[row[1]] = per_doc.get(row[1], 0) + 1
        snippet, highlights = best_window(row[10], terms)
        hits.append(SearchHit(row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8], row[9],
                              round(min(float(row[11]), 1.0), 4), snippet, highlights, row[10]))
        if len(hits) == top_k:
            break
    return hits
