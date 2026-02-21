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
            state_hint = "Your search failed. Try a different query or read a file you already know about."
        else:
            state_hint = "Search successful. Now use 'read_file' on the exact file you need to edit."
    elif state.last_action == "read_file":
        state_hint = "You just read a file. If you have the context you need, use 'rewrite_function' to apply the patch. If you are working on multiple tasks, do them ONE AT A TIME. Edit this file first before moving to the next."
    elif state.last_action == "rewrite_function":
        if "error" in recent_obs:
            state_hint = "CRITICAL: Your last edit failed (Check the SyntaxError or match error). You MUST use 'rewrite_function' again to fix your mistake."
        else:
            state_hint = f"SUCCESS: You just modified a file! Files patched so far: {unique_mod}. Re-read the ORIGINAL GOAL. If there are other tasks or files left, use 'search_repo' or 'read_file' to start the next task. If EVERY task is complete, use 'stop'."

    prompt = f'''You are Operon, an autonomous senior software engineer capable of handling complex, multi-step tasks.

GOAL: 
{state.goal}

CURRENT STATE:
- Files read: {unique_read}
- Files modified (Tasks completed): {unique_mod}
- Last action executed: {state.last_action}

RECENT OBSERVATIONS:
{recent_obs}

{state_hint}

AVAILABLE TOOLS (Choose EXACTLY ONE):
1. {{"action": "search_repo", "query": "actual keywords"}} 
2. {{"action": "read_file", "path": "path/to/file.py"}} 
3. {{"action": "rewrite_function", "file": "path/to/file.py", "function": "function_name"}} 
4. {{"action": "stop"}} 

STRICT RULES FOR MULTI-TASKING:
1. NEVER repeat the exact same action twice in a row.
2. Knock out tasks sequentially. Read File A -> Rewrite File A -> Read File B -> Rewrite File B -> Stop.
3. DO NOT use 'stop' until EVERY part of the Goal has been achieved.
4. Output ONLY valid, raw JSON. No markdown formatting.
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