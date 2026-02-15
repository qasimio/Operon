from agent.llm import call_llm
import json
import re

def decide_next_action(state) -> dict:
    prompt = f"""
You are controlling an execution agent.

Goal: {state.goal}
Plan: {state.plan}
Files read: {state.files_read}
Files modified: {state.files_modified}
Last action: {state.last_action}

Decide the next action.

Available actions:
- read_file(path)
- write_file(path, content)
- run_tests()
- git_commit(message)
- stop()

Return JSON only.
"""

    output = call_llm(prompt)

    # Try direct parse first
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        pass

    # If model added extra text, try to extract JSON block
    match = re.search(r'\{.*\}', output, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    # Final safe fallback
    return {
        "action": "stop",
        "error": "Failed to parse LLM JSON output",
        "raw_output": output
    }





"""
Tell the AI everything about the current project state.
Ask it what action should happen next.
Force it to answer in JSON.
Convert that JSON into a Python dictionary.
Return it.
"""