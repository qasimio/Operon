import json
import re
from agent.llm import call_llm
from agent.logger import log

def decide_next_action(state) -> dict:
    if state.phase == "CODER":
        return _run_coder(state)
    elif state.phase == "REVIEWER":
        return _run_reviewer(state)
    return {}

def _run_coder(state):
    action_log = "\n".join([f"{i+1}. {entry}" for i, entry in enumerate(state.action_log)]) or "No actions yet."
    recent_obs = "\n".join([str(obs) for obs in state.observations[-3:]]) if getattr(state, "observations", []) else "None"
    
    # Render the Working Memory (Context Buffer) cleanly
    context_buffer = getattr(state, "context_buffer", {})
    context_files_text = ""
    if context_buffer:
        for filepath, content in context_buffer.items():
            context_files_text += f"\n--- FILE LOADED: {filepath} ---\n{content}\n--------------------------\n"
    else:
        context_files_text = "No files currently loaded. Use `read_file` to inspect code."

    if not getattr(state, "plan", None):
        current_step_text = "Analyze the goal and execute necessary actions."
    elif state.current_step < len(state.plan):
        current_step_text = state.plan[state.current_step]
    else:
        current_step_text = "All planned steps complete. Use the step_complete tool."

    prompt = f"""You are the CODER of an elite AI engineering team.
OVERALL GOAL: {state.goal}
CURRENT PLAN STEP: {current_step_text}

[WORKING MEMORY: LOADED FILES]
{context_files_text}

[EPISODIC MEMORY: ACTION HISTORY]
{action_log}

[RECENT OBSERVATIONS & ERRORS]
{recent_obs}

CRITICAL RULES FOR MULTI-TASKING:
1. **Never read a file twice:** Look at [WORKING MEMORY]. If the file is already there, DO NOT use `read_file` on it again. Move directly to `rewrite_function`.
2. **Loop Prevention:** If your [RECENT OBSERVATIONS] show "Loop detected", you must use a DIFFERENT tool immediately.
3. **Task Handoff:** If your [ACTION HISTORY] shows you just successfully applied a code patch for the CURRENT PLAN STEP, DO NOT do anything else. You MUST immediately use `step_complete` to hand off to the Reviewer.

ALLOWED TOOLS (Choose exactly ONE and output it as JSON):
- {{"action": "search_repo", "query": "search terms"}}
- {{"action": "read_file", "path": "file/path.py"}}
- {{"action": "rewrite_function", "file": "file/path.py"}}
- {{"action": "step_complete", "message": "Summary of what I completed"}}

REQUIREMENT: Output a JSON object containing "thought" and "tool".
"""
    return _call_and_parse(prompt)


def _run_reviewer(state):
    action_log = "\n".join([f"{i+1}. {entry}" for i, entry in enumerate(state.action_log[-5:])]) if state.action_log else "None"
    
    if not state.plan:
        current_step_text = "Analyze the goal and execute necessary actions."
    elif state.current_step < len(state.plan):
        current_step_text = state.plan[state.current_step]
    else:
        current_step_text = "All planned steps complete."
        
    prompt = f"""You are the REVIEWER of an elite AI engineering team.
OVERALL GOAL: {state.goal}
CURRENT PLAN STEP: {current_step_text}

RECENT CODER ACTIONS:
{action_log}

YOUR JOB:
1. Evaluate if the CODER successfully completed the CURRENT PLAN STEP.
2. If YES and there are more steps: Use `approve_step`.
3. If NO: Use `reject_step` and provide specific "feedback".
4. If ALL steps are complete, use `finish`.

ALLOWED TOOLS (Choose exactly ONE and output it as JSON):
- {{"action": "approve_step", "message": "Good job, moving to next step"}}
- {{"action": "reject_step", "feedback": "You forgot to do X"}}
- {{"action": "finish", "message": "Goal accomplished"}}

REQUIREMENT: Output a JSON object containing "thought" and "tool".
"""
    return _call_and_parse(prompt)

def _call_and_parse(prompt):
    raw_output = call_llm(prompt, require_json=True)
    clean_json = re.sub(r"```(?:json)?\n?(.*?)\n?```", r"\1", raw_output, flags=re.DOTALL).strip()
    try:
        data = json.loads(clean_json)
        if "action" in data and "tool" not in data:
            return {"thought": data.get("thought", "Proceeding with action."), "tool": data}
        if "tool" not in data:
            return {} 
        return data
    except Exception as e:
        log.error(f"Parse error: {e}")
        return {}