# `agent/llm.py`

> Universal LLM router: local / OpenAI / Anthropic / OpenRouter / Deepseek / Groq / Together / Azure.

KEY FIX vs v3.1:
  - PROMPT_CHAR_CAP removed from rewrite prompts — the file content is NEVER
    trimmed when it's passed for editing. Trimming caused the LLM to never
    see the target line and generate empty/noop SEARCH/REPLACE blocks.
  - Trimming only applies to context/history sections, not 


## Overview

This file, `agent/llm.py`, is part of the Operon v3.2 software, which serves as a universal language model (LLM) router. It supports various LLM providers including local, OpenAI, Anthropic, OpenRouter, Deepseek, Groq, Together, and Azure. The file includes configuration settings for these providers and handles model switching dynamically, allowing for hot-reloading without needing a restart. The configuration is managed through a JSON file located at `.operon/llm_config.json`.


## Stats

| Metric | Count |
|--------|-------|
| Lines | 223 |
| Functions | 9 |
| Classes | 0 |
| Variables | 36 |
| Imports | 9 |


## Imports

- `__future__:annotations`
- `json`
- `os`
- `re`
- `time`
- `pathlib:Path`
- `typing:Optional`
- `requests`
- `agent.logger:log`


## Dependencies (imports)

- [`agent/logger.py`](agent_logger.md)


## Imported by

- [`agent/decide.py`](agent_decide.md)
- [`agent/loop.py`](agent_loop.md)
- [`agent/planner.py`](agent_planner.md)
- [`cli/explain.py`](cli_explain.md)
- [`tools/build_brain.py`](tools_build_brain.md)
- [`tui/app.py`](tui_app.md)
- [`tui/app.py`](tui_app.md)
- [`tui/app.py`](tui_app.md)
- [`tui/app.py`](tui_app.md)
- [`tui/app.py`](tui_app.md)


## Functions


### `def _cfg_path()`

- **Lines:** 67–68


### `def _load_config()`

- **Lines:** 71–88


### `def save_config(cfg: dict)`

- **Lines:** 91–96
- **Docstring:** Write config. Takes effect on next call_llm() call without restart.


### `def _strip_fences(text: str)`

- **Lines:** 101–109


### `def extract_json(raw: str)`

- **Lines:** 112–115


### `def _openai_compat(cfg: dict, messages: list, require_json: bool)`

- **Lines:** 120–153


### `def _anthropic(cfg: dict, messages: list)`

- **Lines:** 156–175


### `def call_llm(prompt: str, require_json: bool, retries: Optional[int])`

- **Lines:** 180–214
- **Docstring:** Call the configured LLM. Hot-reloads config on every call.
    Never truncates the prompt (caller is responsible for sizing).


### `def get_model_info()`

- **Lines:** 217–223


## Constants

- `_DEFAULT_CFG` = `{'provider': 'local', 'model': 'local', 'api_key': '', 'base_url': 'http://127.0` (line 29)
- `SYSTEM_PROMPT` = `'You are Operon, an elite autonomous AI software engineer. You reason step by st` (line 53)
- `_CONTEXT_CAP` = `2000` (line 62)
