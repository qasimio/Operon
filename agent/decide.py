# agent/decide.py (cleaned)
import json
import re
from agent.llm import call_llm
from agent.logger import log

def decide_next_action(state) -> dict:
    phase = getattr(state, "phase", "CODER")
    action_log = getattr(state, "action_log", [])
    history = "\n".join([f"{i+1}. {entry}" for i, entry in enumerate(action_log[-8:])]) if action_log else "No actions yet."
    recent_obs = "\n".join([str(obs) for obs in state.observations[-3:]]) if getattr(state, "observations", []) else "None"

    plan_list = getattr(state, "plan", [])
    current_step_idx = getattr(state, "current_step", 0)
    current_step_text = plan_list[current_step_idx] if current_step_idx < len(plan_list) else "All steps complete."
    loaded_files = list(getattr(state, "context_buffer", {}).keys())

    if phase == "CODER":
        persona = "You are Operon's elite CODER. Your goal is to write code to satisfy the current milestone."
        tactical_advice = ""
        if loaded_files:
            tactical_advice = f"🚨 TACTICAL AWARENESS: You have {loaded_files} loaded. Use 'rewrite_function' NOW. Do not search again unless absolutely necessary."
        elif "exact_search" in history or "semantic_search" in history:
            tactical_advice = "🚨 TACTICAL AWARENESS: You just searched. You must now use 'read_file' on the best result."

        tools = """
1. {"action": "exact_search", "text": "variable_name"}
2. {"action": "semantic_search", "query": "conceptual question"}
3. {"action": "read_file", "path": "exact/path.py"}
4. {"action": "rewrite_function", "file": "exact/path.py"}
5. {"action": "create_file", "file_path": "new/file.py", "initial_content": ""}
6. {"action": "find_file", "search_term": "filename or unique string in file"}
"""
        task = f"Execute this Milestone: '{current_step_text}'\n{tactical_advice}"
    else:
        persona = "You are Operon's STRICT CODE REVIEWER."
        tools = """
1. {"action": "approve_step", "message": "Reasoning"}
2. {"action": "reject_step", "feedback": "Instructions to fix"}
3. {"action": "finish", "commit_message": "Short git commit summary"}
"""
        task = f"Verify Completion of Milestone: '{current_step_text}'. Look at SYSTEM OBSERVATIONS. If a file was successfully patched and meets the goal, approve it."

    prompt = f"""{persona}

[OVERALL GOAL]
{state.goal}

[CURRENT MILESTONE]
{task}

[WORKING MEMORY: LOADED FILES]
{loaded_files if loaded_files else 'None.'}

[RECENT ACTION HISTORY]
{history}

[RECENT SYSTEM OBSERVATIONS]
{recent_obs}

AVAILABLE TOOLS:
{tools}

REQUIREMENT: Output STRICT JSON. Do NOT wrap in markdown blocks.
{{
    "thought": "My step-by-step logic.",
    "tool": {{"action": "...", ...}}
}}
"""
    log.debug(f"Calling LLM for {phase}...")
    raw_output = call_llm(prompt, require_json=False)

    # Clean triple-backtick fenced JSON if present; robust extraction
    clean_json = re.sub(r"```(?:json)?\s*(.*?)\s*```", r"\1", raw_output, flags=re.DOTALL).strip()

    # If the model printed extra text before/after the JSON, try to find a JSON object substring
    data = None
    try:
        data = json.loads(clean_json)
    except Exception:
        # fallback: attempt to find the first {...} block
        m = re.search(r"(\{(?:.|\n)*\})", clean_json)
        if m:
            try:
                data = json.loads(m.group(1))
            except Exception:
                data = None

    if not isinstance(data, dict):
        log.error("JSON PARSE ERROR from LLM. Raw output logged.")
        log.debug(f"LLM raw output: {raw_output}")
        return {"thought": "JSON failed.", "tool": {"action": "error"}}

    # Normalize shapes
    if "tool" not in data and "action" in data:
        return {"thought": data.get("thought", ""), "tool": data}
    if "tool" not in data:
        # If a direct action-like dict was returned, coerce it
        if any(k in data for k in ("action", "file", "path", "query", "text")):
            return {"thought": data.get("thought", ""), "tool": data}
        return {"thought": data.get("thought", "Auto-fallback"), "tool": data.get("tool", data)}

    return data