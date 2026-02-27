# `agent/repo.py`


## Overview

This Python script defines a function `build_repo_summary` that takes a repository root directory and an optional maximum number of files to list. It recursively searches the repository for files, excluding those in the `.git` directory, and returns a list of file paths relative to the repository root, up to the specified maximum number of files.


## Stats

| Metric | Count |
|--------|-------|
| Lines | 16 |
| Functions | 1 |
| Classes | 0 |
| Variables | 3 |
| Imports | 1 |


## Imports

- `pathlib:Path`


## Functions


### `def build_repo_summary(repo_root: str, max_files: int)`

- **Lines:** 3–16
