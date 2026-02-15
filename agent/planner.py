from agent.llm import call_llm
from agent.repo import build_repo_summary

def make_plan(goal: str, repo_root: str):

    repo_summary = build_repo_summary(repo_root)

    prompt = f"""
### SYSTEM
You are an execution-only coding agent.

Return ONLY numbered steps.
No chat.
No explanation.
No greeting.

### GOAL
{goal}

### FILES
{repo_summary}

### OUTPUT
"""


    output = call_llm(prompt)

    steps = []
    for line in output.splitlines():
        line = line.strip()
        if line:
            steps.append(line)

    return steps



"""
Ask the AI to make a numbered plan for the coding goal.
Take whatever text it writes.
Split it into lines.
Remove blank junk.
Return the lines as a Python list.
"""