# `tools/diff_report.py`


## Overview

This file contains two functions, `dump_diff_report_from_json` and `dump_diff_report_from_repo`, which generate a human-readable diff report from JSON data. The `dump_diff_report_from_json` function reads a JSON file containing diff information and writes a formatted report to a specified output file. The `dump_diff_report_from_repo` function retrieves the diff JSON from a specific path within a repository and generates a report using the first function.


## Stats

| Metric | Count |
|--------|-------|
| Lines | 30 |
| Functions | 2 |
| Classes | 0 |
| Variables | 7 |
| Imports | 3 |


## Imports

- `pathlib:Path`
- `json`
- `datetime`


## Functions


### `def dump_diff_report_from_json(json_path, out_path)`

- **Lines:** 7–22


### `def dump_diff_report_from_repo(repo_root, out_path)`

- **Lines:** 25–30
