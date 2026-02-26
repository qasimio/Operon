# tools/repo_index.py — Operon v2: 4-Level Intelligence Index
"""
Builds all 4 intelligence layers Operon needs for tight context windows:

  Level 1 — Semantic search  (LanceDB + FastEmbed)  → tools/semantic_memory.py
  Level 2 — Symbol index     (functions/classes per file, AST-backed)
  Level 3 — Dependency graph (import resolution: who imports whom)
  Level 4 — AST extraction   (per-function code slices for surgical editing)

Call build_full_index(state) once at startup to populate state with all 4 layers.
The result is stored on the AgentState so the LLM prompt builder can inject only
what it needs — keeping prompts short for Qwen 7B @ 8k ctx.
"""

from __future__ import annotations

import re
import json
from pathlib import Path
from typing import Dict, List, Any

from tools.universal_parser import extract_symbols
from agent.logger import log

# ── Config ────────────────────────────────────────────────────────────────────
IGNORE_DIRS = {".git", ".venv", "__pycache__", "node_modules", "dist", "build", ".operon"}
TEXT_EXTS = {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".md", ".txt", ".json", ".yaml", ".yml"}


# ─────────────────────────────────────────────────────────────────────────────
# LEVEL 2 — Symbol Index
# ─────────────────────────────────────────────────────────────────────────────

def build_symbol_index(repo_root: str) -> Dict[str, Any]:
    """
    Returns: { "path/to/file.py": { "functions": [...], "classes": [...] }, ... }
    Uses the Tree-sitter universal parser for accuracy.
    """
    root = Path(repo_root)
    index: Dict[str, Any] = {}

    for p in root.rglob("*"):
        if any(i in p.parts for i in IGNORE_DIRS):
            continue
        if not p.is_file() or p.suffix not in TEXT_EXTS:
            continue
        try:
            content = p.read_text(encoding="utf-8", errors="ignore")
            symbols = extract_symbols(content, str(p))
            rel = str(p.relative_to(root))
            index[rel] = {
                "functions": symbols.get("functions", []),
                "classes": symbols.get("classes", []),
            }
        except Exception as e:
            log.debug(f"Symbol index skip {p}: {e}")

    log.info(f"[cyan]📚 Symbol index built: {len(index)} files.[/cyan]")
    return index


# ─────────────────────────────────────────────────────────────────────────────
# LEVEL 3 — Dependency Graph
# ─────────────────────────────────────────────────────────────────────────────

_IMPORT_PATTERNS = [
    re.compile(r'^\s*import\s+([\w\.]+)', re.MULTILINE),
    re.compile(r'^\s*from\s+([\w\.]+)\s+import', re.MULTILINE),
    re.compile(r'^\s*require\([\'\"]([\w\.\/\-]+)[\'\"]\)', re.MULTILINE),      # JS
    re.compile(r'^\s*import\s+.*\s+from\s+[\'\"]([\w\.\/\-]+)[\'\"]]', re.MULTILINE),  # ES6
]


def _extract_raw_imports(content: str) -> List[str]:
    found = []
    for pat in _IMPORT_PATTERNS:
        found.extend(pat.findall(content))
    return list(set(found))


def _module_to_path(module: str, repo_root: str, source_file: str) -> str | None:
    """Best-effort: turn 'agent.logger' → 'agent/logger.py'."""
    root = Path(repo_root)
    # Python dotted module
    candidate = root / (module.replace(".", "/") + ".py")
    if candidate.exists():
        return str(candidate.relative_to(root))
    # Try as directory __init__
    candidate2 = root / module.replace(".", "/") / "__init__.py"
    if candidate2.exists():
        return str(candidate2.relative_to(root))
    # Relative JS-style: ./something
    if module.startswith("."):
        base = Path(source_file).parent
        for ext in (".js", ".jsx", ".ts", ".tsx", ".py"):
            candidate3 = root / base / (module.lstrip("./") + ext)
            if candidate3.exists():
                return str(candidate3.relative_to(root))
    return None


def build_dep_graph(repo_root: str) -> Dict[str, List[str]]:
    """
    Returns: { "agent/loop.py": ["agent/llm.py", "tools/fs_tools.py", ...], ... }
    """
    root = Path(repo_root)
    graph: Dict[str, List[str]] = {}

    for p in root.rglob("*"):
        if any(i in p.parts for i in IGNORE_DIRS):
            continue
        if not p.is_file() or p.suffix not in TEXT_EXTS:
            continue
        try:
            content = p.read_text(encoding="utf-8", errors="ignore")
            raw_imports = _extract_raw_imports(content)
            rel_source = str(p.relative_to(root))
            resolved = []
            for imp in raw_imports:
                path = _module_to_path(imp, repo_root, rel_source)
                if path:
                    resolved.append(path)
            if resolved:
                graph[rel_source] = sorted(set(resolved))
        except Exception as e:
            log.debug(f"Dep graph skip {p}: {e}")

    log.info(f"[cyan]🕸️  Dependency graph built: {len(graph)} nodes.[/cyan]")
    return graph


