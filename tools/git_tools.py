import subprocess

def run_git(cmd, repo_root):
    result = subprocess.run(
        ["git"] + cmd,
        cwd=repo_root,
        capture_output=True,
        text=True
    )
    return {
        "success": result.returncode == 0,
        "stdout": result.stdout,
        "stderr": result.stderr
    }

def create_branch(name, repo_root):
    return run_git(["checkout", "-b", name], repo_root)

def commit(message, repo_root):
    return run_git(["commit", "-am", message], repo_root)


"""
run_git       → run a git command and tell me if it worked
create_branch → use git to make a new branch
commit        → use git to save changes with a message

"""