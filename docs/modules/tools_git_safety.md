# `tools/git_safety.py`

> BUG FIX: Old code called `git reset --hard` + `git clean -fd` which nuked ALL
uncommitted user changes, not just Operon's changes.

v3 solution:
  - At startup, stash any existing user changes (git stash).
  - Track only the files Operon touches.
  - On rollback, restore only those files to HEAD, then re-apply the stash.
  - User's pre-existing uncommitted work is always preserved.


## Overview

This file, `tools/git_safety.py`, is designed to enhance the safety of Git operations, particularly when using an AI tool like Operon. It ensures that any uncommitted changes made by the user are preserved during the AI's operations. The script stashes user changes, tracks only the files the AI modifies, and restores only those files on rollback, thus safeguarding the user's work.


## Stats

| Metric | Count |
|--------|-------|
| Lines | 143 |
| Functions | 5 |
| Classes | 0 |
| Variables | 20 |
| Imports | 4 |


## Imports

- `subprocess`
- `uuid`
- `pathlib:Path`
- `agent.logger:log`


## Dependencies (imports)

- [`agent/logger.py`](agent_logger.md)


## Imported by

- [`agent/loop.py`](agent_loop.md)
- [`agent/loop.py`](agent_loop.md)
- [`agent/loop.py`](agent_loop.md)


## Functions


### `def run_git(cmd: list[str], repo_root: str, check: bool)`

- **Lines:** 19–31


### `def _is_git_repo(repo_root: str)`

- **Lines:** 34–35


### `def setup_git_env(repo_root: str)`

- **Lines:** 38–81
- **Docstring:** 1. Check it's a git repo.
    2. Stash any pre-existing uncommitted user changes (with a unique stash message).
    3. If on main/master, create a new operon branch.
    4. Record initial commit so we


### `def rollback_files(repo_root: str, git_state: dict, files_modified: list[str])`

- **Lines:** 84–130
- **Docstring:** SURGICAL rollback — only restore the specific files Operon touched.
    Never touches files the user had already modified before Operon ran.
    Then re-applies the user's stash.


### `def commit_success(repo_root: str, message: str)`

- **Lines:** 133–143
