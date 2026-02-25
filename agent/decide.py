# agent/decide.py
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
1. {"action": "exact_search", "text": "variable_name"} (USE THIS to find exact variables, functions, or strings)
2. {"action": "semantic_search", "query": "conceptual question"} (USE THIS for vague concepts)
3. {"action": "read_file", "path": "exact/path.py"}
4. {"action": "rewrite_function", "file": "exact/path.py"}
5. {"action": "create_file", "file_path": "new/file.py", "initial_content": ""}
6. {"action": "find_file", "search_term": "filename or unique string in file"}
"""

        task = f"Execute this Milestone: '{current_step_text}'\n{tactical_advice}"

    else:  # REVIEWER
        persona = "You are Operon's STRICT CODE REVIEWER."
        tools = """
1. {"action": "approve_step", "message": "Reasoning"} (Use if the SYSTEM OBSERVATIONS confirm a successful rewrite)
2. {"action": "reject_step", "feedback": "Instructions to fix"} (Use if the Coder failed the milestone)
3. {"action": "finish", "commit_message": "Short git commit summary"} (Ends the task. Use this ONLY when the Coder has fully and correctly met the goal.)
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
    raw_output = call_llm(prompt, require_json=True)
    
    clean_json = re.sub(r"(?:json)?\n?(.*?)\n?``", r"\1", raw_output, flags=re.DOTALL).strip()
    try:
        data = json.loads(clean_json)
        # normalize: if user returned a top-level "action" object, wrap it under "tool"
        if "tool" not in data and "action" in data:
            return {"thought": data.get("thought",""), "tool": data}
        if "tool" not in data:
            # If the model returned direct tool dict (rare), coerce it
            if isinstance(data, dict) and any(k in data for k in ("action", "file", "path", "query", "text")):
                return {"thought": data.get("thought", ""), "tool": data}
            # fallback: return the data under "tool" if it's already the correct shape
            return {"thought": data.get("thought", "Auto-fallback"), "tool": data.get("tool", data)}
        return data
    except Exception as e:
        log.error(f"JSON PARSE ERROR from LLM: {e}")
        # Fallback conservative action so run_agent can keep going
        return {"thought": "JSON failed.", "tool": {"action": "error"}}