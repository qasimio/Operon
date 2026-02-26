# agent/approval.py — Operon v3
import agent.logger


def ask_user_approval(action: str, payload: dict) -> bool:
    """
    For rewrite_function and create_file: show diff in TUI and block until user decides.
    All other actions: auto-approve.
    """
    if action in ("rewrite_function", "create_file"):
        file_path = payload.get("file") or payload.get("file_path", "unknown")
        search    = payload.get("search", "")
        replace   = payload.get("replace", payload.get("initial_content", ""))

        if agent.logger.UI_SHOW_DIFF:
            agent.logger.UI_SHOW_DIFF(file_path, search, replace)
        else:
            # Headless fallback: auto-approve
            return True

        agent.logger.log.info(
            "[bold red]⚠️  WAITING FOR APPROVAL[/bold red] — review the diff panel."
        )
        result = agent.logger.APPROVAL_QUEUE.get()

        if result:
            agent.logger.log.info("[bold green]✅ Patch approved.[/bold green]")
        else:
            agent.logger.log.warning("[bold red]❌ Patch rejected by user.[/bold red]")
        return result

    return True