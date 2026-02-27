# `tools/function_locator.py`


## Overview

This file, `tools/function_locator.py`, is part of the Operon v3 software. It defines a function `find_function` that searches a repository for a specified function or class by name. The function returns the relative path to the file containing the function or class, along with the start and end positions of the function or class within the file. It ignores certain directories and file types during the search.


## Stats

| Metric | Count |
|--------|-------|
| Lines | 32 |
| Functions | 1 |
| Classes | 0 |
| Variables | 4 |
| Imports | 3 |


## Imports

- `pathlib:Path`
- `json`
- `tools.universal_parser:extract_symbols`


## Dependencies (imports)

- [`tools/universal_parser.py`](tools_universal_parser.md)


## Imported by

- [`tools/code_slice.py`](tools_code_slice.md)


## Functions


### `def find_function(repo_root: str, func_name: str)`

- **Lines:** 9–32
- **Docstring:** Search the repo for a function or class by name.
    Returns {"file": rel_path, "start": int, "end": int} or None.


## Constants

- `IGNORE` = `{'.git', '.venv', '__pycache__', 'node_modules', 'dist', 'build', '.operon'}` (line 6)
