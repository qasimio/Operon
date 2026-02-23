import agent.logger

def ask_user_approval(action: str, payload: dict) -> bool:
    """
    Pauses the worker thread and forces the TUI to mount an approval dialogue.
    """
    if action == "rewrite_function":
        file_path = payload.get("file", "unknown")
        search = payload.get("search", "# ⚠️ Error: Search block missing from payload")
        replace = payload.get("replace", "# ⚠️ Error: Replace block missing from payload")
        
        # Access the LIVE reference from the module namespace!
        if agent.logger.UI_SHOW_DIFF:
            agent.logger.UI_SHOW_DIFF(file_path, search, replace)
            
        agent.logger.log.info("[bold red]⚠️ WAITING FOR APPROVAL:[/bold red] Please check the right panel.")
        
        # Freeze this thread until the UI pushes a result into the queue
        result = agent.logger.APPROVAL_QUEUE.get() 
        
        if result:
            agent.logger.log.info("[bold green]✅ Patch Approved by User.[/bold green]")
        else:
            agent.logger.log.warning("[bold red]❌ Patch REJECTED by User.[/bold red]")
            
        return result
        
    return True