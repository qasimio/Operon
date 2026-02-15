# tools/git_tools.py
import subprocess
from typing import Dict
import datetime

def run_git(cmd: list, repo_root: str) -> Dict:
    try:
        result = subprocess.run(
            ["git"] + cmd,
            cwd=repo_root,
            capture_output=True,
            text=True
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

def create_branch(name: str, repo_root: str) -> Dict:
    return run_git(["checkout", "-b", name], repo_root)

def stage_all(repo_root: str) -> Dict:
    return run_git(["add", "-A"], repo_root)

def commit(message: str, repo_root: str) -> Dict:
    # stage then commit
    s = stage_all(repo_root)
    if not s.get("success", False):
        return {"success": False, "error": "git add failed", "detail": s}
    return run_git(["commit", "-m", message], repo_root)

def push_current_branch(repo_root: str, remote: str = "origin") -> Dict:
    # get current branch
    br = run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo_root)
    if not br.get("success", False):
        return {"success": False, "error": "cannot determine branch", "detail": br}
    branch = br["stdout"].strip()
    return run_git(["push", remote, branch], repo_root)

def commit_to_new_branch(branch_prefix: str, message: str, repo_root: str) -> Dict:
    ts = datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S")
    branch = f"{branch_prefix}-{ts}"
    cb = create_branch(branch, repo_root)
    if not cb.get("success", False):
        return {"success": False, "error": "create_branch failed", "detail": cb}
    c = commit(message, repo_root)
    if not c.get("success", False):
        return {"success": False, "error": "commit failed", "detail": c}
    p = push_current_branch(repo_root)
    # do not fail hard on push problems (user may not have remote configured)
    return {"success": True, "branch": branch, "commit": c, "push": p}


"""
run_git       → run a git command and tell me if it worked
create_branch → use git to make a new branch
commit        → use git to save changes with a message

"""