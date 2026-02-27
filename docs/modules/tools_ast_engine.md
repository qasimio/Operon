# `tools/ast_engine.py`

> AST-based intelligence engine.  All operations use Python's ast stdlib.

Public API:
  rename_symbol(repo_root, old_name, new_name, dry_run) → RenameResult
  find_all_usages(repo_root, symbol, graph)              → List[UsageEntry]
  migrate_signature(repo_root, func_name, new_params, dry_run) → MigrateResult
  summarize_block(content, start_line, end_line, file_path) → str
  extract_chunk(content


## Overview

This file, `tools/ast_engine.py`, is part of the Operon v5 software and provides an AST-based intelligence engine for various operations on code repositories. It includes functions for renaming symbols, finding all usages of a symbol, migrating function signatures, summarizing code blocks, extracting code chunks, and explaining symbols. The file uses Python's `ast` standard library for parsing and manipulating abstract syntax trees.


## Stats

| Metric | Count |
|--------|-------|
| Lines | 688 |
| Functions | 13 |
| Classes | 4 |
| Variables | 130 |
| Imports | 20 |


## Imports

- `__future__:annotations`
- `ast`
- `io`
- `re`
- `tokenize`
- `dataclasses:dataclass`
- `dataclasses:field`
- `pathlib:Path`
- `typing:Any`
- `typing:Callable`
- `typing:Dict`
- `typing:List`
- `typing:Optional`
- `typing:Tuple`
- `agent.logger:log`
- `collections:defaultdict`
- `tools.universal_parser:get_block_source`
- `tools.symbol_graph:find_definitions`
- `tools.symbol_graph:find_usages`
- `tools.symbol_graph:query_symbol`


## Dependencies (imports)

- [`agent/logger.py`](agent_logger.md)
- [`tools/universal_parser.py`](tools_universal_parser.md)
- [`tools/symbol_graph.py`](tools_symbol_graph.md)
- [`tools/symbol_graph.py`](tools_symbol_graph.md)
- [`tools/symbol_graph.py`](tools_symbol_graph.md)


## Imported by

- [`cli/explain.py`](cli_explain.md)
- [`cli/explain.py`](cli_explain.md)
- [`cli/explain.py`](cli_explain.md)
- [`cli/explain.py`](cli_explain.md)
- [`cli/explain.py`](cli_explain.md)
- [`cli/explain.py`](cli_explain.md)
- [`cli/explain.py`](cli_explain.md)
- [`cli/explain.py`](cli_explain.md)
- [`tools/chunked_loader.py`](tools_chunked_loader.md)
- [`tools/doc_generator.py`](tools_doc_generator.md)


## Classes


### `class Edit`

- **Lines:** 34–41

**Summary:** The `Edit` class represents a modification to a specific line and column range within a file, storing the old and new text, as well as optional context.


### `class RenameResult`

- **Lines:** 45–50

**Summary:** The `RenameResult` class encapsulates the outcome of a renaming operation, storing the old and new names, a list of edits made, any errors encountered, and a boolean indicating whether the renaming was applied.


### `class UsageEntry`

- **Lines:** 54–58

**Summary:** UsageEntry is a data class representing a usage record with attributes for the file path, line number, type of usage (definition, call, reference, attribute, or import), and the context of the source line.


### `class MigrateResult`

- **Lines:** 62–66

**Summary:** MigrateResult encapsulates the outcome of a migration, including the function name, a list of edit call sites, a list of errors, and a boolean indicating whether the migration was applied.


## Functions


### `def _list_py_files(repo_root: str)`

- **Lines:** 73–79


### `def _list_code_files(repo_root: str)`

- **Lines:** 82–89


### `def _read(p: Path)`

- **Lines:** 92–96


### `def _lines(source: str)`

- **Lines:** 99–100


### `def _rename_in_py_source(source: str, old_name: str, new_name: str)`

- **Lines:** 107–153
- **Docstring:** Use tokenize to find every exact token == old_name and replace it.
    Returns (new_source, edits).


### `def _rename_in_generic_source(source: str, old_name: str, new_name: str)`

- **Lines:** 156–174
- **Docstring:** Word-boundary regex rename for non-Python files.
    Safe: only replaces whole-word matches.


### `def rename_symbol(repo_root: str, old_name: str, new_name: str, dry_run: bool)`

- **Lines:** 181–233
- **Docstring:** Rename old_name → new_name across the entire repository.

    Uses tokenize for Python (AST-accurate, formatting-preserving).
    Uses word-boundary regex for JS/TS/Java/other.

    dry_run=True: coll


### `def find_all_usages(repo_root: str, symbol: str, graph: Optional[Dict])`

- **Lines:** 240–310
- **Docstring:** Find every occurrence of symbol across the repository.

    If graph is provided (from symbol_graph.build_symbol_graph), uses the
    pre-built cross-ref index for speed.  Otherwise does a fresh scan.


### `def migrate_signature(repo_root: str, func_name: str, new_params: List[str], dry_run: bool)`

- **Lines:** 317–483
- **Docstring:** When a function's signature changes, find all call sites and
    update them to match new_params.

    Strategy:
      1. Find the function definition to know old params.
      2. Find all call sites.


### `def extract_chunk(content: str, symbol_name: str, file_path: str)`

- **Lines:** 490–519
- **Docstring:** Extract the smallest self-contained block containing symbol_name.

    For Python: finds the function/class definition and extracts just that block.
    For others: returns ±20 lines of context around


### `def summarize_block(content: str, start_line: int, end_line: int, file_path: str, call_llm_fn: Optional[Callable])`

- **Lines:** 526–573
- **Docstring:** Summarize a block of code (function, class, loop, etc.) as a docstring-style comment.

    If call_llm_fn is provided, uses LLM for a richer summary.
    Otherwise returns a structural description.


### `def insert_summary_comment(content: str, start_line: int, summary: str)`

- **Lines:** 580–598
- **Docstring:** Insert a # summary comment immediately above the block at start_line.


### `def explain_symbol(repo_root: str, symbol: str, graph: Optional[Dict], call_llm_fn: Optional[Callable])`

- **Lines:** 605–688
- **Docstring:** Produce a rich explanation of a symbol for the terminal.

    Returns a formatted string covering:
      - Definition location + signature
      - Docstring (if any)
      - Where it's called from
   


## Constants

- `IGNORE_DIRS` = `{'.git', '.venv', '__pycache__', 'node_modules', 'dist', 'build', '.operon'}` (line 25)
- `CODE_EXTS` = `{'.py', '.js', '.jsx', '.ts', '.tsx', '.java'}` (line 26)
