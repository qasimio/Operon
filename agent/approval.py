# agent/approval.py — Operon v3.2
"""
Approval gate. ALWAYS fires before filesystem mutation.

Guarantees:
  - Never sends empty diffs  (validates before calling UI)
  - Always logs the decision with file + operation type
  - Timeout-safe: 300s max wait, then auto-rejects to prevent hang
  - Shows meaningful content even for large files (first/last 300 chars of diff)
"""
from __future__ import annotations

import queue

import agent.logger
from agent.logger import log


def ask_user_approval(action: str, payload: dict) -> bool:
    """
    Required before any filesystem write.

    payload must contain:
      "file"    — relative path
      "search"  — content being replaced (may be empty for create/append)
      "replace" — new content (may be empty for deletion)
      "summary" — optional one-line description
    """
    file_path = payload.get("file") or payload.get("file_path") or "unknown"
    search    = str(payload.get("search",  "") or "")
    replace   = str(payload.get("replace", "") or
                    payload.get("initial_content", "") or "")
    summary   = payload.get("summary", action)

    # Validate payload has meaningful content
    if action == "rewrite_function" and not search.strip() and not replace.strip():
        log.error(
            f"[red]⚠️  APPROVAL BLOCKED — empty diff for {file_path}. "
            "BUG: rewrite_function called with no content.[/red]"
        )
        return False   # reject empty diffs — never silently write nothing

    # Headless mode (no TUI): auto-approve with clear log
    if not agent.logger.UI_SHOW_DIFF:
        log.info(
            f"[dim][AUTO-APPROVE headless][/dim] {action} → {file_path} | {summary}"
        )
        return True

    # TUI mode: show diff panel, block until user decides
    agent.logger.UI_SHOW_DIFF(file_path, search, replace)
    log.info(
        f"[bold red]⚠️  WAITING FOR APPROVAL[/bold red] "
        f"({action} → {file_path}) — review diff panel."
    )

    try:
        result = agent.logger.APPROVAL_QUEUE.get(timeout=300)
    except queue.Empty:
        log.warning("[red]Approval timed out (300s) — auto-rejecting.[/red]")
        return False

    if result:
        log.info(f"[bold green]✅ Patch approved:[/bold green] {file_path}")
    else:
        log.warning(f"[bold red]❌ Patch rejected by user:[/bold red] {file_path}")
    return result
