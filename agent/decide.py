import json
import re
from agent.llm import call_llm
from agent.logger import log

def decide_next_action(state) -> dict:
    # --- MEMORY COMPRESSION ---
    # Keep the last 3 observations, but format them cleanly
    recent_obs = "\n".join([str(obs) for obs in state.observations[-3:]]) if state.observations else "None"
    unique_read = list(set(state.files_read))
    unique_mod = list(set(state.files_modified))
    
# --- DYNAMIC STATE ENFORCEMENT ---
    state_hint = ""
    if state.last_action == "search_repo":
        if "error" in recent_obs:
            state_hint = "CRITICAL INSTRUCTION: Your last search failed. DO NOT search again. Pick a file from previous findings and use 'read_file'."
        else:
            state_hint = "CRITICAL INSTRUCTION: You just searched. You MUST now use 'read_file' on the best file found."
    elif state.last_action == "read_file":
        state_hint = "CRITICAL INSTRUCTION: You just read a file. You MUST now use 'rewrite_function' to make the required changes, or 'stop' if no changes are needed."
    elif state.last_action == "rewrite_function":
        # ========================================
        # MULTITASKING
        # ========================================
        if "error" in recent_obs:
            state_hint = "CRITICAL INSTRUCTION: You last edit failed. Read the error and try 'rewrite_function' again to fix it."
        else:
            state_hint = "CRITICAL INSTRUCITON: You successfully updated a file. Evaluate the original GOAL. If there are other files or functions that still need editing to complete the goal, use 'search_repo' or 'read_file' to continue. If the goal is 100% complete across all files, you must use 'stop'."

    prompt = f'''You are Operon, an autonomous senior software engineer. Your goal is to manage tools to fix code.

GOAL: {state.goal}

CURRENT STATE:
- Files read: {unique_read}
- Files modified: {unique_mod}
- Last action executed: {state.last_action}

RECENT OBSERVATIONS:
{recent_obs}

{state_hint}

AVAILABLE TOOLS (Choose EXACTLY ONE):
1. {{"action": "search_repo", "query": "actual keywords"}} 
   (Find files related to the goal.)
   
2. {{"action": "read_file", "path": "path/to/file.py"}} 
   (Read full context of a file before editing.)
   
3. {{"action": "rewrite_function", "file": "path/to/file.py", "function": "function_name"}} 
   (Delegates actual coding to a sub-agent. DO NOT include new code in this JSON payload.)
   
4. {{"action": "stop"}} 
   (Use this immediately when the goal is completely finished.)

STRICT RULES FOR COMPLETION & SELF-HEALING:
1. NEVER repeat the exact same action twice.
2. DONE HEURISTIC: If you have achieved the functional goal (e.g., changing a port or updating a logger in the actual code), DO NOT hunt down text references in readmes, json files, or main.py. You MUST use 'stop' immediately.
3. Output ONLY valid, raw JSON. No markdown formatting, no conversational text.
'''

    log.debug("Calling LLM to decide next action...")
    raw_output = call_llm(prompt, require_json=True)
    
    # Aggressive JSON cleanup
    clean_json = re.sub(r"```(?:json)?\n?(.*?)\n?```", r"\1", raw_output, flags=re.DOTALL).strip()
    
    try:
        data = json.loads(clean_json)
        return data
    except Exception as e:
        log.error(f"[JSON PARSE ERROR]: {str(e)}\nRaw output was: {raw_output}")
        # If it hallucinates garbage, force it to read the most likely file instead of killing the session
        if "agent/llm.py" not in unique_read:
            return {"action": "read_file", "path": "agent/llm.py"}
        return {"action": "stop", "error": f"Failed to parse LLM JSON: {raw_output}"}