import json
import re
from agent.llm import call_llm
from agent.logger import log

def decide_next_action(state) -> dict:
    # --- EPISODIC MEMORY COMPRESSION ---
    # Instead of raw, noisy observations, we look at the chronological journal of actions
    action_log = getattr(state, "action_log", [])
    if not action_log:
        formatted_history = "No actions taken yet."
    else:
        formatted_history = "\n".join([f"{i+1}. {entry}" for i, entry in enumerate(action_log)])

    # Keep a small buffer of raw recent errors/observations just for immediate context
    recent_obs = "\n".join([str(obs) for obs in state.observations[-2:]]) if state.observations else "None"
    plan_text = getattr(state, "plan", "No plan generated.")

    prompt = f'''You are Operon, an elite autonomous AI software engineer. You have agency to explore, edit, and fix code.

[ORIGINAL GOAL]
{state.goal}

[YOUR PLAN]
{plan_text}

[CHRONOLOGICAL ACTION HISTORY]
(Read this carefully to know exactly what you have already accomplished. DO NOT hallucinate completions. You MUST see "SUCCESS" in this history for a task to be considered done.)
{formatted_history}

[LATEST SYSTEM OBSERVATIONS / ERRORS]
{recent_obs}

[YOUR TASK]
1. Read the ACTION HISTORY strictly.
2. Compare your history against the ORIGINAL GOAL.
3. Determine if EVERY part of the goal is fully complete based ONLY on the ACTION HISTORY.
4. Decide the exact next tool to use.

AVAILABLE TOOLS:
1. {{"action": "search_repo", "query": "search terms"}} 
   (Finds files containing the query. Use this to locate code.)
2. {{"action": "read_file", "path": "path/to/file.py"}} 
   (Reads the exact contents of a file into your observations.)
3. {{"action": "rewrite_function", "file": "path/to/file.py", "function": "function_name"}} 
   (Triggers the code patch engine. DO NOT include the new code here. Use "None" for function if unknown.)
4. {{"action": "finish", "message": "Brief summary of what was completed"}}
   (CRITICAL: Use this ONLY when the ACTION HISTORY proves all parts of the GOAL are met.)

REQUIREMENT: You MUST output a JSON object containing a "thought" and a "tool".
- "thought": Step-by-step reasoning. What did you just do? What is left in the goal?
- "tool": The exact JSON payload from the AVAILABLE TOOLS list.

EXAMPLE OUTPUT (DO NOT COPY THIS - IT IS JUST A FORMAT TEMPLATE):
{{
    "thought": "Looking at my history, I see SUCCESS for patching 'utils/math.py' to fix the division by zero bug. The goal asked for nothing else. I should now terminate the session.",
    "tool": {{"action": "finish", "message": "Division by zero bug fixed."}}
}}
'''    

    log.info("Calling LLM to decide next action (ReAct mode)...")
    raw_output = call_llm(prompt, require_json=True)
    
    # Aggressive JSON cleanup
    clean_json = re.sub(r"```(?:json)?\n?(.*?)\n?```", r"\1", raw_output, flags=re.DOTALL).strip()
    try:
        return json.loads(clean_json)
    except json.JSONDecodeError:
        log.error(f"[JSON PARSE ERROR]: Could not parse cleaned JSON from LLM output: {clean_json}")
        return {"thought": "Failed to parse JSON from LLM output.", "tool": {"action": "read_file", "path": "agent/llm.py"}}