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
        state_hint = "CRITICAL INSTRUCTION: You just edited a file. You MUST now use 'run_tests' to verify changes, or 'stop' if you are completely finished."
    elif state.last_action == "run_tests":
        state_hint = "CRITICAL INSTRUCTION: You just ran tests. If they passed, you MUST use 'stop'. If they failed, use 'read_file' or 'rewrite_function' to fix the error."
    

    prompt = f'''You are Operon, an autonomous senior software engineer. Your goal is to fix code.

GOAL: {state.goal}

CURRENT STATE:
- Files read: {unique_read}
- Files modified: {unique_mod}
- Last action executed: {state.last_action}

RECENT OBSERVATIONS (Read carefully to see if your last action succeeded or failed):
{recent_obs}

{state_hint}

AVAILABLE TOOLS (Choose EXACTLY ONE):
1. {{"action": "search_repo", "query": "exact keywords"}} (Find files)
2. {{"action": "read_file", "path": "path/to/file.py"}} (Read full context)
3. {{"action": "rewrite_function", "file": "path/to/file.py", "function": "name"}} (Edit code. Leave function blank if editing global vars)
4. {{"action": "run_tests"}} (Verify changes)
5. {{"action": "stop"}} (Goal is completely finished)

STRICT RULES:
1. NEVER repeat the exact same action twice.
2. If you know the file to edit (e.g., agent/llm.py), DO NOT SEARCH. Use read_file immediately.
3. Output ONLY valid, raw JSON. No markdown formatting, no conversational text, no explanations.
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