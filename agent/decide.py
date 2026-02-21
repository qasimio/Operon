# agent/decide.py
from agent.llm import call_llm
import json
import re


def decide_next_action(state) -> dict:
    """
    Decide the next action. If the agent has a function_context observation
    (a function slice), ask the LLM to *generate* a replacement for that
    function and return JSON with replace_range + content.
    Otherwise fall back to a generic planning prompt.
    """

    # Look for the most recent function context (set by the loop)
    func_ctx = None
    for obs in reversed(getattr(state, "observations", [])):
        if isinstance(obs, dict) and obs.get("function_context"):
            func_ctx = obs.get("function_context")
            break

    if func_ctx:
        # function slice present — ask the model to produce code for that function only
        file_rel = func_ctx.get("file")
        start = int(func_ctx.get("start", 0))
        end = int(func_ctx.get("end", 0))
        slice_code = func_ctx.get("code", "").strip()

        prompt = f"""
You are Operon, a code-editing assistant. The user goal: {state.goal}

You were given the following function slice from the repository file "{file_rel}" (lines {start}-{end}):

------
{slice_code}
------

Task: produce a corrected/updated implementation of *that function only*.
Requirements:
- Return a JSON object only (no prose).
- JSON must contain:
  - action: "write_file"
  - path: the relative path to the file (e.g. "{file_rel}")
  - replace_range: {{ "start": {start}, "end": {end} }}
  - mode: "replace"
  - content: the exact source code for the new function (function def + body). Must be valid Python and nothing else.
- Do NOT include any explanation, comments, or surrounding file text. Only the function source in "content".
- Preserve behavior unless the goal explicitly asks to change behavior.

Return JSON only.
"""

    # General fallback prompt (no function context)
    
    # --- MEMORY COMPRESSION ---
    # Only show the last 2 observations so we don't blow up the 8k VRAM context
    recent_obs = state.observations[-2:] if state.observations else []
    
    # Deduplicate files read/modified to save tokens
    unique_read = list(set(state.files_read))
    unique_mod = list(set(state.files_modified))

    prompt = f'''
You are controlling an execution agent.

Goal: {state.goal}
Plan: {state.plan}

Context Summary:
- Files read: {unique_read}
- Files modified: {unique_mod}
- Last action: {state.last_action}

Recent Observations:
{recent_obs}

Decide the next action.

Available actions:
- read_file(path)
- write_file(path, content)
- run_tests()
- git_commit(message)
- stop()

Return a JSON object with the "action" and required fields. Return ONLY valid JSON.
'''

    output = call_llm(prompt, require_json=True)
    
    import json
    try:
        data = json.loads(output)
        if data:
            return data
    except Exception:
        pass

    # safe fallback
    return {
        "action": "stop",
        "error": "Failed to parse LLM JSON output",
        "raw_output": output
    }