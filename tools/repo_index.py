# tools/repo_index.py — Operon v5
"""
4-Level Intelligence Index — now backed by symbol_graph.py

  L1  Semantic vector search  (LanceDB + FastEmbed)     → semantic_memory.py
  L2  Symbol index            (AST-based, universal_parser.py)
  L3  Dependency graph        (import resolution)
  L4  Content-addressed cache (file-hash → skip re-index)
  L5  Full cross-ref graph    (symbol_graph.py)  ← NEW in v5

build_full_index() now calls build_symbol_graph() for the richer L5 layer
and populates state.symbol_graph_full.  The L2/L3 state fields are kept
for backward compatibility with decide.py / loop.py context injection.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agent.logger import log

IGNORE_DIRS = {".git", ".venv", "__pycache__", "node_modules", "dist", "build", ".operon"}
CODE_EXTS   = {".py", ".js", ".jsx", ".ts", ".tsx", ".java"}
TEXT_EXTS   = CODE_EXTS | {".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".cfg"}
INDEX_FILE  = ".operon/index.json"


# ─────────────────────────────────────────────────────────────────────────────
# File enumeration
# ─────────────────────────────────────────────────────────────────────────────

def list_repo_files(repo_root: str) -> List[str]:
    root = Path(repo_root)
    out: List[str] = []
    for p in root.rglob("*"):
        if p.is_file() and not any(d in p.parts for d in IGNORE_DIRS):
            out.append(str(p.relative_to(root)))
    return sorted(out)


def _file_hash(p: Path) -> str:
    try:
        return hashlib.md5(p.read_bytes()).hexdigest()
    except Exception:
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# L2 — Symbol index (uses universal_parser with full AST)
# ─────────────────────────────────────────────────────────────────────────────

def _build_symbol_index_for_file(content: str, rel_path: str) -> Dict[str, Any]:
    try:
        from tools.universal_parser import extract_symbols
        return extract_symbols(content, rel_path)
    except Exception:
        pass
    # Regex fallback
    funcs, classes = [], []
    for m in re.finditer(r"^(?:def|async def)\s+(\w+)\s*\(", content, re.MULTILINE):
        lineno = content[:m.start()].count("\n") + 1
        funcs.append({"name": m.group(1), "start": lineno, "end": lineno})
    for m in re.finditer(r"^class\s+(\w+)", content, re.MULTILINE):
        lineno = content[:m.start()].count("\n") + 1
        classes.append({"name": m.group(1), "start": lineno, "end": lineno})
    return {"functions": funcs, "classes": classes}


# ─────────────────────────────────────────────────────────────────────────────
# L3 — Dependency graph
# ─────────────────────────────────────────────────────────────────────────────

_IMPORT_RE = [
    re.compile(r"^\s*import\s+([\w\.]+)", re.MULTILINE),
    re.compile(r"^\s*from\s+([\w\.]+)\s+import", re.MULTILINE),
    re.compile(r'require\(["\']([^"\']+)["\']\)'),
    re.compile(r'from\s+["\']([^"\']+)["\']\s*import'),
    re.compile(r'import\s+["\']([^"\']+)["\']'),
]


def _extract_raw_imports(content: str) -> List[str]:
    found: List[str] = []
    for pat in _IMPORT_RE:
        found.extend(pat.findall(content))
    return list(set(found))


def _module_to_rel(module: str, repo_root: str, source_rel: str) -> Optional[str]:
    root = Path(repo_root)
    for ext in (".py", "/__init__.py"):
        c = root / (module.replace(".", "/") + ext)
        if c.is_file():
            return str(c.relative_to(root))
    if module.startswith("."):
        base = Path(source_rel).parent
        for ext in (".js", ".jsx", ".ts", ".tsx", ".py"):
            c = root / base / (module.lstrip("./") + ext)
            if c.is_file():
                return str(c.relative_to(root))
    return None


def _build_dep_graph(
    repo_root: str,
    files: List[str],
    contents: Dict[str, str],
) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    fwd: Dict[str, List[str]] = {}
    rev: Dict[str, List[str]] = {}
    for rel in files:
        content  = contents.get(rel, "")
        raw      = _extract_raw_imports(content)
        resolved = []
        for imp in raw:
            r = _module_to_rel(imp, repo_root, rel)
            if r and r != rel:
                resolved.append(r)
        if resolved:
            fwd[rel] = sorted(set(resolved))
            for dep in resolved:
                rev.setdefault(dep, [])
                if rel not in rev[dep]:
                    rev[dep].append(rel)
    return fwd, rev


# ─────────────────────────────────────────────────────────────────────────────
# Persistence helpers
# ─────────────────────────────────────────────────────────────────────────────

def _load_cached_index(repo_root: str) -> Dict:
    try:
        idx_path = Path(repo_root) / INDEX_FILE
        if idx_path.exists():
            return json.loads(idx_path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_index(repo_root: str, index: Dict) -> None:
    try:
        idx_path = Path(repo_root) / INDEX_FILE
        idx_path.parent.mkdir(parents=True, exist_ok=True)
        idx_path.write_text(json.dumps(index, indent=2), encoding="utf-8")
    except Exception as e:
        log.debug(f"Index save failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Main builder — incremental
# ─────────────────────────────────────────────────────────────────────────────

def build_full_index(state) -> None:
    """
    Build all index layers and store on state.
    Incremental: re-uses cached entries for unchanged files.
    Also builds the v5 symbol graph (state.symbol_graph_full).
    """
    repo_root = state.repo_root
    t0 = time.time()
    log.info("[bold cyan]🧠 Building intelligence index (incremental)...[/bold cyan]")

    cached        = _load_cached_index(repo_root)
    cached_hashes = cached.get("hashes", {})
    cached_symbols = cached.get("symbols", {})

    files    = list_repo_files(repo_root)
    state.file_tree = files

    contents:    Dict[str, str] = {}
    new_symbols: Dict[str, Any] = {}
    new_hashes:  Dict[str, str] = {}
    changed = 0

    for rel in files:
        if Path(rel).suffix not in TEXT_EXTS:
            continue
        p = Path(repo_root) / rel
        h = _file_hash(p)
        new_hashes[rel] = h

        if h and h == cached_hashes.get(rel) and rel in cached_symbols:
            new_symbols[rel] = cached_symbols[rel]
            try:
                contents[rel] = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                pass
            continue

        try:
            content = p.read_text(encoding="utf-8", errors="ignore")
            contents[rel] = content
            if Path(rel).suffix in CODE_EXTS:
                new_symbols[rel] = _build_symbol_index_for_file(content, rel)
                changed += 1
        except Exception as e:
            log.debug(f"Index skip {rel}: {e}")

    fwd, rev = _build_dep_graph(repo_root, files, contents)

    state.symbol_index = new_symbols
    state.dep_graph    = fwd
    state.rev_dep      = rev

    _save_index(repo_root, {"hashes": new_hashes, "symbols": new_symbols})

    elapsed = time.time() - t0
    log.info(
        f"[bold green]✅ Index ready:[/bold green] "
        f"{len(new_symbols)} symbols, {len(fwd)} dep nodes, "
        f"{changed} files re-indexed ({elapsed:.1f}s)"
    )

    # v5: Build full symbol graph (cross-refs, all symbol types)
    try:
        from tools.symbol_graph import build_symbol_graph
        state.symbol_graph_full = build_symbol_graph(repo_root, incremental=True)
    except Exception as e:
        log.debug(f"symbol_graph build failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Context retrieval
# ─────────────────────────────────────────────────────────────────────────────

def get_context_for_query(state, query: str, max_chars: int = 800) -> str:
    """
    Multi-level context retrieval.
    v5: also uses chunked_loader for semantic chunk retrieval.
    """
    parts: List[str] = []
    q = query.lower()

    # v5: chunked loader (semantic relevance)
    try:
        from tools.chunked_loader import load_context_for_query
        chunk_ctx = load_context_for_query(query, state, max_chars=600)
        if chunk_ctx:
            parts.append(chunk_ctx)
    except Exception:
        pass

    # L2 — symbol hits
    sym_hits: List[str] = []
    for rel, syms in (state.symbol_index or {}).items():
        for item in syms.get("functions", []) + syms.get("classes", []):
            if q in item.get("name", "").lower() or q in rel.lower():
                sym_hits.append(
                    f"  {rel}::{item['name']} (L{item.get('start', '?')}–{item.get('end', '?')})"
                )
    if sym_hits:
        parts.append("Symbol matches:\n" + "\n".join(sym_hits[:6]))

    # L3 — dep graph
    dep_hits: List[str] = []
    for rel, deps in (state.dep_graph or {}).items():
        if q in rel.lower():
            dep_hits.append(f"  {rel} imports: {deps[:3]}")
    for rel, importers in (state.rev_dep or {}).items():
        if q in rel.lower():
            dep_hits.append(f"  {rel} imported by: {importers[:3]}")
    if dep_hits:
        parts.append("Dependency links:\n" + "\n".join(dep_hits[:4]))

    # File tree
    tree_hits = [f"  {p}" for p in (state.file_tree or []) if q in p.lower()]
    if tree_hits and not sym_hits:
        parts.append("Matching files:\n" + "\n".join(tree_hits[:8]))

    result = "\n\n".join(parts)
    if len(result) > max_chars:
        result = result[:max_chars] + "\n  [truncated]"
    return result
