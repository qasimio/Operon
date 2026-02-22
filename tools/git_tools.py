# Replace top of tools/git_tools.py
import subprocess
import re
from agent.logger import log

def _run(cmd, cwd):
    r = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True
    )
    log.debug(f"GIT: {' '.join(cmd)}")
    if r.stdout:
        log.debug(r.stdout.strip())
    if r.stderr:
        log.debug(r.stderr.strip())
    return r


def _current_branch(repo_root):
    r = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo_root)
    return r.stdout.strip()


def _slugify(text):
    text = text.lower()
    text = re.sub(r'[^a-z0-9 ]', '', text)
    words = text.split()[:3]
    return "-".join(words) if words else "update"


def smart_commit_pipeline(goal, repo_root):

    branch = _current_branch(repo_root)

    # If on main/master → create feature branch
    if branch in ("main", "master"):
        slug = _slugify(goal)
        new_branch = f"agent/{slug}"
        _run(["git", "checkout", "-B", new_branch], repo_root)
        branch = new_branch

    # stage & commit
    _run(["git", "add", "."], repo_root)

    msg = f"[Operon Auto-Patch] {goal[:50].strip()}..."
    _run(["git", "commit", "-m", msg], repo_root)

    # push only if remote exists (ignore errors)
    _run(["git", "push", "-u", "origin", branch], repo_root)


"""
run_git       → run a git command and tell me if it worked
create_branch → use git to make a new branch
commit        → use git to save changes with a message

"""