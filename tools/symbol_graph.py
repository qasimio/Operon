# tools/symbol_graph.py — Operon v5
"""
Persistent, cross-file symbol graph.

Stores every symbol in the repo and the cross-file references between them.
Persisted as .operon/symbol_graph.json (incremental, hash-gated).

Schema:
  {
    "schema_version": 5,
    "hashes": { "agent/loop.py": "abc123", ... },
    "files": {
      "agent/loop.py": {
        "functions":  [{name, start, end, args, docstring, decorators, is_async}],
        "classes":    [{name, start, end, bases, methods, docstring}],
        "variables":  [{name, start, value_repr}],
        "imports":    [{name, source, start, kind}],
        "assignments":[{target, start, value_repr}],
        "decorators": [{name, start, target}],
        "annotations":[{name, annotation, start}],
      }
    },
    "cross_refs": {
      "MAX_STEPS": [
        {"file": "agent/loop.py",  "line": 60, "kind": "definition"},
        {"file": "agent/loop.py",  "line": 420, "kind": "usage"},
        {"file": "agent/decide.py","line": 33,  "kind": "usage"},
      ]
    }
  }

Usage:
  graph = load_symbol_graph(repo_root)
  graph = build_symbol_graph(repo_root, incremental=True)
  usages = query_symbol(graph, "MAX_STEPS")
  definitions = find_definitions(graph, "run_agent")
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agent.logger import log

SCHEMA_VERSION = 5
GRAPH_FILE     = ".operon/symbol_graph.json"
IGNORE_DIRS    = {".git", ".venv", "__pycache__", "node_modules", "dist", "build", ".operon"}
CODE_EXTS      = {".py", ".js", ".jsx", ".ts", ".tsx", ".java"}
TEXT_EXTS      = CODE_EXTS | {".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".cfg"}


# ─────────────────────────────────────────────────────────────────────────────
# File utilities
# ─────────────────────────────────────────────────────────────────────────────

def _list_code_files(repo_root: str) -> List[str]:
    root = Path(repo_root)
    out = []
    for p in root.rglob("*"):
        if p.is_file() and p.suffix in CODE_EXTS:
            if not any(d in p.parts for d in IGNORE_DIRS):
                out.append(str(p.relative_to(root)))
    return sorted(out)


def _file_hash(path: Path) -> str:
    try:
        return hashlib.md5(path.read_bytes()).hexdigest()
    except Exception:
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# Python cross-reference extraction — identify all Name usages in a file
# ─────────────────────────────────────────────────────────────────────────────

def _build_py_usages(source: str) -> Dict[str, List[Dict]]:
    """
    Walk the AST and collect every symbol name → list of line numbers
    where it appears (as load/store/call).
    Returns {symbol_name: [{line, kind}]}
    """
    usages: Dict[str, List[Dict]] = {}
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return usages

    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            kind = "def" if isinstance(node.ctx, ast.Store) else "ref"
            usages.setdefault(node.id, []).append({"line": node.lineno, "kind": kind})
        elif isinstance(node, ast.Attribute):
            # foo.bar → record 'bar'
            usages.setdefault(node.attr, []).append({"line": node.lineno, "kind": "attr"})
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                usages.setdefault(node.func.id, []).append({"line": node.lineno, "kind": "call"})
            elif isinstance(node.func, ast.Attribute):
                usages.setdefault(node.func.attr, []).append({"line": node.lineno, "kind": "call"})
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            usages.setdefault(node.name, []).append({"line": node.lineno, "kind": "definition"})
        elif isinstance(node, ast.ClassDef):
            usages.setdefault(node.name, []).append({"line": node.lineno, "kind": "definition"})

    return usages


def _build_regex_usages(source: str) -> Dict[str, List[Dict]]:
    """Regex-based usage extraction for non-Python files."""
    usages: Dict[str, List[Dict]] = {}
    for m in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\b", source):
        name = m.group(1)
        if len(name) < 2:
            continue
        ln = source[:m.start()].count("\n") + 1
        usages.setdefault(name, []).append({"line": ln, "kind": "ref"})
    return usages


# ─────────────────────────────────────────────────────────────────────────────
# Build / load
# ─────────────────────────────────────────────────────────────────────────────

def _graph_path(repo_root: str) -> Path:
    return Path(repo_root) / GRAPH_FILE


def load_symbol_graph(repo_root: str) -> Dict:
    """Load persisted graph or return empty shell."""
    try:
        p = _graph_path(repo_root)
        if p.exists():
            g = json.loads(p.read_text(encoding="utf-8"))
            if g.get("schema_version") == SCHEMA_VERSION:
                return g
    except Exception:
        pass
    return {"schema_version": SCHEMA_VERSION, "hashes": {}, "files": {}, "cross_refs": {}}


def _save_graph(repo_root: str, graph: Dict) -> None:
    try:
        p = _graph_path(repo_root)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(graph, indent=2), encoding="utf-8")
    except Exception as e:
        log.debug(f"symbol_graph save failed: {e}")


def build_symbol_graph(repo_root: str, incremental: bool = True) -> Dict:
    """
    Build (or incrementally update) the full symbol graph.
    Returns the graph dict.  Also persists to disk.
    """
    from tools.universal_parser import extract_symbols

    t0    = time.time()
    graph = load_symbol_graph(repo_root) if incremental else {
        "schema_version": SCHEMA_VERSION, "hashes": {}, "files": {}, "cross_refs": {}
    }
    cached_hashes = graph.get("hashes", {})
    files_data    = graph.get("files", {})

    code_files = _list_code_files(repo_root)
    changed    = 0
    root       = Path(repo_root)

    # Per-file usages collected for cross-ref assembly
    all_usages: Dict[str, Dict[str, List[Dict]]] = {}   # rel → {sym → [{line,kind}]}

    for rel in code_files:
        p    = root / rel
        h    = _file_hash(p)
        if incremental and h and h == cached_hashes.get(rel) and rel in files_data:
            # Re-use cached symbols but still need usages for cross-ref
            try:
                source = p.read_text(encoding="utf-8", errors="ignore")
                if p.suffix == ".py":
                    all_usages[rel] = _build_py_usages(source)
                else:
                    all_usages[rel] = _build_regex_usages(source)
            except Exception:
                pass
            continue

        try:
            source = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        syms = extract_symbols(source, rel)
        files_data[rel]    = syms
        cached_hashes[rel] = h
        changed += 1

        if p.suffix == ".py":
            all_usages[rel] = _build_py_usages(source)
        else:
            all_usages[rel] = _build_regex_usages(source)

    # Build cross_refs: symbol → [{file, line, kind}]
    cross_refs: Dict[str, List[Dict]] = {}
    for rel, usages in all_usages.items():
        for sym, occ_list in usages.items():
            if len(sym) < 2:
                continue
            for occ in occ_list:
                cross_refs.setdefault(sym, []).append({
                    "file": rel,
                    "line": occ["line"],
                    "kind": occ["kind"],
                })

    graph["hashes"]     = cached_hashes
    graph["files"]      = files_data
    graph["cross_refs"] = cross_refs

    _save_graph(repo_root, graph)
    elapsed = time.time() - t0
    log.info(
        f"[bold green]✅ Symbol graph ready:[/bold green] "
        f"{len(files_data)} files, {len(cross_refs)} symbols "
        f"({changed} re-indexed, {elapsed:.1f}s)"
    )
    return graph


# ─────────────────────────────────────────────────────────────────────────────
# Query helpers
# ─────────────────────────────────────────────────────────────────────────────

def query_symbol(graph: Dict, name: str) -> List[Dict]:
    """Return all cross-ref entries for a symbol name (exact match)."""
    return graph.get("cross_refs", {}).get(name, [])


def find_definitions(graph: Dict, name: str) -> List[Dict]:
    """Return only the definition sites."""
    return [e for e in query_symbol(graph, name) if e.get("kind") == "definition"]


def find_usages(graph: Dict, name: str) -> List[Dict]:
    """Return all non-definition sites."""
    return [e for e in query_symbol(graph, name) if e.get("kind") != "definition"]


def symbols_in_file(graph: Dict, rel_path: str) -> Dict:
    """Return the full symbol dict for a specific file."""
    return graph.get("files", {}).get(rel_path, {})


def search_symbols_by_prefix(graph: Dict, prefix: str) -> List[str]:
    """Return symbol names that start with prefix (case-insensitive)."""
    p = prefix.lower()
    return [k for k in graph.get("cross_refs", {}) if k.lower().startswith(p)]


def get_file_summary(graph: Dict, rel_path: str) -> str:
    """One-line human summary of what's in a file."""
    syms = symbols_in_file(graph, rel_path)
    fn_names  = [f["name"] for f in syms.get("functions", [])][:8]
    cl_names  = [c["name"] for c in syms.get("classes", [])][:4]
    var_names = [v["name"] for v in syms.get("variables", [])][:6]
    parts = []
    if cl_names:
        parts.append(f"classes: {', '.join(cl_names)}")
    if fn_names:
        parts.append(f"functions: {', '.join(fn_names)}")
    if var_names:
        parts.append(f"vars: {', '.join(var_names)}")
    return " | ".join(parts) or "(empty)"
