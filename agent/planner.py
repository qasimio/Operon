# agent/planner.py — Operon v2: Context-aware planner using 4-level index
from agent.llm import call_llm
from agent.logger import log
import json
import re


def make_plan(goal: str, repo_root: str, state=None):
    """
    Produce a compact list of milestones (strings) AND a parallel list of
    validators. Optionally uses the 4-level index (via state) to give the
    planner richer repo context for better step granularity.

    Returns: (steps: list[str], is_question: bool, validators: list[dict|None])
    """
    log.info("[bold magenta]🏛️ ARCHITECT: Building plan...[/bold magenta]")

    # Build repo context hint from 4-level index if available
    context_hint = ""
    if state is not None:
        # Symbol summary
        sym_idx = getattr(state, "symbol_index", {})
        if sym_idx:
            sample_files = list(sym_idx.keys())[:8]
            sym_lines = []
            for fp in sample_files:
                fns = [f["name"] for f in sym_idx[fp].get("functions", [])[:4]]
                cls = [c["name"] for c in sym_idx[fp].get("classes", [])[:2]]
                sym_lines.append(f"  {fp}: funcs={fns} classes={cls}")
            context_hint += "SYMBOL INDEX (sample):\n" + "\n".join(sym_lines) + "\n\n"

        # Dep graph sample
        dep_graph = getattr(state, "dep_graph", {})
        if dep_graph:
            sample_deps = list(dep_graph.items())[:5]
            dep_lines = [f"  {fp} → {deps[:3]}" for fp, deps in sample_deps]
            context_hint += "DEP GRAPH (sample):\n" + "\n".join(dep_lines) + "\n\n"

    prompt = f"""You are Operon's ARCHITECT. You produce precise coding plans.

GOAL: {goal}

{context_hint}

Produce the MINIMAL list of coding milestones to complete the goal.
For each milestone, produce a simple validator object when possible.

Output STRICT JSON with exactly two keys:
{{
  "steps": ["short milestone string", ...],
  "validators": [null or {{"type":"...", ...}}, ...]
}}

Validator types (choose the most specific):
  {{"type":"not_contains","file":"path","text":"token_that_should_be_gone"}}
  {{"type":"contains","file":"path","text":"token_that_must_exist"}}
  {{"type":"lines_removed","file":"path","start":N,"end":M}}

Rules:
- steps and validators must have the SAME length.
- Use null validator when you cannot infer a precise check.
- Keep steps short (one action each, max 12 words).
- Return ONLY JSON. No markdown, no explanation.
"""

    raw = call_llm(prompt, require_json=True)
    clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.DOTALL)
    try:
        data = json.loads(clean)
        steps = data.get("steps", [])
        validators = data.get("validators", [None] * len(steps))
        if len(validators) < len(steps):
            validators += [None] * (len(steps) - len(validators))
        if not steps:
            raise ValueError("Empty steps from planner")
        log.info(f"[magenta]Plan ({len(steps)} steps):[/magenta] {steps}")
        return steps, False, validators
    except Exception as e:
        log.error(f"Planner failed: {e}. Using fallback.")
        fallback = ["1. Investigate the codebase", "2. Complete the objective"]
        return fallback, False, [None, None]
