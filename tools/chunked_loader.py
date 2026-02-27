# tools/chunked_loader.py — Operon v5
"""
Semantic chunked loading — Claude Code style.

Principle: never load an entire file.  Always load the MINIMUM set of
code blocks that are relevant to the current query/goal.

Strategy:
  1. Symbol-level:  extract just the function/class/block needed
  2. Dependency-aware: if function A calls function B, include B's signature
  3. Relevance-ranked: cosine similarity on symbol names + docstrings vs query
  4. Budget-aware: assembles chunks up to max_chars, ranked by relevance

Public API:
  load_symbol_chunk(file_path, symbol_name, repo_root) → str
  load_context_for_query(query, state, max_chars) → str
  get_relevant_chunks(query, repo_root, graph, max_chars) → List[Chunk]
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agent.logger import log

IGNORE_DIRS = {".git", ".venv", "__pycache__", "node_modules", "dist", "build", ".operon"}


# ─────────────────────────────────────────────────────────────────────────────
# Data structure
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Chunk:
    file:      str
    symbol:    str
    kind:      str      # function | class | variable | block
    start:     int
    end:       int
    source:    str
    score:     float = 0.0    # relevance score
    docstring: str    = ""


# ─────────────────────────────────────────────────────────────────────────────
# Token-based similarity (no embeddings needed)
# ─────────────────────────────────────────────────────────────────────────────

def _tokenize_query(text: str) -> List[str]:
    """Split text into lowercase identifier tokens."""
    return [t.lower() for t in re.findall(r"[A-Za-z][A-Za-z0-9_]*", text) if len(t) > 1]


def _score_chunk(chunk: Chunk, query_tokens: List[str]) -> float:
    """
    Score a chunk's relevance to query_tokens.
    Uses Jaccard-like overlap on symbol name + docstring + source.
    """
    chunk_text = f"{chunk.symbol} {chunk.docstring} {chunk.source[:400]}"
    chunk_toks = set(_tokenize_query(chunk_text))
    if not chunk_toks:
        return 0.0
    query_set  = set(query_tokens)
    overlap    = len(query_set & chunk_toks)
    # Boost exact symbol name match
    exact_boost = 3.0 if chunk.symbol.lower() in {t.lower() for t in query_tokens} else 0.0
    return overlap / max(len(query_set), 1) + exact_boost


# ─────────────────────────────────────────────────────────────────────────────
# Symbol chunk extraction
# ─────────────────────────────────────────────────────────────────────────────

def _extract_py_chunks(source: str, rel_path: str) -> List[Chunk]:
    """Parse Python file and return one Chunk per function/class."""
    chunks: List[Chunk] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return chunks

    lines = source.splitlines(keepends=True)

    def _get_docstring(node) -> str:
        if (node.body and isinstance(node.body[0], ast.Expr)
                and isinstance(getattr(node.body[0], "value", None), ast.Constant)
                and isinstance(node.body[0].value.value, str)):
            return node.body[0].value.value.strip()[:200]
        return ""

    def _get_source(node) -> str:
        try:
            start = node.lineno - 1
            # Include decorators
            deco_start = min((d.lineno - 1 for d in getattr(node, "decorator_list", [])), default=start)
            end   = getattr(node, "end_lineno", node.lineno)
            return "".join(lines[deco_start:end])
        except Exception:
            return ""

    # Only walk top-level and class-level (not nested functions)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            src = _get_source(node)
            chunks.append(Chunk(
                file=rel_path, symbol=node.name,
                kind="function", start=node.lineno,
                end=getattr(node, "end_lineno", node.lineno),
                source=src, docstring=_get_docstring(node),
            ))
        elif isinstance(node, ast.ClassDef):
            src = _get_source(node)
            chunks.append(Chunk(
                file=rel_path, symbol=node.name,
                kind="class", start=node.lineno,
                end=getattr(node, "end_lineno", node.lineno),
                source=src, docstring=_get_docstring(node),
            ))
            # Also index methods
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    msrc = _get_source(sub)
                    chunks.append(Chunk(
                        file=rel_path, symbol=f"{node.name}.{sub.name}",
                        kind="method", start=sub.lineno,
                        end=getattr(sub, "end_lineno", sub.lineno),
                        source=msrc, docstring=_get_docstring(sub),
                    ))
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id.isupper():
                    try:
                        val = ast.unparse(node.value)[:80]
                    except Exception:
                        val = "?"
                    chunks.append(Chunk(
                        file=rel_path, symbol=t.id,
                        kind="variable", start=node.lineno,
                        end=node.lineno, source=f"{t.id} = {val}",
                    ))

    return chunks


def _extract_regex_chunks(source: str, rel_path: str) -> List[Chunk]:
    """Regex-based chunk extraction for non-Python files."""
    chunks: List[Chunk] = []
    lines = source.splitlines(keepends=True)

    for m in re.finditer(r"(?:function|class|const|def)\s+(\w+)", source):
        name = m.group(1)
        ln   = source[:m.start()].count("\n") + 1
        end  = min(ln + 20, len(lines))
        src  = "".join(lines[ln - 1:end])
        chunks.append(Chunk(
            file=rel_path, symbol=name, kind="block",
            start=ln, end=end, source=src[:400],
        ))

    return chunks


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def load_symbol_chunk(file_path: str, symbol_name: str, repo_root: str) -> str:
    """
    Load ONLY the block defining symbol_name from file_path.
    Returns the source string of just that block.
    """
    from tools.ast_engine import extract_chunk
    p = Path(repo_root) / file_path
    try:
        source = p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""
    return extract_chunk(source, symbol_name, file_path)


def get_relevant_chunks(
    query:     str,
    repo_root: str,
    graph:     Optional[Dict] = None,
    max_chars: int = 3000,
) -> List[Chunk]:
    """
    Find and rank the most relevant code chunks for query across the repo.
    Returns chunks sorted by relevance score, fitting within max_chars.
    """
    query_tokens = _tokenize_query(query)
    if not query_tokens:
        return []

    root = Path(repo_root)
    all_chunks: List[Chunk] = []

    # Fast path: if graph available, find relevant files first
    candidate_files: List[str] = []
    if graph:
        cross_refs = graph.get("cross_refs", {})
        for tok in query_tokens:
            # Exact matches
            if tok in cross_refs:
                for ref in cross_refs[tok][:5]:
                    f = ref["file"]
                    if f not in candidate_files:
                        candidate_files.append(f)
            # Prefix matches
            for sym in cross_refs:
                if sym.lower().startswith(tok):
                    for ref in cross_refs[sym][:2]:
                        f = ref["file"]
                        if f not in candidate_files:
                            candidate_files.append(f)

    # If no candidates from graph, scan all Python files
    if not candidate_files:
        for p in root.rglob("*.py"):
            if not any(d in p.parts for d in IGNORE_DIRS):
                candidate_files.append(str(p.relative_to(root)))

    # Extract chunks from candidate files
    for rel in candidate_files[:20]:
        p = root / rel
        if not p.exists():
            continue
        try:
            source = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if p.suffix == ".py":
            chunks = _extract_py_chunks(source, rel)
        else:
            chunks = _extract_regex_chunks(source, rel)
        all_chunks.extend(chunks)

    # Score and sort
    for chunk in all_chunks:
        chunk.score = _score_chunk(chunk, query_tokens)

    ranked = sorted(all_chunks, key=lambda c: -c.score)

    # Budget-fit selection
    result: List[Chunk] = []
    total  = 0
    for chunk in ranked:
        if chunk.score <= 0:
            break
        sz = len(chunk.source)
        if total + sz > max_chars and result:
            break
        result.append(chunk)
        total += sz

    return result


def load_context_for_query(
    query:     str,
    state:     Any,
    max_chars: int = 3000,
) -> str:
    """
    Build a compact context string for LLM prompts.
    Uses the pre-built symbol graph and chunked loading.
    """
    repo_root = getattr(state, "repo_root", ".")
    graph     = getattr(state, "symbol_graph_full", None)

    chunks = get_relevant_chunks(query, repo_root, graph, max_chars)
    if not chunks:
        return ""

    parts: List[str] = ["[RELEVANT CODE CHUNKS]"]
    for chunk in chunks:
        parts.append(f"\n# {chunk.file}::{chunk.symbol} (L{chunk.start}–{chunk.end})")
        parts.append(chunk.source[:500])
    parts.append("[/RELEVANT CODE CHUNKS]")
    return "\n".join(parts)


def load_multi_file_context(
    files:     List[str],
    symbols:   List[str],
    repo_root: str,
    max_chars: int = 4000,
) -> str:
    """
    Load specific symbols from specific files.
    Used for multi-instance repository interaction.
    """
    root   = Path(repo_root)
    parts: List[str] = []
    budget = max_chars

    for rel in files:
        p = root / rel
        if not p.exists():
            continue
        try:
            source = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        parts.append(f"\n### {rel}")

        if symbols:
            for sym in symbols:
                chunk = load_symbol_chunk(rel, sym, repo_root)
                if chunk:
                    parts.append(f"```python\n# {sym}\n{chunk[:600]}\n```")
                    budget -= len(chunk)
        else:
            # No specific symbols: show top-level signatures only
            try:
                tree   = ast.parse(source)
                sigs   = []
                for node in tree.body:
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        try:
                            args = [a.arg for a in node.args.args]
                            sigs.append(f"def {node.name}({', '.join(args)}): ...")
                        except Exception:
                            sigs.append(f"def {node.name}(...): ...")
                    elif isinstance(node, ast.ClassDef):
                        sigs.append(f"class {node.name}: ...")
                if sigs:
                    parts.append("```python\n" + "\n".join(sigs[:20]) + "\n```")
            except Exception:
                parts.append(source[:300])

        if budget <= 0:
            parts.append("\n[budget exceeded]")
            break

    return "\n".join(parts)
