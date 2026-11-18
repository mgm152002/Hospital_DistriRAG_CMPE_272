"""Covers: TS-1, E12-1."""
import pathlib

import yaml

from common.models import CATEGORIES, CLASSIFICATIONS

ROOT = pathlib.Path(__file__).resolve().parents[2] / "corpus"
MANIFEST = yaml.safe_load((ROOT / "manifest.yaml").read_text())
GROUPS = set(yaml.safe_load((ROOT.parent / "config" / "personas.yaml").read_text())["known_groups"])
BANNER = "SYNTHETIC — FOR DEMONSTRATION ONLY — NOT CLINICAL GUIDANCE"
REQUIRED = {"key", "file", "title", "category", "department", "classification", "groups", "version"}


def text_of(entry):
    path = ROOT / entry["file"]
    if path.suffix == ".pdf":
        from pipeline.stages.extract import extract_pages
        return "\n".join(extract_pages(path.read_bytes(), path.name, "application/pdf"))
    return path.read_text(encoding="utf-8")


def test_manifest_valid_and_files_exist():
    docs = MANIFEST["documents"]
    assert len({d["key"] for d in docs if d["version"] == 1}) == 24
    assert sum(1 for d in docs if d["version"] == 2) == 4
    for d in docs:
        assert set(d) >= REQUIRED, d
        assert (ROOT / d["file"]).is_file(), d["file"]


def test_every_file_has_synthetic_banner():
    for d in MANIFEST["documents"]:
        assert BANNER.replace("—", "-") in text_of(d).replace("—", "-"), d["file"]


def test_categories_classifications_and_groups_known():
    for d in MANIFEST["documents"]:
        assert d["category"] in CATEGORIES and d["classification"] in CLASSIFICATIONS
        assert set(d["groups"]) <= GROUPS, d


def test_v2_differs_from_v1():
    by_key = {}
    for d in MANIFEST["documents"]:
        by_key.setdefault(d["key"], {})[d["version"]] = d
    for versions in by_key.values():
        if 2 in versions:
            assert text_of(versions[1]) != text_of(versions[2])
            assert versions[2]["title"] == versions[1]["title"]


def test_formats_mix():
    suffixes = {pathlib.Path(d["file"]).suffix for d in MANIFEST["documents"]}
    assert suffixes == {".md", ".txt", ".pdf"}
