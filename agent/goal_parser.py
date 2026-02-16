import re

def extract_target_files(goal: str):
    """
    Pull filenames like readme.md, main.py, config.json from goal text.
    """
    matches = re.findall(r'\b[\w\-/]+\.\w+\b', goal.lower())
    return list(set(matches))
