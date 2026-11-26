"""Play the demo conversations in corpus/demo_chats.yaml through the public API and give each one its title.

    python scripts/seed_chats.py              # every conversation not already present (by title)
    python scripts/seed_chats.py --only sam   # one persona
    python scripts/seed_chats.py --replace    # delete and replay conversations that already exist

Free model tiers rate-limit hard. A turn that comes back as a provider outage (429s surface that way), or an
"answer" turn that falls back to passages, deletes the half-built conversation and retries it after an
exponential backoff with jitter. Safe to re-run: finished conversations are skipped.
"""
import argparse
import json
import os
import pathlib
import random
import sys
import time

import httpx
import yaml

CASES = pathlib.Path(__file__).resolve().parents[1] / "corpus" / "demo_chats.yaml"
RETRY_FALLBACKS = {"provider_unavailable", "citations", "model_hedge"}  # worth another try for a real answer
OUTAGE = "provider_unavailable"


class Persona:
    """One signed-in demo person (cookie session for local auth, X-User-Id for header auth)."""

    def __init__(self, base: str, user: str):
        self.user = user
        self.http = httpx.Client(base_url=base, timeout=httpx.Timeout(120, connect=15))
        mode = self.http.get("/api/auth/config").raise_for_status().json()["mode"]
        if mode == "local":
            self.http.post(f"/api/auth/demo/{user}").raise_for_status()
        else:
            self.http.headers["X-User-Id"] = user

    def titles(self) -> dict[str, str]:
        rows = self.http.get("/api/conversations").raise_for_status().json()
        return {r["title"]: r["conversation_id"] for r in rows}

    def ask(self, message: str, conversation_id: str | None) -> dict:
        """Send one turn and return the final SSE event; HTTP rate limits are reported as an outage."""
        body = {"message": message, "conversation_id": conversation_id}
        with self.http.stream("POST", "/api/chat", json=body) as r:
            if r.status_code in (429, 502, 503, 504):
                return {"fallback": OUTAGE, "http_status": r.status_code}
            r.raise_for_status()
            event, final = None, None
            for line in r.iter_lines():
                if line.startswith("event: "):
                    event = line[7:]
                elif line.startswith("data: ") and event == "final":
                    final = json.loads(line[6:])
        if final is None:
            return {"fallback": OUTAGE, "error": "stream ended without a final event"}
        return final

    def delete(self, conversation_id: str) -> None:
        self.http.delete(f"/api/conversations/{conversation_id}")

    def rename(self, conversation_id: str, title: str) -> str:
        return self.http.patch(f"/api/conversations/{conversation_id}",
                               json={"title": title}).raise_for_status().json()["title"]


def needs_retry(case: dict, final: dict) -> bool:
    fallback = final.get("fallback")
    if case.get("expect", "answer") == "guardrail":
        return fallback == OUTAGE
    return fallback in RETRY_FALLBACKS


def play(person: Persona, case: dict, attempts: int, base_delay: float, turn_gap: float) -> str:
    """Play every turn of one case, retrying the whole conversation with backoff; return a one-line outcome."""
    for attempt in range(1, attempts + 1):
        conversation_id, outcome = None, []
        for turn in case["turns"]:
            final = person.ask(turn, conversation_id)
            conversation_id = final.get("conversation_id") or conversation_id
            outcome.append(final.get("fallback") or "answered")
            if needs_retry(case, final):
                break
            time.sleep(turn_gap)
        else:
            if conversation_id:
                person.rename(conversation_id, case["title"])
            return " → ".join(outcome)
        if conversation_id:
            person.delete(conversation_id)
        delay = min(base_delay * 2 ** (attempt - 1), 300) * random.uniform(0.8, 1.2)
        print(f"    attempt {attempt}/{attempts}: {' → '.join(outcome)}; retrying in {delay:.0f}s", flush=True)
        time.sleep(delay)
    raise RuntimeError(f"gave up after {attempts} attempts")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="persona id, e.g. sam")
    parser.add_argument("--replace", action="store_true", help="delete and replay conversations that already exist")
    parser.add_argument("--attempts", type=int, default=6)
    parser.add_argument("--base-delay", type=float, default=20.0, help="first backoff in seconds (doubles each try)")
    parser.add_argument("--turn-gap", type=float, default=4.0, help="pause between turns, to stay under rate limits")
    args = parser.parse_args()
    base = os.environ.get("API_URL", "http://localhost:8000")
    cases = [c for c in yaml.safe_load(CASES.read_text())["conversations"]
             if not args.only or c["persona"] == args.only]

    people: dict[str, Persona] = {}
    failed = 0
    for case in cases:
        person = people.get(case["persona"]) or people.setdefault(case["persona"], Persona(base, case["persona"]))
        existing = person.titles().get(case["title"])
        if existing and not args.replace:
            print(f"skip  {case['persona']:<7} {case['title']}")
            continue
        if existing:
            person.delete(existing)
        print(f"play  {case['persona']:<7} {case['title']}", flush=True)
        try:
            print(f"      {play(person, case, args.attempts, args.base_delay, args.turn_gap)}", flush=True)
        except RuntimeError as error:
            failed += 1
            print(f"FAIL  {case['title']}: {error}", flush=True)
    print(f"done: {len(cases) - failed}/{len(cases)} conversations in place")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
