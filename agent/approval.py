# agent/approval.py
from agent.logger import log

def ask_user_approval(action: str, payload: dict) -> bool:
    """
    Phase 1: Auto-approve all actions to prevent TUI thread locking.
    Interactive approval widget will be introduced in Phase 3.
    """
    log.info(f"[bold cyan]Auto-approving action:[/bold cyan] {action}")
    return True