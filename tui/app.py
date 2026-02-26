# tui/app.py — Operon v2 (full drop-in replacement)
import os
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.widgets import Header, Footer, RichLog, Input, Static, Button
from textual.events import Key
from rich.panel import Panel
from rich.console import Group
from rich.syntax import Syntax
from typing import cast

from runtime.state import AgentState
from agent.loop import run_agent
import agent.logger
from tools.diff_report import dump_diff_report_from_repo


class DiffApproval(Vertical):
    """Widget shown when a patch needs approval."""

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
        # Use python lexer as fallback — works for most code
        lang = "python"
        if self.filename.endswith((".js", ".jsx", ".ts", ".tsx")):
            lang = "javascript"
        elif self.filename.endswith(".java"):
            lang = "java"

        search_syntax = Syntax(self.search or "(empty)", lang, theme="monokai", line_numbers=True, word_wrap=True)
        replace_syntax = Syntax(self.replace or "(empty — deletion)", lang, theme="monokai", line_numbers=True, word_wrap=True)
        diff_view = Group(
            Panel(search_syntax, title="[bold red]Old Code / SEARCH[/bold red]", border_style="red"),
            Panel(replace_syntax, title="[bold green]New Code / REPLACE[/bold green]", border_style="green"),
        )
        self.query_one("#diff-area", Static).update(diff_view)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-approve":
            cast("OperonUI", self.app).resolve_approval(True)
        elif event.button.id == "btn-reject":
            cast("OperonUI", self.app).resolve_approval(False)


