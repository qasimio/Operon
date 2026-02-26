# tui/app.py — Operon v3
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


# ─── Diff approval widget ─────────────────────────────────────────────────────

class DiffApproval(Vertical):
    def __init__(self, filename: str, search: str, replace: str, **kwargs):
        super().__init__(**kwargs)
        self.filename = filename
        self.search   = search
        self.replace  = replace

    def compose(self) -> ComposeResult:
        yield Static(f"⚠️  PENDING APPROVAL: {self.filename}", classes="diff-title")
        with ScrollableContainer(id="diff-scroll"):
            yield Static(id="diff-area")
        with Horizontal(classes="diff-buttons"):
            yield Button("✅ Approve  (y)", id="btn-approve", variant="success")
            yield Button("❌ Reject   (n)", id="btn-reject",  variant="error")

    def on_mount(self) -> None:
        ext  = self.filename.rsplit(".", 1)[-1].lower()
        lang = {"py": "python", "js": "javascript", "jsx": "javascript",
                "ts": "typescript", "tsx": "typescript", "java": "java"}.get(ext, "text")

        search_s  = Syntax(self.search  or "(empty — new content)", lang, theme="monokai", line_numbers=True, word_wrap=True)
        replace_s = Syntax(self.replace or "(empty — deletion)",     lang, theme="monokai", line_numbers=True, word_wrap=True)

        self.query_one("#diff-area", Static).update(Group(
            Panel(search_s,  title="[bold red]OLD / SEARCH[/bold red]",    border_style="red"),
            Panel(replace_s, title="[bold green]NEW / REPLACE[/bold green]", border_style="green"),
        ))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        app: OperonUI = cast("OperonUI", self.app)
        if event.button.id == "btn-approve":
            app.resolve_approval(True)
        elif event.button.id == "btn-reject":
            app.resolve_approval(False)


# ─── Main TUI ─────────────────────────────────────────────────────────────────

