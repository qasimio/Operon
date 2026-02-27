# Contributing to Operon

Thank you for your interest in contributing. This document covers the contribution workflow, architecture conventions, and areas where help is most needed.

---

## Before You Start

- Search [existing issues](https://github.com/qasimio/Operon/issues) before opening a new one
- For significant changes, open an issue first to discuss approach
- All contributions are subject to the [Code of Conduct](CODE_OF_CONDUCT.md)

---

## Development Setup

```bash
git clone https://github.com/qasimio/Operon.git
cd Operon
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt   # if it exists, else: pip install pytest black ruff
```

Verify your environment:
```bash
python -m py_compile agent/loop.py tools/ast_engine.py tools/symbol_graph.py
python -c "from tools.universal_parser import extract_symbols; print('OK')"
```

---

## Project Layout

The codebase has three distinct layers. Changes should stay within their layer unless the change is intentionally cross-cutting.

| Layer | Location | Responsibility |
|-------|----------|----------------|
| **Agent** | `agent/` | LLM dispatch, planning, phase machine, approval |
| **Intelligence** | `tools/` | Symbol graph, AST engine, chunked loading, docs |
| **Presentation** | `tui/`, `cli/` | TUI (Textual), CLI commands |

The `runtime/state.py` `AgentState` dataclass is the single source of truth for all in-flight agent data. Add fields here, not as ad-hoc attributes.

---

## Workflow

1. **Fork** the repository and create a branch from `main`:
   ```bash
   git checkout -b feat/your-feature-name
   # or
   git checkout -b fix/issue-123
   ```

2. **Make your changes.** Follow the conventions below.

3. **Test manually** against a real repository. The agent loop is harder to unit-test in isolation than the intelligence layer — prioritise integration testing.

4. **Lint:**
   ```bash
   black .
   ruff check .
   ```

5. **Open a pull request** against `main`. Fill in the PR template.

---

## Code Conventions

### Python style
- Black-formatted, line length 100
- Type annotations on all public functions
- Docstrings on public functions — one-line summary + parameter notes for complex functions
- No `print()` in library code — use `from agent.logger import log`

### Error handling
- Agent-layer errors: use `log.error(...)` and propagate via `state.errors`
- Tool-layer errors: return `(None, "reason string")` or `{"success": False, "error": "..."}` tuples — never raise from tool functions

### AST / tokenize
- Python symbol work must use `ast` or `tokenize`, not regex on source
- Regex is acceptable as a fallback for non-Python files only
- Document clearly when a function falls back to regex

### LLM calls
- All LLM calls go through `agent/llm.py:call_llm()`
- Never call `requests` directly from tool or agent code
- Prompts that include file content must never truncate that content (see `llm.py` docstring)

### State mutations
- Only `agent/loop.py` mutates `AgentState` during a run
- Intelligence tools (`tools/`) are pure functions or read-only on state
- Write to `state.diff_memory` whenever a file is patched

### Approval gate
- Every code path that writes to disk must call `_approve()` (or `ask_user_approval()` directly)
- Never bypass approval under any condition, including test mode

---

## Good First Issues

These require no deep knowledge of the agent loop:

- **`--json` output for CLI commands** — add `--json` flag to `explain`, `usages`, `rename` that outputs structured JSON instead of formatted text. Useful for editor integrations.

- **Test suite for `diff_engine`** — `tools/diff_engine.py` has 5-tier matching logic that needs edge case coverage: Unicode content, Windows line endings, trailing whitespace variants.

- **`operon diff` command** — show all uncommitted Operon-made changes across the repo (read from `diff_memory` persisted in `.operon/last_diff.json`).

- **Improve `--no-llm` docs quality** — when `--no-llm` is used in `summarize` and `docs`, the structural fallback descriptions are minimal. Improve them using heuristics from the AST (e.g. infer purpose from function name patterns, parameter names, return type annotations).

- **`tools/universal_parser.py` — JS/TS method extraction** — currently misses class methods inside `class Foo {}` blocks. Improve the regex to detect method definitions inside class bodies.

---

## Advanced Contribution Areas

### JS/TS AST integration
The current JS/TS extraction is regex-based. A proper integration would use one of:
- `py_mini_racer` + Babel parser (single-file approach)
- `node` subprocess with a small Babel script
- `ts-morph` via subprocess for TypeScript

Target: `tools/universal_parser.py` `_regex_extract_js()` → replace with AST extraction. The output schema must match the Python extractor exactly so `symbol_graph.py` works uniformly.

### LSP server mode
Expose Operon's symbol graph as a Language Server Protocol server so editors can query it directly. `pylsp` or a raw `asyncio` implementation.

Entry point: new `cli/lsp.py` + `main.py` dispatch.

### Symbol graph visualizer
Generate an interactive HTML graph from `.operon/symbol_graph.json` using D3 or similar. Could be a standalone `tools/graph_viz.py` that writes `docs/graph.html`.

### Test generation
Use the symbol graph to automatically generate pytest stubs for all public functions — parameter types from annotations, docstrings as test description comments.

### Multi-repo awareness
Allow `AgentState` to track multiple `repo_root` values and query the symbol graph across repos. Useful for monorepos and microservice architectures.

---

## Submitting Issues

Use the issue templates. For bug reports include:

1. The exact command or TUI action
2. The relevant section of `operon.log`
3. Your LLM provider and model
4. Python version (`python --version`)

For feature requests, describe the problem you're solving, not just the solution you want.

---

## Questions

Open a [GitHub Discussion](https://github.com/qasimio/Operon/discussions) for anything that isn't a bug or feature request.
