# tools/ast_engine.py — Operon v5
"""
AST-based intelligence engine.  All operations use Python's ast stdlib.

Public API:
  rename_symbol(repo_root, old_name, new_name, dry_run) → RenameResult
  find_all_usages(repo_root, symbol, graph)              → List[UsageEntry]
  migrate_signature(repo_root, func_name, new_params, dry_run) → MigrateResult
  summarize_block(content, start_line, end_line, file_path) → str
  extract_chunk(content, symbol_name, file_path)         → str
  explain_symbol(repo_root, symbol, graph, call_llm_fn)  → str
"""
from __future__ import annotations

import ast
import io
import re
import tokenize
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from agent.logger import log

IGNORE_DIRS = {".git", ".venv", "__pycache__", "node_modules", "dist", "build", ".operon"}
CODE_EXTS   = {".py", ".js", ".jsx", ".ts", ".tsx", ".java"}


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Edit:
    file:        str
    line:        int
    col_start:   int
    col_end:     int
    old_text:    str
    new_text:    str
    context:     str = ""


@dataclass
class RenameResult:
    old_name:  str
    new_name:  str
    edits:     List[Edit] = field(default_factory=list)
    errors:    List[str]  = field(default_factory=list)
    applied:   bool       = False


@dataclass
class UsageEntry:
    file:    str
    line:    int
    kind:    str    # definition | call | ref | attr | import
    context: str    # the source line


@dataclass
class MigrateResult:
    func_name:   str
    call_sites:  List[Edit] = field(default_factory=list)
    errors:      List[str]  = field(default_factory=list)
    applied:     bool       = False


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _list_py_files(repo_root: str) -> List[Path]:
    root = Path(repo_root)
    out = []
    for p in root.rglob("*.py"):
        if not any(d in p.parts for d in IGNORE_DIRS):
            out.append(p)
    return sorted(out)


def _list_code_files(repo_root: str) -> List[Path]:
    root = Path(repo_root)
    out = []
    for p in root.rglob("*"):
        if p.is_file() and p.suffix in CODE_EXTS:
            if not any(d in p.parts for d in IGNORE_DIRS):
                out.append(p)
    return sorted(out)


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _lines(source: str) -> List[str]:
    return source.splitlines()


# ─────────────────────────────────────────────────────────────────────────────
# Token-level rename for Python (preserves formatting exactly)
# ─────────────────────────────────────────────────────────────────────────────

def _rename_in_py_source(source: str, old_name: str, new_name: str) -> Tuple[str, List[Edit]]:
    """
    Use tokenize to find every exact token == old_name and replace it.
    Returns (new_source, edits).
    """
    edits: List[Edit] = []
    tokens = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            tokens.append(tok)
    except tokenize.TokenError:
        # Still process what we got
        pass

    # Collect replacement positions
    replacements: List[Tuple[int, int, int, str, str]] = []  # (srow, scol, ecol, old, new)
    for tok in tokens:
        if tok.type == tokenize.NAME and tok.string == old_name:
            srow, scol = tok.start
            erow, ecol = tok.end
            replacements.append((srow, scol, ecol, tok.string, new_name))

    if not replacements:
        return source, []

    # Apply replacements line by line (reverse order per line to keep offsets valid)
    src_lines = source.splitlines(keepends=True)
    # Group by line
    from collections import defaultdict
    by_line: Dict[int, List[Tuple]] = defaultdict(list)
    for srow, scol, ecol, old, new in replacements:
        by_line[srow].append((scol, ecol, old, new))

    new_lines = list(src_lines)
    for lno, changes in by_line.items():
        line = new_lines[lno - 1] if lno - 1 < len(new_lines) else ""
        # Sort descending by column to apply right-to-left
        for scol, ecol, old, new in sorted(changes, key=lambda x: -x[0]):
            context = line.rstrip()
            edits.append(Edit(
                file="", line=lno, col_start=scol, col_end=ecol,
                old_text=old, new_text=new, context=context[:120]
            ))
            line = line[:scol] + new + line[ecol:]
        new_lines[lno - 1] = line

    return "".join(new_lines), edits


