import os
import sys
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.widgets import Header, Footer, RichLog, Input, Static, Button
from textual.events import Key
from rich.text import Text
from rich.panel import Panel
from rich.console import Group
from rich.syntax import Syntax
from typing import cast
from runtime.state import AgentState
from agent.loop import run_agent
import agent.logger

class DiffApproval(Vertical):
    """Dynamically injected widget for the right pane during approval."""
    def __init__(self, filename: str, search: str, replace: str, **kwargs):
        super().__init__(**kwargs)
        self.filename = filename
        self.search = search
        self.replace = replace

    def compose(self) -> ComposeResult:
        yield Static(f"⚠️ PENDING APPROVAL: {self.filename}", classes="diff-title")
        with ScrollableContainer(id="diff-scroll"):
            yield Static(id="diff-area")
        with Horizontal(classes="diff-buttons"):
            yield Button("Approve (y)", id="btn-approve", variant="success")
            yield Button("Reject (n)", id="btn-reject", variant="error")

    def on_mount(self) -> None:
        search_syntax = Syntax(self.search, "python", theme="monokai", line_numbers=True, word_wrap=True)
        replace_syntax = Syntax(self.replace, "python", theme="monokai", line_numbers=True, word_wrap=True)
        
        diff_view = Group(
            Panel(search_syntax, title="[bold red]Old Code[/bold red]", border_style="red"),
            Panel(replace_syntax, title="[bold green]New Code[/bold green]", border_style="green")
        )
        self.query_one("#diff-area", Static).update(diff_view)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        # Route button clicks to the App's resolver
        if event.button.id == "btn-approve":
            cast("OperonUI", self.app).resolve_approval(True)
        elif event.button.id == "btn-reject":
            cast("OperonUI", self.app).resolve_approval(False)

class OperonUI(App):
    """The official TUI for Operon."""
    
    CSS = """
    Screen { background: $surface; }
    #chat-pane { width: 45%; border-right: solid $primary; padding: 1; height: 100%; }
    #workspace-pane { width: 55%; padding: 1; height: 100%; }
    RichLog { background: $surface; border: none; height: 1fr; }
    Input { dock: bottom; margin-top: 1; }
    .diff-title { text-style: bold; color: magenta; margin-bottom: 1; }
    .diff-buttons { height: 3; align: center middle; dock: bottom; margin-top: 1;}
    Button { margin: 0 2; }
    #diff-scroll { height: 1fr; overflow-y: auto; }
    """

    BINDINGS = [("ctrl+c", "quit", "Quit")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal():
            with Vertical(id="chat-pane"):
                yield RichLog(id="chat-log", highlight=True, markup=True)
                yield Input(placeholder="Ask Operon... (or type /clear, /quit)", id="prompt-input")
            with Vertical(id="workspace-pane"):
                yield Static("Workspace & Diff Preview will appear here.", id="workspace-view")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "Operon - Autonomous SWE"
        log = self.query_one("#chat-log", RichLog)
        log.write("[bold blue] 🧬 **Operon** TUI Initialized.[/bold blue]")
        log.write("Type your goal below. Use Ctrl+Shift+V to paste.")
        
        # Hook up the bridges
        agent.logger.UI_CALLBACK = self.safe_update_log
        agent.logger.UI_SHOW_DIFF = self.safe_show_diff

        # ------- BACKGROUNT INDEXING ---------
        self.run_worker(self._background_index, exclusive=True, thread=True)

    def _background_index(self) -> None:
        """Indexes the repo into LanceDB on starup."""
        from tools.semantic_memory import index_repo
        try:
            index_repo(os.getcwd())
        except Exception as e:
            import agent.logger
            agent.logger.log.error(f"Failed to boot memory: {e}")


    def on_key(self, event: Key) -> None:
        """Global key interceptor for 'y' or 'n' when the input is disabled."""
        input_box = self.query_one("#prompt-input", Input)
        if input_box.disabled and event.character:
            char = event.character.lower()
            if char == "y":
                self.resolve_approval(True)
            elif char == "n":
                self.resolve_approval(False)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        user_prompt = event.value.strip()
        if not user_prompt: return
        event.input.value = ""
        
        if user_prompt == "/quit":
            self.exit()
            return
        elif user_prompt == "/clear":
            self.query_one("#chat-log", RichLog).clear()
            return
            
        self.query_one("#chat-log", RichLog).write(f"\n[bold green]User:[/bold green] {user_prompt}")
        self.run_worker(lambda: self.execute_agent(user_prompt), exclusive=True, thread=True)

    def execute_agent(self, goal: str) -> None:
        state = AgentState(goal=goal, repo_root=os.getcwd())
        agent.logger.log.info("[bold yellow]⚙️ Spinning up Operon Engine...[/bold yellow]")
        run_agent(state)
        agent.logger.log.info(f"[bold blue]🏁 Session finished in {state.step_count} steps.[/bold blue]")

    def safe_update_log(self, message: str) -> None:
        self.call_from_thread(self._write_to_log, message)

    def _write_to_log(self, message: str) -> None:
        self.query_one("#chat-log", RichLog).write(message)

    def safe_show_diff(self, filename: str, search: str, replace: str) -> None:
        self.call_from_thread(self._render_approval_ui, filename, search, replace)

    def _render_approval_ui(self, filename: str, search: str, replace: str) -> None:
        """Locks the UI and displays the diff widget in the workspace pane."""
        self.query_one("#prompt-input", Input).disabled = True
        
        workspace = self.query_one("#workspace-pane", Vertical)
        for child in workspace.children:
            child.remove()
            
        workspace.mount(DiffApproval(filename, search, replace))

    def resolve_approval(self, approved: bool) -> None:
        """Handles the y/n logic and resets the UI."""
        # 1. Unblock the background worker thread
        agent.logger.APPROVAL_QUEUE.put(approved)
        
        # 2. Reset the Workspace pane
        workspace = self.query_one("#workspace-pane", Vertical)
        for child in workspace.children:
            child.remove()
        workspace.mount(Static("Workspace cleared. Engine resuming...", id="workspace-view"))
        
        # 3. Re-enable the chat input
        input_box = self.query_one("#prompt-input", Input)
        input_box.disabled = False
        input_box.focus()