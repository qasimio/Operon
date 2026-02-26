# agent/planner.py — Operon v3.1
import json
import re
from agent.llm import call_llm
from agent.logger import log


def make_plan(goal: str, repo_root: str, state=None):
    """Returns (steps, is_question, validators)."""
    log.info("[bold magenta]🏛️ ARCHITECT: Building plan...[/bold magenta]")

    # Compact repo context
    ctx = ""
    if state is not None:
        sym  = getattr(state, "symbol_index", {})
        tree = getattr(state, "file_tree", [])
        if sym:
            sample = list(sym.items())[:8]
            lines  = ["REPO SYMBOLS:"]
            for rel, syms in sample:
                fns = [f["name"] for f in syms.get("functions", [])[:3]]
                lines.append(f"  {rel}: {fns}")
            ctx = "\n".join(lines)
        elif tree:
            ctx = "REPO FILES:\n" + "\n".join(f"  {f}" for f in tree[:15])

    prompt = f"""You are Operon's ARCHITECT. Produce a precise coding plan.

GOAL: {goal}

{ctx}

Output STRICT JSON with exactly these keys:
{{
  "steps": ["short milestone string", ...],
  "validators": [null or {{"type":"...", ...}}, ...],
  "multi_file": [{{"file": "rel/path", "action": "rewrite|create", "description": "..."}}]
}}

Validator types:
  {{"type":"not_contains","file":"path","text":"token"}}
  {{"type":"contains","file":"path","text":"token"}}
  {{"type":"lines_removed","file":"path","start":N,"end":M}}

Rules:
- steps and validators MUST have equal length.
- null validator if unsure.
- multi_file = [] if only one file changes.
- Each step: one action, max 10 words.
- Return ONLY JSON.
"""
    raw   = call_llm(prompt, require_json=True)
    clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.DOTALL)

    try:
        data       = json.loads(clean)
        steps      = data.get("steps", [])
        validators = data.get("validators", [None] * len(steps))
        multi_file = data.get("multi_file", [])

        if len(validators) < len(steps):
            validators += [None] * (len(steps) - len(validators))

        if not steps:
            raise ValueError("Empty steps")

        if state is not None and multi_file:
            state.multi_file_queue = [
                x for x in multi_file
                if isinstance(x, dict) and x.get("file")
            ]
            if state.multi_file_queue:
                log.info(
                    f"[cyan]📁 Multi-file: "
                    f"{[x['file'] for x in state.multi_file_queue]}[/cyan]"
                )

        log.info(f"[magenta]Plan ({len(steps)} steps):[/magenta]")
        for i, s in enumerate(steps):
            log.info(f"  {i+1}. {s}")

        return steps, False, validators

    except Exception as e:
        log.error(f"Planner failed ({e}) — using fallback.")
        return [goal], False, [None]
