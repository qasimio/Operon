# agent/validators.py — Operon v3
"""
FIX for Bug #2: "no change made" was treated as successful rewrite.
FIX for Bug #3: token-presence check caused false negatives on deletion goals.

v3 validator:
  - Never returns True when before == after (noop is always a failure)
  - For deletion goals, checks what was ACTUALLY REMOVED, not what's still present
  - Structural line-count verification for "delete lines X–Y"
  - Falls back to "diff is non-trivial" check
"""

import re
import difflib
from pathlib import Path
from typing import Optional


_STOPWORDS = {
    "delete", "remove", "the", "from", "in", "all", "lines", "line",
    "and", "or", "to", "a", "an", "this", "that", "file", "function",
    "code", "block", "section", "part", "class", "method",
}


def _removed_lines(before: str, after: str) -> list[str]:
    diff = difflib.unified_diff(
        before.splitlines(), after.splitlines(), lineterm=""
    )
    return [l[1:] for l in diff if l.startswith("-") and not l.startswith("---")]


def _added_lines(before: str, after: str) -> list[str]:
    diff = difflib.unified_diff(
        before.splitlines(), after.splitlines(), lineterm=""
    )
    return [l[1:] for l in diff if l.startswith("+") and not l.startswith("+++")]


def validate_step(state, target_file: str, before_text: str, after_text: str) -> bool:
    """
    Returns True only if the change is meaningful AND satisfies the goal.
    Returns False for noop changes (before == after).
    """

    # ── Hard rule: noop is never a success ────────────────────────────────────
    if before_text.strip() == after_text.strip():
        return False

    # ── Custom per-step callable ──────────────────────────────────────────────
    try:
        idx = getattr(state, "current_step", 0)
        sv = getattr(state, "step_validators", {}) or {}
        per_step = sv.get(idx) or sv.get(str(idx))
        if callable(per_step):
            return bool(per_step(state, target_file, before_text, after_text))
    except Exception:
        pass

    goal = (getattr(state, "goal", "") or "").lower()

    # ── "delete lines X–Y" structural check ───────────────────────────────────
    m = re.search(r"delete\s+lines?\s+(\d+)\s*[-–]\s*(\d+)", goal)
    if m:
        try:
            start, end = int(m.group(1)), int(m.group(2))
            before_lines = before_text.splitlines()
            after_lines  = after_text.splitlines()
            removed_count = len(before_lines) - len(after_lines)
            expected = end - start + 1
            # Accept if removed enough lines OR file is now shorter than the end line
            return removed_count >= expected or len(after_lines) < end
        except Exception:
            pass

    # ── Generic deletion/removal goal ─────────────────────────────────────────
    if "delete" in goal or "remove" in goal:
        removed = _removed_lines(before_text, after_text)
        if not removed:
            return False  # Nothing was removed at all

        # Extract meaningful tokens from the goal
        tokens = [
            t for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", goal)
            if len(t) > 2 and t not in _STOPWORDS
        ]
        if not tokens:
            return True  # No specific tokens — any removal counts

        # Check tokens appear in the REMOVED lines (not in after_text)
        removed_text = " ".join(removed).lower()
        matched = sum(1 for t in tokens if t.lower() in removed_text)
        return matched > 0

    # ── Modification goal: verify diff is non-trivial ─────────────────────────
    removed = _removed_lines(before_text, after_text)
    added   = _added_lines(before_text, after_text)
    substantive = [l for l in removed + added if l.strip()]
    return len(substantive) > 0
