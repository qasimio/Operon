# cli/explain.py — Operon v5
"""
Terminal explanation mode.

Commands:
  operon explain <symbol>               # explain a symbol
  operon explain <file>:<line>          # explain code at line
  operon explain flow <function>        # explain execution flow
  operon explain file <path>            # explain an entire file
  operon usages <symbol>                # show all usages
  operon rename <old> <new> [--apply]   # rename symbol
  operon docs [--no-llm]                # generate /docs/
  operon summarize <file>               # summarize symbols in file
  operon signature <func> <new_params>  # migrate function signature
"""
from __future__ import annotations

import os
import sys
import argparse
from pathlib import Path
from typing import List, Optional


def _find_repo_root() -> str:
    """Walk up from cwd to find the repo root (has .git or .operon)."""
    p = Path.cwd()
    for _ in range(8):
        if (p / ".git").exists() or (p / ".operon").exists():
            return str(p)
        p = p.parent
    return str(Path.cwd())


def _get_llm() -> Optional[callable]:
    """Return call_llm function or None if LLM not configured."""
    try:
        from agent.llm import call_llm
        return call_llm
    except Exception:
        return None


def _get_graph(repo_root: str):
    """Load or build symbol graph."""
    try:
        from tools.symbol_graph import load_symbol_graph, build_symbol_graph
        graph = load_symbol_graph(repo_root)
        if not graph.get("files"):
            print("Building symbol graph (first run)...", flush=True)
            graph = build_symbol_graph(repo_root)
        return graph
    except Exception as e:
        print(f"[warn] Could not load symbol graph: {e}", file=sys.stderr)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# explain
# ─────────────────────────────────────────────────────────────────────────────

def cmd_explain(args: argparse.Namespace) -> None:
    repo_root = _find_repo_root()
    graph     = _get_graph(repo_root)
    llm       = _get_llm() if not args.no_llm else None

    target = args.target

    # file:line mode
    if ":" in target and not target.startswith("."):
        parts = target.rsplit(":", 1)
        if parts[1].isdigit():
            file_path = parts[0]
            line      = int(parts[1])
            _explain_at_line(repo_root, file_path, line, llm)
            return

    # flow mode
    if args.flow:
        _explain_flow(repo_root, target, graph, llm)
        return

    # file mode
    if args.file:
        _explain_file(repo_root, target, graph, llm)
        return

    # default: symbol
    _explain_symbol(repo_root, target, graph, llm)


def _explain_symbol(repo_root: str, symbol: str, graph, llm) -> None:
    from tools.ast_engine import explain_symbol
    result = explain_symbol(repo_root, symbol, graph, llm)
    print(f"\n{'='*60}")
    print(f"  {symbol}")
    print('='*60)
    print(result)
    print()


def _explain_at_line(repo_root: str, file_path: str, line: int, llm) -> None:
    p = Path(repo_root) / file_path
    if not p.exists():
        # Try relative to cwd
        p = Path(file_path)
    try:
        source = p.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        print(f"Cannot read {file_path}: {e}")
        return

    lines = source.splitlines()
    start = max(0, line - 5)
    end   = min(len(lines), line + 15)
    snippet = "\n".join(f"{'→' if i+1==line else ' '} {i+1:4d} | {lines[i]}"
                        for i in range(start, end))

    print(f"\n{'='*60}")
    print(f"  {file_path}:{line}")
    print('='*60)
    print(snippet)

    if llm:
        context = "\n".join(lines[max(0, line-10):min(len(lines), line+20)])
        prompt  = (
            f"Explain what line {line} does in this code. "
            f"Focus on the logic at line {line}. Plain text, 2-3 sentences.\n\n"
            f"```python\n{context}\n```"
        )
        try:
            print(f"\nEXPLANATION:")
            print(f"  {llm(prompt).strip()}")
        except Exception:
            pass
    print()


