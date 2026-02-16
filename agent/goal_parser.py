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
    """
    Parse goals like:
      append "TEXT" to readme.md
      add 'TEXT' in docs/notes.md
      write TEXT into README.md

    Returns a dict action or None.
    """
    g = goal.strip()

    # prefer quoted content
    m = re.search(r'(?:append|add|write|insert)\s+[\'"](.+?)[\'"]\s+(?:to|in|into)\s+([\w\-/\.]+)', g, flags=re.IGNORECASE)
    if not m:
        # fallback: take quoted-less form (less reliable)
        m = re.search(r'(?:append|add|write|insert)\s+(.+?)\s+(?:to|in|into)\s+([\w\-/\.]+)', g, flags=re.IGNORECASE)

    if not m:
        return None

    content = m.group(1).strip()
    path = m.group(2).strip()

    # verify path is acceptable
    if repo_root:
        repo = Path(repo_root)
        p = repo / Path(path)
        # allow if exists OR looks like known extension
        if not p.exists() and not _looks_like_file(path):
            return None
    else:
        if not _looks_like_file(path):
            return None

    return {
        "action": "write_file",
        "path": Path(path).as_posix(),
        "content": content,
        "mode": "append"
    }
