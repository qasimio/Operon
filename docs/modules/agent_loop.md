# `agent/loop.py`

> Production agent loop. Root cause fixes:

ROOT CAUSE 1 — "rewrite called but file unchanged":
  The LLM inside _rewrite_function is asked to produce SEARCH/REPLACE blocks.
  Small models (Qwen 7B) often produce blocks that don't match the file because:
    a) They reconstruct from memory instead of copying verbatim.
    b) The prompt didn't include full file content.
  FIX: Prompt includes full fi


## Overview

The `agent/loop.py` file is part of the Operon v4 system, which manages the production agent loop. It includes fixes for issues related to file changes, reviewer hallucinations, approval bypasses, and model switching crashes. The file imports various modules and functions to handle logging, calling the language model, deciding the next action, making plans, and validating steps.


## Stats

| Metric | Count |
|--------|-------|
| Lines | 983 |
| Functions | 9 |
| Classes | 0 |
| Variables | 126 |
| Imports | 28 |


## Imports

- `__future__:annotations`
- `difflib`
- `json`
- `os`
- `re`
- `time`
- `pathlib:Path`
- `typing:Any`
- `agent.logger:log`
- `agent.llm:call_llm`
- `agent.decide:decide_next_action`
- `agent.planner:make_plan`
- `agent.validators:validate_step`
- `tools.diff_engine:parse_search_replace`
- `tools.diff_engine:apply_patch`
- `tools.diff_engine:insert_import`
- `tools.diff_engine:insert_above`
- `tools.diff_engine:append_to_file`
- `tools.git_safety:setup_git_env`
- `tools.git_safety:rollback_files`


## Dependencies (imports)

- [`agent/logger.py`](agent_logger.md)
- [`agent/llm.py`](agent_llm.md)
- [`agent/decide.py`](agent_decide.md)
- [`agent/planner.py`](agent_planner.md)
- [`agent/validators.py`](agent_validators.md)
- [`tools/diff_engine.py`](tools_diff_engine.md)
- [`tools/diff_engine.py`](tools_diff_engine.md)
- [`tools/diff_engine.py`](tools_diff_engine.md)
- [`tools/diff_engine.py`](tools_diff_engine.md)
- [`tools/diff_engine.py`](tools_diff_engine.md)
- [`tools/git_safety.py`](tools_git_safety.md)
- [`tools/git_safety.py`](tools_git_safety.md)
- [`tools/git_safety.py`](tools_git_safety.md)
- [`tools/path_resolver.py`](tools_path_resolver.md)
- [`tools/path_resolver.py`](tools_path_resolver.md)


## Imported by

- [`tui/app.py`](tui_app.md)


## Functions


### `def _ensure(state)`

- **Lines:** 64–94


### `def _norm(act: str, p: dict)`

- **Lines:** 99–117


### `def _canon(payload: dict)`

- **Lines:** 120–124


### `def _is_noop_action(act: str, p: dict)`

- **Lines:** 127–134


### `def _approve(action: str, payload: dict, summary: str)`

- **Lines:** 139–154


### `def _persist_diff(state)`

- **Lines:** 159–172


### `def _crud_fast_path(goal: str, original: str)`

- **Lines:** 177–277
- **Docstring:** Detect and apply structured CRUD intent deterministically.
    Returns (new_content | None, description).
    None means "not a CRUD pattern — use LLM".


### `def _rewrite_function(state, file_path: str)`

- **Lines:** 282–482
- **Docstring:** Returns:
      {"success": True,  "file": path, "noop": False} — change applied
      {"success": True,  "file": path, "noop": True}  — no change
      {"success": False, "error": "..."}              


### `def run_agent(state)`

- **Lines:** 487–983


## Constants

- `MAX_STEPS` = `35` (line 57)
- `NOOP_STREAK_MAX` = `2` (line 58)
- `REJECT_THRESHOLD` = `3` (line 59)
