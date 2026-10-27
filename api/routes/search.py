from fastapi import APIRouter, Depends, Query

from api.auth import current_user
from api.deps import AppState, get_state
from api.errors import ApiError
from assistant.phi import screen
from common import audit
from common.models import User
from search.query import search

router = APIRouter(prefix="/api")


@router.get("/search")
async def search_route(q: str = "", category: list[str] | None = Query(None),
                       department: list[str] | None = Query(None), top_k: int = Query(8, ge=1, le=20),
                       user: User = Depends(current_user), state: AppState = Depends(get_state)):
    q = q.strip()
    if not 2 <= len(q) <= 500:
        raise ApiError(422, "invalid_query", "Search text must be 2–500 characters.")
    phi = screen(q)
    if phi.found and state.settings.phi_mode == "block":
        raise ApiError(400, "phi_detected", "Please remove patient-identifying information and search again.")
    if not phi.search_text:  # nothing but identifiers: there is nothing to look for
        return []
    async with state.pool.connection() as conn:
        hits = await search(conn, state.embedder, user, phi.search_text, category, department, top_k,
                            text_weight=state.settings.hybrid_text_weight)
        await audit.record(conn, user.user_id, "search.performed", None,
                           {"query": phi.redacted, "results": len(hits), "categories": category or []})
    return [hit.public() for hit in hits if hit.score >= state.settings.min_relevance]
