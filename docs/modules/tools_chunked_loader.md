# `tools/chunked_loader.py`

> Semantic chunked loading — Claude Code style.

Principle: never load an entire file.  Always load the MINIMUM set of
code blocks that are relevant to the current query/goal.

Strategy:
  1. Symbol-level:  extract just the function/class/block needed
  2. Dependency-aware: if function A calls function B, include B's signature
  3. Relevance-ranked: cosine similarity on symbol names + docstrings vs 


## Overview

This file, `tools/chunked_loader.py`, is part of the Operon v5 system and is designed for efficient code loading and retrieval. It provides a public API to load relevant code chunks based on a query, ensuring that only the minimum set of code blocks necessary for the query is loaded. The system uses a combination of symbol-level extraction, dependency-aware inclusion, relevance ranking based on cosine similarity, and budget-aware assembly to achieve this.


## Stats

| Metric | Count |
|--------|-------|
| Lines | 340 |
| Functions | 10 |
| Classes | 1 |
| Variables | 61 |
| Imports | 12 |


## Imports

- `__future__:annotations`
- `ast`
- `re`
- `dataclasses:dataclass`
- `pathlib:Path`
- `typing:Any`
- `typing:Dict`
- `typing:List`
- `typing:Optional`
- `typing:Tuple`
- `agent.logger:log`
- `tools.ast_engine:extract_chunk`


## Dependencies (imports)

- [`agent/logger.py`](agent_logger.md)
- [`tools/ast_engine.py`](tools_ast_engine.md)


## Imported by

- [`tools/repo_index.py`](tools_repo_index.md)


## Classes


### `class Chunk`

- **Lines:** 37–45

**Summary:** The `Chunk` class represents a segment of code with metadata such as file location, symbol name, type, and relevance score.


## Functions


### `def _tokenize_query(text: str)`

- **Lines:** 52–54
- **Docstring:** Split text into lowercase identifier tokens.


### `def _score_chunk(chunk: Chunk, query_tokens: List[str])`

- **Lines:** 57–70
- **Docstring:** Score a chunk's relevance to query_tokens.
    Uses Jaccard-like overlap on symbol name + docstring + source.


### `def _extract_py_chunks(source: str, rel_path: str)`

- **Lines:** 77–145
- **Docstring:** Parse Python file and return one Chunk per function/class.


### `def _extract_regex_chunks(source: str, rel_path: str)`

- **Lines:** 148–163
- **Docstring:** Regex-based chunk extraction for non-Python files.


### `def load_symbol_chunk(file_path: str, symbol_name: str, repo_root: str)`

- **Lines:** 170–181
- **Docstring:** Load ONLY the block defining symbol_name from file_path.
    Returns the source string of just that block.


### `def get_relevant_chunks(query: str, repo_root: str, graph: Optional[Dict], max_chars: int)`

- **Lines:** 184–259
- **Docstring:** Find and rank the most relevant code chunks for query across the repo.
    Returns chunks sorted by relevance score, fitting within max_chars.


### `def load_context_for_query(query: str, state: Any, max_chars: int)`

- **Lines:** 262–283
- **Docstring:** Build a compact context string for LLM prompts.
    Uses the pre-built symbol graph and chunked loading.


### `def load_multi_file_context(files: List[str], symbols: List[str], repo_root: str, max_chars: int)`

- **Lines:** 286–340
- **Docstring:** Load specific symbols from specific files.
    Used for multi-instance repository interaction.


### `def _get_docstring(node)`

- **Lines:** 87–92


### `def _get_source(node)`

- **Lines:** 94–102


## Constants

- `IGNORE_DIRS` = `{'.git', '.venv', '__pycache__', 'node_modules', 'dist', 'build', '.operon'}` (line 29)
