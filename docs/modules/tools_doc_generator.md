# `tools/doc_generator.py`

> DeepWiki-style documentation generator for Operon.

Generates:
  docs/README.md            — repo overview + dependency graph
  docs/modules/<file>.md    — per-module documentation
  docs/symbols.md           — cross-repo symbol reference
  docs/call_graph.md        — call relationships

Usage:
  from tools.doc_generator import generate_repo_docs
  generate_repo_docs(repo_root, graph, call_llm_fn=


## Overview

This file, `tools/doc_generator.py`, is part of the Operon v5 project and serves as a DeepWiki-style documentation generator. It generates various documentation files such as `README.md`, per-module documentation, a cross-repo symbol reference, and a call graph. The `generate_repo_docs` function is the primary entry point, which takes the repository root, a graph, and an optional call LLM function as parameters. The file includes helper functions for reading files, writing documentation, and formatting module and function signatures.


## Stats

| Metric | Count |
|--------|-------|
| Lines | 462 |
| Functions | 12 |
| Classes | 0 |
| Variables | 85 |
| Imports | 17 |


## Imports

- `__future__:annotations`
- `ast`
- `re`
- `time`
- `pathlib:Path`
- `typing:Any`
- `typing:Callable`
- `typing:Dict`
- `typing:List`
- `typing:Optional`
- `agent.logger:log`
- `datetime`
- `tools.ast_engine:extract_chunk`
- `tools.ast_engine:summarize_block`
- `tools.ast_engine:insert_summary_comment`
- `tools.symbol_graph:build_symbol_graph`
- `tools.ast_engine:extract_chunk`


## Dependencies (imports)

- [`agent/logger.py`](agent_logger.md)
- [`tools/ast_engine.py`](tools_ast_engine.md)
- [`tools/ast_engine.py`](tools_ast_engine.md)
- [`tools/ast_engine.py`](tools_ast_engine.md)
- [`tools/symbol_graph.py`](tools_symbol_graph.md)
- [`tools/ast_engine.py`](tools_ast_engine.md)


## Imported by

- [`cli/explain.py`](cli_explain.md)


## Functions


### `def _read(p: Path)`

- **Lines:** 34–38


### `def _write_doc(path: Path, content: str)`

- **Lines:** 41–44


### `def _safe_module_name(rel: str)`

- **Lines:** 47–48


### `def _function_signature(sym: Dict)`

- **Lines:** 51–53


### `def _class_signature(sym: Dict)`

- **Lines:** 56–60


### `def _generate_module_doc(rel_path: str, symbols: Dict, dep_fwd: List[str], dep_rev: List[str], call_llm_fn: Optional[Callable], repo_root: str)`

- **Lines:** 67–203


### `def _generate_readme(repo_root: str, graph: Dict, call_llm_fn: Optional[Callable], file_summaries: Dict[str, str])`

- **Lines:** 210–268


### `def _generate_symbol_reference(graph: Dict)`

- **Lines:** 275–294


### `def _generate_call_graph(graph: Dict)`

- **Lines:** 301–324


### `def _ts()`

- **Lines:** 331–333


### `def generate_repo_docs(repo_root: str, graph: Optional[Dict], call_llm_fn: Optional[Callable])`

- **Lines:** 336–420
- **Docstring:** Generate complete /docs/ tree for the repository.

    Args:
        repo_root:   path to repo
        graph:       pre-built symbol graph (built if None)
        call_llm_fn: optional callable for LL


### `def generate_block_summary_comment(file_path: str, symbol_name: str, repo_root: str, call_llm_fn: Optional[Callable])`

- **Lines:** 423–462
- **Docstring:** Generate a summary comment for a symbol and insert it above the definition.
    Returns the new file content, or None if symbol not found.


## Constants

- `IGNORE_DIRS` = `{'.git', '.venv', '__pycache__', 'node_modules', 'dist', 'build', '.operon'}` (line 25)
- `CODE_EXTS` = `{'.py', '.js', '.jsx', '.ts', '.tsx', '.java'}` (line 26)
- `DOCS_DIR` = `'docs'` (line 27)
