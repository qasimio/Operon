# `tools/symbol_graph.py`

> Persistent, cross-file symbol graph.

Stores every symbol in the repo and the cross-file references between them.
Persisted as .operon/symbol_graph.json (incremental, hash-gated).

Schema:
  {
    "schema_version": 5,
    "hashes": { "agent/loop.py": "abc123", ... },
    "files": {
      "agent/loop.py": {
        "functions":  [{name, start, end, args, docstring, decorators, is_async}],
        "


## Overview

This file, `tools/symbol_graph.py`, is part of the Operon v5 software and is responsible for creating and managing a persistent, cross-file symbol graph for a repository. The symbol graph stores information about symbols (functions, classes, variables, etc.) in each file, as well as cross-file references between these symbols. The graph is persisted in a JSON file located at `.operon/symbol_graph.json`. The file includes functions for loading, building, querying, and finding definitions within the symbol graph.


## Stats

| Metric | Count |
|--------|-------|
| Lines | 277 |
| Functions | 14 |
| Classes | 0 |
| Variables | 37 |
| Imports | 14 |


## Imports

- `__future__:annotations`
- `ast`
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


## Dependencies (imports)

- [`agent/logger.py`](agent_logger.md)
- [`tools/universal_parser.py`](tools_universal_parser.md)


## Imported by

- [`cli/explain.py`](cli_explain.md)
- [`cli/explain.py`](cli_explain.md)
- [`cli/explain.py`](cli_explain.md)
- [`cli/explain.py`](cli_explain.md)
- [`cli/explain.py`](cli_explain.md)
- [`cli/explain.py`](cli_explain.md)
- [`cli/explain.py`](cli_explain.md)
- [`tools/ast_engine.py`](tools_ast_engine.md)
- [`tools/ast_engine.py`](tools_ast_engine.md)
- [`tools/ast_engine.py`](tools_ast_engine.md)


## Functions


### `def _list_code_files(repo_root: str)`

- **Lines:** 61–68


### `def _file_hash(path: Path)`

- **Lines:** 71–75


### `def _build_py_usages(source: str)`

- **Lines:** 82–111
- **Docstring:** Walk the AST and collect every symbol name → list of line numbers
    where it appears (as load/store/call).
    Returns {symbol_name: [{line, kind}]}


### `def _build_regex_usages(source: str)`

- **Lines:** 114–123
- **Docstring:** Regex-based usage extraction for non-Python files.


### `def _graph_path(repo_root: str)`

- **Lines:** 130–131


### `def load_symbol_graph(repo_root: str)`

- **Lines:** 134–144
- **Docstring:** Load persisted graph or return empty shell.


### `def _save_graph(repo_root: str, graph: Dict)`

- **Lines:** 147–153


### `def build_symbol_graph(repo_root: str, incremental: bool)`

- **Lines:** 156–231
- **Docstring:** Build (or incrementally update) the full symbol graph.
    Returns the graph dict.  Also persists to disk.


### `def query_symbol(graph: Dict, name: str)`

- **Lines:** 238–240
- **Docstring:** Return all cross-ref entries for a symbol name (exact match).


### `def find_definitions(graph: Dict, name: str)`

- **Lines:** 243–245
- **Docstring:** Return only the definition sites.


### `def find_usages(graph: Dict, name: str)`

- **Lines:** 248–250
- **Docstring:** Return all non-definition sites.


### `def symbols_in_file(graph: Dict, rel_path: str)`

- **Lines:** 253–255
- **Docstring:** Return the full symbol dict for a specific file.


### `def search_symbols_by_prefix(graph: Dict, prefix: str)`

- **Lines:** 258–261
- **Docstring:** Return symbol names that start with prefix (case-insensitive).


### `def get_file_summary(graph: Dict, rel_path: str)`

- **Lines:** 264–277
- **Docstring:** One-line human summary of what's in a file.


## Constants

- `SCHEMA_VERSION` = `5` (line 50)
- `GRAPH_FILE` = `'.operon/symbol_graph.json'` (line 51)
- `IGNORE_DIRS` = `{'.git', '.venv', '__pycache__', 'node_modules', 'dist', 'build', '.operon'}` (line 52)
- `CODE_EXTS` = `{'.py', '.js', '.jsx', '.ts', '.tsx', '.java'}` (line 53)
- `TEXT_EXTS` = `CODE_EXTS | {'.md', '.txt', '.json', '.yaml', '.yml', '.toml', '.cfg'}` (line 54)
