# `tools/repo_search.py`


## Overview

This file defines a function `search_repo` that searches a repository for files containing a given query. It first attempts to use a semantic search function from `tools.semantic_memory`, but if that fails, it falls back to a simple text search using `grep`-like functionality. The search ignores files and directories containing `.git` or `.operon`.


## Stats

| Metric | Count |
|--------|-------|
| Lines | 23 |
| Functions | 1 |
| Classes | 0 |
| Variables | 4 |
| Imports | 4 |


## Imports

- `agent.logger:log`
- `tools.semantic_memory:search_memory`
- `os`
- `pathlib:Path`


## Dependencies (imports)

- [`agent/logger.py`](agent_logger.md)
- [`tools/semantic_memory.py`](tools_semantic_memory.md)


## Imported by

- [`agent/loop.py`](agent_loop.md)


## Functions


### `def search_repo(repo_root: str, query: str)`

- **Lines:** 4–23
