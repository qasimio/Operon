# `tools/path_resolver.py`

> Resolves any user-supplied filename to an actual repo path.
This is the fix for: "can not figure out file if it is inside folder."

5-tier search (same logic as your working loop.py's resolve_repo_path,
but extended):
  1. Exact relative path
  2. Case-insensitive exact match
  3. Recursive filename match  (all extensions, shortest path wins)
  4. Fuzzy basename stem match  (e.g. "semantic" → "too


## Overview

This file, `tools/path_resolver.py`, is part of Operon v3.1 and is designed to resolve user-supplied filenames to actual repository paths. It implements a 5-tier search logic to handle various cases, including exact relative paths, case-insensitive matches, recursive filename matches, fuzzy basename stem matches, and symbol index lookups if a state is provided. The function `resolve_path` returns the resolved relative path and a boolean indicating whether the file was found.


## Stats

| Metric | Count |
|--------|-------|
| Lines | 85 |
| Functions | 3 |
| Classes | 0 |
| Variables | 12 |
| Imports | 4 |


## Imports

- `__future__:annotations`
- `pathlib:Path`
- `typing:Optional`
- `typing:Tuple`


## Imported by

- [`agent/decide.py`](agent_decide.md)
- [`agent/loop.py`](agent_loop.md)
- [`agent/loop.py`](agent_loop.md)


## Functions


### `def _all_files(repo_root: str)`

- **Lines:** 22–26


### `def resolve_path(user_path: str, repo_root: str, state)`

- **Lines:** 29–71
- **Docstring:** Returns (resolved_relative_path, found: bool).
    If not found, returns (user_path, False) so callers can create it.


### `def read_resolved(user_path: str, repo_root: str, state)`

- **Lines:** 74–85
- **Docstring:** Returns (resolved_path, content, success).


## Constants

- `IGNORE_DIRS` = `{'.git', '.venv', '__pycache__', 'node_modules', 'dist', 'build', '.operon'}` (line 19)
