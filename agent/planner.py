from agent.llm import call_llm

def make_plan(goal: str, repo_summary: str) -> list:
    prompt = f"""
You are a junior software engineer.

Goal:
{goal}

Repository summary:
{repo_summary}

Return a numbered step-by-step plan.
No explanations.
"""
    output = call_llm(prompt)
    steps = [line.strip() for line in output.splitlines() if line.strip()]
    return steps




"""
Ask the AI to make a numbered plan for the coding goal.
Take whatever text it writes.
Split it into lines.
Remove blank junk.
Return the lines as a Python list.
"""