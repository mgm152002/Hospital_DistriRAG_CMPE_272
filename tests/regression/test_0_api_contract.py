"""API contract snapshot: routes, methods and parameters may only change on purpose (UPDATE_SNAPSHOTS=1).
The frontend's hand-written types (web/src/api/types.ts) depend on this contract. Covers: TS-4."""
import json
import os
import pathlib

from api.app import create_app

SNAPSHOT = pathlib.Path(__file__).with_name("openapi.snapshot.json")


def contract() -> dict:
    spec = create_app().openapi()
    out = {}
    for path, methods in sorted(spec["paths"].items()):
        for method, op in sorted(methods.items()):
            params = sorted(p["name"] for p in op.get("parameters", []))
            body = op.get("requestBody", {}).get("content", {})
            out[f"{method.upper()} {path}"] = {"params": params, "body": sorted(body)}
    return out


def test_api_contract_matches_snapshot():
    current = contract()
    if os.environ.get("UPDATE_SNAPSHOTS") or not SNAPSHOT.exists():
        SNAPSHOT.write_text(json.dumps(current, indent=2) + "\n")
    assert current == json.loads(SNAPSHOT.read_text())