def _explain_flow(repo_root: str, func_name: str, graph, llm) -> None:
    """Trace the execution flow of a function."""
    import ast
    from tools.ast_engine import extract_chunk, find_all_usages

    root = Path(repo_root)
    # Find definition
    usages = find_all_usages(repo_root, func_name, graph)
    defs   = [u for u in usages if u.kind == "definition"]

    if not defs:
        print(f"Function '{func_name}' not found.")
        return

    d      = defs[0]
    source = (root / d.file).read_text(encoding="utf-8", errors="ignore")
    chunk  = extract_chunk(source, func_name, d.file)

    print(f"\n{'='*60}")
    print(f"  Execution Flow: {func_name}")
    print(f"  Defined in: {d.file}:{d.line}")
    print('='*60)

    # Extract calls made inside the function
    called: List[str] = []
    try:
        tree = ast.parse(chunk)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    called.append(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    called.append(f"{node.func.attr}")
    except Exception:
        pass
    called = sorted(set(called))

    print(f"\nFUNCTION SOURCE:\n{chunk[:800]}")
    if called:
        print(f"\nCALLS: {', '.join(called[:20])}")
    callers = [u for u in usages if u.kind in ("call", "ref")]
    if callers:
        print(f"\nCALLED BY ({len(callers)}):")
        for c in callers[:8]:
            print(f"  {c.file}:{c.line}  {c.context[:80]}")

    if llm and chunk:
        prompt = (
            f"Trace the execution flow of this function step by step. "
            f"What does it do? What are the key branches? Plain text.\n\n"
            f"```python\n{chunk[:1200]}\n```"
        )
        try:
            print(f"\nFLOW ANALYSIS:\n  {llm(prompt).strip()}")
        except Exception:
            pass
    print()


def _explain_file(repo_root: str, file_path: str, graph, llm) -> None:
    from tools.symbol_graph import symbols_in_file, get_file_summary
    p = Path(repo_root) / file_path
    if not p.exists():
        p = Path(file_path)
    try:
        source = p.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        print(f"Cannot read {file_path}: {e}")
        return

    syms = symbols_in_file(graph, file_path) if graph else {}
    fns  = [f["name"] for f in syms.get("functions", [])]
    cls  = [c["name"] for c in syms.get("classes", [])]

    print(f"\n{'='*60}")
    print(f"  {file_path}")
    print('='*60)
    print(f"Lines:     {len(source.splitlines())}")
    print(f"Functions: {', '.join(fns[:10]) or '(none)'}")
    print(f"Classes:   {', '.join(cls[:5]) or '(none)'}")

    if llm:
        prompt = (
            f"Describe what this file does in 3-5 sentences. "
            f"Mention its main purpose and key components. Plain text.\n\n"
            f"File: {file_path}\n\n```\n{source[:3000]}\n```"
        )
        try:
            print(f"\nSUMMARY:\n  {llm(prompt).strip()}")
        except Exception:
            pass
    print()


# ─────────────────────────────────────────────────────────────────────────────
# usages
# ─────────────────────────────────────────────────────────────────────────────

def cmd_usages(args: argparse.Namespace) -> None:
    repo_root = _find_repo_root()
    graph     = _get_graph(repo_root)
    from tools.ast_engine import find_all_usages

    usages = find_all_usages(repo_root, args.symbol, graph)
    if not usages:
        print(f"No usages found for '{args.symbol}'")
        return

    defs  = [u for u in usages if u.kind == "definition"]
    calls = [u for u in usages if u.kind == "call"]
    refs  = [u for u in usages if u.kind not in ("definition", "call")]

    print(f"\n{'='*60}")
    print(f"  Usages of '{args.symbol}' ({len(usages)} total)")
    print('='*60)

    if defs:
        print(f"\nDEFINITIONS ({len(defs)}):")
        for u in defs:
            print(f"  {u.file}:{u.line}  {u.context[:80]}")

    if calls:
        print(f"\nCALL SITES ({len(calls)}):")
        for u in calls[:20]:
            print(f"  {u.file}:{u.line}  {u.context[:80]}")

    if refs:
        print(f"\nOTHER REFERENCES ({len(refs)}):")
        for u in refs[:10]:
            print(f"  {u.file}:{u.line}  {u.context[:80]}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# rename
# ─────────────────────────────────────────────────────────────────────────────

def cmd_rename(args: argparse.Namespace) -> None:
    repo_root = _find_repo_root()
    from tools.ast_engine import rename_symbol

    dry_run = not args.apply
    result  = rename_symbol(repo_root, args.old_name, args.new_name, dry_run=dry_run)

    files_affected = sorted({e.file for e in result.edits})
    print(f"\n{'='*60}")
    print(f"  Rename: '{args.old_name}' → '{args.new_name}'")
    print(f"  Mode:   {'DRY RUN (pass --apply to write)' if dry_run else 'APPLIED'}")
    print('='*60)
    print(f"\n{len(result.edits)} edit(s) across {len(files_affected)} file(s):\n")
    for f in files_affected:
        edits = [e for e in result.edits if e.file == f]
        print(f"  {f}  ({len(edits)} sites)")
        for e in edits[:5]:
            print(f"    L{e.line}: {e.context[:70]}")

    if result.errors:
        print(f"\nERRORS:")
        for err in result.errors:
            print(f"  {err}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# docs
# ─────────────────────────────────────────────────────────────────────────────

def cmd_docs(args: argparse.Namespace) -> None:
    repo_root = _find_repo_root()
    from tools.symbol_graph import build_symbol_graph
    from tools.doc_generator import generate_repo_docs

    llm   = _get_llm() if not args.no_llm else None
    graph = build_symbol_graph(repo_root)
    docs_dir = generate_repo_docs(repo_root, graph, call_llm_fn=llm)
    print(f"\n✅ Documentation written to: {docs_dir}\n")


# ─────────────────────────────────────────────────────────────────────────────
# summarize
# ─────────────────────────────────────────────────────────────────────────────

def cmd_summarize(args: argparse.Namespace) -> None:
    repo_root = _find_repo_root()
    llm       = _get_llm() if not args.no_llm else None
    from tools.symbol_graph import build_symbol_graph, symbols_in_file
    from tools.ast_engine import summarize_block, extract_chunk

    graph = _get_graph(repo_root)
    syms  = symbols_in_file(graph, args.file) if graph else {}

    p = Path(repo_root) / args.file
    if not p.exists():
        p = Path(args.file)
    try:
        source = p.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        print(f"Cannot read {args.file}: {e}")
        return

    print(f"\n{'='*60}")
    print(f"  Summaries: {args.file}")
    print('='*60)

    for fn in syms.get("functions", []):
        chunk   = extract_chunk(source, fn["name"], args.file)
        summary = summarize_block(source, fn["start"], fn["end"], args.file, llm)
        print(f"\n  def {fn['name']}() [L{fn['start']}–{fn['end']}]")
        print(f"    → {summary}")

    for cl in syms.get("classes", []):
        chunk   = extract_chunk(source, cl["name"], args.file)
        summary = summarize_block(source, cl["start"], cl["end"], args.file, llm)
        print(f"\n  class {cl['name']} [L{cl['start']}–{cl['end']}]")
        print(f"    → {summary}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# signature migration
# ─────────────────────────────────────────────────────────────────────────────

def cmd_signature(args: argparse.Namespace) -> None:
    repo_root = _find_repo_root()
    from tools.ast_engine import migrate_signature

    new_params = [p.strip() for p in args.params.split(",")]
    dry_run    = not args.apply
    result     = migrate_signature(repo_root, args.func, new_params, dry_run=dry_run)

    print(f"\n{'='*60}")
    print(f"  Signature migration: {args.func}({', '.join(new_params)})")
    print(f"  Mode: {'DRY RUN (pass --apply to write)' if dry_run else 'APPLIED'}")
    print('='*60)

    if result.errors:
        for e in result.errors:
            print(f"  ERROR: {e}")
        return

    print(f"\n{len(result.call_sites)} call site(s) found:\n")
    for edit in result.call_sites[:20]:
        print(f"  {edit.file}:{edit.line}")
        print(f"    before: {edit.old_text[:80]}")
        print(f"    after:  {edit.new_text[:80]}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# Main CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="operon",
        description="Operon — repository-aware semantic code intelligence",
    )
    sub = p.add_subparsers(dest="command")

    # explain
    ep = sub.add_parser("explain", help="Explain a symbol, file, or line")
    ep.add_argument("target", help="symbol name, file:line, or file path")
    ep.add_argument("--flow",   action="store_true", help="Show execution flow")
    ep.add_argument("--file",   action="store_true", help="Explain entire file")
    ep.add_argument("--no-llm", action="store_true", help="Skip LLM calls")

    # usages
    up = sub.add_parser("usages", help="Show all usages of a symbol")
    up.add_argument("symbol")

    # rename
    rp = sub.add_parser("rename", help="Rename a symbol across the repo")
    rp.add_argument("old_name")
    rp.add_argument("new_name")
    rp.add_argument("--apply", action="store_true", help="Write changes to disk")

    # docs
    dp = sub.add_parser("docs", help="Generate /docs/ documentation")
    dp.add_argument("--no-llm", action="store_true", help="Skip LLM summaries")

    # summarize
    sp = sub.add_parser("summarize", help="Summarize all symbols in a file")
    sp.add_argument("file", help="Relative path to file")
    sp.add_argument("--no-llm", action="store_true", help="Skip LLM calls")

    # signature
    sigp = sub.add_parser("signature", help="Migrate function signature")
    sigp.add_argument("func",   help="Function name")
    sigp.add_argument("params", help='New params, comma-separated: "a, b=None, c"')
    sigp.add_argument("--apply", action="store_true")

    return p


def main(argv: Optional[List[str]] = None) -> None:
    parser = build_parser()
    args   = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return

    dispatch = {
        "explain":   cmd_explain,
        "usages":    cmd_usages,
        "rename":    cmd_rename,
        "docs":      cmd_docs,
        "summarize": cmd_summarize,
        "signature": cmd_signature,
    }
    fn = dispatch.get(args.command)
    if fn:
        fn(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
