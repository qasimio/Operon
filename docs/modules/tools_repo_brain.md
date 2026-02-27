# `tools/repo_brain.py`


## Overview

This file, `repo_brain.py`, is designed to analyze a repository by building a tree of its files and extracting information about the files, such as their structure, functions, classes, and imports. It uses a universal parser to extract symbols from the files and then calls an LLM (Large Language Model) to generate a summary of each file in plain English. The results are stored in JSON files named `repo_tree.json` and `repo_files.json`.


## Stats

| Metric | Count |
|--------|-------|
| Lines | 116 |
| Functions | 3 |
| Classes | 0 |
| Variables | 17 |
| Imports | 4 |


## Imports

- `pathlib:Path`
- `json`
- `re`
- `tools.universal_parser:extract_symbols`


## Dependencies (imports)

- [`tools/universal_parser.py`](tools_universal_parser.md)


## Imported by

- [`tools/build_brain.py`](tools_build_brain.md)


## Functions


### `def build_tree(repo)`

- **Lines:** 12–21


### `def extract_imports_regex(text)`

- **Lines:** 24–34
- **Docstring:** Cheap universal-ish import detection.


### `def build_repo_brain(repo_root, call_llm)`

- **Lines:** 37–116
- **Docstring:** Walk repo, build repo_tree.json + repo_files.json
    Uses Universal Parser for structure.


## Constants

- `IGNORE` = `{'.git', '.venv', '__pycache__', 'node_modules', 'dist', 'build'}` (line 7)
- `TEXT` = `{'.py', '.md', '.txt', '.json', '.yaml', '.yml', '.toml', '.cfg', '.ini', '.java` (line 9)
