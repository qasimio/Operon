# `tui/app.py`


## Overview

This file, `tui/app.py`, is part of an application that provides a text user interface (TUI) for interacting with an agent. It imports various modules and classes from the `textual` and `rich` libraries to create a user interface for configuring and running an agent. The file includes a list of providers for language models and default settings for each provider.


## Stats

| Metric | Count |
|--------|-------|
| Lines | 456 |
| Functions | 29 |
| Classes | 3 |
| Variables | 34 |
| Imports | 36 |


## Imports

- `__future__:annotations`
- `json`
- `os`
- `pathlib:Path`
- `typing:cast`
- `textual.app:App`
- `textual.app:ComposeResult`
- `textual.containers:Horizontal`
- `textual.containers:Vertical`
- `textual.containers:ScrollableContainer`
- `textual.containers:Grid`
- `textual.widgets:Header`
- `textual.widgets:Footer`
- `textual.widgets:RichLog`
- `textual.widgets:Input`
- `textual.widgets:Static`
- `textual.widgets:Button`
- `textual.widgets:Select`
- `textual.widgets:Label`
- `textual.widgets:Switch`


## Dependencies (imports)

- [`runtime/state.py`](runtime_state.md)
- [`agent/loop.py`](agent_loop.md)
- [`agent/llm.py`](agent_llm.md)
- [`agent/llm.py`](agent_llm.md)
- [`agent/llm.py`](agent_llm.md)
- [`agent/llm.py`](agent_llm.md)
- [`tools/semantic_memory.py`](tools_semantic_memory.md)
- [`tools/repo_index.py`](tools_repo_index.md)
- [`agent/llm.py`](agent_llm.md)


## Imported by

- [`main.py`](main.md)


## Classes


### `class LLMSettingsPanel(Vertical)`

- **Lines:** 67–181
- **Docstring:** Full-screen settings panel for provider / model / API key.
- **Methods:** `compose`, `on_mount`, `_load_current`, `_update_guide`, `on_select_changed`, `_set_status`, `on_button_pressed`, `_do_save`, `_test_connection`
- **Inherits:** `Vertical`

**Summary:** The `LLMSettingsPanel` class is a vertical layout for configuring language model settings, including provider, model, and API key, with a title and input fields for each setting.


### `class DiffApproval(Vertical)`

- **Lines:** 188–226
- **Methods:** `__init__`, `compose`, `on_mount`, `on_button_pressed`
- **Inherits:** `Vertical`

**Summary:** DiffApproval is a class that extends Vertical, initializes with a filename, search string, and replace string, and composes a UI with a title, scrollable area for displaying differences, and buttons for approving or rejecting changes.


### `class OperonUI(App)`

- **Lines:** 233–456
- **Methods:** `compose`, `on_mount`, `_bg_index`, `_refresh_model_bar`, `_set_status`, `action_settings`, `_open_settings`, `_close_settings`, `on_key`, `on_input_submitted`
- **Inherits:** `App`

**Summary:** OperonUI is a class that extends App and defines a user interface with specific CSS styles for various components such as chat pane, workspace pane, rich log, input, status bar, and model bar.


## Functions


### `def compose(self)`

- **Lines:** 70–97


### `def on_mount(self)`

- **Lines:** 99–100


### `def _load_current(self)`

- **Lines:** 102–115


### `def _update_guide(self, provider: str)`

- **Lines:** 117–121


### `def on_select_changed(self, event: Select.Changed)`

- **Lines:** 123–130


### `def _set_status(self, msg: str)`

- **Lines:** 132–133


### `def on_button_pressed(self, event: Button.Pressed)`

- **Lines:** 135–147


### `def _do_save(self)`

- **Lines:** 149–167


### `def _test_connection(self)`

- **Lines:** 169–181


### `def __init__(self, filename: str, search: str, replace: str, **kw)`

- **Lines:** 189–193


### `def compose(self)`

- **Lines:** 195–202


### `def on_mount(self)`

- **Lines:** 204–222


### `def on_button_pressed(self, event: Button.Pressed)`

- **Lines:** 224–226


### `def compose(self)`

- **Lines:** 267–284


### `def on_mount(self)`

- **Lines:** 288–298


### `def _bg_index(self)`

- **Lines:** 300–314


### `def _refresh_model_bar(self)`

- **Lines:** 316–327


### `def _set_status(self, text: str)`

- **Lines:** 329–332


### `def action_settings(self)`

- **Lines:** 336–337


### `def _open_settings(self)`

- **Lines:** 339–344


### `def _close_settings(self)`

- **Lines:** 346–357


### `def on_key(self, event: Key)`

- **Lines:** 361–368


### `def on_input_submitted(self, event: Input.Submitted)`

- **Lines:** 372–407


### `def _run(self, goal: str)`

- **Lines:** 411–425


### `def _log(self, msg: str)`

- **Lines:** 429–430


### `def safe_log(self, msg: str)`

- **Lines:** 432–433


### `def safe_diff(self, filename: str, search: str, replace: str)`

- **Lines:** 435–436


### `def _show_diff(self, filename: str, search: str, replace: str)`

- **Lines:** 438–443


### `def resolve_approval(self, approved: bool)`

- **Lines:** 445–456


## Constants

- `PROVIDERS` = `[('Local (llama.cpp / Ollama / LM Studio)', 'local'), ('OpenAI  (gpt-4o, o1, o3…` (line 30)
- `PROVIDER_DEFAULTS` = `{'local': {'base_url': 'http://127.0.0.1:8080/v1', 'model': 'local', 'needs_key'` (line 42)
- `PROVIDER_GUIDE` = `{'local': 'Point llama-server to --port 8080. No API key needed.', 'openai': 'Ge` (line 54)
- `CSS` = `'\n    Screen { background: $surface; }\n\n    #chat-pane      { width: 48%; bor` (line 235)
- `BINDINGS` = `[('ctrl+c', 'quit', 'Quit'), ('ctrl+s', 'settings', 'LLM Settings')]` (line 262)
