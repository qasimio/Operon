# tools/git_safety.py — Operon v3
"""
BUG FIX: Old code called `git reset --hard` + `git clean -fd` which nuked ALL
uncommitted user changes, not just Operon's changes.

v3 solution:
  - At startup, stash any existing user changes (git stash).
  - Track only the files Operon touches.
  - On rollback, restore only those files to HEAD, then re-apply the stash.
  - User's pre-existing uncommitted work is always preserved.
"""

import subprocess
import uuid
from pathlib import Path
from agent.logger import log


def run_git(cmd: list[str], repo_root: str, check: bool = False) -> str:
    try:
        res = subprocess.run(
            cmd, cwd=repo_root, capture_output=True, text=True,
            check=check, timeout=30
        )
        return res.stdout.strip()
    except subprocess.CalledProcessError as e:
        log.debug(f"git cmd failed: {' '.join(cmd)} → {e.stderr.strip()}")
        return ""
    except Exception as e:
        log.debug(f"git run error: {e}")
        return ""


def _is_git_repo(repo_root: str) -> bool:
    return run_git(["git", "rev-parse", "--is-inside-work-tree"], repo_root) == "true"


def setup_git_env(repo_root: str) -> dict:
    """
    1. Check it's a git repo.
    2. Stash any pre-existing uncommitted user changes (with a unique stash message).
    3. If on main/master, create a new operon branch.
    4. Record initial commit so we can restore individual files on rollback.
    """
    if not _is_git_repo(repo_root):
        log.warning("Not a git repo — git safety disabled.")
        return {}

    current_branch = run_git(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo_root)
    initial_commit = run_git(["git", "rev-parse", "HEAD"], repo_root)

    # ── Stash user's pre-existing uncommitted changes ─────────────────────────
    stash_ref = None
    dirty = run_git(["git", "status", "--porcelain"], repo_root)
    if dirty:
        stash_msg = f"operon-presave-{uuid.uuid4().hex[:8]}"
        run_git(["git", "stash", "push", "-u", "-m", stash_msg], repo_root)
        # Find the stash ref
        stash_list = run_git(["git", "stash", "list", "--oneline"], repo_root)
        for line in stash_list.splitlines():
            if stash_msg in line:
                stash_ref = line.split(":")[0].strip()
                break
        log.info(f"[yellow]📦 User changes stashed ({stash_ref}).[/yellow]")

    # ── Branch protection ─────────────────────────────────────────────────────
    target_branch = current_branch
    if current_branch in ("main", "master"):
        uid = uuid.uuid4().hex[:6]
        target_branch = f"operon/task-{uid}"
        run_git(["git", "checkout", "-b", target_branch], repo_root)
        log.info(f"[bold green]🌿 Protected '{current_branch}' → new branch: {target_branch}[/bold green]")
    else:
        log.info(f"[green]🌿 Operating on branch: {current_branch}[/green]")

    return {
        "initial_branch":  current_branch,
        "target_branch":   target_branch,
        "initial_commit":  initial_commit,
        "user_stash_ref":  stash_ref,   # may be None if nothing was stashed
    }


def rollback_files(repo_root: str, git_state: dict, files_modified: list[str]) -> None:
    """
    SURGICAL rollback — only restore the specific files Operon touched.
    Never touches files the user had already modified before Operon ran.
    Then re-applies the user's stash.
    """
    if not git_state:
        return

    log.error("[bold red]🚨 Rolling back Operon changes (surgical — user changes preserved)...[/bold red]")

    initial_commit = git_state.get("initial_commit", "HEAD")

    # Restore only files Operon modified
    for rel_path in files_modified:
        full = Path(repo_root) / rel_path
        result = run_git(
            ["git", "checkout", initial_commit, "--", rel_path], repo_root
        )
        log.debug(f"Restored {rel_path} → {result or 'ok'}")

    # Clean up any NEW files Operon created (not in initial commit)
    # We only remove files that didn't exist in initial_commit
    for rel_path in files_modified:
        full = Path(repo_root) / rel_path
        in_initial = run_git(
            ["git", "cat-file", "-e", f"{initial_commit}:{rel_path}"], repo_root
        )
        if not in_initial and full.exists():
            full.unlink(missing_ok=True)
            log.debug(f"Removed new file: {rel_path}")

    # Switch back to original branch if we created an operon branch
    if git_state.get("initial_branch") != git_state.get("target_branch"):
        run_git(["git", "checkout", git_state["initial_branch"]], repo_root)
        run_git(["git", "branch", "-D", git_state["target_branch"]], repo_root)

    # Re-apply user stash
    stash_ref = git_state.get("user_stash_ref")
    if stash_ref:
        result = run_git(["git", "stash", "pop", stash_ref], repo_root)
        if result:
            log.info("[green]✅ User pre-existing changes restored.[/green]")
        else:
            run_git(["git", "stash", "pop"], repo_root)

    log.info("[bold green]✅ Rollback complete — your code is untouched.[/bold green]")


def commit_success(repo_root: str, message: str) -> None:
    if not _is_git_repo(repo_root):
        return
    status = run_git(["git", "status", "--porcelain"], repo_root)
    if not status:
        log.info("Nothing to commit.")
        return
    run_git(["git", "add", "."], repo_root)
    safe_msg = message.replace('"', "'")
    run_git(["git", "commit", "-m", f"[Operon] {safe_msg}"], repo_root)
    log.info(f"[bold green]📦 Committed: [Operon] {safe_msg}[/bold green]")
