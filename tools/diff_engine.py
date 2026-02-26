# tools/diff_engine.py — Operon v3
"""
Upgraded diff engine with:
- Multiple SEARCH/REPLACE block parsers (handles Qwen formatting variations)
- Fuzzy-line matching with configurable tolerance
- Explicit deletion support
- Meaningful return codes so callers know WHY a patch failed
"""

import re
from typing import Optional


# ── Parser ────────────────────────────────────────────────────────────────────

# Support multiple fence styles LLMs emit
_PATTERNS = [
    # canonical:  <<<<<<< SEARCH \n ... \n ======= \n ... \n >>>>>>> REPLACE
    re.compile(
        r"<{7}\s*SEARCH\r?\n(.*?)\r?\n={7}\r?\n(.*?)\r?\n>{7}\s*REPLACE",
        re.DOTALL,
    ),
    # alternate: <<<<<<< / ======= / >>>>>>>
    re.compile(
        r"<{7}[^\n]*\r?\n(.*?)\r?\n={7}\r?\n(.*?)\r?\n>{7}[^\n]*",
        re.DOTALL,
    ),
    # SEARCH: / REPLACE: block style
    re.compile(
        r"SEARCH:\s*\n(.*?)\nREPLACE:\s*\n(.*?)(?=\nSEARCH:|\Z)",
        re.DOTALL,
    ),
]


def parse_search_replace(text: str) -> list[tuple[str, str]]:
    """
    Extract (search, replace) pairs from LLM output.
    Tries multiple patterns, returns first non-empty result.
    """
    for pat in _PATTERNS:
        matches = pat.findall(text)
        if matches:
            return [(s.strip("\n"), r.strip("\n")) for s, r in matches]
    return []


# ── Patch engine ──────────────────────────────────────────────────────────────

def _normalize(lines: list[str]) -> list[str]:
    return [l.strip() for l in lines]


def _fuzzy_match(
    orig_lines: list[str],
    search_norm: list[str],
    tolerance: int = 0,
) -> Optional[int]:
    """
    Sliding window match. Returns start index or None.
    tolerance=0  → exact (after strip)
    tolerance>0  → allow that many mismatched lines in the window
    """
    slen = len(search_norm)
    if slen == 0:
        return None
    for i in range(len(orig_lines) - slen + 1):
        window = [l.strip() for l in orig_lines[i : i + slen]]
        mismatches = sum(1 for a, b in zip(window, search_norm) if a != b)
        if mismatches <= tolerance:
            return i
    return None


def _apply_indent(replace_block: str, original_indent: int) -> list[str]:
    """Re-indent replace_block to match the original code's indentation."""
    replace_lines = replace_block.splitlines()
    if not replace_lines:
        return []
    first_content = next((l for l in replace_lines if l.strip()), "")
    replace_indent = len(first_content) - len(first_content.lstrip())
    diff = original_indent - replace_indent

    result = []
    for line in replace_lines:
        if not line.strip():
            result.append("")
            continue
        if diff > 0:
            result.append(" " * diff + line)
        elif diff < 0:
            strip = abs(diff)
            result.append(line[strip:] if line.startswith(" " * strip) else line)
        else:
            result.append(line)
    return result


def apply_patch(
    original_text: str,
    search_block: str,
    replace_block: str,
) -> tuple[Optional[str], str]:
    """
    Returns (patched_text | None, reason_string).

    Reason is one of:
      "ok"                    — patch applied
      "appended"              — appended (empty search)
      "no_match"              — search block not found
      "noop"                  — patch would produce identical content
    """
    # ── Append / new-file mode ────────────────────────────────────────────────
    if not search_block.strip():
        if original_text.strip():
            result = original_text.rstrip() + "\n\n" + replace_block.strip() + "\n"
        else:
            result = replace_block.strip() + "\n"
        return result, "appended"

    # ── 1. Exact string match ─────────────────────────────────────────────────
    if search_block in original_text:
        result = original_text.replace(search_block, replace_block, 1)
        if result == original_text:
            return result, "noop"
        return result, "ok"

    # ── 2. Whitespace-normalized exact match ──────────────────────────────────
    orig_lines  = original_text.splitlines()
    search_norm = _normalize(search_block.splitlines())
    idx = _fuzzy_match(orig_lines, search_norm, tolerance=0)

    if idx is not None:
        original_indent = len(orig_lines[idx]) - len(orig_lines[idx].lstrip())
        adjusted = _apply_indent(replace_block, original_indent)
        final = orig_lines[:idx] + adjusted + orig_lines[idx + len(search_norm):]
        result = "\n".join(final) + "\n"
        if result.strip() == original_text.strip():
            return result, "noop"
        return result, "ok"

    # ── 3. Fuzzy match (allow 1 mismatched line — handles minor LLM drift) ───
    idx = _fuzzy_match(orig_lines, search_norm, tolerance=1)
    if idx is not None:
        original_indent = len(orig_lines[idx]) - len(orig_lines[idx].lstrip())
        adjusted = _apply_indent(replace_block, original_indent)
        final = orig_lines[:idx] + adjusted + orig_lines[idx + len(search_norm):]
        result = "\n".join(final) + "\n"
        if result.strip() == original_text.strip():
            return result, "noop"
        return result, "ok"

    return None, "no_match"
