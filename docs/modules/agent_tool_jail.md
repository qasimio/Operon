# `agent/tool_jail.py`

> Tool permission enforcement + model-switch support.


## Overview

This file defines a system for enforcing tool permissions and managing tool usage based on the current phase (either "CODER" or "REVIEWER"). It includes a dictionary of required parameters for each tool and a function `validate_tool` that checks if a given tool action is allowed in the current phase and if all required parameters are provided. Additionally, it includes logic to throttle repeated search actions to prevent abuse.


## Stats

| Metric | Count |
|--------|-------|
| Lines | 70 |
| Functions | 1 |
| Classes | 0 |
| Variables | 10 |
| Imports | 0 |


## Imported by

- [`agent/loop.py`](agent_loop.md)


## Functions


### `def validate_tool(action: str, payload: dict, phase: str, state)`

- **Lines:** 28–70
- **Docstring:** Returns (is_valid, reason_string).


## Constants

- `CODER_TOOLS` = `{'find_file', 'read_file', 'semantic_search', 'exact_search', 'rewrite_function'` (line 6)
- `REVIEWER_TOOLS` = `{'approve_step', 'reject_step', 'finish'}` (line 10)
- `_PHASE_TOOLS` = `{'CODER': CODER_TOOLS, 'REVIEWER': REVIEWER_TOOLS}` (line 12)
- `_REQUIRED` = `{'read_file': ['path'], 'rewrite_function': ['file'], 'create_file': ['file_path` (line 14)
