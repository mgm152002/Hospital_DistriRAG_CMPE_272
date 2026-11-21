"""Remove test leftovers from the demo database so they never show up in staff search.

    python scripts/clean_demo.py            # dry run: list what would be deleted and what is kept
    python scripts/clean_demo.py --apply    # delete, as the compliance persona (the pipeline removes the vectors)

Managed documents are the ones in corpus/manifest.yaml. Anything else matching LEFTOVER (the titles the test suites
create) is deleted; an unmanaged document that does not look like a test is only reported.
"""
import argparse
import os
import pathlib
import re
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
LEFTOVER = r"^(Synthetic Ward Guide|Quiet Hours Policy|Acceptance Policy)\b"  # titles the test suites create


def plan(documents: list[dict], managed: set[str], pattern: str) -> tuple[list[dict], list[dict]]:
    """(to delete, unmanaged but kept), each sorted by title."""
    unmanaged = sorted((d for d in documents if d["title"] not in managed), key=lambda d: d["title"])
    delete = [d for d in unmanaged if re.search(pattern, d["title"])]
    return delete, [d for d in unmanaged if d not in delete]


def main() -> int:
    from scripts.seed import SeedClient, existing, headers

    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="delete; without it nothing changes")
    parser.add_argument("--pattern", default=LEFTOVER, help="regex of titles to delete")
    args = parser.parse_args()
    managed = {e["title"] for e in yaml.safe_load((ROOT / "corpus" / "manifest.yaml").read_text())["documents"]}
    with SeedClient(base_url=os.environ.get("API_URL", "http://localhost:8000"), timeout=60) as client:
        client.configure_auth()
        docs = list(existing(client).values())
        delete, kept = plan(docs, managed, args.pattern)
        for d in kept:
            print(f"keep    {d['title']}  (unmanaged, does not look like a test)")
        for d in delete:
            if args.apply:
                response = client.delete(f"/api/documents/{d['document_id']}", headers=headers("taylor"))
                response.raise_for_status()
            print(f"{'deleted' if args.apply else 'would delete'}  {d['title']}")
    managed_count = len(docs) - len(delete) - len(kept)
    print(f"{len(delete)} {'deleted' if args.apply else 'to delete'}, {len(kept)} kept, {managed_count} managed")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    sys.exit(main())
