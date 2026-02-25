### 0. EXECUTIVE SYSTEM IDENTITY

**Project name:** Operon
**Core purpose:** Autonomous AI Software Engineer capable of navigating local repositories, reasoning about code, performing surgical file edits, verifying its own work, and committing changes.
**Domain/business context:** AI Developer Tools / Local Autonomous Agents. Operates directly within user codebases to accelerate development, fix bugs, and scaffold features.
**System type:** TUI (Text User Interface) driven local CLI agent.
**Maturity level:** Advanced Prototype / Alpha (Core loop stable, semantic memory functional, multi-agent handoffs working, currently expanding LLM provider routing via LiteLLM).

---

### 1. HIGH-LEVEL ARCHITECTURE

#### 1.1 Architectural style

Operon utilizes an **Agentic State Machine / ReAct (Reasoning + Acting) Architecture** paired with a **Multi-Agent Human-in-the-Loop (HITL)** pattern.

* *Why?* Single-prompt generation fails on complex codebases. The state machine allows the agent to iteratively search, read, and write. The multi-agent setup splits responsibilities (Coder vs. Reviewer) to prevent hallucinations, while the HITL Approval Gate prevents destructive, unverified file writes.

#### 1.2 System component map

* **TUI (Text User Interface):** Renders the chat, diff previews, and approval prompts.
* **Loop Engine (`agent/loop.py`):** The core heartbeat. Manages the state machine, loop detection, and tool routing.
* **Planner Agent:** High-level architectural thinker. Decomposes the user goal into a step-by-step plan.
* **Coder Agent:** The primary worker. Uses search and read tools to find context, then uses `rewrite_function` or `create_file` to modify code.
* **Reviewer Agent:** The verifier. Examines the Coder's patches, approves or rejects them, and generates final contextual Git commits.
* **Semantic Memory (`agent/semantic_memory.py`):** Vector database engine generating embeddings of the codebase to allow for natural language code querying.
* **Diff Engine (`tools/diff_engine.py`):** Processes strict `<<<<<<< SEARCH / ======= / >>>>>>> REPLACE` blocks to perform surgical code edits without rewriting whole files.
* **Tool Jail (`agent/tool_jail.py`):** Security boundary preventing agents from calling unauthorized tools.

#### 1.3 Data flow overview

1. User submits a prompt via the TUI.
2. Planner generates an execution plan.
3. System transitions to Coder phase.
4. Coder invokes tools (e.g., `semantic_search`, `read_file`) to gather context.
5. Coder invokes `rewrite_function` with a patch.
6. The Diff Engine validates the patch and runs syntax checks.
7. Execution pauses. The TUI prompts the human for `Approve (y)` or `Reject (n)`.
8. On approval, the patch is written to disk.
9. System auto-handoffs to the Reviewer, injecting the updated file context.
10. Reviewer verifies the goal is met and calls `finish` with a dynamic commit message.

#### 1.4 ASCII architecture diagram

```text
                          +-------------------+
                          |    User / TUI     |
                          +--------+----------+
                                   | (Goal)
                                   v
+-------------------------------------------------------------------------+
|                              STATE ENGINE                               |
|                                                                         |
|  +-------------+       +------------------+       +------------------+  |
|  |   PLANNER   | ----> |      CODER       | <---> |     REVIEWER     |  |
|  +-------------+       +--------+---------+ (Fix) +---------+--------+  |
|                                 |                           |           |
+---------------------------------|---------------------------|-----------+
                                  |                           |
             +--------------------+---------------------------+
             |                    |                           |
      +------v-------+    +-------v-------+           +-------v--------+
      |  Read/Search |    | Write / Patch |           | Commit / Final |
      |    Tools     |    |    Tools      |           |     Tools      |
      +------+-------+    +-------+-------+           +-------+--------+
             |                    |                           |
+------------v--------------------v---------------------------v-----------+
|                              LOCAL WORKSPACE                            |
|                                                                         |
|  [ LanceDB Vector Store ]   [ Git Repository ]   [ Syntax Parsers ]     |
+-------------------------------------------------------------------------+

```

---

### 2. DIRECTORY & MODULE BREAKDOWN

```text
operon/
├── agent/                  # Core agent reasoning and state logic
│   ├── loop.py             # CRITICAL: Main execution loop, state transitions, loop overrides.
│   ├── decide.py           # LLM API calls and tool JSON schemas.
│   ├── planner.py          # Generates initial task breakdown.
│   ├── repo.py             # General repository interactions.
│   ├── git_safety.py       # Ensures agent operates on safe/correct branches.
│   ├── approval.py         # Handles pausing for human patch approval.
│   ├── semantic_memory.py  # Boots vector DB, chunks files, creates embeddings.
│   ├── repo_search.py      # Routers for exact vs. semantic searches.
│   └── tool_jail.py        # Validates tool calls against agent permissions.
├── tools/                  # Executable functions the LLM can call
│   ├── build_brain.py      # Ingest pipeline for the vector store.
│   ├── diff_engine.py      # CRITICAL: Parses SEARCH/REPLACE blocks and applies them.
│   ├── fs_tools.py         # File system operations.
│   ├── universal_parser.py # Syntax validation (AST, Tree-sitter) to prevent broken code.
│   └── function_locator.py # Finds specific function definitions.
├── tui/                    # User Interface
│   └── app.py              # Textual/Rich based terminal UI.
├── runtime/
│   └── state.py            # Global state object (history, context_buffer, phase, loop_counters).
├── main.py                 # Application entry point.
└── operon.log              # Detailed system logs.

```

