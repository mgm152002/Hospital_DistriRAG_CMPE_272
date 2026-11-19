"""Requirement coverage matrix (spec 9.3): every Must requirement must be named by at least one test.

Tests declare what they cover in a docstring or comment: `Covers: RL-4, CR-3, AG-1..AG-9`.
Usage: python scripts/coverage_matrix.py      (exit 1 if a Must requirement has no test)
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
MUST = {
    "FR": [1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 13], "RL": list(range(1, 11)), "CR": list(range(1, 8)),
    "AG": [1, 2, 3, 4, 5, 6, 7, 9], "DP": list(range(1, 8)), "CP": list(range(1, 10)), "UX": list(range(1, 11)),
    "TS": list(range(1, 7)),
}
SHOULD = {"FR": [9, 11], "AG": [8, 10], "CP": [10]}
ID = re.compile(r"\b([A-Z]{2})-(\d+)(?:\.\.(?:[A-Z]{2}-)?(\d+))?")
COVERS = re.compile(r"Covers:([^\n\"]*)")


def covered() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    files = list((ROOT / "tests").rglob("*.py")) + list((ROOT / "web" / "src").rglob("*.test.tsx"))
    for path in files:
        for block in COVERS.findall(path.read_text(encoding="utf-8")):
            for prefix, start, end in ID.findall(block):
                for n in range(int(start), int(end or start) + 1):
                    found.setdefault(f"{prefix}-{n}", set()).add(str(path.relative_to(ROOT)))
    return found


def main() -> int:
    found = covered()
    missing = []
    print(f"{'requirement':12s} tests")
    for prefix, numbers in MUST.items():
        for n in numbers:
            rid = f"{prefix}-{n}"
            files = sorted(found.get(rid, set()))
            print(f"{rid:12s} {len(files):3d}  {', '.join(pathlib.Path(f).name for f in files[:3])}")
            if not files:
                missing.append(rid)
    should = [f"{p}-{n}" for p, ns in SHOULD.items() for n in ns if f"{p}-{n}" not in found]
    total = sum(len(v) for v in MUST.values())
    print(f"\n{total - len(missing)}/{total} Must requirements covered")
    if should:
        print("Should requirements without a test:", ", ".join(should))
    if missing:
        print("MISSING:", ", ".join(missing))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
