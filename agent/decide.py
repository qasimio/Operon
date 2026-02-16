from agent.llm import call_llm
from agent.tool_jail import validate_action


def decide_next_action(state):

    prompt = f"""
You are NOT a chatbot.
You are NOT a terminal.
You are NOT a human assistant.

You are a deterministic software execution controller.
If no file has been read yet, your first action MUST be read_file.


Your ONLY job is to output ONE valid JSON tool call.

You CANNOT:
- write explanations
- write shell commands
- write steps
- write markdown
- write greetings
- output anything except JSON
- Do NOT use git_commit unless files were modified.


AVAILABLE TOOLS:

read_file
{{"action":"read_file","path":"relative_path"}}

write_file
{{"action":"write_file","path":"relative_path","content":"new_file_content"}}

run_tests
{{"action":"run_tests"}}

git_commit
{{"action":"git_commit","message":"commit message"}}

stop
{{"action":"stop"}}

GOAL:
{state.goal}

PLAN:
{state.plan}

FILES READ:
{state.files_read}

FILES MODIFIED:
{state.files_modified}

LAST ACTION:
{state.last_action}

OUTPUT JSON ONLY:
"""

    raw = call_llm(prompt)

    action, err = validate_action(raw)

    # retry once if broken
    if err:
        retry_prompt = f"""
Your previous output was INVALID because: {err}

You MUST output ONLY valid JSON.

Retry now.
"""
        raw = call_llm(prompt + retry_prompt)
        action, err = validate_action(raw)

    # final fallback safety
    if err:
        return {"action": "stop", "error": err}

    return action





"""
Tell the AI everything about the current project state.
Ask it what action should happen next.
Force it to answer in JSON.
Convert that JSON into a Python dictionary.
Return it.
"""