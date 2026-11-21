import httpx

from api.app import create_app
from api.deps import AppState
from common.blob.local import LocalBlobStore
from common.config import Settings
from common.embed import HashingEmbedder
from common.llm import load_providers
from common.llm.fake import FakeLLM


def build_state(pool, redis, tmp_path, llm=None, **overrides) -> AppState:
    settings = Settings(_env_file=None, blob_root=str(tmp_path), **overrides)
    return AppState(settings=settings, pool=pool, redis=redis, blobs=LocalBlobStore(str(tmp_path)),
                    embedder=HashingEmbedder(), llm=llm or FakeLLM(), providers=load_providers())


def client(state) -> httpx.AsyncClient:
    app = create_app(state=state)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def as_user(user: str, **extra) -> dict:
    return {"X-User-Id": user, **extra}


def upload_form(title="Hand Hygiene Policy", category="Infection Control", classification="internal",
                groups="all-staff", department="Infection Prevention"):
    return {"title": title, "category": category, "classification": classification, "groups": groups,
            "department": department, "effective_date": "2026-11-01", "review_due": "2027-11-01"}
