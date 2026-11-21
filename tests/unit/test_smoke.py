"""Covers: DP-6 (single codebase), E0-1."""
import importlib
import pathlib

PACKAGES = ["common", "api", "pipeline", "search", "assistant", "documents"]
ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_packages_import():
    for name in PACKAGES:
        importlib.import_module(name)


def test_no_temporal_imports():
    offenders = [
        str(path.relative_to(ROOT))
        for path in ROOT.rglob("*.py")
        if ".superpowers" not in path.parts and "node_modules" not in path.parts
        and "temporalio" in path.read_text(encoding="utf-8", errors="ignore")
        and path.name != "test_smoke.py"
    ]
    assert offenders == []