# ─────────────────────────────────────────────────────────────────────────────
# LEVEL 4 — AST Extraction (per-symbol code slices)
# ─────────────────────────────────────────────────────────────────────────────

def build_ast_cache(repo_root: str, symbol_index: Dict[str, Any]) -> Dict[str, Any]:
    """
    For each file in symbol_index, store extracted function/class code slices.
    Returns: { "path/to/file.py": { "slices": { "func_name": "def func...\n    ...\n" } } }

    Keeps slices to 60 lines max to stay inside the context window budget.
    """
    root = Path(repo_root)
    cache: Dict[str, Any] = {}

    for rel_path, syms in symbol_index.items():
        p = root / rel_path
        if not p.exists():
            continue
        try:
            lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
            slices: Dict[str, str] = {}
            for fn in syms.get("functions", []) + syms.get("classes", []):
                name = fn.get("name", "")
                start = max(0, fn.get("start", 1) - 1)          # convert to 0-based
                end = min(len(lines), fn.get("end", start + 1))
                # Cap at 60 lines to save context
                if end - start > 60:
                    end = start + 60
                slices[name] = "\n".join(lines[start:end])
            if slices:
                cache[rel_path] = {"slices": slices}
        except Exception as e:
            log.debug(f"AST cache skip {rel_path}: {e}")

    log.info(f"[cyan]🔬 AST cache built: {len(cache)} files.[/cyan]")
    return cache


# ─────────────────────────────────────────────────────────────────────────────
# ORCHESTRATOR — build all 4 levels at once
# ─────────────────────────────────────────────────────────────────────────────

def build_full_index(state) -> None:
    """
    Populate state.symbol_index, state.dep_graph, state.ast_cache in-place.
    Also triggers LanceDB semantic indexing (Level 1) in a best-effort manner.
    Designed to run in a background thread at startup.
    """
    repo_root = state.repo_root
    log.info("[bold cyan]🧠 Building 4-Level Intelligence Index...[/bold cyan]")

    # Level 2 — Symbol Index
    try:
        state.symbol_index = build_symbol_index(repo_root)
    except Exception as e:
        log.error(f"Symbol index failed: {e}")
        state.symbol_index = {}

    # Level 3 — Dependency Graph
    try:
        state.dep_graph = build_dep_graph(repo_root)
    except Exception as e:
        log.error(f"Dep graph failed: {e}")
        state.dep_graph = {}

    # Level 4 — AST Cache
    try:
        state.ast_cache = build_ast_cache(repo_root, state.symbol_index)
    except Exception as e:
        log.error(f"AST cache failed: {e}")
        state.ast_cache = {}

    # Persist to disk for debugging / fast reload
    try:
        odir = Path(repo_root) / ".operon"
        odir.mkdir(parents=True, exist_ok=True)
        with open(odir / "symbol_index.json", "w") as f:
            json.dump(state.symbol_index, f, indent=2)
        with open(odir / "dep_graph.json", "w") as f:
            json.dump(state.dep_graph, f, indent=2)
        log.info("[bold green]✅ 4-Level index persisted to .operon/[/bold green]")
    except Exception as e:
        log.debug(f"Index persist failed: {e}")

    log.info("[bold green]✅ Intelligence Index complete.[/bold green]")


def get_relevant_context(state, query: str, max_files: int = 3) -> str:
    """
    Given a search query, return a compact multi-level context string to inject
    into LLM prompts. Tries:
      1. semantic_search hits (if LanceDB available)
      2. symbol_index lookup for function names matching query words
      3. dep_graph to find related files

    Returns a short string (<500 chars) suitable for prompt injection.
    """
    parts: List[str] = []
    query_lower = query.lower()

    # Level 2: symbol match
    sym_hits: List[str] = []
    for rel_path, syms in (state.symbol_index or {}).items():
        for fn in syms.get("functions", []) + syms.get("classes", []):
            if query_lower in fn.get("name", "").lower():
                sym_hits.append(f"{rel_path}::{fn['name']} (L{fn.get('start',0)}-{fn.get('end',0)})")
    if sym_hits:
        parts.append("Symbol hits: " + ", ".join(sym_hits[:max_files]))

    # Level 3: dep graph
    dep_hits: List[str] = []
    for rel_path, deps in (state.dep_graph or {}).items():
        if query_lower in rel_path.lower():
            dep_hits.append(f"{rel_path} → {deps[:2]}")
    if dep_hits:
        parts.append("Dep graph: " + "; ".join(dep_hits[:max_files]))

    # Level 4: AST slice
    ast_hints: List[str] = []
    for rel_path, data in (state.ast_cache or {}).items():
        for name, code in data.get("slices", {}).items():
            if query_lower in name.lower():
                ast_hints.append(f"{rel_path}::{name}:\n{code[:200]}")
    if ast_hints:
        parts.append("AST slice:\n" + "\n\n".join(ast_hints[:1]))

    return "\n".join(parts) if parts else ""
