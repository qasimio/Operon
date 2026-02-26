# tools/path_resolver.py — Operon v3.1
"""
Resolves any user-supplied filename to an actual repo path.
This is the fix for: "can not figure out file if it is inside folder."

5-tier search (same logic as your working loop.py's resolve_repo_path,
but extended):
  1. Exact relative path
  2. Case-insensitive exact match
  3. Recursive filename match  (all extensions, shortest path wins)
  4. Fuzzy basename stem match  (e.g. "semantic" → "tools/semantic_memory.py")
  5. Symbol index lookup        (if state provided)
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

IGNORE_DIRS = {".git", ".venv", "__pycache__", "node_modules", "dist", "build", ".operon"}


def _all_files(repo_root: str):
    root = Path(repo_root)
    for p in root.rglob("*"):
        if p.is_file() and not any(d in p.parts for d in IGNORE_DIRS):
            yield p


def resolve_path(user_path: str, repo_root: str, state=None) -> Tuple[str, bool]:
    """
    Returns (resolved_relative_path, found: bool).
    If not found, returns (user_path, False) so callers can create it.
    """
    if not user_path:
        return user_path, False

    root = Path(repo_root)

    # 1. Exact relative path
    if (root / user_path).is_file():
        return user_path, True

    # 2. Case-insensitive exact
    user_lower = user_path.lower().replace("\\", "/")
    for p in _all_files(repo_root):
        rel = str(p.relative_to(root)).replace("\\", "/")
        if rel.lower() == user_lower:
            return rel, True

    # 3. Recursive filename match
    target_name = Path(user_path).name.lower()
    matches = [p for p in _all_files(repo_root) if p.name.lower() == target_name]
    if matches:
        best = min(matches, key=lambda p: len(p.parts))
        return str(best.relative_to(root)), True

    # 4. Fuzzy stem match
    stem = Path(user_path).stem.lower()
    if len(stem) > 2:
        fuzzy = [p for p in _all_files(repo_root) if stem in p.stem.lower()]
        if fuzzy:
            best = min(fuzzy, key=lambda p: len(p.parts))
            return str(best.relative_to(root)), True

    # 5. Symbol index
    if state is not None:
        for rel in getattr(state, "symbol_index", {}):
            if Path(rel).stem.lower() == stem:
                return rel, True

    return user_path, False


def read_resolved(
    user_path: str, repo_root: str, state=None
) -> Tuple[str, str, bool]:
    """Returns (resolved_path, content, success)."""
    resolved, found = resolve_path(user_path, repo_root, state)
    if not found:
        return resolved, "", False
    try:
        content = (Path(repo_root) / resolved).read_text(encoding="utf-8", errors="ignore")
        return resolved, content, True
    except Exception:
        return resolved, "", False
