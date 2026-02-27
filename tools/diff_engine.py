# tools/diff_engine.py — Operon v4
from __future__ import annotations
import re
from typing import Optional, Tuple, List

_FENCE_PATTERNS = [
    re.compile(r"<{7}\s*SEARCH\r?\n(.*?)\r?\n={7}\r?\n(.*?)\r?\n>{7}\s*REPLACE", re.DOTALL),
    re.compile(r"<{7}[^\n]*\r?\n(.*?)\r?\n={7}\r?\n(.*?)\r?\n>{7}[^\n]*", re.DOTALL),
    re.compile(r"SEARCH:\s*\n(.*?)\nREPLACE:\s*\n(.*?)(?=\nSEARCH:|\Z)", re.DOTALL),
]

def parse_search_replace(text: str) -> List[Tuple[str, str]]:
    for pat in _FENCE_PATTERNS:
        matches = pat.findall(text)
        if matches:
            return [(s.strip("\n"), r.strip("\n")) for s, r in matches]
    return []

def _norm(lines: List[str]) -> List[str]:
    return [l.strip() for l in lines]

def _find_block(orig: List[str], snorm: List[str], tol: int = 0) -> Optional[int]:
    slen = len(snorm)
    if slen == 0:
        return None
    for i in range(len(orig) - slen + 1):
        window = [l.strip() for l in orig[i: i + slen]]
        if sum(1 for a, b in zip(window, snorm) if a != b) <= tol:
            return i
    return None

def _reindent(block: str, indent: int) -> List[str]:
    lines = block.splitlines()
    if not lines:
        return []
    first = next((l for l in lines if l.strip()), "")
    src = len(first) - len(first.lstrip())
    delta = indent - src
    result = []
    for line in lines:
        if not line.strip():
            result.append("")
        elif delta > 0:
            result.append(" " * delta + line)
        elif delta < 0 and line.startswith(" " * abs(delta)):
            result.append(line[abs(delta):])
        else:
            result.append(line)
    return result

def apply_patch(original_text: str, search_block: str, replace_block: str) -> Tuple[Optional[str], str]:
    """Returns (patched | None, reason). reason: ok|noop|appended|no_match"""
    if not (search_block or "").strip():
        if original_text.strip():
            result = original_text.rstrip() + "\n\n" + (replace_block or "").strip() + "\n"
        else:
            result = (replace_block or "").strip() + "\n"
        return result, "appended"

    if search_block in original_text:
        result = original_text.replace(search_block, replace_block or "", 1)
        return (result, "noop") if result == original_text else (result, "ok")

    orig_lines  = original_text.splitlines()
    search_norm = _norm(search_block.splitlines())

    idx = _find_block(orig_lines, search_norm, tol=0)
    if idx is not None:
        indent   = len(orig_lines[idx]) - len(orig_lines[idx].lstrip())
        adjusted = _reindent(replace_block or "", indent) if (replace_block or "").strip() else []
        final    = orig_lines[:idx] + adjusted + orig_lines[idx + len(search_norm):]
        result   = "\n".join(final) + "\n"
        return (result, "noop") if result.strip() == original_text.strip() else (result, "ok")

    if len(search_norm) == 1:
        s = search_norm[0]
        m = re.match(r'^(\s*[\w\.]+)\s*=', s)
        if m:
            lhs = m.group(1).strip()
            pat = re.compile(r'^\s*' + re.escape(lhs) + r'\s*=')
            for i, line in enumerate(orig_lines):
                if pat.match(line):
                    indent   = len(line) - len(line.lstrip())
                    adjusted = _reindent(replace_block or "", indent) if (replace_block or "").strip() else []
                    final    = orig_lines[:i] + adjusted + orig_lines[i + 1:]
                    result   = "\n".join(final) + "\n"
                    return (result, "noop") if result.strip() == original_text.strip() else (result, "ok")
        for i, line in enumerate(orig_lines):
            if line.strip() == s:
                indent   = len(line) - len(line.lstrip())
                adjusted = _reindent(replace_block or "", indent) if (replace_block or "").strip() else []
                final    = orig_lines[:i] + adjusted + orig_lines[i + 1:]
                result   = "\n".join(final) + "\n"
                return (result, "noop") if result.strip() == original_text.strip() else (result, "ok")

    if len(search_norm) >= 3:
        idx = _find_block(orig_lines, search_norm, tol=1)
        if idx is not None:
            indent   = len(orig_lines[idx]) - len(orig_lines[idx].lstrip())
            adjusted = _reindent(replace_block or "", indent) if (replace_block or "").strip() else []
            final    = orig_lines[:idx] + adjusted + orig_lines[idx + len(search_norm):]
            result   = "\n".join(final) + "\n"
            return (result, "noop") if result.strip() == original_text.strip() else (result, "ok")

    return None, "no_match"


def insert_import(original: str, import_line: str) -> Tuple[str, bool]:
    stripped = import_line.strip()
    for line in original.splitlines():
        if line.strip() == stripped:
            return original, True
    lines = original.splitlines(keepends=True)
    last_import = -1
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("import ") or s.startswith("from "):
            last_import = i
        elif s and not s.startswith("#") and last_import >= 0:
            break
    lines.insert(last_import + 1, stripped + "\n")
    return "".join(lines), False


def insert_above(original: str, target: str, new_line: str) -> Tuple[str, bool]:
    lines = original.splitlines(keepends=True)
    ts = target.strip()
    for i, line in enumerate(lines):
        if ts in line.strip():
            if i > 0 and new_line.strip() in lines[i - 1]:
                return original, True
            indent = len(line) - len(line.lstrip())
            lines.insert(i, " " * indent + new_line.rstrip("\n") + "\n")
            return "".join(lines), True
    return original, False


def append_to_file(original: str, content: str) -> str:
    return original.rstrip("\n") + "\n" + content.rstrip("\n") + "\n"
