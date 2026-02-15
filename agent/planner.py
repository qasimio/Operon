# agent/planner.py
from agent.llm import call_llm
import os
from pathlib import Path
from typing import List

def build_repo_summary(repo_root: str, max_files: int = 20, max_bytes: int = 2000) -> str:
    """
    Make a short repo summary: top-level file list and small previews of a few files
    to keep context size reasonable for 7B models.
    """
    p = Path(repo_root)
    entries = []
    count = 0
    for root, dirs, files in os.walk(repo_root):
        # skip hidden and .git
        if ".git" in root.split(os.sep):
            continue
        for f in files:
            if count >= max_files:
                break
            fp = Path(root) / f
            try:
                preview = fp.read_text(encoding="utf-8", errors="ignore")[:max_bytes]
            except Exception:
                preview = "<unreadable>"
            rel = str(fp.relative_to(p))
            entries.append(f"FILE: {rel}\nPREVIEW:\n{preview}\n---")
            count += 1
        if count >= max_files:
            break
    return "\n".join(entries)

def make_plan(goal: str, repo_root: str) -> List[str]:
    repo_summary = build_repo_summary(repo_root)
    prompt = f"""
You are a pragmatic junior software engineer with strict discipline. 

Goal:
{goal}

Short repository summary (few files with short previews):
{repo_summary}

Return a short, numbered, step-by-step plan to accomplish the Goal.
Do not include any extra commentary.
"""
    output = call_llm(prompt)
    # return cleaned lines, drop empty
    lines = [l.strip() for l in output.splitlines() if l.strip()]
    # collapse lines starting with numbers into step strings
    steps = []
    for line in lines:
        # optionally strip leading numbering
        line = line.lstrip("0123456789. )\t")
        steps.append(line)
    return steps




"""
Ask the AI to make a numbered plan for the coding goal.
Take whatever text it writes.
Split it into lines.
Remove blank junk.
Return the lines as a Python list.
"""