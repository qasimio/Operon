# `tools/diff_engine.py`


## Overview

This file contains a Python script for parsing and applying search-and-replace patches to text. It defines functions to parse search and replace blocks from a given text, find matching blocks in an original text, reindent the replacement block, and apply the patch, returning the patched text or a reason for no change.


## Stats

| Metric | Count |
|--------|-------|
| Lines | 139 |
| Functions | 8 |
| Classes | 0 |
| Variables | 44 |
| Imports | 5 |


## Imports

- `__future__:annotations`
- `re`
- `typing:Optional`
- `typing:Tuple`
- `typing:List`


## Imported by

- [`agent/loop.py`](agent_loop.md)
- [`agent/loop.py`](agent_loop.md)
- [`agent/loop.py`](agent_loop.md)
- [`agent/loop.py`](agent_loop.md)
- [`agent/loop.py`](agent_loop.md)


## Functions


### `def parse_search_replace(text: str)`

- **Lines:** 12–17


### `def _norm(lines: List[str])`

- **Lines:** 19–20


### `def _find_block(orig: List[str], snorm: List[str], tol: int)`

- **Lines:** 22–30


### `def _reindent(block: str, indent: int)`

- **Lines:** 32–49


### `def apply_patch(original_text: str, search_block: str, replace_block: str)`

- **Lines:** 51–105
- **Docstring:** Returns (patched | None, reason). reason: ok|noop|appended|no_match


### `def insert_import(original: str, import_line: str)`

- **Lines:** 108–122


### `def insert_above(original: str, target: str, new_line: str)`

- **Lines:** 125–135


### `def append_to_file(original: str, content: str)`

- **Lines:** 138–139


## Constants

- `_FENCE_PATTERNS` = `[re.compile('<{7}\\s*SEARCH\\r?\\n(.*?)\\r?\\n={7}\\r?\\n(.*?)\\r?\\n>{7}\\s*REP` (line 6)
