# agent/decide.py
from agent.llm import call_llm
import json
import re
from typing import Dict

ACTION_SCHEMA_EXAMPLE = {
    "action": "read_file",
    "path": "src/utils.py"
}

# Minimal allowed actions and examples are explicitly listed to reduce hallucination.
def decide_next_action(state) -> Dict:
    prompt = f"""
You control a local execution agent. Reply with JSON only.

Current goal:
{state.goal}

Plan:
{state.plan}

Files read so far: {state.files_read}
Files modified so far: {state.files_modified}
Last action: {state.last_action}

Available actions (choose exactly one and return JSON):
1) read_file -> {{ "action": "read_file", "path": "<relative_path>" }}
2) write_file -> {{ "action": "write_file", "path": "<relative_path>", "content": "<new file content>" }}
3) run_tests -> {{ "action": "run_tests" }}
4) git_commit -> {{ "action": "git_commit", "message": "<commit message>", "branch_prefix": "agent/refactor" }}
5) stop -> {{ "action": "stop" }}

Return JSON only. Example:
{json.dumps(ACTION_SCHEMA_EXAMPLE)}
"""
    output = call_llm(prompt)

    # Try to parse JSON strictly
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        # extract first {...} block
        m = re.search(r"\{.*\}", output, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    # fallback
    return {"action": "stop", "error": "failed_to_parse", "raw": output}





"""
Tell the AI everything about the current project state.
Ask it what action should happen next.
Force it to answer in JSON.
Convert that JSON into a Python dictionary.
Return it.
"""