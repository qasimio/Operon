from agent.llm import call_llm
from tools.repo_search import search_repo
import json
import re
from agent.logger import log

def make_plan(goal: str, repo_root: str):
    log.info("[bold magenta]🏛️ ARCHITECT: Gathering context for plan...[/bold magenta]")
    
    context = search_repo(repo_root, goal)
    
    prompt = f"""You are the ARCHITECT of an elite AI engineering team.
GOAL: {goal}
CONTEXT (Semantic Search Matches): {context}

Your job is to analyze the goal and write a strict step-by-step plan.
Determine if the goal is a QUESTION (no code changes needed) or a TASK (requires modifying files).

CRITICAL RULES:
1. You MUST provide at least one step in the "steps" array. It CANNOT be empty.
2. If the user is asking a question, create steps to find the answer (e.g., "1. Search for relevant code", "2. Read the files", "3. Formulate the answer").
3. If the user is giving multiple tasks (e.g. "change X and add Y"), break them into distinct steps.

Output strictly in JSON format:
{{
    "is_question": true or false,
    "steps": [
        "1. Search for X",
        "2. Read file Y",
        "3. Rewrite function Z or Answer the question"
    ]
}}
"""
    raw_output = call_llm(prompt, require_json=True)
    clean_json = re.sub(r"```(?:json)?\n?(.*?)\n?```", r"\1", raw_output, flags=re.DOTALL).strip()
    
    try:
        data = json.loads(clean_json)
        steps = data.get("steps", [])
        if not steps:
            # Fallback to prevent empty plan crashes
            steps = ["1. Investigate the codebase", "2. Complete the objective"]
        return steps, data.get("is_question", False)
    except json.JSONDecodeError:
        log.error("Architect failed to output JSON. Falling back to default plan.")
        return ["1. Search for context", "2. Read the file", "3. Complete the task"], False