# `runtime/state.py`


## Overview

This file defines a data class `AgentState` for managing the state of an agent in a software development process. It includes fields for tracking the agent's goal, current phase, plan, file operations, history, counters, memory, and a 4-level intelligence index.


## Stats

| Metric | Count |
|--------|-------|
| Lines | 68 |
| Functions | 0 |
| Classes | 1 |
| Variables | 35 |
| Imports | 6 |


## Imports

- `dataclasses:dataclass`
- `dataclasses:field`
- `typing:List`
- `typing:Dict`
- `typing:Any`
- `typing:Optional`


## Imported by

- [`tui/app.py`](tui_app.md)


## Classes


### `class AgentState`

- **Lines:** 7–68

**Summary:** The `AgentState` class in Python is a data class that encapsulates the state of an agent, including its goal, repository root, current phase in a phase machine, a plan with validators, the current step in the plan, and tracking of files read.
