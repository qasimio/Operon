# `agent/validators.py`

> Deterministic step validation.

Rule 1: before == after → ALWAYS False (noop is never success).
Rule 2: For "delete lines X-Y" → count lines removed.
Rule 3: For "add import X" → check X is in after but not before.
Rule 4: For "update VAR = N" → check new value in after.
Rule 5: For "add comment ..." → check new comment line added.
Rule 6: Generic: any non-trivial diff → True.


## Overview

This file contains a module for validating code changes based on specific rules. It uses the `difflib` library to compare the before and after text of a file and applies various rules to determine if the changes meet the specified goals. The rules include checking for no-op changes, deleting lines, adding imports, updating variable values, adding comments, and handling generic non-trivial diffs.


## Stats

| Metric | Count |
|--------|-------|
| Lines | 99 |
| Functions | 3 |
| Classes | 0 |
| Variables | 16 |
| Imports | 4 |


## Imports

- `__future__:annotations`
- `difflib`
- `re`
- `typing:Optional`


## Imported by

- [`agent/loop.py`](agent_loop.md)


## Functions


### `def _removed(before: str, after: str)`

- **Lines:** 27–29


### `def _added(before: str, after: str)`

- **Lines:** 32–34


### `def validate_step(state, target_file: str, before_text: str, after_text: str)`

- **Lines:** 37–99
- **Docstring:** Returns True if step goal is satisfied, False otherwise.
    Never returns True on a noop.


## Constants

- `_STOPWORDS` = `{'delete', 'remove', 'add', 'the', 'from', 'in', 'all', 'lines', 'line', 'and', ` (line 19)
