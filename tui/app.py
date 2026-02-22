from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Footer, RichLog, Input, Static
from textual.worker import get_current_worker
from rich.text import Text
from rich.panel import Panel
from rich.console import Group
from rich.syntax import Syntax
import agent.logger

import os


class OperonUI(App):
    """The official TUI for Operon."""

    CSS = """
    Screen {
        background: $surface;
    }
    #chat-pane {
        width: 40%;
        border-right: solid $primary;
        padding: 1;
    }
    #workspace-pane {
        width: 60%;
        padding: 1;
    }
    RichLog {
        background: $surface;
        border: none;
    }
    Input {
        dock: bottom;
        margin-top: 1;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("ctrl+c", "quit", "Quit"),
    ]

    # ---------- UI LAYOUT ----------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Horizontal():

            # LEFT: chat / agent thoughts
            with Vertical(id="chat-pane"):
                yield RichLog(id="chat-log", highlight=True, markup=True)
                yield Input(
                    placeholder="Ask Operon to do something...",
                    id="prompt-input"
                )

            # RIGHT: workspace preview
            with Vertical(id="workspace-pane"):
                yield Static(
                    "Workspace & Diff Preview will appear here.",
                    id="workspace-view"
                )

        yield Footer()

    # ---------- STARTUP ----------

    def on_mount(self) -> None:
        self.title = "Operon - Autonomous SWE"

        log_widget = self.query_one("#chat-log", RichLog)
        log_widget.write("[bold blue]🚀 Operon TUI Initialized.[/bold blue]")
        log_widget.write("Type your goal below and press Enter.")

        # Hook agent logger -> UI
        agent.logger.UI_CALLBACK = self.safe_update_log
        agent.logger.DIFF_CALLBACK = self.safe_show_diff

    # ---------- USER INPUT ----------

    def on_input_submitted(self, event: Input.Submitted) -> None:
        user_prompt = event.value
        if not user_prompt.strip():
            return

        event.input.value = ""

        self.query_one("#chat-log", RichLog).write(
            f"\n[bold green]User:[/bold green] {user_prompt}"
        )

        # Run engine in background worker thread
        self.run_worker(
            self.execute_agent(user_prompt),
            exclusive=True,
            thread=True,
        )

    # ---------- ENGINE THREAD ----------

    async def execute_agent(self, goal: str) -> None:
        """Runs the Operon engine in a background thread."""
        from runtime.state import AgentState
        from agent.loop import run_agent
        from agent.logger import log

        state = AgentState(
            goal=goal,
            repo_root=os.getcwd(),   # dynamic repo execution
        )

        log.info("[bold yellow]⚙️ Spinning up Operon Engine...[/bold yellow]")

        run_agent(state)

        log.info(
            f"[bold blue]🏁 Session finished in {state.step_count} steps.[/bold blue]"
        )

    # ---------- THREAD-SAFE LOGGING ----------

    def safe_update_log(self, message: str) -> None:
        """Called by logger from background threads."""
        self.call_from_thread(self._write_to_log, message)

    def _write_to_log(self, message: str) -> None:
        log_widget = self.query_one("#chat-log", RichLog)
        log_widget.write(message)
    

    # tui/app.py (Add inside OperonUI class)

    def safe_show_diff(self, filename: str, search: str, replace: str) -> None:
        """Thread-safe call to update the workspace pane."""
        self.call_from_thread(self._render_diff, filename, search, replace)

    def _render_diff(self, filename: str, search: str, replace: str) -> None:
        """Draws a beautiful before/after diff in the right panel."""
        workspace = self.query_one("#workspace-view", Static)
        
        # Format the code blocks with syntax highlighting
        search_syntax = Syntax(search, "python", theme="monokai", line_numbers=True)
        replace_syntax = Syntax(replace, "python", theme="monokai", line_numbers=True)
        
        diff_view = Group(
            Text(f"File: {filename}", style="bold magenta"),
            Panel(search_syntax, title="[bold red]Old Code (Search)[/bold red]", border_style="red"),
            Panel(replace_syntax, title="[bold green]New Code (Replace)[/bold green]", border_style="green")
        )
        workspace.update(diff_view)

# ---------- ENTRY ----------

if __name__ == "__main__":
    OperonUI().run()