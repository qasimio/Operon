# `tools/semantic_memory.py`


## Overview

This file, `tools/semantic_memory.py`, is part of a system designed to create a semantic memory for a repository. It initializes an ONNX embedding model, defines a function to get the database path, and includes a function to index the repository by scanning files, hashing their contents, and updating a vector database with embeddings. The system aims to provide a way to store and retrieve semantic information about the code and text files in a repository, which can be used for various purposes such as code search, retrieval, and analysis.


## Stats

| Metric | Count |
|--------|-------|
| Lines | 113 |
| Functions | 4 |
| Classes | 0 |
| Variables | 26 |
| Imports | 8 |


## Imports

- `os`
- `hashlib`
- `pathlib:Path`
- `lancedb`
- `pyarrow`
- `fastembed:TextEmbedding`
- `tools.universal_parser:extract_symbols`
- `agent.logger:log`


## Dependencies (imports)

- [`tools/universal_parser.py`](tools_universal_parser.md)
- [`agent/logger.py`](agent_logger.md)


## Imported by

- [`tools/repo_search.py`](tools_repo_search.md)
- [`tui/app.py`](tui_app.md)


## Functions


### `def get_db_path(repo_root: str)`

- **Lines:** 14–17


### `def _hash_file(file_path: Path)`

- **Lines:** 19–23
- **Docstring:** Returns MD5 hash of a file to detect changes.


### `def index_repo(repo_root: str)`

- **Lines:** 25–91
- **Docstring:** Scans the repo, hashes files, and updates the vector database.


### `def search_memory(repo_root: str, query: str, top_k: int)`

- **Lines:** 93–113
- **Docstring:** Performs a semantic vector search across the codebase.
