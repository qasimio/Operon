# `agent/approval.py`

> Approval gate. ALWAYS fires before filesystem mutation.

Guarantees:
  - Never sends empty diffs  (validates before calling UI)
  - Always logs the decision with file + operation type
  - Timeout-safe: 300s max wait, then auto-rejects to prevent hang
  - Shows meaningful content even for large files (first/last 300 chars of diff)


## Overview

This file, `agent/approval.py`, serves as an approval gate for filesystem mutations in an application. It ensures that any write operation is validated and approved by the user before proceeding. The script checks for empty diffs, logs the decision, and handles both headless and TUI (Text User Interface) modes, displaying the diff for user review.


## Stats

| Metric | Count |
|--------|-------|
| Lines | 67 |
| Functions | 1 |
| Classes | 0 |
| Variables | 5 |
| Imports | 4 |


## Imports

- `__future__:annotations`
- `queue`
- `agent.logger`
- `agent.logger:log`


## Dependencies (imports)

- [`agent/logger.py`](agent_logger.md)


## Imported by

- [`agent/loop.py`](agent_loop.md)


## Functions


### `def ask_user_approval(action: str, payload: dict)`

- **Lines:** 19–67
- **Docstring:** Required before any filesystem write.

    payload must contain:
      "file"    — relative path
      "search"  — content being replaced (may be empty for create/append)
      "replace" — new content
