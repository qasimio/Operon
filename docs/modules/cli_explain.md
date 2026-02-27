# `cli/explain.py`

> Terminal explanation mode.

Commands:
  operon explain <symbol>               # explain a symbol
  operon explain <file>:<line>          # explain code at line
  operon explain flow <function>        # explain execution flow
  operon explain file <path>            # explain an entire file
  operon usages <symbol>                # show all usages
  operon rename <old> <new> [--apply]   # rename sym


## Overview

This file, `cli/explain.py`, is part of the Operon v5 software and provides a command-line interface for explaining various aspects of code, such as symbols, lines, execution flow, and files. It includes functions to find the repository root, retrieve a language model function, and load or build a symbol graph. The `cmd_explain` function is defined but incomplete, likely to handle the `explain` command.


## Stats

| Metric | Count |
|--------|-------|
| Lines | 457 |
| Functions | 15 |
| Classes | 0 |
| Variables | 81 |
| Imports | 25 |


## Imports

- `__future__:annotations`
- `os`
- `sys`
- `argparse`
- `pathlib:Path`
- `typing:List`
- `typing:Optional`
- `tools.ast_engine:explain_symbol`
- `ast`
- `tools.ast_engine:extract_chunk`
- `tools.ast_engine:find_all_usages`
- `tools.symbol_graph:symbols_in_file`
- `tools.symbol_graph:get_file_summary`
- `tools.ast_engine:find_all_usages`
- `tools.ast_engine:rename_symbol`
- `tools.symbol_graph:build_symbol_graph`
- `tools.doc_generator:generate_repo_docs`
- `tools.symbol_graph:build_symbol_graph`
- `tools.symbol_graph:symbols_in_file`
- `tools.ast_engine:summarize_block`


## Dependencies (imports)

- [`tools/ast_engine.py`](tools_ast_engine.md)
- [`tools/ast_engine.py`](tools_ast_engine.md)
- [`tools/ast_engine.py`](tools_ast_engine.md)
- [`tools/symbol_graph.py`](tools_symbol_graph.md)
- [`tools/symbol_graph.py`](tools_symbol_graph.md)
- [`tools/ast_engine.py`](tools_ast_engine.md)
- [`tools/ast_engine.py`](tools_ast_engine.md)
- [`tools/symbol_graph.py`](tools_symbol_graph.md)
- [`tools/doc_generator.py`](tools_doc_generator.md)
- [`tools/symbol_graph.py`](tools_symbol_graph.md)
- [`tools/symbol_graph.py`](tools_symbol_graph.md)
- [`tools/ast_engine.py`](tools_ast_engine.md)
- [`tools/ast_engine.py`](tools_ast_engine.md)
- [`tools/ast_engine.py`](tools_ast_engine.md)
- [`agent/llm.py`](agent_llm.md)


## Imported by

- [`main.py`](main.md)


## Functions


### `def _find_repo_root()`

- **Lines:** 25–32
- **Docstring:** Walk up from cwd to find the repo root (has .git or .operon).


### `def _get_llm()`

- **Lines:** 35–41
- **Docstring:** Return call_llm function or None if LLM not configured.


### `def _get_graph(repo_root: str)`

- **Lines:** 44–55
- **Docstring:** Load or build symbol graph.


### `def cmd_explain(args: argparse.Namespace)`

- **Lines:** 62–89


### `def _explain_symbol(repo_root: str, symbol: str, graph, llm)`

- **Lines:** 92–99


### `def _explain_at_line(repo_root: str, file_path: str, line: int, llm)`

- **Lines:** 102–136


### `def _explain_flow(repo_root: str, func_name: str, graph, llm)`

- **Lines:** 139–195
- **Docstring:** Trace the execution flow of a function.


### `def _explain_file(repo_root: str, file_path: str, graph, llm)`

- **Lines:** 198–230


### `def cmd_usages(args: argparse.Namespace)`

- **Lines:** 237–269


### `def cmd_rename(args: argparse.Namespace)`

- **Lines:** 276–299


### `def cmd_docs(args: argparse.Namespace)`

- **Lines:** 306–314


### `def cmd_summarize(args: argparse.Namespace)`

- **Lines:** 321–354


### `def cmd_signature(args: argparse.Namespace)`

- **Lines:** 361–384


### `def build_parser()`

- **Lines:** 391–430


### `def main(argv: Optional[List[str]])`

- **Lines:** 433–453