def _rename_in_generic_source(source: str, old_name: str, new_name: str) -> Tuple[str, List[Edit]]:
    """
    Word-boundary regex rename for non-Python files.
    Safe: only replaces whole-word matches.
    """
    edits: List[Edit] = []
    pattern = re.compile(r'\b' + re.escape(old_name) + r'\b')
    lines = source.splitlines(keepends=True)
    new_lines = []
    for i, line in enumerate(lines, 1):
        new_line = line
        for m in reversed(list(pattern.finditer(line))):
            edits.append(Edit(
                file="", line=i, col_start=m.start(), col_end=m.end(),
                old_text=old_name, new_text=new_name, context=line.rstrip()[:120]
            ))
            new_line = new_line[:m.start()] + new_name + new_line[m.end():]
        new_lines.append(new_line)
    return "".join(new_lines), edits


# ─────────────────────────────────────────────────────────────────────────────
# Public: rename_symbol
# ─────────────────────────────────────────────────────────────────────────────

def rename_symbol(
    repo_root: str,
    old_name:  str,
    new_name:  str,
    dry_run:   bool = True,
) -> RenameResult:
    """
    Rename old_name → new_name across the entire repository.

    Uses tokenize for Python (AST-accurate, formatting-preserving).
    Uses word-boundary regex for JS/TS/Java/other.

    dry_run=True: collect edits without writing.
    dry_run=False: write all changed files.
    """
    result = RenameResult(old_name=old_name, new_name=new_name)

    for p in _list_code_files(repo_root):
        source = _read(p)
        if not source or old_name not in source:
            continue

        rel = str(p.relative_to(repo_root))

        if p.suffix == ".py":
            new_src, edits = _rename_in_py_source(source, old_name, new_name)
        else:
            new_src, edits = _rename_in_generic_source(source, old_name, new_name)

        if not edits:
            continue

        for e in edits:
            e.file = rel
        result.edits.extend(edits)

        if not dry_run:
            try:
                p.write_text(new_src, encoding="utf-8")
                log.info(f"[green]Renamed {old_name}→{new_name} in {rel} ({len(edits)} sites)[/green]")
            except Exception as exc:
                result.errors.append(f"{rel}: {exc}")

    if not dry_run and not result.errors:
        result.applied = True

    log.info(
        f"[cyan]rename_symbol:[/cyan] {old_name}→{new_name} | "
        f"{len(result.edits)} edits across "
        f"{len({e.file for e in result.edits})} files"
        + (" [DRY RUN]" if dry_run else " [APPLIED]")
    )
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Public: find_all_usages
# ─────────────────────────────────────────────────────────────────────────────

def find_all_usages(
    repo_root: str,
    symbol:    str,
    graph:     Optional[Dict] = None,
) -> List[UsageEntry]:
    """
    Find every occurrence of symbol across the repository.

    If graph is provided (from symbol_graph.build_symbol_graph), uses the
    pre-built cross-ref index for speed.  Otherwise does a fresh scan.
    """
    entries: List[UsageEntry] = []

    if graph:
        cross = graph.get("cross_refs", {}).get(symbol, [])
        root  = Path(repo_root)
        for entry in cross:
            rel = entry["file"]
            try:
                lines = _read(root / rel).splitlines()
                ln    = entry["line"]
                ctx   = lines[ln - 1].strip() if 0 < ln <= len(lines) else ""
            except Exception:
                ctx = ""
            entries.append(UsageEntry(
                file=rel, line=entry["line"],
                kind=entry.get("kind", "ref"), context=ctx
            ))
        return entries

    # Full scan fallback
    for p in _list_code_files(repo_root):
        source = _read(p)
        if not source or symbol not in source:
            continue
        rel   = str(p.relative_to(repo_root))
        lines = source.splitlines()

        if p.suffix == ".py":
            try:
                tree = ast.parse(source)
                for node in ast.walk(tree):
                    ln = None
                    kind = "ref"
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == symbol:
                        ln, kind = node.lineno, "definition"
                    elif isinstance(node, ast.ClassDef) and node.name == symbol:
                        ln, kind = node.lineno, "definition"
                    elif isinstance(node, ast.Name) and node.id == symbol:
                        ln = node.lineno
                        kind = "def" if isinstance(node.ctx, ast.Store) else "ref"
                    elif isinstance(node, ast.Call):
                        if isinstance(node.func, ast.Name) and node.func.id == symbol:
                            ln, kind = node.lineno, "call"
                        elif isinstance(node.func, ast.Attribute) and node.func.attr == symbol:
                            ln, kind = node.lineno, "call"
                    elif isinstance(node, ast.Attribute) and node.attr == symbol:
                        ln, kind = node.lineno, "attr"
                    if ln is not None:
                        ctx = lines[ln - 1].strip() if 0 < ln <= len(lines) else ""
                        entries.append(UsageEntry(file=rel, line=ln, kind=kind, context=ctx))
            except SyntaxError:
                pass
        else:
            # Regex fallback
            pattern = re.compile(r'\b' + re.escape(symbol) + r'\b')
            for i, line in enumerate(lines, 1):
                if pattern.search(line):
                    entries.append(UsageEntry(file=rel, line=i, kind="ref", context=line.strip()[:120]))

    return entries


