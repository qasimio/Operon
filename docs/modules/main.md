# `main.py`

> Entry point.

  python main.py              → launch TUI
  python main.py explain <X>  → explain symbol X
  python main.py rename <old> <new> [--apply]
  python main.py usages <X>
  python main.py docs [--no-llm]
  python main.py summarize <file>
  python main.py signature <func> <params> [--apply]


## Overview

This file serves as the entry point for the application, providing various commands such as 'explain', 'rename', 'usages', 'docs', 'summarize', and 'signature'. Each command is handled by a specific function defined in the file.


## Stats

| Metric | Count |
|--------|-------|
| Lines | 47 |
| Functions | 1 |
| Classes | 0 |
| Variables | 1 |
| Imports | 3 |


## Imports

- `sys`
- `cli.explain:main`
- `tui.app:OperonUI`


## Dependencies (imports)

- [`cli/explain.py`](cli_explain.md)
- [`tui/app.py`](tui_app.md)


## Functions


### `def _is_cli_command(argv: list)`

- **Lines:** 16–18


## Constants

- `CLI_COMMANDS` = `{'explain', 'usages', 'rename', 'docs', 'summarize', 'signature'}` (line 17)
