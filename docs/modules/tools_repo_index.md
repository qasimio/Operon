# `tools/repo_index.py`

> 4-Level Intelligence Index — now backed by symbol_graph.py

  L1  Semantic vector search  (LanceDB + FastEmbed)     → semantic_memory.py
  L2  Symbol index            (AST-based, universal_parser.py)
  L3  Dependency graph        (import resolution)
  L4  Content-addressed cache (file-hash → skip re-index)
  L5  Full cross-ref graph    (symbol_graph.py)  ← NEW in v5

build_full_index() now calls b


## Overview

The file `tools/repo_index.py` is part of the Operon v5 system, which is designed to create a comprehensive index of a repository. It includes functions to list repository files, compute file hashes, and build a symbol index using an AST-based parser. The file also mentions the integration of a full cross-reference graph for enhanced intelligence.


## Stats

| Metric | Count |
|--------|-------|
| Lines | 279 |
| Functions | 10 |
| Classes | 0 |
| Variables | 44 |
| Imports | 15 |


## Imports

- `__future__:annotations`
- `hashlib`
- `json`
- `re`
- `time`
- `pathlib:Path`
- `typing:Any`
- `typing:Dict`
- `typing:List`
- `typing:Optional`
- `typing:Tuple`
- `agent.logger:log`
- `tools.universal_parser:extract_symbols`
- `tools.symbol_graph:build_symbol_graph`
- `tools.chunked_loader:load_context_for_query`


## Dependencies (imports)

- [`agent/logger.py`](agent_logger.md)
- [`tools/universal_parser.py`](tools_universal_parser.md)
- [`tools/symbol_graph.py`](tools_symbol_graph.md)
- [`tools/chunked_loader.py`](tools_chunked_loader.md)


## Imported by

- [`agent/decide.py`](agent_decide.md)
- [`agent/loop.py`](agent_loop.md)
- [`tui/app.py`](tui_app.md)


## Functions


### `def list_repo_files(repo_root: str)`

- **Lines:** 36–42


### `def _file_hash(p: Path)`

- **Lines:** 45–49


### `def _build_symbol_index_for_file(content: str, rel_path: str)`

- **Lines:** 56–70


### `def _extract_raw_imports(content: str)`

- **Lines:** 86–90


### `def _module_to_rel(module: str, repo_root: str, source_rel: str)`

- **Lines:** 93–105


### `def _build_dep_graph(repo_root: str, files: List[str], contents: Dict[str, str])`

- **Lines:** 108–129


### `def _load_cached_index(repo_root: str)`

- **Lines:** 136–143


### `def _save_index(repo_root: str, index: Dict)`

- **Lines:** 146–152


### `def build_full_index(state)`

- **Lines:** 159–225
- **Docstring:** Build all index layers and store on state.
    Incremental: re-uses cached entries for unchanged files.
    Also builds the v5 symbol graph (state.symbol_graph_full).


### `def get_context_for_query(state, query: str, max_chars: int)`

- **Lines:** 232–279
- **Docstring:** Multi-level context retrieval.
    v5: also uses chunked_loader for semantic chunk retrieval.


## Constants

- `IGNORE_DIRS` = `{'.git', '.venv', '__pycache__', 'node_modules', 'dist', 'build', '.operon'}` (line 26)
- `CODE_EXTS` = `{'.py', '.js', '.jsx', '.ts', '.tsx', '.java'}` (line 27)
- `TEXT_EXTS` = `CODE_EXTS | {'.md', '.txt', '.json', '.yaml', '.yml', '.toml', '.cfg'}` (line 28)
- `INDEX_FILE` = `'.operon/index.json'` (line 29)
- `_IMPORT_RE` = `[re.compile('^\\s*import\\s+([\\w\\.]+)', re.MULTILINE), re.compile('^\\s*from\\` (line 77)
