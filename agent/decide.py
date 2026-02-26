# agent/decide.py  — REPLACE decide_next_action with this version
import json
import re
from agent.llm import call_llm
from agent.logger import log

def decide_next_action(state) -> dict:
    phase = getattr(state, "phase", "CODER")

    # produce compact recent action history (most recent first)
    recent = getattr(state, "recent_actions", [])[-12:]
    recent_simple = []
    for act, canon in recent:
        if act is None: continue
        recent_simple.append(f"{act}")

    recent_obs = "\n".join([str(o) for o in getattr(state, "observations", [])[-6:]]) or "None."
    action_log = getattr(state, "action_log", [])[-8:]
    history = "\n".join([f"{i+1}. {entry}" for i, entry in enumerate(action_log)]) if action_log else "No actions yet."

    plan_list = getattr(state, "plan", [])
    current_step_idx = getattr(state, "current_step", 0)
    current_step_text = plan_list[current_step_idx] if current_step_idx < len(plan_list) else "All steps complete."

    # Observed search counts for throttling guidance
    search_counts = getattr(state, "search_counts", {}) or {}
    top_searches = sorted(search_counts.items(), key=lambda kv: -kv[1].get("count", 0))[:4]
    search_summary = ", ".join([f"{k}({v['count']})" for k, v in top_searches]) or "None."

    # Guidance/constraints to reduce loops
    guidance = """
Important constraints to avoid repeating loops or useless work:
- If a previous tool produced a file list or content, prefer 'read_file' on that exact path instead of searching again.
- Do NOT repeat the same 'semantic_search', 'exact_search', or 'find_file' query more than 3 times; if the query has already been tried often (see SEARCH_SUMMARY), escalate by choosing 'reject_step' with reviewer feedback or switch to 'read_file'/'find_file' with a broader pattern.
- If you plan to write or patch a file, use 'rewrite_function' only after you have loaded the target file into context via 'read_file' (unless creating a new file).
- If you want to append new content to a file and the file is empty, 'create_file' is preferred; otherwise prefer 'rewrite_function' with precise SEARCH/REPLACE or provide an 'initial_content' replacement in state.context_buffer.
- Always output STRICT JSON only, with shape:
  {{
    "thought": "Your reasoning.",
    "tool": {{"action": "...", ...}}
  }}
"""

    if phase == "CODER":
        persona = "You are Operon's CODER. Execute the current milestone efficiently."
        tools = """
AVAILABLE TOOLS (choose one):
1) {"action": "exact_search", "text": "..."}
2) {"action": "semantic_search", "query": "..."}
3) {"action": "find_file", "search_term": "..."}
4) {"action": "read_file", "path": "path/to/file"}
5) {"action": "rewrite_function", "file": "path/to/file"}  # only after read_file
6) {"action": "create_file", "file_path": "path", "initial_content": "..."}
"""
        task = f"Execute milestone: '{current_step_text}'. If you have a file path from previous steps, use read_file on it."
    else:
        persona = "You are Operon's REVIEWER. Verify completion and avoid approving broken or partial work."
        tools = """
REVIEWER TOOLS:
1) {"action": "approve_step", "message": "..."}
2) {"action": "reject_step", "feedback": "..."}
3) {"action": "finish", "commit_message": "..."}
"""
        task = f"Verify completion of milestone: '{current_step_text}'. Use system observations to decide."

    prompt = f"""{persona}

[OVERALL GOAL]
{state.goal}

[CURRENT MILESTONE]
{task}

[RECENT ACTIONS]
{', '.join(recent_simple) or 'None.'}

[RECENT SYSTEM OBSERVATIONS]
{recent_obs}

[RECENT SEARCH SUMMARY]
{search_summary}

[RECENT ACTION HISTORY]
{history}

{guidance}

{tools}

REQUIREMENT: Output STRICT JSON. Do NOT wrap in markdown blocks.
{{ 
  "thought": "Step-by-step reasoning (brief).",
  "tool": {{"action": "...", ...}}
}}
"""
    log.debug("Calling LLM for decide_next_action...")
    raw_output = call_llm(prompt, require_json=True)

    # clean any stray fences and load JSON
    clean_json = re.sub(r"(?:```json)?\n?(.*?)\n?```", r"\1", raw_output, flags=re.DOTALL).strip()
    try:
        data = json.loads(clean_json)
        # normalization: if top-level "action" returned, wrap under "tool"
        if "tool" not in data and "action" in data:
            return {"thought": data.get("thought", ""), "tool": data}
        if "tool" not in data:
            # if model returned direct tool dict
            if isinstance(data, dict) and any(k in data for k in ("action", "file", "path", "query", "text")):
                return {"thought": data.get("thought", ""), "tool": data}
            return {"thought": data.get("thought", "Auto-fallback"), "tool": data.get("tool", data)}
        return data
    except Exception as e:
        log.error(f"JSON PARSE ERROR from LLM in decide_next_action: {e}")
        return {"thought": "JSON failed.", "tool": {"action": "error"}}