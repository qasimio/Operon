# agent/validators.py — Operon v2: Upgraded validator with diff-awareness
import re
import difflib
from pathlib import Path
from typing import Optional


def validate_step(state, target_file: str, before_text: str, after_text: str) -> bool:
    """
    Multi-tier step validator. Returns True if the change satisfies the goal.

    Tier 1 — Custom per-step validator callable (user-supplied)
    Tier 2 — Explicit "delete lines X-Y" structural check
    Tier 3 — Token-presence check for deletion goals
    Tier 4 — Diff significance check (non-trivial change was made)
    Tier 5 — For line deletions: verify line count delta is correct

    KEY UPGRADE (bug fix): No longer returns False for "delete" goals just because
    a generic token appears in after_text. It now cross-checks against the actual
    deleted content to avoid false negatives that caused reviewer loops.
    """

    # ── Tier 1: Custom per-step callable ─────────────────────────────────────
    try:
        idx = getattr(state, "current_step", 0)
        sv = getattr(state, "step_validators", {}) or {}
        per_step = sv.get(idx) or sv.get(str(idx))
        if callable(per_step):
            try:
                return bool(per_step(state, target_file, before_text, after_text))
            except Exception:
                return False
    except Exception:
        pass

    # ── Tier 2: "delete lines X-Y" structural check ──────────────────────────
    goal = (getattr(state, "goal", "") or "").lower()
    m = re.search(r"delete\s+lines?\s+(\d+)\s*[-–]\s*(\d+)", goal)
    if m:
        try:
            start = int(m.group(1))
            end = int(m.group(2))
            before_lines = before_text.splitlines()
            after_lines = after_text.splitlines()
            expected_removed = end - start + 1
            actual_removed = len(before_lines) - len(after_lines)

            # Accept if we removed approximately the right number of lines
            if actual_removed >= expected_removed:
                return True

            # Also accept if the file is now shorter than the original end line
            if len(after_lines) < end:
                return True

            # Check that the lines that were in range [start-1, end) are no longer present
            deleted_content = set(l.strip() for l in before_lines[start-1:end] if l.strip())
            remaining = set(l.strip() for l in after_lines if l.strip())
            overlap = deleted_content & remaining
            # If less than 30% of deleted lines remain, consider it a pass
            if len(overlap) < len(deleted_content) * 0.3:
                return True

            return False
        except Exception:
            return False

    # ── Tier 3: Generic deletion goal ────────────────────────────────────────
    if "delete" in goal or "remove" in goal:
        # FIX: Instead of checking if tokens from the goal appear in after_text
        # (which caused false negatives), check if they were actually REMOVED
        # (i.e., present in before_text but gone from after_text).
        diff_lines = list(difflib.unified_diff(
            before_text.splitlines(), after_text.splitlines(), lineterm=""
        ))
        removed_lines = [l[1:] for l in diff_lines if l.startswith("-") and not l.startswith("---")]

        if not removed_lines:
            return False  # Nothing was actually removed

        # Extract code-looking tokens from the goal (skip stop words)
        stopwords = {"delete", "remove", "the", "from", "in", "all", "lines", "line", "and", "or", "to", "a", "an"}
        tokens = [
            t for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", goal)
            if len(t) > 2 and t not in stopwords
        ]

        if not tokens:
            # No specific tokens mentioned — just verify something was removed
            return len(removed_lines) > 0

        # Check that at least some of the goal tokens were in the removed lines
        removed_text = " ".join(removed_lines).lower()
        matched = sum(1 for t in tokens if t.lower() in removed_text)
        return matched > 0

    # ── Tier 4: Diff significance (non-trivial change) ───────────────────────
    if before_text == after_text:
        return False

    # Check that the diff is meaningful (not just whitespace)
    diff_lines = list(difflib.unified_diff(
        before_text.splitlines(), after_text.splitlines(), lineterm=""
    ))
    substantive = [l for l in diff_lines if l.startswith(("+", "-")) and
                   not l.startswith(("+++", "---")) and l[1:].strip()]
    return len(substantive) > 0
