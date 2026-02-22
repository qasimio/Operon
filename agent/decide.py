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
        if "error" in recent_obs.lower():
            state_hint = "Your search failed. Try a different query or read a file you already know about."
        else:
            state_hint = "Search successful. Now use 'read_file' on the exact file you need to edit."
    elif state.last_action == "read_file":
        if "error" in recent_obs.lower() or "not found" in recent_obs.lower():
            state_hint = "CRITICAL: The file you tried to read was not found. DO NOT try to read it again. Look at your search results for the correct path, or move to the next task."
        else:
            state_hint = "You just read a file. If you have the context you need, use 'rewrite_function' to apply the patch. Focus ONLY on this file before moving to the next task."
    elif state.last_action == "rewrite_function":
        if "error" in recent_obs.lower():
            state_hint = "CRITICAL: Your last edit failed (Check the SyntaxError or match error). You MUST use 'rewrite_function' again to fix your mistake."
        else:
            # FIXED: Tell it to use 'finish', not 'stop'
            state_hint = f"SUCCESS: You just modified a file! Files patched so far: {unique_mod}. Re-read the ORIGINAL GOAL. If there are other tasks or files left, use 'search_repo' or 'read_file' to start the next task. If EVERY task is complete, use the 'finish' tool immediately."

    prompt = f'''You are Operon, an autonomous senior software engineer capable of handling complex, multi-step tasks.

GOAL: 
{state.goal}

CURRENT STATE:
- Files read: {unique_read}
- Files modified (Tasks completed!): {unique_mod}
- Last action executed: {state.last_action}

RECENT OBSERVATIONS:
{recent_obs}

{state_hint}

MEMORY & PROGRESS CHECK:
Look at your Recent History and "Files modified". Ask yourself: "Have I completed ALL parts of the GOAL?"
- If YES: You MUST use the 'finish' action immediately to end the session.
- If NO: Determine the exact next file you need to search or read.

AVAILABLE TOOLS:
1. {{"action": "search_repo", "query": "search terms"}} 
   (Finds files containing the query. Use this first.)
2. {{"action": "read_file", "path": "path/to/file.py"}} 
   (Reads the exact contents of a file.)
3. {{"action": "rewrite_function", "file": "path/to/file.py", "function": "function_name"}} 
   (Triggers the patch engine. DO NOT put the new code in this JSON payload! You will be asked for the code in the next step. If adding to the bottom of a file, use "None" for function.)
4. {{"action": "finish", "message": "Brief summary of what was completed"}}
   (CRITICAL: Use this immediately when ALL parts of the GOAL have been achieved. This is your stop button.)

STRICT RULES FOR MULTI-TASKING:
1. NEVER repeat the exact same action twice in a row.
2. Knock out tasks sequentially. Read File A -> Rewrite File A -> Read File B -> Rewrite File B -> finish.
3. DO NOT use 'finish' until EVERY part of the Goal has been achieved.
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
