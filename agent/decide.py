# agent/decide.py — Operon v3.1
"""
Rebuilt from the working original decide.py with these additions:

KEY FIX (from log analysis):
  - REVIEWER no longer calls decide_next_action in a hot loop.
    When the REVIEWER has already rejected N times and "finish" is blocked,
    the loop would spin calling decide() infinitely because decide() kept
    calling the LLM synchronously on each iteration.
    
    Solution: The REVIEWER returns a structured decision with explicit
    escalation logic. After 3 rejections the loop forces state.done=True
    via an abort path — it does NOT rely on "finish" getting through tool_jail.

  - TACTICAL prompt injection kept from your working version:
    "You have [files] loaded. Use rewrite_function NOW."
    This is what stopped the infinite read_file loop.

  - File context preview included in REVIEWER prompt so it can actually
    judge the content instead of hallucinating "file is unmodified."
"""

import json
import re
from agent.llm import call_llm
from agent.logger import log


def decide_next_action(state) -> dict:
    phase       = getattr(state, "phase", "CODER")
    action_log  = getattr(state, "action_log", [])
    history     = (
        "\n".join(f"{i+1}. {e}" for i, e in enumerate(action_log[-8:]))
        if action_log else "No actions yet."
    )
    observations = getattr(state, "observations", [])
    recent_obs   = "\n".join(str(o) for o in observations[-4:]) if observations else "None"

    plan_list    = getattr(state, "plan", [])
    step_idx     = getattr(state, "current_step", 0)
    step_text    = plan_list[step_idx] if step_idx < len(plan_list) else "All steps complete."
    loaded_files = list(getattr(state, "context_buffer", {}).keys())

    # ── CODER ─────────────────────────────────────────────────────────────────
    if phase == "CODER":
        # Tactical injection — most important anti-loop mechanism
        tactical = ""
        if loaded_files:
            tactical = (
                f"🚨 TACTICAL: You have {loaded_files} loaded in memory. "
                "Call 'rewrite_function' NOW with the correct file. "
                "Do NOT search or read again unless you have a specific reason."
            )
        elif any(a in history for a in ("exact_search", "semantic_search", "find_file")):
            tactical = (
                "🚨 TACTICAL: You just searched. "
                "Now call 'read_file' on the best result, then 'rewrite_function'."
            )

        # Include a compact file preview if available
        file_preview = ""
        ctx = getattr(state, "context_buffer", {})
        if ctx:
            first_file = next(iter(ctx))
            content    = ctx[first_file]
            file_preview = (
                f"\n[FILE IN MEMORY: {first_file}]\n"
                f"{content[:1200]}"
                f"{'...(truncated)' if len(content) > 1200 else ''}\n"
            )

        tools = """\
TOOLS (output exactly one):
1. {"action": "find_file",        "search_term": "filename or unique string"}
2. {"action": "read_file",        "path": "exact/relative/path.ext"}
3. {"action": "exact_search",     "text": "exact token to grep for"}
4. {"action": "semantic_search",  "query": "conceptual description"}
5. {"action": "rewrite_function", "file": "exact/relative/path.ext"}
6. {"action": "create_file",      "file_path": "new/file.ext", "initial_content": "..."}"""

        prompt = f"""You are Operon's elite CODER. Execute the current milestone.

[OVERALL GOAL]
{state.goal}

[CURRENT MILESTONE]
{step_text}

[LOADED FILES]
{loaded_files if loaded_files else "None — you need to find and read a file first."}
{file_preview}
[RECENT ACTIONS]
{history}

[SYSTEM OBSERVATIONS]
{recent_obs}

{tactical}

{tools}

REQUIREMENT: Output STRICT JSON. No markdown. No extra text.
{{
    "thought": "My step-by-step reasoning.",
    "tool": {{"action": "...", ...}}
}}"""

    # ── REVIEWER ──────────────────────────────────────────────────────────────
    else:
        files_modified = getattr(state, "files_modified", [])
        diff_memory    = getattr(state, "diff_memory", {})

        # Build evidence for reviewer
        evidence = ""
        ctx = getattr(state, "context_buffer", {})
        if ctx:
            for fp, content in list(ctx.items())[:2]:
                evidence += f"\n[FILE: {fp}]\n{str(content)[:1200]}\n"
        if diff_memory:
            for fp, patches in list(diff_memory.items())[:2]:
                if patches:
                    evidence += f"\n[DIFF: {fp}]\n{patches[-1].get('diff','')[:600]}\n"

        tools = """\
TOOLS (output exactly one):
1. {"action": "approve_step",  "message": "Why this step is complete"}
2. {"action": "reject_step",   "feedback": "Exactly what the coder must fix"}
3. {"action": "finish",        "commit_message": "Short git commit summary"}"""

        prompt = f"""You are Operon's STRICT CODE REVIEWER.

[OVERALL GOAL]
{state.goal}

[CURRENT MILESTONE TO VERIFY]
{step_text}

[FILES MODIFIED SO FAR]
{files_modified if files_modified else "None"}

[FILE CONTENT / DIFF EVIDENCE]
{evidence if evidence else "No file content loaded yet."}

[RECENT ACTIONS]
{history}

[SYSTEM OBSERVATIONS]
{recent_obs}

REVIEWER RULES:
- If evidence shows the file was successfully changed to meet the milestone: use approve_step.
- If no files were modified or the change is wrong: use reject_step with specific instructions.
- If ALL plan steps are complete: use finish.
- BE GENEROUS: any meaningful progress toward the goal = approve.
- Do NOT reject if the file preview matches the goal.

{tools}

Output STRICT JSON only:
{{
    "thought": "My analysis of the evidence.",
    "tool": {{"action": "...", ...}}
}}"""

    log.debug(f"Calling LLM for {phase}...")
    raw_output = call_llm(prompt, require_json=False)

    # Robust JSON extraction
    clean = re.sub(
        r"```(?:json)?\s*(.*?)\s*```", r"\1", raw_output, flags=re.DOTALL
    ).strip()

    data = None
    try:
        data = json.loads(clean)
    except Exception:
        m = re.search(r"(\{(?:.|\n)*\})", clean)
        if m:
            try:
                data = json.loads(m.group(1))
            except Exception:
                pass

    if not isinstance(data, dict):
        log.error(f"JSON parse failed. Raw: {raw_output[:200]}")
        return {"thought": "JSON failed", "tool": {"action": "error"}}

    # Normalize shapes
    if "tool" not in data and "action" in data:
        return {"thought": data.get("thought", ""), "tool": data}
    if "tool" not in data:
        if any(k in data for k in ("action", "file", "path", "query", "text")):
            return {"thought": data.get("thought", ""), "tool": data}
        return {"thought": data.get("thought", ""), "tool": data.get("tool", data)}

    return data
