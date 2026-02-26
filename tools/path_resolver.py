# tools/path_resolver.py — Operon v3
"""
THE FIX for Bug #1: "can not figure out file if it is inside folder"

Claude Code-style path resolution:
  1. Exact relative path match
  2. Case-insensitive exact match
  3. Recursive filename match (shortest path wins)
  4. Fuzzy basename match (substring)
  5. Cross-check against the 4-level symbol index
  6. Give up and return original (let caller create it)
"""

from __future__ import annotations
from pathlib import Path
from typing import Optional
import os

IGNORE_DIRS = {".git", ".venv", "__pycache__", "node_modules", "dist", "build", ".operon"}


def _all_files(repo_root: str) -> list[Path]:
    root = Path(repo_root)
    out: list[Path] = []
    for p in root.rglob("*"):
        if p.is_file() and not any(d in p.parts for d in IGNORE_DIRS):
            out.append(p)
    return out


def resolve_path(
    user_path: str,
    repo_root: str,
    state=None,
    must_exist: bool = False,
) -> tuple[str, bool]:
    """
    Returns (resolved_relative_path, found: bool).

    If must_exist=True and nothing found, returns (user_path, False).
    Callers should check `found` before assuming the file exists.
    """
    if not user_path:
        return user_path, False

    root = Path(repo_root)

    # ── 1. Exact relative path ────────────────────────────────────────────────
    candidate = root / user_path
    if candidate.is_file():
        return str(candidate.relative_to(root)), True

    # ── 2. Case-insensitive exact match ───────────────────────────────────────
    user_lower = user_path.lower().replace("\\", "/")
    for p in _all_files(repo_root):
        rel = str(p.relative_to(root)).replace("\\", "/")
        if rel.lower() == user_lower:
            return rel, True

    # ── 3. Recursive filename match (shortest wins) ───────────────────────────
    target_name = Path(user_path).name.lower()
    matches: list[Path] = [
        p for p in _all_files(repo_root) if p.name.lower() == target_name
    ]
    if matches:
        best = min(matches, key=lambda p: len(p.parts))
        return str(best.relative_to(root)), True

    # ── 4. Fuzzy basename substring match ─────────────────────────────────────
    stem = Path(user_path).stem.lower()
    if len(stem) > 3:  # avoid matching single-char stems
        fuzzy: list[Path] = [
            p for p in _all_files(repo_root) if stem in p.stem.lower()
        ]
        if len(fuzzy) == 1:
            return str(fuzzy[0].relative_to(root)), True
        if len(fuzzy) > 1:
            # Pick shortest (most likely to be the root-level file)
            best = min(fuzzy, key=lambda p: len(p.parts))
            return str(best.relative_to(root)), True

    # ── 5. Symbol index lookup ────────────────────────────────────────────────
    if state is not None:
        sym_idx = getattr(state, "symbol_index", {})
        for rel_path in sym_idx:
            if Path(rel_path).stem.lower() == stem:
                return rel_path, True

    # ── 6. Give up ────────────────────────────────────────────────────────────
    return user_path, False


def file_exists(user_path: str, repo_root: str, state=None) -> bool:
    _, found = resolve_path(user_path, repo_root, state)
    return found


def read_resolved(user_path: str, repo_root: str, state=None) -> tuple[str, str, bool]:
    """
    Returns (resolved_path, content, success).
    Tries to resolve the path and read the file.
    """
    resolved, found = resolve_path(user_path, repo_root, state)
    if not found:
        return resolved, "", False
    try:
        full = Path(repo_root) / resolved
        content = full.read_text(encoding="utf-8", errors="ignore")
        return resolved, content, True
    except Exception:
        return resolved, "", False
