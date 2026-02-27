# `tools/fs_tools.py`


## Overview

This file provides functions for reading and writing files in a repository. The `read_file` function reads the content of a file and returns it as a dictionary with the file path, content, and length. The `write_file` function writes content to a file, either overwriting the existing content or appending to it, and returns a dictionary indicating success or failure along with the file path and mode used.


## Stats

| Metric | Count |
|--------|-------|
| Lines | 30 |
| Functions | 2 |
| Classes | 0 |
| Variables | 3 |
| Imports | 2 |


## Imports

- `pathlib:Path`
- `typing:Dict`


## Functions


### `def read_file(path: str, repo_root: str)`

- **Lines:** 6–12


### `def write_file(path: str, content: str, repo_root: str, mode: str)`

- **Lines:** 15–30
