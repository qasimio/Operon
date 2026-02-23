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
    recent_obs = "\n".join([str(obs) for obs in state.observations[-3:]]) if state.observations else "None"
    
    if not state.plan:
        current_step_text = "Analyze the goal and execute necessary actions."
    elif state.current_step < len(state.plan):
        current_step_text = state.plan[state.current_step]
    else:
        current_step_text = "All planned steps complete. Use the step_complete tool."

    prompt = f"""You are the CODER of an elite AI engineering team.
OVERALL GOAL: {state.goal}
CURRENT PLAN STEP: {current_step_text}

ACTION HISTORY:
{action_log}

RECENT OBSERVATIONS:
{recent_obs}

YOUR JOB:
1. You ONLY have access to code editing tools.
2. Do NOT try to finish the entire goal at once. Focus ONLY on the CURRENT PLAN STEP.
3. If the step requires finding information, use `search_repo` and `read_file`.
4. If the step requires modifying code, use `rewrite_function`.
5. Once you believe the CURRENT PLAN STEP is achieved, use the `step_complete` tool to hand off to the Reviewer.

ALLOWED TOOLS (Choose exactly ONE and output it as JSON):
- {{"action": "search_repo", "query": "search terms"}}
- {{"action": "read_file", "path": "file/path.py"}}
- {{"action": "rewrite_function", "file": "file/path.py"}}
- {{"action": "step_complete", "message": "Summary of what I completed for this step"}}

REQUIREMENT: Output a JSON object containing "thought" and "tool".
EXAMPLE FORMAT:
{{
    "thought": "I need to search for the agent logic to answer the question.",
    "tool": {{"action": "search_repo", "query": "agent logic"}}
}}
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
IS THIS JUST A QUESTION?: {state.is_question}
CURRENT PLAN STEP: {current_step_text}

RECENT CODER ACTIONS:
{action_log}

YOUR JOB:
1. Evaluate if the CODER successfully completed the CURRENT PLAN STEP based on their actions.
2. If YES and there are more steps: Use `approve_step`.
3. If NO: Use `reject_step` and provide specific "feedback".
4. If ALL steps are complete and the overall goal is fully achieved (or the question has been answered), use `finish`.

ALLOWED TOOLS (Choose exactly ONE and output it as JSON):
- {{"action": "approve_step", "message": "Good job, moving to next step"}}
- {{"action": "reject_step", "feedback": "You forgot to do X"}}
- {{"action": "finish", "message": "Goal accomplished: [final answer or summary]"}}

REQUIREMENT: Output a JSON object containing "thought" and "tool".
EXAMPLE FORMAT:
{{
    "thought": "The coder found the answer to the question.",
    "tool": {{"action": "finish", "message": "The step limit is controlled by MAX_STEPS in agent/loop.py"}}
}}
"""
    return _call_and_parse(prompt)

def _call_and_parse(prompt):
    raw_output = call_llm(prompt, require_json=True)
    clean_json = re.sub(r"```(?:json)?\n?(.*?)\n?```", r"\1", raw_output, flags=re.DOTALL).strip()
    try:
        data = json.loads(clean_json)
        # Handle if LLM forgets the wrapper and just outputs the tool dict
        if "action" in data and "tool" not in data:
            return {"thought": data.get("thought", "Proceeding with action."), "tool": data}
        if "tool" not in data:
            # Force empty dict to trigger the Jail error gracefully rather than a hard crash
            return {} 
        return data
    except Exception as e:
        log.error(f"Parse error: {e}")
        return {}