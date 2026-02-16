from agent.llm import call_llm
from agent.goal_parser import extract_target_files


def make_plan(goal: str, repo_root: str):

    targets = extract_target_files(repo_root, goal)

    prompt = f"""
You are planning for an automated software agent.

STRICT RULES:

- ONLY operate on these files: {targets}
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
