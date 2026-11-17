"""Relevance calibration (spec E12-4): compare the best score of the expected document with the best score
for questions that should find nothing, for the configured embedder. Usage: python scripts/calibrate.py --api URL"""
import argparse
import statistics

import httpx
import yaml

with open("evals/cases.yaml", encoding="utf-8") as handle:
    cases = yaml.safe_load(handle)["cases"]
parser = argparse.ArgumentParser()
parser.add_argument("--api", default="http://localhost:8000")
base = parser.parse_args().api
relevant, irrelevant = [], []
with httpx.Client(base_url=base, timeout=60) as api:
    for case in cases:
        hits = api.get("/api/search", params={"q": case["question"]}, headers={"X-User-Id": case["persona"]}).json()
        if case.get("docs") and case.get("expect") == "answer":
            scores = [h["score"] for h in hits if h["title"] in case["docs"]]
            relevant.append(max(scores) if scores else 0.0)
        elif case.get("expect") in ("out_of_scope", "no_sources") or case["id"].startswith("R"):
            irrelevant.append(max((h["score"] for h in hits), default=0.0))
for name, values in (("expected document", relevant), ("should find nothing", irrelevant)):
    q = statistics.quantiles(values, n=10) if len(values) > 1 else values
    print(f"{name:22s} n={len(values):3d} min={min(values):.3f} p10={q[0]:.3f} median={statistics.median(values):.3f} "
          f"max={max(values):.3f}")
