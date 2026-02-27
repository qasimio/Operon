# `agent/decide.py`

> REVIEWER is deterministic-first.
  - Reads file from DISK, not cache.
  - Checks diff_memory hash to confirm change happened before calling LLM.
  - LLM sees actual current file content for goal-satisfaction check.
CODER gets full file preview for verbatim SEARCH block copying.


## Overview

The `decide.py` file in the `agent` directory is part of the Operon v4 system, which is designed to determine the next action for an AI agent based on the state of the repository and the files that have been modified. The file includes functions to read files from disk, review changes using a deterministic approach, and decide whether to reject a change or ask a language model (LLM) for further evaluation. The `_reviewer_deterministic` function checks if any files have been modified and compares their current content with a previous snapshot to determine if the change is significant. If the change is significant, it asks the LLM for approval; otherwise, it rejects the change.


## Stats

| Metric | Count |
|--------|-------|
| Lines | 237 |
| Functions | 3 |
| Classes | 0 |
| Variables | 41 |
| Imports | 8 |


## Imports

- `__future__:annotations`
- `json`
- `re`
- `pathlib:Path`
- `agent.llm:call_llm`
- `agent.logger:log`
- `tools.path_resolver:resolve_path`
- `tools.repo_index:get_context_for_query`


## Dependencies (imports)

- [`agent/llm.py`](agent_llm.md)
- [`agent/logger.py`](agent_logger.md)
- [`tools/path_resolver.py`](tools_path_resolver.md)
- [`tools/repo_index.py`](tools_repo_index.md)


## Imported by

- [`agent/loop.py`](agent_loop.md)


## Functions


### `def _read_disk(state, file_path: str)`

- **Lines:** 19–31


### `def _reviewer_deterministic(state)`

- **Lines:** 34–60
- **Docstring:** Returns (decision, detail).
    decision: "reject" | "ask_llm"
    detail:   reason string | file_path for evidence


### `def decide_next_action(state)`

- **Lines:** 63–237
