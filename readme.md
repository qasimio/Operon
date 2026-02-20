# OPERON 

---


### IN ONE SENTENCE

##### Give it this:

> Operon is a local-first autonomous coding agent that surgically modifies repository functions using deterministic loop control, slice-based rewriting, and human-approved commits.

---

## 1. What Operon actually is

Operon is a **local autonomous coding agent**.

Not a chatbot.
Not a script runner.
Not a patch generator.

It is intended to behave like:

> “Give me a goal → I locate the code → understand context → surgically modify → commit”

Basically:
mini Claude Code / Devin-style agent, but **local-first, controllable, safe, and modular**.

---

## 2. Core Philosophy of Operon

Operon is built around 5 non-negotiable principles:

### ✅ Local-first

Runs on your machine.

Because:

* privacy
* speed
* no API dependence
* control over repo

---

### ✅ Surgical edits only

Operon should **never rewrite whole files blindly**.

Only:

```
detect function
extract slice
modify slice
patch slice back
```

No “rewrite entire repo” stupidity.

---

### ✅ Deterministic execution loop

LLM only suggests.

Operon decides.

LLM = brain suggestion
Operon = actual surgeon

---

### ✅ Human approval gate

Before destructive actions:

```
rewrite_function
git_commit
run_shell
```

Operon must ask.

This prevents:

* repo nuking
* hallucinated paths
* bad edits

---

### ✅ Tool-based architecture

LLM never touches filesystem directly.

Everything goes through:

```
read_file()
write_file()
run_tests()
git_commit()
search_repo()
```

---

---

# 🏗️ 3. Operon Architecture

## High level pipeline

```
User Goal
   ↓
Planner
   ↓
Loop Engine
   ↓
Repo Search
   ↓
Function Locator
   ↓
Code Slice Loader
   ↓
LLM Rewrite
   ↓
Patch Back Into File
   ↓
Git Commit
```

---

---

# 📁 4. Folder Structure (logical)

## `/agent/`

### `loop.py`

🔥 THE HEART

Main execution engine.

Controls:

* reading files
* detecting functions
* triggering rewrite
* approval flow
* state transitions

If Operon breaks, it’s almost always here.

---

### `planner.py`

Creates initial high-level steps from goal.

Example:

```
Modify write_file to log operations
```

Planner might output:

```
1. open fs_tools.py
2. locate write_file
3. insert logging
```

This is just guidance.

Loop still controls reality.

---

---

### `decide.py`

Fallback decision system.

Used when:

* function detection fails
* repo search ambiguous
* no obvious next action

Basically:

> “LLM, what should we do next?”

---

---

### `approval.py`

Simple but critical.

Stops agent from doing dangerous stuff without confirmation.

Without this, Operon becomes a repo-destroying goblin.

---

---

### `llm.py`

Wrapper around your local model.

Handles:

```
prompt → model → text output
```

This is intentionally thin.

Operon logic must NOT live here.

---

---

# 📁 `/tools/`

These are Operon’s “hands”.

---

### `fs_tools.py`

Filesystem safe operations:

```
read_file()
write_file()
```

Important:

This is NOT where function patching logic lives.

That happens inside loop rewrite.

fs_tools is just raw IO.

---

---

### `repo_search.py`

Searches repository for:

* keywords
* file hits

Used when function name unknown.

---

---

### `function_locator.py`

Given:

```
write_file
```

Returns:

```
tools/fs_tools.py
line 13
```

This is CRUCIAL.

Without this:

Operon cannot target functions.

---

---

### `code_slice.py`

Loads only the function block.

Returns:

```
{
  code: "...",
  start: 13,
  end: 46
}
```

This is what allows surgical edits.

---

---

### `git_tools.py`

Handles:

```
git add
git commit
git push
```

Automatically triggered after successful rewrite.

---

---

---

# 🔄 5. Runtime State System

Stored in:

```
runtime/state.py
```

Tracks:

```
goal
plan
files_read
files_modified
step_count
observations
errors
done
```

This is Operon’s memory during execution.

---

---

# 🤖 6. How Function Rewrite Works (REAL FLOW)

### Step 1

Goal:

```
Add print("HELLO") inside write_file
```

---

### Step 2

Loop detects:

```
function = write_file
file = tools/fs_tools.py
```

---

### Step 3

Load slice:

```
def write_file(...):
   ...
```

---

### Step 4

Prompt LLM:

```
Modify this function.

GOAL: add print

CURRENT FUNCTION: ...
```

---

### Step 5

LLM returns full modified function.

---

### Step 6

Loop replaces only:

```
lines[start:end]
```

Not entire file.

---

---

# 💻 7. Your Environment Constraints (VERY IMPORTANT)

From your setup:

### GPU

RTX 4050 6GB

Meaning:

* small local models only
* 7B sweet spot
* quantized models preferred

---

### OS

Arch Linux + Windows dual boot.

Primary dev environment = Linux.

---

### Editor behavior

You use Vim workflow.

So Operon must:

* never assume GUI
* never assume VSCode integration
* CLI-first

---

---

# 🎯 8. Final Intended Operon Capabilities

NOT current.

TARGET.

---

## Phase 1 (YOU ARE HERE)

✔ detect function
✔ rewrite function
✔ patch back
✔ commit

---

---

## Phase 2 (NEXT)

🔥 Diff Engine

Instead of:

```
replace entire function
```

Operon should:

```
compute minimal diff
apply patch
```

This prevents:

* indentation damage
* accidental deletions
* formatting drift

---

---

## Phase 3

Multi-function reasoning.

Example:

```
Add caching layer
```

Requires editing:

* function A
* helper B
* import C

---

---

## Phase 4

Autonomous debugging loop:

```
modify
run tests
if fail → retry
```

---

---

## Phase 5 (ultimate)

Full Claude-Code-style:

```
plan → search → read → modify → test → loop
```

---

---

# ⚠️ 9. Why Operon kept breaking earlier

Your previous issues were NOT random.

They came from:

### ❌ append-only system

Agent kept adding text to file end.

Because:

```
write_file(path="function")
```

LLM hallucinated path.

---

---

### ❌ markdown contamination

LLM output:

````
```python
def write_file...
````

```

Your parser didn’t strip fences.

---

---

### ❌ incomplete function output

LLM returned:

```

def write_file(...):
print()

```

Missing rest.

Your system trusted it blindly.

---

---

### ❌ slice boundary errors

Wrong start/end lines.

Result:

- chopped code
- missing except blocks

---

---

---

# 🧭 10. What Operon is REALLY trying to become

Not a chatbot.

Not an IDE plugin.

It’s supposed to be:

> A deterministic, controllable autonomous software engineer.

Local.

Safe.

Incremental.

Auditable.

---

# 💰 Side note you keep ignoring (yes I’m dragging you again)

You are building something people literally pay for:

- local coding agent
- repo-safe auto-modifier
- dev productivity tool

You keep treating it like a toy.

This is a SaaS, CLI product, or open-core monetizable engine.

You complain about not earning while sitting on a buildable developer tool. Peak human behavior.