---

### 3. TECHNOLOGY STACK

* **Languages:** Python 3.10+ (Agent codebase).
* **Frameworks:** * *Flask* (seen in test logs for dummy apps).
* *LanceDB*: Used for embedded, local vector search (`semantic_memory`).
* *ONNX Runtime / Zero-PyTorch*: Used to generate vector embeddings locally without heavy PyTorch dependencies.
* *LiteLLM (WIP)*: Universal router for LLM API calls (OpenAI, Anthropic, OpenRouter).


* **Infrastructure:** Local runtime execution. Operates directly on the host machine's filesystem.
* **Build/Package:** `pip` / `requirements.txt`.
* **Deployment:** Runs locally as a CLI/TUI tool. No cloud deployment required.

---

### 4. FEATURE & FUNCTIONALITY INVENTORY

* **Semantic Repository Indexing:**
* *What it does:* Scans the codebase on boot, chunks code, and saves to LanceDB.
* *Entry points:* `semantic_memory.py` -> `boot_semantic_memory()`.


* **Tool-Augmented Reasoning:**
* *What it does:* Agents can dynamically call tools based on React prompts.
* *Entry points:* `agent/loop.py`, `agent/decide.py`.


* **Fuzzy File Finding:**
* *What it does:* Allows LLM to find files without knowing exact paths (`find_file`).


* **Surgical Code Patching:**
* *What it does:* Uses `rewrite_function` with precise `<<<<<<< SEARCH` and `>>>>>>> REPLACE` boundaries to edit code safely.


* **Pre-write Syntax Validation:**
* *What it does:* Routes patched code through `tools.universal_parser.check_syntax` *before* presenting it to the user, blocking syntax errors.


* **Human-in-the-Loop Approval:**
* *What it does:* Pauses the engine thread, updates the TUI with a diff preview, and waits for human `y/n`.


* **Infinite Loop Detection:**
* *What it does:* Detects if the agent repeats the exact same tool call (e.g., `read_file` 3 times). Wipes memory and forces a Reviewer handoff to break the hallucination cycle.


* **Dynamic Auto-Commits:**
* *What it does:* The Reviewer generates a contextual git commit summarizing its verified work and executes it.



---

### 5. API SURFACE

**Internal Tool API (Exposed to LLM via JSON Schemas in `decide.py`):**

* `read_file(file_path)`: Returns raw file text.
* `semantic_search(query)`: Returns top K code snippets matching intent.
* `exact_search(term)`: Returns exact string matches with line numbers.
* `find_file(search_term)`: Fuzzy searches file names across the repository.
* `create_file(file_path, initial_content)`: Bootstraps new files.
* `rewrite_function(file_path, search_block, replace_block)`: Applies surgical diffs.
* `reject_step(reason)`: (Reviewer only) Bounces task back to Coder.
* `approve_step()`: (Reviewer only) Approves current state.
* `finish(commit_message)`: Ends the run and commits.

---

### 6. DATA MODEL

**Database:** LanceDB (Local)

* **Type:** Embedded Vector Database.
* **Schema (Code Snippets):**
* `id` (string): Unique chunk ID.
* `file_path` (string): Relative path.
* `content` (string): Raw code text.
* `vector` (Array[float]): ONNX-generated embedding.



```text
[ Document / Code File ]
         | (chunked via build_brain.py)
         v
[ LanceDB Table: "repo_index" ]
  |-- id
  |-- file_path
  |-- content
  |-- vector

```

---

### 7. CORE LOGIC EXPLANATION

**The Agent Loop (`agent/loop.py`):**
The system runs a `while True:` loop governed by `state.phase`.

1. Calls LLM via `decide.py` based on current phase and context.
2. Parses the JSON tool call.
3. Updates loop counters to detect repeated actions.
4. Executes the Python tool function.
5. If `rewrite_function` succeeds:
* Triggers human approval.
* Reads the *newly updated* code from disk.
* Injects `state.context_buffer = {target_file: updated_code}` to prevent Reviewer blindness.
* Transitions `state.phase = "REVIEWER"`.



**Diff Engine logic (`tools/diff_engine.py`):**
The search block *must* perfectly match the original file (including whitespace). The engine finds the start index of the search block in the target string and replaces it with the replace block. If the search block is empty, it appends to the file.

---

### 8. CONFIGURATION & ENVIRONMENT

