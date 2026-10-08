"""Covers: CP-10, TS-6 (documentation is current and complete)."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
LEGACY = re.compile(r"\b(Temporal|Kubernetes|k3s|KEDA|helpdesk|SigNoz)\b", re.IGNORECASE)
HISTORY = {"DECISIONS.md", "PROPOSAL.md"}


def docs():
    yield ROOT / "README.md"
    yield from (ROOT / "docs").glob("*.md")


def test_no_legacy_terms_outside_history():
    offenders = [f"{p.name}: {m.group(0)}" for p in docs() if p.name not in HISTORY
                 for m in LEGACY.finditer(p.read_text(encoding="utf-8"))]
    assert offenders == []


def test_required_documents_exist():
    names = {p.name for p in docs()}
    assert {"README.md", "ARCHITECTURE.md", "DECISIONS.md", "SECURITY.md", "COMPLIANCE.md", "DEMO.md",
            "DEVELOPMENT.md", "RESULTS.md"} <= names
    assert (ROOT / "deploy" / "cloud" / "README.md").is_file()


def test_compliance_maps_hipaa_safeguards():
    text = (ROOT / "docs" / "COMPLIANCE.md").read_text(encoding="utf-8")
    for safeguard in ("Access control", "Audit controls", "Integrity", "authentication", "Transmission security"):
        assert safeguard.lower() in text.lower(), safeguard
