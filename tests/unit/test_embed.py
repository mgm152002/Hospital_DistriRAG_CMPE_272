"""Covers: DP-3, TS-3, E4-5."""
import math

from common.embed import HashingEmbedder


def cos(a, b):
    return sum(x * y for x, y in zip(a, b, strict=True))


async def test_hashing_embedder_deterministic_and_normalized():
    e = HashingEmbedder(dim=384)
    [a] = await e.embed(["Perform hand hygiene before patient contact"])
    [b] = await e.embed(["Perform hand hygiene before patient contact"])
    assert a == b and len(a) == 384
    assert math.isclose(sum(x * x for x in a), 1.0, rel_tol=1e-6)


async def test_hashing_similar_texts_closer():
    e = HashingEmbedder(dim=384)
    a, b, c = await e.embed([
        "Rub hands with alcohol-based hand rub for 20 seconds",
        "How long should the alcohol hand rub last?",
        "Visitor parking hours and the front desk",
    ])
    assert cos(a, b) > cos(a, c) + 0.1


async def test_hashing_empty_text_is_unit_vector():
    [v] = await HashingEmbedder(dim=384).embed(["   "])
    assert math.isclose(sum(x * x for x in v), 1.0)


async def test_generic_hospital_words_carry_less_weight():
    e = HashingEmbedder(dim=384)
    query, specific, generic = await e.embed([
        "How much heparin should I give a patient?",
        "Heparin infusions need an independent double-check.",
        "The patient should give the patient care to every patient on the unit.",
    ])
    assert cos(query, specific) > cos(query, generic)
