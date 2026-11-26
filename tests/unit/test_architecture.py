"""Business rules stay pure: rule modules never import I/O libraries (ports-and-adapters rule).
Covers: TS-6."""
import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
PURE = [
    "assistant/classify.py", "assistant/phi.py", "assistant/citations.py", "assistant/clinical.py",
    "assistant/confidence.py", "assistant/egress_policy.py", "assistant/injection.py", "assistant/prompt.py",
    "assistant/history.py",
    "pipeline/stages/chunk.py", "search/snippet.py", "documents/validation.py", "common/ids.py",
]
IO = {"psycopg", "psycopg_pool", "redis", "httpx", "fastapi", "boto3", "azure", "fastembed"}


def imported_roots(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text())
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_rule_modules_do_not_import_io():
    for rel in PURE:
        path = ROOT / rel
        if path.exists():
            assert not (imported_roots(path) & IO), f"{rel} imports I/O: {imported_roots(path) & IO}"
