# agent/validators.py — Operon v4
"""
Deterministic step validation.

Rule 1: before == after → ALWAYS False (noop is never success).
Rule 2: For "delete lines X-Y" → count lines removed.
Rule 3: For "add import X" → check X is in after but not before.
Rule 4: For "update VAR = N" → check new value in after.
Rule 5: For "add comment ..." → check new comment line added.
Rule 6: Generic: any non-trivial diff → True.
"""
from __future__ import annotations

import difflib
import re
from typing import Optional


_STOPWORDS = {
    "delete", "remove", "add", "the", "from", "in", "all", "lines", "line",
    "and", "or", "to", "a", "an", "this", "that", "file", "function", "code",
    "block", "section", "class", "method", "update", "change", "modify",
    "insert", "above", "below", "top", "bottom",
}


def _removed(before: str, after: str) -> list[str]:
    d = difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="")
    return [l[1:] for l in d if l.startswith("-") and not l.startswith("---")]


def _added(before: str, after: str) -> list[str]:
    d = difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="")
    return [l[1:] for l in d if l.startswith("+") and not l.startswith("+++")]


def validate_step(state, target_file: str,
                  before_text: str, after_text: str) -> bool:
    """
    Returns True if step goal is satisfied, False otherwise.
    Never returns True on a noop.
    """
    # Hard noop rule
    if before_text.strip() == after_text.strip():
        return False

    goal = (getattr(state, "goal", "") or "").lower().strip()

    # ── delete lines X-Y ──────────────────────────────────────────────────────
    m = re.search(r"delete\s+lines?\s+(\d+)\s*[-–]\s*(\d+)", goal)
    if m:
        try:
            start, end = int(m.group(1)), int(m.group(2))
            bl = len(before_text.splitlines())
            al = len(after_text.splitlines())
            return (bl - al) >= (end - start)
        except Exception:
            pass

    # ── add import X ──────────────────────────────────────────────────────────
    m = re.search(r"add\s+(?:an?\s+)?import\s+([\w\.]+)", goal)
    if m:
        imp = m.group(1).strip()
        return imp in after_text and imp not in before_text

    # ── update/change VAR = N ─────────────────────────────────────────────────
    m = re.search(r"(?:update|change|set|modify)\s+([\w]+)\s*(?:=|to)\s*([\w\.\-]+)", goal)
    if m:
        var, val = m.group(1), m.group(2)
        # Check new value appears in after alongside the variable
        return (
            val in after_text
            and re.search(rf"\b{re.escape(var)}\b", after_text, re.IGNORECASE) is not None
        )

    # ── add comment ───────────────────────────────────────────────────────────
    if "comment" in goal:
        new_lines = _added(before_text, after_text)
        comment_lines = [l for l in new_lines if l.strip().startswith("#")]
        return len(comment_lines) > 0

    # ── delete/remove goal: verify removal happened ───────────────────────────
    if "delete" in goal or "remove" in goal:
        removed = _removed(before_text, after_text)
        if not removed:
            return False
        tokens = [
            t for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", goal)
            if len(t) > 2 and t not in _STOPWORDS
        ]
        if not tokens:
            return True
        removed_text = " ".join(removed).lower()
        return any(t.lower() in removed_text for t in tokens)

    # ── Generic: any substantive diff ────────────────────────────────────────
    changed = [l for l in _removed(before_text, after_text) + _added(before_text, after_text)
               if l.strip()]
    return len(changed) > 0
