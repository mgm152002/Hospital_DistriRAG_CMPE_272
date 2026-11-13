"""Resolve public files while refusing traversal and symlinks outside the web build."""
from pathlib import Path


def resolve_public_path(root: str | Path, request_path: str) -> Path:
    base = Path(root).resolve()
    candidate = (base / request_path).resolve()
    if not candidate.is_relative_to(base):
        raise ValueError("The requested file is outside the public directory.")
    return candidate


def cache_control(request_path: str) -> str:
    """Hashed build assets never change, so they cache for good; everything else (the HTML shell) is revalidated on
    every load so a deploy is visible without a hard refresh."""
    if request_path.lstrip("/").startswith("assets/"):
        return "public, max-age=31536000, immutable"
    return "no-cache"
