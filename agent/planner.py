from agent.llm import call_llm


def make_plan(goal: str, repo_root: str):

    prompt = f"""
You are planning for an automated software agent.

STRICT RULES:

- NEVER invent new files
- NEVER mention git commands
- NEVER mention shell commands
- ONLY describe logical editing steps

Return 3–5 short steps only.
One step per line.

GOAL:
{goal}
"""

    output = call_llm(prompt)

    steps = []

    for line in output.splitlines():
        line = line.strip()
        if line:
            steps.append(line)

    if not steps:
        steps = [
            "Locate target file",
            "Read the file",
            "Modify content according to goal",
            "Write updated file",
            "Finish"
        ]

    return steps[:6]
