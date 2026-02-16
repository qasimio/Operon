from agent.llm import call_llm
from agent.repo import build_repo_summary

def make_plan(goal: str, repo_root: str):

    repo_summary = build_repo_summary(repo_root)

    prompt = f"""
You are an execution-only coding agent.

Your job: produce a SHORT actionable plan.

STRICT RULES:
- return between 3 and 6 steps ONLY
- each step must contain REAL TEXT
- do NOT return empty numbering
- do NOT explain anything
- do NOT chat
- output ONE step per line

GOAL:
{goal}

FILES:
{repo_summary}

PLAN:
"""

    output = call_llm(prompt)

    steps = []

    for line in output.splitlines():
        line = line.strip()

        if not line:
            continue

        # remove leading numbers like "1." or "2)"
        while len(line) > 0 and (line[0].isdigit() or line[0] in ". )-"):
            line = line[1:].strip()

        if len(line) > 3:  # ignore garbage like "1."
            steps.append(line)

    # 🚑 fallback if model still dumb
    if len(steps) == 0:
        steps = [
            "Locate target file",
            "Read the file",
            "Modify content according to goal",
            "Write updated file",
            "Finish"
        ]

    return steps[:6]



"""
Ask the AI to make a numbered plan for the coding goal.
Take whatever text it writes.
Split it into lines.
Remove blank junk.
Return the lines as a Python list.
"""