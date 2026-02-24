# agent/approval.py
from rich.console import Console
from rich.panel import Panel

console = Console()

def ask_user_approval(tool_name: str, payload: dict) -> bool:
    """Forces the terminal to stop and wait for a human."""
    
    if tool_name == "edit_files":
        console.print(Panel.fit(
            f"[bold cyan]File:[/bold cyan] {payload.get('file')}\n\n"
            f"[bold red]<<<<<<< SEARCH (Removing)[/bold red]\n{payload.get('search')}\n"
            f"[bold green]======= REPLACE (Adding)[/bold green]\n{payload.get('replace')}\n"
            f"[bold blue]>>>>>>>[/bold blue]",
            title="⚠️ OPERON WANTS TO MODIFY CODE ⚠️",
            border_style="yellow"
        ))
    
    while True:
        # This input() literally freezes the python process until you hit Enter
        response = input("\nApprove this change? (y/n/exit): ").strip().lower()
        if response in ['y', 'yes']:
            return True
        elif response in ['n', 'no']:
            return False
        elif response == 'exit':
            console.print("[bold red]Aborting entirely.[/bold red]")
            exit(0)
        else:
            print("Invalid input. Type 'y' or 'n'.")