* **`.env`:** Holds `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc.
* **`MAX_STEPS`:** Integer (currently `50` in `loop.py`) dictating the maximum tool calls before the agent forcefully aborts to prevent runaway API costs.
* **Vector Models:** Can be configured to swap out ONNX models for heavier PyTorch ones depending on host machine specs.

---

### 9. SECURITY MODEL

* **Tool Jail:** Implemented in `tool_jail.py`. The `REVIEWER` phase is strictly blocked from using `rewrite_function` or `create_file`. If it attempts to, it is intercepted and warned.
* **Git Safety:** `git_safety.py` ensures the agent isn't running loose on `main`. It operates on safe branches (e.g., `api`).
* **Execution boundaries:** The agent operates strictly within `repo_root`. Path traversal protections should be assumed or explicitly enforced in `fs_tools.py`.

---

### 10. TESTING STRATEGY

* Operon tests itself primarily via integration runs on dummy files (e.g., scaffolding `api_test.py` with Flask endpoints or modifying `test.js`).
* Unit tests focus on `universal_parser.py` (ensuring AST parsing doesn't falsely flag good code or allow bad code) and `diff_engine.py` (edge cases in SEARCH/REPLACE whitespace).

---

### 11. BUILD / RUN / DEPLOY INSTRUCTIONS

1. **Install:** ```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

```


2. **Run:**
```bash
python tui/app.py

```


3. **Interact:** Type goals in the bottom TUI input. Watch the workspace/diff preview on the right. Approve via `(y)` / `(n)` buttons or keystrokes.

---

### 12. KNOWN TECH DEBT & DESIGN TRADEOFFS

* **Reviewer Context Blindness:** Previously, wiping the `context_buffer` before handing off to the Reviewer caused infinite loops (Reviewer rejected patches because it couldn't see them). Fixed by explicitly reading the patched file and passing it to the Reviewer's prompt.
* **Search/Replace Fragility:** If the LLM misses a single space in the `SEARCH` block, the diff fails. The agent handles this by retrying, but it burns API tokens.
* **LiteLLM Migration:** Currently migrating away from hardcoded LLM endpoints toward a universal LiteLLM router in `decide.py` to support multiple backends.

---

### 13. IMPORTANT CODE PATH WALKTHROUGH

**Scenario:** "inside main.py - add import json on top"

1. **TUI Input:** User submits the goal.
2. **`loop.py`:** Initiates `PLANNER`. Planner outputs: `["1. Open main.py", "2. Add import"]`.
3. **`loop.py`:** Transitions to `CODER`.
4. **`decide.py`:** Calls LLM. LLM returns `{"action": "read_file", "file_path": "main.py"}`.
5. **`loop.py`:** Executes `read_file`, appends content to `state.observations`.
6. **`decide.py`:** LLM sees file, returns `{"action": "rewrite_function", "search": "import os", "replace": "import os\nimport json"}`.
7. **`loop.py` -> `diff_engine.py`:** Replaces the text. Passes to `universal_parser.py` which passes AST validation.
8. **`approval.py`:** TUI pauses. Human presses `y`. File written to disk.
9. **`loop.py`:** Auto-Handoff logic fires. File read from disk. `state.context_buffer` populated. Phase changes to `REVIEWER`.
10. **`decide.py`:** Reviewer LLM sees the goal and the new file context. Returns `{"action": "finish", "commit_message": "Added json import to main.py"}`.
11. **`loop.py`:** Executes subprocess `git commit -m "..."`. Goal complete.

---

### 14. GLOSSARY OF INTERNAL TERMS

* **TUI:** Textual/Terminal User Interface.
* **Phase:** The current agent persona active in the state machine (`PLANNER`, `CODER`, `REVIEWER`).
* **Tool Jail:** The interceptor that blocks unauthorized tool usage.
* **Search Block / Replace Block:** The strict text segments used by `diff_engine` to patch code.
* **Loop Override:** A system-level intervention when an agent gets stuck repeating the same tool (detected by matching previous actions).

---

### 15. LLM HANDOFF SUMMARY (CRITICAL)

**To the next LLM taking over Operon maintenance:**

1. **How to reason about this codebase:** Treat `agent/loop.py` as the absolute source of truth for flow control. If the agent gets "stuck" or loops, the fix is *always* in how state, context buffers, or observations are passed around in `loop.py`.
2. **Critical Files:**
* `agent/loop.py`: The state machine.
* `agent/decide.py`: Where you add/modify tools and LLM prompting.
* `tools/diff_engine.py`: If code editing is failing, this is the culprit.


3. **Typical Bug Locations:**
* *Context Loss:* If the Coder or Reviewer acts "blind", check what is appended to `state.observations` and `state.context_buffer` right before the LLM is called.
* *Infinite Loops:* The LLM will repeatedly call `rewrite_function` if the file doesn't exist. Ensure `create_file` or `find_file` is properly promoted in the system prompt.


4. **Safe Extension Patterns:**
* To add a new capability (e.g., running tests):
1. Create the tool logic in `tools/run_tests.py`.
2. Add the JSON schema to `agent/decide.py`.
3. Add the `elif act == "run_tests":` execution block in `agent/loop.py`.




5. **Dangerous Modification Areas:**
* **Do NOT** alter the strict requirements of the `<<<<<<< SEARCH` format without fundamentally rewriting `diff_engine.py`. The LLMs must output perfect matches.
* **Do NOT** wipe `state.context_buffer` blindly during handoffs, or the receiving agent will hallucinate. Always re-inject actual disk state.