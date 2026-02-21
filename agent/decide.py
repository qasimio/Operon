import json
from agent.llm import call_llm

def decide_next_action(state) -> dict:
    # --- MEMORY COMPRESSION ---
    # Only keep the last 2 observations to save VRAM context
    recent_obs = state.observations[-2:] if state.observations else []
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
3. Rewrite a specific function (if you know what to change):
   {{"action": "rewrite_function", "file": "path/to/file.py", "function": "function_name"}}
4. Run tests (CRITICAL: You MUST run tests immediately after rewriting a function!):
   {{"action": "run_tests"}}
5. Stop execution if the goal is met AND tests have passed:
   {{"action": "stop"}}

CRITICAL RULES FOR SELF-HEALING:
- If your "Recent Observations" show that tests FAILED or a command crashed, you MUST look at the stderr/traceback, identify the file and function that caused the error, and use "rewrite_function" to fix your mistake!

You must return ONLY a raw JSON object. Do not include markdown formatting or explanations at all.
'''


    # Call LLM with native JSON enforcement
    raw_output = call_llm(prompt, require_json=True)
    
    print("\n[LLM RAW OUTPUT]:\n", raw_output, "\n")
    
    try:
        # It should parse perfectly every time now
        data = json.loads(raw_output)
        return data
    except Exception as e:
        print(f"[JSON PARSE ERROR]: {str(e)}")
        # Emergency fallback so the loop doesn't crash
        return {"action": "stop", "error": f"Failed to parse LLM JSON: {raw_output}"}