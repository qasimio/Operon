from agent.llm import call_llm


def make_plan(goal: str, repo_root: str):

    prompt = f'''
You are the Planning Module for an automated software agent.

GOAL: {goal}

STRICT RULES:
1. DO NOT WRITE ANY CODE.
2. Outline 3-5 high-level logical steps to achieve the goal.
3. Keep steps short and action-oriented.
4. Output one step per line.
'''

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

    return steps[:10]
