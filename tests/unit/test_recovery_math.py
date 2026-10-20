"""Covers: RL-5, RL-7."""
from pipeline.recovery import due_idle_ms


def test_due_idle_backoff():
    assert [due_idle_ms(n, 60_000) for n in (1, 2, 3, 4, 10)] == [60_000, 120_000, 240_000, 480_000, 600_000]


def test_due_idle_scales_with_base():
    assert due_idle_ms(1, 200) == 200 and due_idle_ms(9, 200) == 2000
