# `runtime/state.py`


## Overview

This file defines a dataclass `AgentState` for managing the state of an agent in a software development process. It includes fields for the agent's goal, repository root, phase in the development cycle, plan and validators, file tracking, history of actions, counters for various metrics, and memory buffers for context and Git state.


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

**Summary:** The `AgentState` class encapsulates the current state of an agent, including its goal, repository root, phase in a state machine, plan, file tracking, and other relevant metadata.