class OperonUI(App):

    CSS = """
    Screen { background: $surface; }
    #chat-pane { width: 45%; border-right: solid $primary; padding: 1; height: 100%; }
    #workspace-pane { width: 55%; padding: 1; height: 100%; }
    RichLog { background: $surface; border: none; height: 1fr; }
    Input { dock: bottom; margin-top: 1; }
    .diff-title { text-style: bold; color: magenta; margin-bottom: 1; }
    .diff-buttons { height: 3; align: center middle; dock: bottom; margin-top: 1; }
    Button { margin: 0 2; }
    #diff-scroll { height: 1fr; overflow-y: auto; }
    #index-status { color: $accent; text-style: italic; }
    """

    BINDINGS = [("ctrl+c", "quit", "Quit")]

    # ── Layout ────────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal():
            with Vertical(id="chat-pane"):
                yield RichLog(id="chat-log", highlight=True, markup=True)
                yield Static("🔍 Indexing repo...", id="index-status")
                yield Input(
                    placeholder="Ask Operon... ( /clear /quit /diff /status )",
                    id="prompt-input"
                )
            with Vertical(id="workspace-pane"):
                yield Static("Workspace & Diff Preview will appear here.", id="workspace-view")
        yield Footer()

    # ── Startup ───────────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        self.title = "Operon v2 — Autonomous SWE"
        log_widget = self.query_one("#chat-log", RichLog)
        log_widget.write("[bold blue]🧬 Operon v2 ready — 4-Level Intelligence Indexing...[/bold blue]")

        agent.logger.UI_CALLBACK = self.safe_update_log
        agent.logger.UI_SHOW_DIFF = self.safe_show_diff
        self.last_state = None

        # Pre-build a shared AgentState to hold the 4-level index
        self._index_state = AgentState(goal="__index__", repo_root=os.getcwd())
        self.run_worker(self._background_index, exclusive=True, thread=True)

    def _background_index(self) -> None:
        """Background: Level 1 (LanceDB semantic) + Levels 2-4 (symbol/dep/ast)."""
        try:
            from tools.semantic_memory import index_repo
            index_repo(os.getcwd())
        except Exception as e:
            agent.logger.log.error(f"Semantic memory failed: {e}")

        try:
            from tools.repo_index import build_full_index
            build_full_index(self._index_state)
            self.call_from_thread(
                lambda: self.query_one("#index-status", Static).update(
                    "✅ 4-Level index ready"
                )
            )
            agent.logger.log.info("[bold green]🧠 4-level index ready.[/bold green]")
        except Exception as e:
            agent.logger.log.error(f"4-level index failed: {e}")
            self.call_from_thread(
                lambda: self.query_one("#index-status", Static).update("⚠️ Index partial")
            )

    # ── Key handler ───────────────────────────────────────────────────────────

    def on_key(self, event: Key) -> None:
        input_box = self.query_one("#prompt-input", Input)
        if input_box.disabled and event.character:
            c = event.character.lower()
            if c == "y":
                self.resolve_approval(True)
            elif c == "n":
                self.resolve_approval(False)

    # ── Command handler ───────────────────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.value = ""
        log_widget = self.query_one("#chat-log", RichLog)

        if text == "/quit":
            self.exit()
            return
        if text == "/clear":
            log_widget.clear()
            return
        if text == "/diff":
            if self.last_state:
                try:
                    path = dump_diff_report_from_repo(self.last_state.repo_root)
                    log_widget.write(f"[bold cyan]Diff report → {path}[/bold cyan]")
                except Exception as e:
                    log_widget.write(f"[red]Diff dump failed: {e}[/red]")
            else:
                log_widget.write("No session yet.")
            return
        if text == "/status":
            if self.last_state:
                s = self.last_state
                log_widget.write(
                    f"[cyan]Steps: {s.step_count} | Phase: {s.phase} | "
                    f"Modified: {s.files_modified} | "
                    f"Symbol files: {len(s.symbol_index)} | "
                    f"Dep nodes: {len(s.dep_graph)}[/cyan]"
                )
            else:
                log_widget.write("No session yet.")
            return

        log_widget.write(f"\n[bold green]User:[/bold green] {text}")
        self.run_worker(lambda: self.execute_agent(text), exclusive=True, thread=True)

    # ── Run agent ─────────────────────────────────────────────────────────────

    def execute_agent(self, goal: str) -> None:
        state = AgentState(goal=goal, repo_root=os.getcwd())

        # Inject pre-built 4-level index from background thread (avoid re-building)
        if hasattr(self, "_index_state"):
            state.symbol_index = self._index_state.symbol_index
            state.dep_graph = self._index_state.dep_graph
            state.ast_cache = self._index_state.ast_cache

        agent.logger.log.info("[bold yellow]⚙️ Operon Engine starting...[/bold yellow]")
        run_agent(state)
        self.last_state = state
        agent.logger.log.info(f"[bold blue]🏁 Session done in {state.step_count} steps.[/bold blue]")

        try:
            path = dump_diff_report_from_repo(state.repo_root)
            agent.logger.log.info(f"[bold cyan]📄 Diff report → {path}[/bold cyan]")
        except Exception:
            pass

    # ── UI bridge ─────────────────────────────────────────────────────────────

    def safe_update_log(self, message: str) -> None:
        self.call_from_thread(lambda: self.query_one("#chat-log", RichLog).write(message))

    def safe_show_diff(self, filename: str, search: str, replace: str) -> None:
        self.call_from_thread(self._render_approval_ui, filename, search, replace)

    def _render_approval_ui(self, filename: str, search: str, replace: str) -> None:
        self.query_one("#prompt-input", Input).disabled = True
        workspace = self.query_one("#workspace-pane", Vertical)
        for c in workspace.children:
            c.remove()
        workspace.mount(DiffApproval(filename, search, replace))

    def resolve_approval(self, approved: bool) -> None:
        agent.logger.APPROVAL_QUEUE.put(approved)
        workspace = self.query_one("#workspace-pane", Vertical)
        for c in workspace.children:
            c.remove()
        workspace.mount(Static("Workspace cleared. Engine resuming...", id="workspace-view"))
        box = self.query_one("#prompt-input", Input)
        box.disabled = False
        box.focus()
