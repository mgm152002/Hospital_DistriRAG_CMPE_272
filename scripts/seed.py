"""Seed the synthetic corpus through the public API: upload as Alex, approve as Taylor, wait until READY.

    python scripts/seed.py            # every version-1 document
    python scripts/seed.py --v2       # the four version-2 updates (for the live version demo)
    python scripts/seed.py --review-queue   # drafts uploaded but left pending, for the approval demo

Safe to re-run: documents that already exist (by title) are skipped, and uploads carry an Idempotency-Key.
"""
import argparse
import os
import pathlib
import sys
import time

import httpx
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1] / "corpus"
TYPES = {".md": "text/markdown", ".txt": "text/plain", ".pdf": "application/pdf"}


def headers(user: str, key: str | None = None) -> dict[str, str]:
    return {"X-User-Id": user, **({"Idempotency-Key": key} if key else {})}


class SeedClient(httpx.Client):
    """Keep independent demo cookies for upload and approval when local auth is enabled."""

    def configure_auth(self) -> None:
        self._local = self.get("/api/auth/config").raise_for_status().json()["mode"] == "local"
        self._persona_cookies: dict[str, httpx.Cookies] = {}

    def send(self, request: httpx.Request, **kwargs) -> httpx.Response:
        user = request.headers.get("X-User-Id")
        if getattr(self, "_local", False) and user:
            if user not in self._persona_cookies:
                self.cookies.clear()
                response = self.post(f"/api/auth/demo/{user}")
                response.raise_for_status()
                self._persona_cookies[user] = httpx.Cookies(self.cookies)
            request.headers.pop("Cookie", None)
            self._persona_cookies[user].set_cookie_header(request)
        return super().send(request, **kwargs)


def existing(client: httpx.Client) -> dict[str, dict]:
    return {d["title"]: d for d in client.get("/api/documents", headers=headers("alex")).raise_for_status().json()}


def upload(client: httpx.Client, entry: dict, document_id: str | None, approve: bool = True) -> str:
    path = ROOT / entry["file"]
    files = {"file": (path.name, path.read_bytes(), TYPES[path.suffix])}
    key = f"seed:{entry['key']}:v{entry['version']}"
    if document_id:
        response = client.post(f"/api/documents/{document_id}/versions", headers=headers("alex", key), files=files)
    else:
        form = {k: entry[k] for k in ("title", "category", "department", "classification")}
        form["groups"] = ",".join(entry["groups"])
        response = client.post("/api/documents", headers=headers("alex", key), data=form, files=files)
    response.raise_for_status()
    version_id = response.json()["version_id"]
    if not approve:
        return version_id
    approved = client.post(f"/api/versions/{version_id}/approve", headers=headers("taylor"), json={"comment": "seed"})
    approved.raise_for_status()
    return version_id


def wait_ready(client: httpx.Client, version_ids: list[str], timeout: float) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    statuses: dict[str, str] = {}
    while time.monotonic() < deadline:
        statuses = {v: client.get(f"/api/versions/{v}/status", headers=headers("alex")).json()["status"]
                    for v in version_ids}
        if all(s in ("READY", "FAILED") for s in statuses.values()):
            break
        time.sleep(1)
    return statuses


def review_queue(base: str) -> int:
    entries = yaml.safe_load((ROOT / "review" / "queue.yaml").read_text())["documents"]
    with SeedClient(base_url=base, timeout=60) as client:
        client.configure_auth()
        have = existing(client)
        for entry in entries:
            if entry["title"] in have:
                print(f"skip   {entry['title']} (exists)")
                continue
            upload(client, entry, None, approve=False)
            print(f"draft  {entry['title']} (pending approval)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--v2", action="store_true", help="upload the version-2 updates")
    parser.add_argument("--review-queue", action="store_true", help="upload drafts and leave them pending approval")
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args()
    base = os.environ.get("API_URL", "http://localhost:8000")
    if args.review_queue:
        return review_queue(base)
    entries = yaml.safe_load((ROOT / "manifest.yaml").read_text())["documents"]
    wanted = 2 if args.v2 else 1
    with SeedClient(base_url=base, timeout=60) as client:
        client.configure_auth()
        have = existing(client)
        started = time.monotonic()
        version_ids = []
        for entry in (e for e in entries if e["version"] == wanted):
            current = have.get(entry["title"])
            if wanted == 1 and current:
                print(f"skip   {entry['title']} (exists)")
                continue
            if wanted == 2 and (current is None or (current.get("latest_version_number") or 0) >= 2):
                print(f"skip   {entry['title']} (v2 present or v1 missing)")
                continue
            version_ids.append(upload(client, entry, current["document_id"] if wanted == 2 and current else None))
            print(f"upload {entry['title']} v{entry['version']}")
        statuses = wait_ready(client, version_ids, args.timeout)
    ready = sum(s == "READY" for s in statuses.values())
    print(f"{ready}/{len(version_ids)} READY in {time.monotonic() - started:.1f}s")
    return 0 if ready == len(version_ids) else 1


if __name__ == "__main__":
    sys.exit(main())
