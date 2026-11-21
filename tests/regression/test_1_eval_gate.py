"""Guardrail and retrieval eval as a CI gate (spec 10.2, TS-5). Covers: AG-1..AG-9, CR-2, CR-7, CP-3, TS-5."""
import pytest

from evals.run import check, evaluate, render

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_eval_meets_every_threshold(seeded):
    report = await evaluate(seeded.api)
    print(render(report))
    assert report["cases"] >= 74
    assert check(report) == [], report["failures"]
