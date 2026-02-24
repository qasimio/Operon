from agent.llm import call_llm
from tools.repo_search import search_repo
import json
import re
from agent.logger import log

def make_plan(goal: str, repo_root: str):
    log.info("[bold magenta]🏛️ ARCHITECT: Gathering context for plan...[/bold magenta]")
    
    context = search_repo(repo_root, goal)
    
    prompt = f"""You are Operon's ARCHITECT.
Your job is to break down the user's goal into logical, high-level MILESTONES.

USER GOAL: {goal}

CRITICAL RULES:
1. DO NOT output execution steps like "search for X", "read file Y", or "rewrite function". The Coder knows how to do its job.
2. Output ONLY the actual coding objectives.
3. Keep it as few steps as possible. If it's a simple task, a 1-step plan is perfect.

BAD PLAN:
1. Search for max_steps
2. Read the file
3. Add a comment
4. Save the file

GOOD PLAN:
1. Locate the 'max_steps' variable and add the required comment above it.

Output strictly a JSON list of strings.
    """
    # ... rest of your LLM call ...
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