import json
import re
from agent.llm import call_llm

def decide_next_action(state) -> dict:
    # --- MEMORY COMPRESSION ---
    recent_obs = state.observations[-3:] if state.observations else []
    unique_read = list(set(state.files_read))
    unique_mod = list(set(state.files_modified))

    prompt = f'''
Goal: {state.goal}
Plan: {state.plan}

Context Summary:
- Files read: {unique_read}
- Files modified: {unique_mod}
- Last action: {state.last_action}

Recent Observations:
{recent_obs}

Decide the next logical action to progress towards the goal.

AVAILABLE ACTIONS (Choose ONE):
1. Search the repository for keywords if you don't know which file to edit:
   {{"action": "search_repo", "query": "search terms here"}}
2. Read a file to understand its full context:
   {{"action": "read_file", "path": "path/to/file.py"}}
3. Edit a file (provide "function" if editing a specific function, or leave it blank to edit global variables):
   {{"action": "rewrite_function", "file": "path/to/file.py", "function": "function_name_or_blank"}}
4. Run tests (CRITICAL: You MUST run tests immediately after editing a file!):
   {{"action": "run_tests"}}
5. Stop execution if the goal is met AND tests have passed:
   {{"action": "stop"}}

CRITICAL RULES FOR BEHAVIOR & SELF-HEALING:
- ANTI-LOOP RULE: NEVER repeat the exact same action twice in a row! If you just read a file, DO NOT read it again! You must move on to editing it or stop.
- If a search returns "No matches found", DO NOT repeat the exact same search. Try a single, unique keyword.
- If your "Recent Observations" show that tests FAILED or a command crashed, you MUST identify the file and function that caused the error, and use "rewrite_function" to fix your mistake!

You must return ONLY a raw JSON object. Do not include markdown formatting or explanations.
'''

    raw_output = call_llm(prompt, require_json=True)
    
    clean_json = re.sub(r"```(?:json)?\n?(.*?)\n?```", r"\1", raw_output, flags=re.DOTALL).strip()
    
    try:
        data = json.loads(clean_json)
        return data
    except Exception as e:
        print(f"[JSON PARSE ERROR]: {str(e)}")
        return {"action": "stop", "error": f"Failed to parse LLM JSON: {raw_output}"}