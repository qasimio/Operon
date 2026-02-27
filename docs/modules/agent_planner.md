# `agent/planner.py`

> ARCHITECT planner. Produces tight, executable plans.

KEY FIXES:
  - No 'Locate X' / 'Find Y' steps — pure write milestones only.
  - Each step names the TARGET file explicitly when known.
  - Validator attached to each step so REVIEWER has ground truth.


## Overview

The `agent/planner.py` file is part of the Operon v3.2 system, specifically the ARCHITECT planner. It generates tight, executable coding plans for a given goal, ensuring that each step is a single atomic write to a specific file, and avoids using terms like "locate" or "find." The planner outputs the plan in strict JSON format, including steps, validators, and multi-file actions.


## Stats

| Metric | Count |
|--------|-------|
| Lines | 92 |
| Functions | 1 |
| Classes | 0 |
| Variables | 12 |
| Imports | 5 |


## Imports

- `__future__:annotations`
- `json`
- `re`
- `agent.llm:call_llm`
- `agent.logger:log`


## Dependencies (imports)

- [`agent/llm.py`](agent_llm.md)
- [`agent/logger.py`](agent_logger.md)


## Imported by

- [`agent/loop.py`](agent_loop.md)


## Functions


### `def make_plan(goal: str, repo_root: str, state)`

- **Lines:** 19–92
- **Docstring:** Returns (steps, is_question, validators).
