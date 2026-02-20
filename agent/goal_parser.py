# agent/goal_parser.py
import re
from pathlib import Path

# allowed file extensions we accept as targets (lowercase, no leading dot)
_ALLOWED_EXT = {"md", "markdown", "txt", "py", "toml", "json", "yaml", "yml", "cfg", "ini", "rst", "mdx"}

def _looks_like_file(candidate: str) -> bool:
    parts = candidate.split(".")
    if len(parts) < 2:
        return False
    ext = parts[-1].lower()
    return ext in _ALLOWED_EXT

def extract_target_files(repo_root: str, goal: str):
    """
    Return filenames mentioned in the goal that are either existing in the repo
    or look like sane files (allowed extensions). Keep order and uniqueness.
    """
    repo = Path(repo_root)
    # find tokens like some/path/file.ext
    matches = re.findall(r'[\w\-/]+\.\w+', goal)
    seen = []
    for m in matches:
        p = repo / Path(m)
        if p.exists():
            candidate = str(Path(m).as_posix())
            if candidate not in seen:
                seen.append(candidate)
            continue
        # keep if extension is in allowed list (even if file doesn't yet exist)
        if _looks_like_file(m):
            candidate = str(Path(m).as_posix())
            if candidate not in seen:
                seen.append(candidate)
    return seen

def parse_write_instruction(goal: str, repo_root: str | None = None):

    g = goal.strip()
    lower = g.lower()

    # 🚨 CRITICAL: if goal is modification instruction, DO NOT convert to direct write
    # this forces the loop to call the LLM generator instead of appending English text
    BLOCK_WORDS = ("modify", "update", "fix", "change", "refactor", "improve")

    if any(w in lower for w in BLOCK_WORDS):
        return None

    # detect overwrite vs append
    if "overwrite" in lower or "replace" in lower:
        mode = "overwrite"
    else:
        mode = "append"

    # quoted content first
    m = re.search(
        r'(?:append|add|write|insert|overwrite|replace)\s+[\'"](.+?)[\'"]\s+(?:to|in|into)\s+([\w\-/\.]+)',
        g,
        flags=re.IGNORECASE
    )

    if not m:
        m = re.search(
            r'(?:append|add|write|insert|overwrite|replace)\s+(.+?)\s+(?:to|in|into)\s+([\w\-/\.]+)',
            g,
            flags=re.IGNORECASE
        )

    if not m:
        return None

    content = m.group(1).strip()
    path = m.group(2).strip()

    if repo_root:
        repo = Path(repo_root)
        p = repo / Path(path)
        if not p.exists() and "." not in path:
            return None

    return {
        "action": "write_file",
        "path": Path(path).as_posix(),
        "content": content,
        "mode": mode
    }

def extract_multiline_append(goal: str):

    """
    Detect goals like:

    Append the following code ... to file X:

    <MULTILINE BLOCK>

    Returns:
    {"path": "...", "content": "...", "mode":"append"}
    """

    import re

    # find file target first
    m = re.search(r'file\s+([\w\-/\.]+)', goal, re.IGNORECASE)
    if not m:
        return None

    path = m.group(1)

    # everything after first blank line is treated as payload
    parts = goal.split("\n\n", 1)

    if len(parts) < 2:
        return None

    payload = parts[1].strip()

    if not payload:
        return None

    return {
        "action": "write_file",
        "path": path,
        "content": "\n" + payload + "\n",
        "mode": "append"
    }
