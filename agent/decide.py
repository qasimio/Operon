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
You are a deterministic execution agent.

NEVER chat.
NEVER explain.
ONLY output valid JSON.

Choose ONE action.

Valid actions:
read_file(path)
write_file(path, content)
run_tests()
git_commit(message)
stop()

Goal:
{state.goal}

Plan:
{state.plan}

Files read:
{state.files_read}

Files modified:
{state.files_modified}

Return JSON ONLY.
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