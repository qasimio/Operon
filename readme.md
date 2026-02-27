# 🧬 Operon

### Autonomous Code Intelligence Agent for Your Local Repository

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)
[![Code Style: Black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Stars](https://img.shields.io/github/stars/qasimio/Operon?style=social)](https://github.com/qasimio/Operon/stargazers)

**Operon is a terminal-native, LLM-powered code agent that understands your entire repository, not just the file you have open.**

[Features](#features) ·
[Architecture](#architecture) ·
[Installation](#installation) ·
[Quick-Start](#quick-start) ·
[CLI-Reference](#cli-reference) ·
[Contributing](#contributing)

---

## What is Operon?

Operon is a local code intelligence system that lets you interact with your codebase through natural language, an interactive TUI, or a headless CLI.

It builds a persistent symbol graph of your repository, understands cross-file relationships, and executes code transformations through an autonomous agent loop.

Unlike chat-based coding assistants, Operon operates **on your repository**:

* Reads real files
* Builds AST indexes
* Tracks diffs
* Requests approval before writing
* Rolls back safely on failure

```
You: Rename UI_CALLBACK to safe_log across the entire project

Operon:
- Scanned 28 files
- Found 7 occurrences (3 files)

Dry run preview:
agent/logger.py L9   UI_CALLBACK → safe_log
agent/approval.py L44 UI_CALLBACK → safe_log
tui/app.py L433       UI_CALLBACK → safe_log

⚠ Awaiting approval...
[A]pprove [R]eject

✅ Applied. 3 files updated.
```

---

## The Problem Operon Solves

Most AI coding tools are **stateless and file-scoped**.

They cannot safely:

* Track symbols across files
* Rename functions without breaking callers
* Understand dependency relationships
* Generate accurate documentation

Operon builds a **live persistent model of your repository** enabling:

* Safe multi-file refactors
* Structure-aware documentation
* Execution-flow reasoning
* Approval-gated filesystem mutation

---

## Features

### 🔬 AST-Based Symbol Intelligence

Operon uses Python's `ast` and `tokenize` modules.

Indexed elements include:

* Functions
* Classes
* Variables
* Imports
* Decorators
* Assignments
* Annotations

No external parser required.

---

### 🔁 Repository-Wide Symbol Refactoring

Rename symbols across the entire repository with token-level precision.

```bash
python main.py rename MAX_STEPS STEP_LIMIT
python main.py rename MAX_STEPS STEP_LIMIT --apply
```

---

### 📊 Persistent Cross-File Symbol Graph

Stored at:

```
.operon/symbol_graph.json
```

Features:

* Incremental indexing
* File hash validation
* Definition / call / reference tracking

---

### 📄 Automatic Deep Documentation

Generates a full `/docs/` tree:

* docs/README.md
* docs/modules/*.md
* docs/symbols.md
* docs/call_graph.md

---

### 🔍 Intelligent Chunked Loading

Operon never loads full files unnecessarily.

Context is assembled using:

* Symbol relevance
* Token overlap
* Dependency proximity

---

### 🔄 Safe Function Signature Migration

Automatically updates all call sites when a function signature changes.

```bash
python main.py signature configure "host, port, timeout=30" --apply
```

---

### 💬 Terminal Explanation Mode

```bash
python main.py explain run_agent
python main.py explain agent/loop.py:420
python main.py explain --flow run_agent
python main.py usages MAX_STEPS
```

---

### 🤖 Universal LLM Support

Supports local and hosted providers:

| Provider   | Examples          |
| ---------- | ----------------- |
| Local      | llama.cpp, Ollama |
| OpenAI     | gpt-4o            |
| Anthropic  | Claude            |
| OpenRouter | Any               |
| DeepSeek   | deepseek-coder    |
| Groq       | llama models      |
| Together   | Qwen              |
| Azure      | OpenAI            |

Hot reload enabled. No restart required.

---

### 🛡️ Deterministic Safety Layer

* Deterministic REVIEWER validation
* CRUD fast-path operations
* Mandatory approval gate
* Git rollback safety

---

### 🖥️ Textual TUI

Interactive terminal interface powered by Textual:

* Chat interface
* Diff preview
* Approval dialogs
* Provider configuration

---

## Architecture

```
TUI
 └── Agent Loop
      ├── ARCHITECT
      ├── CODER
      └── REVIEWER
            ↓
      Intelligence Layer
            ↓
      File Safety Layer
```

Core systems:

* Symbol Graph
* Chunk Loader
* AST Engine
* Documentation Generator
* Diff Engine
* Git Safety

---

## Core Concepts

### Phase Machine

Every task flows through:

1. ARCHITECT
2. CODER
3. REVIEWER

---

### Symbol Graph

Persistent cross-repository symbol index.

Example:

```json
{
  "cross_refs": {
    "run_agent": [
      {"file": "agent/loop.py", "line": 487, "kind": "definition"}
    ]
  }
}
```

---

### Approval Gate

No filesystem write occurs without explicit confirmation.

Timeout automatically rejects pending operations.

---

## Repository Structure

```
Operon/
├── agent/
├── tools/
├── cli/
├── runtime/
├── tui/
└── main.py
```

---

## Installation

Requirements:

* Python 3.10+
* Git

```bash
git clone https://github.com/qasimio/Operon.git
cd Operon

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Optional:

```bash
pip install lancedb fastembed
pip install textual[dev]
```

---

## Quick Start

### TUI Mode

```bash
python main.py
```

Configure LLM provider on first launch.

---

### CLI Mode

```bash
python main.py explain run_agent
python main.py usages MAX_STEPS
python main.py rename OLD NEW
python main.py docs
python main.py summarize agent/loop.py
```

---

## CLI Reference

### explain

```
python main.py explain <symbol>
```

### usages

```
python main.py usages <symbol>
```

### rename

```
python main.py rename OLD NEW [--apply]
```

### docs

```
python main.py docs [--no-llm]
```

### signature

```
python main.py signature <func> "<args>" [--apply]
```

---

## Roadmap

| Status | Feature                 |
| ------ | ----------------------- |
| ✅      | Symbol graph            |
| ✅      | Repo rename             |
| ✅      | Documentation generator |
| ✅      | Chunk loading           |
| 🔜     | JS/TS AST               |
| 🔜     | Java AST                |
| 🔜     | LSP server              |
| 🔜     | Multi-repo awareness    |
| 🔜     | VS Code extension       |

---

## Philosophy

1. Filesystem is the source of truth.
2. Deterministic before LLM.
3. User approves every write.
4. Context must be minimal and relevant.
5. Indexing must be incremental.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

Quick steps:

1. Fork repository
2. Create feature branch
3. Commit changes
4. Open PR against `main`

---

## Credits

**Creator:** Muhammad Qasim (@qasimio)

Built using:

* Textual
* LanceDB
* FastEmbed
* Python `ast` and `tokenize`

---

## License

MIT License
