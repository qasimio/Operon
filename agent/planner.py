# agent/planner.py — Operon v3
"""
Context-aware planner:
  - Uses the 4-level index (symbol index + dep graph + file tree) to ground the plan
  - Detects multi-file tasks and returns a structured work queue
  - Produces precise per-step validators
  - Keeps prompts short for Qwen 7B @ 8k ctx
"""

import json
import re
from agent.llm import call_llm
from agent.logger import log


def make_plan(goal: str, repo_root: str, state=None):
    """
    Returns: (steps: list[str], is_question: bool, validators: list[dict|None])

    Also populates state.multi_file_queue if multiple files need changing.
    """
    log.info("[bold magenta]🏛️ ARCHITECT: Building plan...[/bold magenta]")

    # ── Build compact repo context from 4-level index ─────────────────────────
    context_lines: list[str] = []

    if state is not None:
        sym = getattr(state, "symbol_index", {})
        if sym:
            sample = list(sym.items())[:10]
            context_lines.append("SYMBOL INDEX (sample):")
            for rel, syms in sample:
                fns  = [f["name"] for f in syms.get("functions", [])[:4]]
                clss = [c["name"] for c in syms.get("classes",   [])[:2]]
                context_lines.append(f"  {rel}: funcs={fns} classes={clss}")

        dep = getattr(state, "dep_graph", {})
        if dep:
            context_lines.append("DEP GRAPH (sample):")
            for rel, deps in list(dep.items())[:6]:
                context_lines.append(f"  {rel} → {deps[:3]}")

        tree = getattr(state, "file_tree", [])
        if tree:
            context_lines.append(f"FILE TREE ({len(tree)} files, first 15):")
            for rel in tree[:15]:
                context_lines.append(f"  {rel}")

    context_block = "\n".join(context_lines)

    prompt = f"""You are Operon's ARCHITECT. Produce a precise coding plan.

GOAL: {goal}

REPO CONTEXT:
{context_block}

OUTPUT STRICT JSON with exactly these keys:
{{
  "steps": ["short milestone string", ...],
  "validators": [null or {{"type":"...", ...}}, ...],
  "multi_file": [{{"file": "rel/path", "action": "rewrite|create", "description": "..."}}]
}}

Validator types (choose the best match):
  {{"type":"not_contains","file":"path","text":"token"}}
  {{"type":"contains","file":"path","text":"token"}}
  {{"type":"lines_removed","file":"path","start":N,"end":M}}

Rules:
  - steps and validators MUST have the same length.
  - Use null validator when unsure.
  - multi_file lists ALL files that need changes (empty list if just one file).
  - Keep steps short: one action per step, max 12 words.
  - Return ONLY JSON. No markdown, no explanation.
"""

    raw = call_llm(prompt, require_json=True)
    clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.DOTALL)

    try:
        data = json.loads(clean)
        steps = data.get("steps", [])
        validators = data.get("validators", [None] * len(steps))
        multi_file = data.get("multi_file", [])

        if len(validators) < len(steps):
            validators += [None] * (len(steps) - len(validators))

        if not steps:
            raise ValueError("Empty plan")

        # Populate multi_file_queue on state
        if state is not None and multi_file:
            state.multi_file_queue = [
                item for item in multi_file
                if isinstance(item, dict) and item.get("file")
            ]
            if state.multi_file_queue:
                log.info(
                    f"[cyan]📁 Multi-file plan: "
                    f"{[x['file'] for x in state.multi_file_queue]}[/cyan]"
                )

        log.info(f"[magenta]Plan ({len(steps)} steps):[/magenta]")
        for i, s in enumerate(steps):
            log.info(f"  {i+1}. {s}")

        return steps, False, validators

    except Exception as e:
        log.error(f"Planner failed ({e}) — using minimal fallback.")
        fallback = ["1. Read the relevant files", "2. Apply the required change"]
        return fallback, False, [None, None]
