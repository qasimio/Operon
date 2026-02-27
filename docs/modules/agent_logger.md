# `agent/logger.py`


## Overview

This file sets up a logging system for the Operon application. It defines a `TUILogHandler` that sends log messages to a user interface callback function if available, or falls back to standard error if the UI is not running. The `setup_logger` function configures a logger that writes to both a file and the UI, with different formats for each output.


## Stats

| Metric | Count |
|--------|-------|
| Lines | 61 |
| Functions | 3 |
| Classes | 1 |
| Variables | 9 |
| Imports | 3 |


## Imports

- `logging`
- `sys`
- `queue`


## Imported by

- [`agent/approval.py`](agent_approval.md)
- [`agent/decide.py`](agent_decide.md)
- [`agent/llm.py`](agent_llm.md)
- [`agent/loop.py`](agent_loop.md)
- [`agent/planner.py`](agent_planner.md)
- [`tools/ast_engine.py`](tools_ast_engine.md)
- [`tools/chunked_loader.py`](tools_chunked_loader.md)
- [`tools/doc_generator.py`](tools_doc_generator.md)
- [`tools/git_safety.py`](tools_git_safety.md)
- [`tools/repo_index.py`](tools_repo_index.md)


## Classes


### `class TUILogHandler(logging.Handler)`

- **Lines:** 34–37
- **Methods:** `emit`
- **Inherits:** `logging.Handler`

**Summary:** TUILogHandler is a logging handler that formats log records and passes them to a UI callback for display.


## Functions


### `def _safe_ui_callback(msg: str)`

- **Lines:** 12–31
- **Docstring:** Call UI_CALLBACK safely — never crash when TUI has shut down.


### `def setup_logger(log_file: str)`

- **Lines:** 40–58


### `def emit(self, record: logging.LogRecord)`

- **Lines:** 35–37


## Constants

- `UI_CALLBACK` = `None` (line 7)
- `UI_SHOW_DIFF` = `None` (line 8)
- `APPROVAL_QUEUE` = `queue.Queue()` (line 9)