# ─────────────────────────────────────────────────────────────────────────────
# Public: migrate_signature
# ─────────────────────────────────────────────────────────────────────────────

def migrate_signature(
    repo_root:  str,
    func_name:  str,
    new_params: List[str],
    dry_run:    bool = True,
) -> MigrateResult:
    """
    When a function's signature changes, find all call sites and
    update them to match new_params.

    Strategy:
      1. Find the function definition to know old params.
      2. Find all call sites.
      3. For each call site: if it passes positional args, reorder/add/remove
         to match new_params.  Named kwargs are preserved.

    dry_run=True: collect edits only.
    dry_run=False: write files.

    NOTE: Complex type inference is out of scope — this handles the common cases:
      - Added param with default at end → auto-insert default in calls
      - Removed param → remove the positional arg
      - Reorder → positional args reordered
    """
    result = MigrateResult(func_name=func_name)

    # Step 1: find old params from definition
    old_params: List[str] = []
    for p in _list_py_files(repo_root):
        source = _read(p)
        if func_name not in source:
            continue
        try:
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
                    old_params = [a.arg for a in node.args.args]
                    break
        except SyntaxError:
            pass
        if old_params:
            break

    if not old_params:
        result.errors.append(f"Could not find definition of '{func_name}'")
        return result

    # Build param mapping: old_index → new_index
    # new_params may have "name=default" format
    new_names = [p.split("=")[0].strip().lstrip("*") for p in new_params]
    old_names = old_params

    log.info(f"[cyan]migrate_signature:[/cyan] {func_name}({', '.join(old_names)}) → ({', '.join(new_names)})")

    # Step 2: find all call sites
    for p in _list_py_files(repo_root):
        source = _read(p)
        if func_name not in source:
            continue
        rel = str(p.relative_to(repo_root))
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue

        lines = source.splitlines(keepends=True)
        new_lines = list(lines)
        local_edits: List[Edit] = []

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name) and node.func.id != func_name:
                continue
            if isinstance(node.func, ast.Attribute) and node.func.attr != func_name:
                continue

            # Get the source slice for this call
            try:
                call_src = ast.get_source_segment(source, node)
                if not call_src:
                    continue
            except Exception:
                continue

            # Collect existing positional args
            existing_args = [ast.unparse(a) for a in node.args]

            # Build new arg list
            new_args = []
            for i, new_nm in enumerate(new_names):
                # Check if arg provided positionally
                if i < len(existing_args):
                    # Find old position of this param
                    if new_nm in old_names:
                        old_pos = old_names.index(new_nm)
                        if old_pos < len(existing_args):
                            new_args.append(existing_args[old_pos])
                        else:
                            # param added — use default if available
                            param_str = new_params[i] if i < len(new_params) else new_nm
                            if "=" in param_str:
                                new_args.append(param_str.split("=", 1)[1].strip())
                            else:
                                new_args.append("None")  # placeholder
                    else:
                        # New param not in old list
                        param_str = new_params[i] if i < len(new_params) else new_nm
                        if "=" in param_str:
                            new_args.append(param_str.split("=", 1)[1].strip())
                        else:
                            new_args.append("None")
                else:
                    # Param removed or new
                    if new_nm in old_names:
                        old_pos = old_names.index(new_nm)
                        if old_pos < len(existing_args):
                            new_args.append(existing_args[old_pos])
                        else:
                            param_str = new_params[i] if i < len(new_params) else new_nm
                            if "=" in param_str:
                                new_args.append(param_str.split("=", 1)[1].strip())
                            else:
                                new_args.append("None")
                    else:
                        param_str = new_params[i] if i < len(new_params) else new_nm
                        if "=" in param_str:
                            new_args.append(param_str.split("=", 1)[1].strip())
                        else:
                            new_args.append("None")

            # Also keep existing kwargs
            existing_kwargs = [f"{kw.arg}={ast.unparse(kw.value)}" for kw in node.keywords if kw.arg]
            all_args = new_args + existing_kwargs

            new_call_inner = ", ".join(all_args)
            new_call_src   = re.sub(r'\(.*\)$', f'({new_call_inner})', call_src, flags=re.DOTALL)

            ln = node.lineno
            ctx = lines[ln - 1].strip() if 0 < ln <= len(lines) else ""
            edit = Edit(
                file=rel, line=ln, col_start=0, col_end=0,
                old_text=call_src, new_text=new_call_src, context=ctx
            )
            local_edits.append(edit)

            if not dry_run:
                # Replace in source
                if new_call_src != call_src:
                    idx = ln - 1
                    if idx < len(new_lines):
                        new_lines[idx] = new_lines[idx].replace(call_src, new_call_src, 1)

        result.call_sites.extend(local_edits)

        if not dry_run and local_edits:
            try:
                new_src = "".join(new_lines)
                p.write_text(new_src, encoding="utf-8")
                log.info(f"[green]migrate_signature: updated {len(local_edits)} call(s) in {rel}[/green]")
            except Exception as exc:
                result.errors.append(f"{rel}: {exc}")

    if not dry_run and not result.errors:
        result.applied = True

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Public: extract_chunk
# ─────────────────────────────────────────────────────────────────────────────

