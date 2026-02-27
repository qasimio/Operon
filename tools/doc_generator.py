# tools/doc_generator.py — Operon v5
"""
DeepWiki-style documentation generator for Operon.

Generates:
  docs/README.md            — repo overview + dependency graph
  docs/modules/<file>.md    — per-module documentation
  docs/symbols.md           — cross-repo symbol reference
  docs/call_graph.md        — call relationships

Usage:
  from tools.doc_generator import generate_repo_docs
  generate_repo_docs(repo_root, graph, call_llm_fn=None)
"""
from __future__ import annotations

import ast
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from agent.logger import log

IGNORE_DIRS = {".git", ".venv", "__pycache__", "node_modules", "dist", "build", ".operon"}
CODE_EXTS   = {".py", ".js", ".jsx", ".ts", ".tsx", ".java"}
DOCS_DIR    = "docs"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _write_doc(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    log.info(f"[green]📄 Generated:[/green] {path}")


def _safe_module_name(rel: str) -> str:
    return rel.replace("/", ".").replace("\\", ".").rsplit(".", 1)[0]


def _function_signature(sym: Dict) -> str:
    args = sym.get("args", [])
    return f"def {sym['name']}({', '.join(args)})"


def _class_signature(sym: Dict) -> str:
    bases = sym.get("bases", [])
    if bases:
        return f"class {sym['name']}({', '.join(bases)})"
    return f"class {sym['name']}"


# ─────────────────────────────────────────────────────────────────────────────
# Per-module documentation
# ─────────────────────────────────────────────────────────────────────────────

def _generate_module_doc(
    rel_path:    str,
    symbols:     Dict,
    dep_fwd:     List[str],
    dep_rev:     List[str],
    call_llm_fn: Optional[Callable],
    repo_root:   str,
) -> str:
    root   = Path(repo_root)
    source = _read(root / rel_path)
    lines  = source.splitlines()

    mod_name = _safe_module_name(rel_path)
    parts    = [f"# `{rel_path}`\n"]

    # Module docstring
    module_doc = ""
    if rel_path.endswith(".py") and source:
        try:
            tree = ast.parse(source)
            if (tree.body and isinstance(tree.body[0], ast.Expr)
                    and isinstance(tree.body[0].value, ast.Constant)):
                module_doc = str(tree.body[0].value.value).strip()
        except Exception:
            pass

    if module_doc:
        parts.append(f"> {module_doc[:400]}\n")

    # LLM summary
    if call_llm_fn and source:
        prompt = (
            f"Summarize what this file does in 2-3 sentences. Plain text only.\n\n"
            f"File: {rel_path}\n\n```\n{source[:2000]}\n```"
        )
        try:
            summary = call_llm_fn(prompt).strip()
            parts.append(f"\n## Overview\n\n{summary}\n")
        except Exception:
            pass

    # Stats
    fn_count  = len(symbols.get("functions", []))
    cl_count  = len(symbols.get("classes", []))
    var_count = len(symbols.get("variables", []))
    imp_count = len(symbols.get("imports", []))
    parts.append(
        f"\n## Stats\n\n"
        f"| Metric | Count |\n|--------|-------|\n"
        f"| Lines | {len(lines)} |\n"
        f"| Functions | {fn_count} |\n"
        f"| Classes | {cl_count} |\n"
        f"| Variables | {var_count} |\n"
        f"| Imports | {imp_count} |\n"
    )

    # Imports section
    imports = symbols.get("imports", [])
    if imports:
        parts.append("\n## Imports\n")
        for imp in imports[:20]:
            parts.append(f"- `{imp.get('source', imp.get('name', '?'))}`")
        parts.append("")

    # Dependencies
    if dep_fwd:
        parts.append("\n## Dependencies (imports)\n")
        for d in dep_fwd[:15]:
            parts.append(f"- [`{d}`]({d.replace('/', '_').replace('.py', '.md')})")
        parts.append("")
    if dep_rev:
        parts.append("\n## Imported by\n")
        for d in dep_rev[:10]:
            parts.append(f"- [`{d}`]({d.replace('/', '_').replace('.py', '.md')})")
        parts.append("")

    # Classes
    classes = symbols.get("classes", [])
    if classes:
        parts.append("\n## Classes\n")
        for cl in classes:
            parts.append(f"\n### `{_class_signature(cl)}`")
            parts.append(f"\n- **Lines:** {cl['start']}–{cl['end']}")
            if cl.get("docstring"):
                parts.append(f"- **Docstring:** {cl['docstring'][:200]}")
            if cl.get("methods"):
                parts.append(f"- **Methods:** {', '.join(f'`{m}`' for m in cl['methods'][:10])}")
            if cl.get("bases"):
                parts.append(f"- **Inherits:** {', '.join(f'`{b}`' for b in cl['bases'])}")

            # LLM class summary
            if call_llm_fn and source:
                from tools.ast_engine import extract_chunk
                chunk = extract_chunk(source, cl["name"], rel_path)
                if chunk:
                    try:
                        pr = f"Summarize class '{cl['name']}' in 1 sentence. Plain text.\n\n```\n{chunk[:600]}\n```"
                        s  = call_llm_fn(pr).strip()
                        parts.append(f"\n**Summary:** {s}")
                    except Exception:
                        pass
            parts.append("")

    # Functions
    functions = symbols.get("functions", [])
    if functions:
        parts.append("\n## Functions\n")
        for fn in functions:
            deco = ""
            if fn.get("decorators"):
                deco = " ".join(f"`@{d}`" for d in fn["decorators"])
                parts.append(f"\n### `{_function_signature(fn)}` {deco}")
            else:
                parts.append(f"\n### `{_function_signature(fn)}`")
            parts.append(f"\n- **Lines:** {fn['start']}–{fn['end']}")
            if fn.get("is_async"):
                parts.append("- **Async:** Yes")
            if fn.get("docstring"):
                parts.append(f"- **Docstring:** {fn['docstring'][:200]}")

            # Extract and show usage examples from cross-refs
            parts.append("")

    # Variables / constants
    variables = symbols.get("variables", [])
    constants = [v for v in variables if v.get("name", "").isupper()]
    if constants:
        parts.append("\n## Constants\n")
        for v in constants[:20]:
            val = v.get("value_repr", "?")
            parts.append(f"- `{v['name']}` = `{val}` (line {v['start']})")
        parts.append("")

    # Usage examples (cross-file)
    # (added by generate_repo_docs after cross-ref pass)

    return "\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Repo README
# ─────────────────────────────────────────────────────────────────────────────

def _generate_readme(
    repo_root:   str,
    graph:       Dict,
    call_llm_fn: Optional[Callable],
    file_summaries: Dict[str, str],
) -> str:
    files     = sorted(graph.get("files", {}).keys())
    dep_graph = graph.get("cross_refs", {})

    parts = ["# Repository Documentation\n", f"> Auto-generated by Operon on {_ts()}\n"]

    if call_llm_fn:
        # Sample a few files for overall summary
        sample_files = files[:5]
        file_snippets = []
        root = Path(repo_root)
        for rel in sample_files:
            src = _read(root / rel)
            if src:
                file_snippets.append(f"--- {rel} ---\n{src[:500]}")
        if file_snippets:
            prompt = (
                "Describe this software project in 3-5 sentences. "
                "What does it do? What are its main components?\n\n"
                + "\n\n".join(file_snippets[:3])
            )
            try:
                overview = call_llm_fn(prompt).strip()
                parts.append(f"\n## Project Overview\n\n{overview}\n")
            except Exception:
                pass

    # File tree
    parts.append("\n## Module Index\n")
    parts.append("| Module | Summary |")
    parts.append("|--------|---------|")
    for rel in files:
        summary = file_summaries.get(rel, "")
        link    = f"modules/{rel.replace('/', '_').replace('.py', '.md')}"
        parts.append(f"| [`{rel}`]({link}) | {summary[:80]} |")

    # Dependency graph (Mermaid)
    dep_fwd = {}
    for rel, syms in graph.get("files", {}).items():
        imports = syms.get("imports", [])
        deps = [i.get("module", "") for i in imports if i.get("module")]
        if deps:
            dep_fwd[rel] = deps[:5]

    if dep_fwd:
        parts.append("\n## Dependency Graph\n\n```mermaid\ngraph TD")
        for src, dsts in list(dep_fwd.items())[:20]:
            src_n = src.replace("/", "_").replace(".", "_")
            for dst in dsts[:3]:
                dst_n = dst.replace(".", "_")
                parts.append(f"  {src_n} --> {dst_n}")
        parts.append("```\n")

    return "\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Cross-repo symbol reference
# ─────────────────────────────────────────────────────────────────────────────

def _generate_symbol_reference(graph: Dict) -> str:
    cross_refs = graph.get("cross_refs", {})
    # Only symbols that appear in >1 file or are definitions
    multi = {
        name: refs for name, refs in cross_refs.items()
        if len({r["file"] for r in refs}) > 1 and len(name) > 2
    }

    parts = [
        "# Symbol Cross-Reference\n",
        f"> {len(multi)} symbols used across multiple files\n",
        "\n| Symbol | Definitions | References | Files |\n|--------|-------------|------------|-------|",
    ]
    for name, refs in sorted(multi.items())[:300]:
        defs = sum(1 for r in refs if r["kind"] == "definition")
        uses = len(refs) - defs
        files = len({r["file"] for r in refs})
        parts.append(f"| `{name}` | {defs} | {uses} | {files} |")

    return "\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Call graph
# ─────────────────────────────────────────────────────────────────────────────

def _generate_call_graph(graph: Dict) -> str:
    cross_refs = graph.get("cross_refs", {})
    # Build: function → called functions (inferred from usage in function bodies)
    # Simple heuristic: if symbol A is used inside file X at call kind, and X defines functions,
    # attribute to the nearest containing function.
    parts = [
        "# Call Relationships\n",
        "Symbols and their cross-file usage patterns.\n",
    ]
    # Top 30 most-called symbols
    call_counts: Dict[str, int] = {}
    for name, refs in cross_refs.items():
        calls = sum(1 for r in refs if r.get("kind") == "call")
        if calls > 0:
            call_counts[name] = calls

    if call_counts:
        parts.append("## Most Called Symbols\n")
        parts.append("| Symbol | Call Count |")
        parts.append("|--------|-----------|")
        for name, cnt in sorted(call_counts.items(), key=lambda x: -x[1])[:40]:
            parts.append(f"| `{name}` | {cnt} |")

    return "\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def _ts() -> str:
    import datetime
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def generate_repo_docs(
    repo_root:   str,
    graph:       Optional[Dict] = None,
    call_llm_fn: Optional[Callable] = None,
) -> str:
    """
    Generate complete /docs/ tree for the repository.

    Args:
        repo_root:   path to repo
        graph:       pre-built symbol graph (built if None)
        call_llm_fn: optional callable for LLM summaries

    Returns:
        Path to generated docs directory.
    """
    t0 = time.time()
    log.info("[bold cyan]📚 Generating repository documentation...[/bold cyan]")

    # Build graph if not provided
    if graph is None:
        from tools.symbol_graph import build_symbol_graph
        graph = build_symbol_graph(repo_root, incremental=True)

    root     = Path(repo_root)
    docs_dir = root / DOCS_DIR
    docs_dir.mkdir(parents=True, exist_ok=True)
    mod_dir  = docs_dir / "modules"
    mod_dir.mkdir(exist_ok=True)

    dep_fwd: Dict[str, List[str]] = {}
    dep_rev: Dict[str, List[str]] = {}
    for rel, syms in graph["files"].items():
        imports = syms.get("imports", [])
        deps = []
        for imp in imports:
            mod = imp.get("module", "")
            if mod:
                # Try to resolve to a repo file
                candidate = mod.replace(".", "/") + ".py"
                if (root / candidate).exists():
                    deps.append(candidate)
        if deps:
            dep_fwd[rel] = deps
            for d in deps:
                dep_rev.setdefault(d, []).append(rel)

    # Per-module docs + collect summaries
    file_summaries: Dict[str, str] = {}
    files = sorted(graph["files"].keys())
    for rel in files:
        syms = graph["files"][rel]
        fn_names = [f["name"] for f in syms.get("functions", [])][:5]
        cl_names = [c["name"] for c in syms.get("classes", [])][:3]
        file_summaries[rel] = ", ".join(cl_names + fn_names) or "(empty)"

        md = _generate_module_doc(
            rel_path    = rel,
            symbols     = syms,
            dep_fwd     = dep_fwd.get(rel, []),
            dep_rev     = dep_rev.get(rel, []),
            call_llm_fn = call_llm_fn,
            repo_root   = repo_root,
        )
        fname = rel.replace("/", "_").replace("\\", "_").replace(".py", ".md")
        _write_doc(mod_dir / fname, md)

    # README
    readme_md = _generate_readme(repo_root, graph, call_llm_fn, file_summaries)
    _write_doc(docs_dir / "README.md", readme_md)

    # Symbol reference
    sym_ref = _generate_symbol_reference(graph)
    _write_doc(docs_dir / "symbols.md", sym_ref)

    # Call graph
    call_gr = _generate_call_graph(graph)
    _write_doc(docs_dir / "call_graph.md", call_gr)

    elapsed = time.time() - t0
    log.info(
        f"[bold green]✅ Docs generated:[/bold green] "
        f"{len(files)} modules → {docs_dir} ({elapsed:.1f}s)"
    )
    return str(docs_dir)


def generate_block_summary_comment(
    file_path:   str,
    symbol_name: str,
    repo_root:   str,
    call_llm_fn: Optional[Callable] = None,
) -> Optional[str]:
    """
    Generate a summary comment for a symbol and insert it above the definition.
    Returns the new file content, or None if symbol not found.
    """
    from tools.ast_engine import extract_chunk, summarize_block
    root   = Path(repo_root)
    source = _read(root / file_path)
    if not source:
        return None

    chunk = extract_chunk(source, symbol_name, file_path)
    if not chunk:
        return None

    # Find start line
    lines = source.splitlines()
    start = None
    for i, line in enumerate(lines, 1):
        if symbol_name in line and (
            line.strip().startswith("def ") or
            line.strip().startswith("class ") or
            symbol_name + " =" in line
        ):
            start = i
            break
    if start is None:
        return None

    summary = summarize_block(source, start, start + len(chunk.splitlines()), file_path, call_llm_fn)
    if not summary:
        return None

    from tools.ast_engine import insert_summary_comment
    return insert_summary_comment(source, start, summary)
