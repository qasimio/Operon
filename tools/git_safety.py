# tools/git_safety.py
import subprocess
import uuid
from agent.logger import log

def run_git(cmd: list, repo_root: str) -> str:
    """Helper to run git commands safely and return stripped stdout."""
    try:
        res = subprocess.run(cmd, cwd=repo_root, check=True, capture_output=True, text=True)
        return res.stdout.strip()
    except subprocess.CalledProcessError:
        return ""

def setup_git_env(repo_root: str) -> dict:
    """Sets up the branch and tracks the initial state before Operon starts."""
    if run_git(["git", "rev-parse", "--is-inside-work-tree"], repo_root) != "true":
        log.warning("Not a git repository. Git macro-safety disabled.")
        return {}

    current_branch = run_git(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo_root)
    initial_commit = run_git(["git", "rev-parse", "HEAD"], repo_root)
    
    target_branch = current_branch
    
    # If on main/master, branch off automatically
    if current_branch in ["main", "master"]:
        uid = str(uuid.uuid4())[:6]
        target_branch = f"operon/task-{uid}"
        run_git(["git", "checkout", "-b", target_branch], repo_root)
        log.info(f"[bold green]🌿 Protected 'main'. Switched to new branch: {target_branch}[/bold green]")
    else:
        log.info(f"🌿 Operating safely on current branch: {current_branch}")

    return {
        "initial_branch": current_branch,
        "target_branch": target_branch,
        "initial_commit": initial_commit
    }

def rollback_macro(repo_root: str, git_state: dict):
    """Nukes all failed changes and restores the exact starting state."""
    if not git_state: 
        return
        
    log.error("[bold red]🚨 TASK ABORTED. Executing Macro-Rollback...[/bold red]")
    
    # 1. Reset all tracked files to the initial commit hash
    run_git(["git", "reset", "--hard", git_state["initial_commit"]], repo_root)
    
    # 2. Clean up any untracked files/garbage Operon created
    run_git(["git", "clean", "-fd"], repo_root)
    
    # 3. If we created a temporary branch, go back to main and delete the failed branch
    if git_state["initial_branch"] != git_state["target_branch"]:
        run_git(["git", "checkout", git_state["initial_branch"]], repo_root)
        run_git(["git", "branch", "-D", git_state["target_branch"]], repo_root)
        
    log.info("[bold green]✅ Rollback complete. Your code is completely untouched.[/bold green]")

def commit_success(repo_root: str, message: str):
    """Stages and commits successful work with the Operon prefix."""
    if run_git(["git", "rev-parse", "--is-inside-work-tree"], repo_root) != "true":
        return
        
    status = run_git(["git", "status", "--porcelain"], repo_root)
    if not status:
        log.info("No file changes detected to commit.")
        return
        
    run_git(["git", "add", "."], repo_root)
    
    # Sanitize message to prevent bash injection
    safe_msg = message.replace('"', "'")
    run_git(["git", "commit", "-m", f"[Operon] {safe_msg}"], repo_root)
    log.info(f"[bold green]📦 Code successfully committed: [Operon] {safe_msg}[/bold green]")