def extract_chunk(content: str, symbol_name: str, file_path: str = "") -> str:
    """
    Extract the smallest self-contained block containing symbol_name.

    For Python: finds the function/class definition and extracts just that block.
    For others: returns ±20 lines of context around first occurrence.
    """
    if file_path.endswith(".py") or not file_path:
        try:
            tree = ast.parse(content)
            lines = content.splitlines(keepends=True)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    if node.name == symbol_name:
                        start = node.lineno - 1
                        end   = getattr(node, "end_lineno", node.lineno)
                        # Include decorators
                        deco_start = min((d.lineno - 1 for d in getattr(node, "decorator_list", [])), default=start)
                        return "".join(lines[deco_start:end])
        except SyntaxError:
            pass

    # Fallback: ±20 lines around first occurrence
    lines = content.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if symbol_name in line:
            start = max(0, i - 3)
            end   = min(len(lines), i + 20)
            return "".join(lines[start:end])
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# Public: summarize_block
# ─────────────────────────────────────────────────────────────────────────────

def summarize_block(
    content:    str,
    start_line: int,
    end_line:   int,
    file_path:  str = "",
    call_llm_fn: Optional[Callable] = None,
) -> str:
    """
    Summarize a block of code (function, class, loop, etc.) as a docstring-style comment.

    If call_llm_fn is provided, uses LLM for a richer summary.
    Otherwise returns a structural description.
    """
    from tools.universal_parser import get_block_source
    block = get_block_source(content, start_line, end_line)
    if not block.strip():
        return ""

    # Structural summary (no LLM)
    lines = block.splitlines()
    first = lines[0].strip() if lines else ""

    if call_llm_fn:
        prompt = (
            f"Summarize this code block in 1-2 sentences. "
            f"Be concise. Return plain text, no markdown.\n\n"
            f"```\n{block[:1200]}\n```"
        )
        try:
            return call_llm_fn(prompt).strip()
        except Exception:
            pass

    # Fallback structural description
    if first.startswith("def ") or first.startswith("async def "):
        m = re.match(r"(?:async\s+)?def\s+(\w+)\s*\(([^)]*)\)", first)
        if m:
            name, args = m.group(1), m.group(2)
            return f"Function '{name}' taking ({args}) — {len(lines)} lines"
    if first.startswith("class "):
        m = re.match(r"class\s+(\w+)", first)
        if m:
            return f"Class '{m.group(1)}' — {len(lines)} lines"
    if first.startswith("for ") or first.startswith("while "):
        return f"Loop block — {len(lines)} lines"
    if first.startswith("if "):
        return f"Conditional block — {len(lines)} lines"
    return f"Code block — {len(lines)} lines starting with: {first[:60]}"