class OperonUI(App):

    CSS = """
    Screen { background: $surface; }
    #chat-pane      { width: 45%; border-right: solid $primary; padding: 1; height: 100%; }
    #workspace-pane { width: 55%; padding: 1; height: 100%; }
    RichLog         { height: 1fr; background: $surface; }
    Input           { dock: bottom; margin-top: 1; }
    #status-bar     { height: 1; color: $accent; text-style: italic; dock: bottom; }
    .diff-title     { text-style: bold; color: magenta; margin-bottom: 1; }
    .diff-buttons   { height: 3; align: center middle; dock: bottom; margin-top: 1; }
    Button          { margin: 0 2; }
    #diff-scroll    { height: 1fr; overflow-y: auto; }
    """

    BINDINGS = [("ctrl+c", "quit", "Quit")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal():
            with Vertical(id="chat-pane"):
                yield RichLog(id="chat-log", highlight=True, markup=True)
                yield Input(
                    placeholder="Ask Operon… ( /clear  /quit  /diff  /status  /files )",
                    id="prompt-input",
                )
            with Vertical(id="workspace-pane"):
                yield Static("Workspace — diff preview will appear here.", id="workspace-view")
        yield Static("🔍 Indexing…", id="status-bar")
        yield Footer()

    # ── Startup ───────────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        self.title = "Operon v3 — Autonomous SWE"
        self._log("🧬 [bold blue]Operon v3 ready[/bold blue] — building intelligence index…")

        agent.logger.UI_CALLBACK  = self.safe_log
        agent.logger.UI_SHOW_DIFF = self.safe_diff

        self.last_state: AgentState | None = None
        # Shared index state — built once, injected into every session
        self._index_state = AgentState(goal="__index__", repo_root=os.getcwd())
        self.run_worker(self._bg_index, exclusive=True, thread=True)

    def _bg_index(self) -> None:
        """Background: L1 semantic + L2-L4 symbol/dep/ast."""
        try:
            from tools.semantic_memory import index_repo
            index_repo(os.getcwd())
        except Exception as e:
            agent.logger.log.error(f"Semantic index failed: {e}")

        try:
            from tools.repo_index import build_full_index
            build_full_index(self._index_state)
            self._set_status(
                f"✅ Index ready — "
                f"{len(self._index_state.symbol_index)} files, "
                f"{len(self._index_state.file_tree)} total"
            )
            agent.logger.log.info("[bold green]🧠 4-level index ready.[/bold green]")
        except Exception as e:
            agent.logger.log.error(f"Index build failed: {e}")
            self._set_status("⚠️  Index partial")

    def _set_status(self, text: str) -> None:
        self.call_from_thread(lambda: self.query_one("#status-bar", Static).update(text))

    # ── Keys ─────────────────────────────────────────────────────────────────

    def on_key(self, event: Key) -> None:
        box = self.query_one("#prompt-input", Input)
        if box.disabled and event.character:
            c = event.character.lower()
            if c == "y":
                self.resolve_approval(True)
            elif c == "n":
                self.resolve_approval(False)

    # ── Commands ──────────────────────────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.value = ""

        if text == "/quit":
            self.exit()
            return

        if text == "/clear":
            self.query_one("#chat-log", RichLog).clear()
            return

        if text == "/diff":
            if self.last_state:
                try:
                    from tools.diff_report import dump_diff_report_from_repo
                    path = dump_diff_report_from_repo(self.last_state.repo_root)
                    self._log(f"[cyan]Diff report → {path}[/cyan]")
                except Exception as e:
                    self._log(f"[red]Diff failed: {e}[/red]")
            else:
                self._log("No session yet.")
            return

        if text == "/status":
            if self.last_state:
                s = self.last_state
                self._log(
                    f"[cyan]steps={s.step_count} phase={s.phase} "
                    f"modified={s.files_modified} "
                    f"symbols={len(s.symbol_index)} "
                    f"deps={len(s.dep_graph)}[/cyan]"
                )
            else:
                self._log("No session yet.")
            return

        if text == "/files":
            tree = getattr(self._index_state, "file_tree", [])
            self._log("[cyan]Repo files:[/cyan]\n" + "\n".join(f"  {f}" for f in tree[:40]))
            return

        self._log(f"\n[bold green]You:[/bold green] {text}")
        self.run_worker(lambda: self._run(text), exclusive=True, thread=True)

    # ── Agent execution ───────────────────────────────────────────────────────

    def _run(self, goal: str) -> None:
        state = AgentState(goal=goal, repo_root=os.getcwd())

        # Inject pre-built index
        if hasattr(self, "_index_state"):
            state.symbol_index = self._index_state.symbol_index
            state.dep_graph    = self._index_state.dep_graph
            state.rev_dep      = self._index_state.rev_dep
            state.file_tree    = self._index_state.file_tree

        agent.logger.log.info("[bold yellow]⚙️  Operon engine starting…[/bold yellow]")
        run_agent(state)
        self.last_state = state
        agent.logger.log.info(
            f"[bold blue]🏁 Done in {state.step_count} steps. "
            f"Modified: {state.files_modified}[/bold blue]"
        )

        try:
            from tools.diff_report import dump_diff_report_from_repo
            dump_diff_report_from_repo(state.repo_root)
        except Exception:
            pass

    # ── UI bridges ────────────────────────────────────────────────────────────

    def _log(self, msg: str) -> None:
        self.query_one("#chat-log", RichLog).write(msg)

    def safe_log(self, msg: str) -> None:
        self.call_from_thread(lambda: self._log(msg))

    def safe_diff(self, filename: str, search: str, replace: str) -> None:
        self.call_from_thread(self._show_diff, filename, search, replace)

    def _show_diff(self, filename: str, search: str, replace: str) -> None:
        self.query_one("#prompt-input", Input).disabled = True
        pane = self.query_one("#workspace-pane", Vertical)
        for child in pane.children:
            child.remove()
        pane.mount(DiffApproval(filename, search, replace))

    def resolve_approval(self, approved: bool) -> None:
        agent.logger.APPROVAL_QUEUE.put(approved)
        pane = self.query_one("#workspace-pane", Vertical)
        for child in pane.children:
            child.remove()
        pane.mount(Static("Workspace cleared — engine resuming…", id="workspace-view"))
        box = self.query_one("#prompt-input", Input)
        box.disabled = False
        box.focus()
