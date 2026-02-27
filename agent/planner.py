# agent/planner.py — Operon v3.2
"""
ARCHITECT planner. Produces tight, executable plans.

KEY FIXES:
  - No 'Locate X' / 'Find Y' steps — pure write milestones only.
  - Each step names the TARGET file explicitly when known.
  - Validator attached to each step so REVIEWER has ground truth.
"""
from __future__ import annotations

import json
import re

from agent.llm import call_llm
from agent.logger import log


def make_plan(goal: str, repo_root: str, state=None):
    """Returns (steps, is_question, validators)."""
    log.info("[bold magenta]🏛️ ARCHITECT: Building plan...[/bold magenta]")

    ctx = ""
    if state is not None:
        sym  = getattr(state, "symbol_index", {})
        tree = getattr(state, "file_tree", [])
        if sym:
            ctx = "REPO SYMBOLS:\n" + "\n".join(
                f"  {k}: {[f['name'] for f in v.get('functions', [])[:3]]}"
                for k, v in list(sym.items())[:8]
            )
        elif tree:
            ctx = "REPO FILES:\n" + "\n".join(f"  {f}" for f in tree[:20])

    prompt = f"""You are Operon's ARCHITECT. Write a precise, minimal coding plan.

GOAL: {goal}

{ctx}

RULES FOR STEPS:
- Each step = ONE atomic write (one file, one specific change).
- NEVER include "locate", "find", "read", or "search" steps. Coder does that.
- Name the file AND the exact change. Example:
    GOOD: "Change MAX_STEPS = 30 to MAX_STEPS = 40 in agent/loop.py"
    BAD:  "Update the variable"
- Simple 1-2 change task: 1-2 steps. Multi-file: one step per file change.

Output STRICT JSON only:
{{
  "steps": ["...", ...],
  "validators": [null or {{"type":"contains","file":"path","text":"token"}}, ...],
  "multi_file": [{{"file":"rel/path","action":"rewrite|create","description":"..."}}]
}}

Validator types: contains | not_contains | lines_removed
"""

    raw   = call_llm(prompt, require_json=True)
    clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.DOTALL)

    try:
        data       = json.loads(clean)
        steps      = data.get("steps", [])
        validators = data.get("validators", [])
        mf         = data.get("multi_file", [])

        if not steps:
            raise ValueError("empty steps")

        while len(validators) < len(steps):
            validators.append(None)

        if state is not None and mf:
            state.multi_file_queue = [
                x for x in mf if isinstance(x, dict) and x.get("file")
            ]
            if state.multi_file_queue:
                log.info(
                    "[cyan]📁 Multi-file: "
                    f"{[x['file'] for x in state.multi_file_queue]}[/cyan]"
                )

        log.info(f"[magenta]Plan ({len(steps)} steps):[/magenta]")
        for i, s in enumerate(steps):
            log.info(f"  {i+1}. {s}")

        return steps, False, validators

    except Exception as e:
        log.error(f"Planner failed ({e}) — fallback to goal as single step.")
        return [goal], False, [None]
