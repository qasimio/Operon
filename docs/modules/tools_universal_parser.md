# `tools/universal_parser.py`

> Full AST-based symbol extraction + syntax checking.

Supports:
  Python  — uses ast stdlib (zero dependencies)
  JS/TS   — regex fallback with heuristic accuracy
  Java    — regex fallback
  Other   — best-effort regex

extract_symbols() returns:
  {
    "functions":  [{name, start, end, args, docstring, decorators, is_async}],
    "classes":    [{name, start, end, bases, methods, docstring}],
   


## Overview

The `tools/universal_parser.py` file provides a universal parser for extracting symbols and performing syntax checking across multiple programming languages, including Python, JavaScript/TypeScript, Java, and others. It uses the Python `ast` module for Python code and falls back to regex for other languages. The parser can extract information such as functions, classes, variables, imports, and more, and it includes a syntax check function to validate the code.


## Stats

| Metric | Count |
|--------|-------|
| Lines | 360 |
| Functions | 14 |
| Classes | 0 |
| Variables | 38 |
| Imports | 10 |


## Imports

- `__future__:annotations`
- `ast`
- `re`
- `tokenize`
- `io`
- `pathlib:Path`
- `typing:Any`
- `typing:Dict`
- `typing:List`
- `typing:Optional`


## Imported by

- [`agent/loop.py`](agent_loop.md)
- [`tools/ast_engine.py`](tools_ast_engine.md)
- [`tools/function_locator.py`](tools_function_locator.md)
- [`tools/repo_brain.py`](tools_repo_brain.md)
- [`tools/repo_index.py`](tools_repo_index.md)
- [`tools/semantic_memory.py`](tools_semantic_memory.md)
- [`tools/symbol_graph.py`](tools_symbol_graph.md)


## Functions


### `def check_syntax(code: str, file_path: str)`

- **Lines:** 37–53
- **Docstring:** Returns True if code appears syntactically valid.


### `def _ast_extract_python(source: str)`

- **Lines:** 60–217


### `def _extract_comments_python(source: str)`

- **Lines:** 220–232


### `def _regex_extract_js(source: str)`

- **Lines:** 239–276


### `def _regex_extract_java(source: str)`

- **Lines:** 283–311


### `def extract_symbols(content: str, file_path: str, include_comments: bool)`

- **Lines:** 318–352
- **Docstring:** Extract all symbols from source code.

    Returns dict with keys:
      functions, classes, variables, imports, assignments, decorators,
      annotations, comments


### `def get_block_source(content: str, start_line: int, end_line: int)`

- **Lines:** 355–360
- **Docstring:** Extract lines [start_line..end_line] (1-based, inclusive).


### `def _get_end_line(node)`

- **Lines:** 73–77


### `def _docstring(node)`

- **Lines:** 79–84


### `def _args_list(args_node)`

- **Lines:** 86–101


### `def _decorator_names(node)`

- **Lines:** 103–110


### `def _value_repr(node)`

- **Lines:** 112–116


### `def lineno_at(pos: int)`

- **Lines:** 247–248


### `def lineno_at(pos: int)`

- **Lines:** 290–291