# ─────────────────────────────────────────────────────────────────────────────
# Public: insert_summary_comment
# ─────────────────────────────────────────────────────────────────────────────

def insert_summary_comment(
    content:    str,
    start_line: int,
    summary:    str,
) -> str:
    """
    Insert a # summary comment immediately above the block at start_line.
    """
    lines = content.splitlines(keepends=True)
    idx   = start_line - 1
    if idx < 0 or idx >= len(lines):
        return content

    # Match indentation of the target line
    indent = re.match(r"^(\s*)", lines[idx]).group(1)
    comment_line = f"{indent}# {summary}\n"
    lines.insert(idx, comment_line)
    return "".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Public: explain_symbol
# ─────────────────────────────────────────────────────────────────────────────

def explain_symbol(
    repo_root:   str,
    symbol:      str,
    graph:       Optional[Dict] = None,
    call_llm_fn: Optional[Callable] = None,
) -> str:
    """
    Produce a rich explanation of a symbol for the terminal.

    Returns a formatted string covering:
      - Definition location + signature
      - Docstring (if any)
      - Where it's called from
      - What it calls
      - Brief LLM-generated plain-English explanation (if call_llm_fn provided)
    """
    from tools.symbol_graph import find_definitions, find_usages, query_symbol

    parts: List[str] = []
    root  = Path(repo_root)

    # Definitions
    defs = find_definitions(graph, symbol) if graph else []
    usages_list = find_usages(graph, symbol) if graph else []

    if not defs and not usages_list:
        # Full scan
        all_u = find_all_usages(repo_root, symbol, graph)
        defs       = [u.__dict__ for u in all_u if u.kind == "definition"]
        usages_list = [u.__dict__ for u in all_u if u.kind != "definition"]

    if defs:
        parts.append(f"DEFINITION{'S' if len(defs) > 1 else ''}:")
        for d in defs[:3]:
            parts.append(f"  {d['file']}:{d['line']}")

    # Extract docstring from first definition
    docstring = ""
    chunk_src = ""
    if defs:
        d = defs[0]
        try:
            src = _read(root / d["file"])
            chunk_src = extract_chunk(src, symbol, d["file"])
            if chunk_src:
                try:
                    tree = ast.parse(chunk_src)
                    for node in ast.walk(tree):
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                            if node.name == symbol and node.body:
                                first = node.body[0]
                                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                                    docstring = str(first.value.value).strip()[:300]
                except Exception:
                    pass
        except Exception:
            pass

    if docstring:
        parts.append(f"\nDOCSTRING:\n  {docstring}")

    if chunk_src:
        parts.append(f"\nSOURCE PREVIEW:\n{chunk_src[:600]}")

    # Callers / usages
    call_sites = [u for u in usages_list if u.get("kind") in ("call", "ref")][:10]
    if call_sites:
        parts.append(f"\nCALLED / USED IN ({len(call_sites)} shown):")
        for u in call_sites[:8]:
            parts.append(f"  {u['file']}:{u['line']}  {u.get('context','')[:80]}")

    # LLM explanation
    if call_llm_fn and chunk_src:
        prompt = (
            f"Explain what this Python symbol '{symbol}' does in 2-3 sentences. "
            f"Be concise and precise. Plain text, no markdown.\n\n```python\n{chunk_src[:1000]}\n```"
        )
        try:
            explanation = call_llm_fn(prompt).strip()
            parts.append(f"\nEXPLANATION:\n  {explanation}")
        except Exception:
            pass

    return "\n".join(parts) if parts else f"Symbol '{symbol}' not found in repository."
