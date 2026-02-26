# tui/app.py — Operon v3.1
from __future__ import annotations
import json
import os
from pathlib import Path
from typing import cast

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, ScrollableContainer, Grid
from textual.widgets import (
    Header, Footer, RichLog, Input, Static, Button,
    Select, Label, Switch
)
from textual.events import Key
from textual.reactive import reactive
from rich.panel import Panel
from rich.console import Group
from rich.syntax import Syntax
from rich.table import Table

from runtime.state import AgentState
from agent.loop import run_agent
import agent.logger


# ─────────────────────────────────────────────────────────────────────────────
# LLM Settings panel
# ─────────────────────────────────────────────────────────────────────────────

PROVIDERS = [
    ("Local (llama.cpp / Ollama / LM Studio)", "local"),
    ("OpenAI  (gpt-4o, o1, o3…)",              "openai"),
    ("Anthropic  (Claude)",                    "anthropic"),
    ("OpenRouter  (any model)",                "openrouter"),
    ("Deepseek",                               "deepseek"),
    ("Groq",                                   "groq"),
    ("Together AI",                            "together"),
    ("Azure OpenAI",                           "azure"),
    ("Custom / Other",                         "custom"),
]

PROVIDER_DEFAULTS = {
    "local":      {"base_url": "http://127.0.0.1:8080/v1",         "model": "local",                              "needs_key": False},
    "openai":     {"base_url": "https://api.openai.com/v1",         "model": "gpt-4o",                            "needs_key": True},
    "anthropic":  {"base_url": "https://api.anthropic.com",         "model": "claude-sonnet-4-6",                 "needs_key": True},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1",      "model": "anthropic/claude-3.5-sonnet",       "needs_key": True},
    "deepseek":   {"base_url": "https://api.deepseek.com/v1",       "model": "deepseek-coder",                    "needs_key": True},
    "groq":       {"base_url": "https://api.groq.com/openai/v1",    "model": "llama-3.1-70b-versatile",           "needs_key": True},
    "together":   {"base_url": "https://api.together.xyz/v1",       "model": "Qwen/Qwen2.5-Coder-32B-Instruct",  "needs_key": True},
    "azure":      {"base_url": "",                                   "model": "gpt-4o",                            "needs_key": True},
    "custom":     {"base_url": "",                                   "model": "",                                  "needs_key": False},
}

PROVIDER_GUIDE = {
    "local":      "Point llama-server to --port 8080. No API key needed.",
    "openai":     "Get API key from https://platform.openai.com/api-keys",
    "anthropic":  "Get API key from https://console.anthropic.com/",
    "openrouter": "Get API key from https://openrouter.ai/keys\nModel examples: anthropic/claude-3.5-sonnet, meta-llama/llama-3.1-70b",
    "deepseek":   "Get API key from https://platform.deepseek.com/",
    "groq":       "Get API key from https://console.groq.com/",
    "together":   "Get API key from https://api.together.xyz/settings/api-keys",
    "azure":      "Set base_url to your Azure endpoint URL.\nGet API key from Azure Portal.",
    "custom":     "Enter the OpenAI-compatible base URL and your API key.",
}


class LLMSettingsPanel(Vertical):
    """Full-screen settings panel for provider / model / API key."""

    def compose(self) -> ComposeResult:
        yield Static("⚙️  [bold]LLM Provider Settings[/bold]", classes="settings-title")
        yield Static("", id="settings-guide")
        yield Label("Provider:")
        yield Select(
            options=PROVIDERS,
            id="sel-provider",
            value="local",
        )
        yield Label("Model:")
        yield Input(placeholder="model name or ID", id="inp-model")
        yield Label("API Key (stored locally in .operon/llm_config.json):")
        yield Input(
            placeholder="sk-... or leave empty for local",
            id="inp-apikey",
            password=True,
        )
        yield Label("Base URL (auto-filled; override if needed):")
        yield Input(placeholder="http://127.0.0.1:8080/v1", id="inp-baseurl")
        yield Label("Max tokens:")
        yield Input(value="2800", id="inp-maxtok")
        yield Label("Temperature:")
        yield Input(value="0.15", id="inp-temp")
        with Horizontal(classes="settings-buttons"):
            yield Button("💾 Save & Close",  id="btn-save",   variant="success")
            yield Button("🔗 Test Connection", id="btn-test", variant="primary")
            yield Button("✖ Cancel",         id="btn-cancel", variant="error")
        yield Static("", id="settings-status")

    def on_mount(self) -> None:
        self._load_current()

    def _load_current(self) -> None:
        from agent.llm import _load_config
        cfg = _load_config()
        provider = cfg.get("provider", "local")
        try:
            self.query_one("#sel-provider", Select).value = provider
        except Exception:
            pass
        self.query_one("#inp-model",   Input).value = cfg.get("model",    "")
        self.query_one("#inp-apikey",  Input).value = cfg.get("api_key",  "")
        self.query_one("#inp-baseurl", Input).value = cfg.get("base_url", "")
        self.query_one("#inp-maxtok",  Input).value = str(cfg.get("max_tokens", 2800))
        self.query_one("#inp-temp",    Input).value = str(cfg.get("temperature", 0.15))
        self._update_guide(provider)

    def _update_guide(self, provider: str) -> None:
        guide = PROVIDER_GUIDE.get(provider, "")
        self.query_one("#settings-guide", Static).update(
            f"[dim]{guide}[/dim]" if guide else ""
        )

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "sel-provider":
            return
        provider = str(event.value)
        defaults = PROVIDER_DEFAULTS.get(provider, {})
        self.query_one("#inp-baseurl", Input).value = defaults.get("base_url", "")
        self.query_one("#inp-model",   Input).value = defaults.get("model", "")
        self._update_guide(provider)

    def _set_status(self, msg: str) -> None:
        self.query_one("#settings-status", Static).update(msg)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel":
            cast("OperonUI", self.app)._close_settings()
            return

        if event.button.id == "btn-test":
            self._set_status("[yellow]Testing…[/yellow]")
            self.app.run_worker(self._test_connection, thread=True)
            return

        if event.button.id == "btn-save":
            self._do_save()
            cast("OperonUI", self.app)._close_settings()

    def _do_save(self) -> None:
        from agent.llm import save_config, _load_config
        cfg             = _load_config()
        cfg["provider"] = str(self.query_one("#sel-provider", Select).value)
        cfg["model"]    = self.query_one("#inp-model",   Input).value.strip()
        cfg["api_key"]  = self.query_one("#inp-apikey",  Input).value.strip()
        cfg["base_url"] = self.query_one("#inp-baseurl", Input).value.strip()
        try:
            cfg["max_tokens"]  = int(self.query_one("#inp-maxtok", Input).value)
        except ValueError:
            pass
        try:
            cfg["temperature"] = float(self.query_one("#inp-temp", Input).value)
        except ValueError:
            pass
        save_config(cfg)
        agent.logger.log.info(
            f"[green]✅ LLM config saved: {cfg['provider']} / {cfg['model']}[/green]"
        )

    def _test_connection(self) -> None:
        self._do_save()
        try:
            from agent.llm import call_llm
            result = call_llm("Reply with exactly the word PONG.", retries=0)
            msg = (
                f"[bold green]✅ Connected! Response: {result[:80]}[/bold green]"
                if result and "error" not in result.lower()
                else f"[red]⚠️ Unexpected: {result[:80]}[/red]"
            )
        except Exception as e:
            msg = f"[bold red]❌ Connection failed: {e}[/bold red]"
        cast("OperonUI", self.app).call_from_thread(self._set_status, msg)


# ─────────────────────────────────────────────────────────────────────────────
# Diff approval widget
# ─────────────────────────────────────────────────────────────────────────────

class DiffApproval(Vertical):
    def __init__(self, filename: str, search: str, replace: str, **kw):
        super().__init__(**kw)
        self.filename = filename
        self.search   = search
        self.replace  = replace

    def compose(self) -> ComposeResult:
        yield Static(f"⚠️  [bold]PENDING APPROVAL:[/bold] {self.filename}",
                     classes="diff-title")
        with ScrollableContainer(id="diff-scroll"):
            yield Static(id="diff-area")
        with Horizontal(classes="diff-buttons"):
            yield Button("✅ Approve  (y)", id="btn-approve", variant="success")
            yield Button("❌ Reject   (n)", id="btn-reject",  variant="error")

    def on_mount(self) -> None:
        ext  = self.filename.rsplit(".", 1)[-1].lower()
        lang = {
            "py": "python", "js": "javascript", "jsx": "javascript",
            "ts": "typescript", "tsx": "typescript", "java": "java",
            "cpp": "cpp", "c": "c", "go": "go", "rs": "rust",
        }.get(ext, "text")
        s = Syntax(
            self.search  or "(empty — new content)", lang,
            theme="monokai", line_numbers=True, word_wrap=True,
        )
        r = Syntax(
            self.replace or "(empty — deletion)",    lang,
            theme="monokai", line_numbers=True, word_wrap=True,
        )
        self.query_one("#diff-area", Static).update(Group(
            Panel(s, title="[bold red]BEFORE / SEARCH[/bold red]",    border_style="red"),
            Panel(r, title="[bold green]AFTER / REPLACE[/bold green]", border_style="green"),
        ))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        app: OperonUI = cast("OperonUI", self.app)
        app.resolve_approval(event.button.id == "btn-approve")


# ─────────────────────────────────────────────────────────────────────────────
# Main TUI
# ─────────────────────────────────────────────────────────────────────────────

class OperonUI(App):

    CSS = """
    Screen { background: $surface; }

    #chat-pane      { width: 48%; border-right: solid $primary; padding: 1; height: 100%; }
    #workspace-pane { width: 52%; padding: 1; height: 100%; }

    RichLog         { height: 1fr; background: $surface; }
    Input           { dock: bottom; margin-top: 1; }
    #status-bar     { height: 1; color: $accent; text-style: italic; }
    #model-bar      { height: 1; color: $success; }

    .diff-title     { text-style: bold; color: magenta; margin-bottom: 1; }
    .diff-buttons   { height: 3; align: center middle; dock: bottom; margin-top: 1; }
    #diff-scroll    { height: 1fr; overflow-y: auto; }

    LLMSettingsPanel { padding: 2; }
    .settings-title  { text-style: bold; color: $accent; margin-bottom: 1; }
    .settings-buttons { height: 3; align: center middle; dock: bottom; margin-top: 1; }
    #settings-guide  { color: $text-muted; margin-bottom: 1; }
    #settings-status { margin-top: 1; }

    Button          { margin: 0 1; }
    Select          { margin-bottom: 1; }
    Label           { color: $text-muted; }
    Input           { margin-bottom: 1; }
    """

    BINDINGS = [
        ("ctrl+c", "quit",     "Quit"),
        ("ctrl+s", "settings", "LLM Settings"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal():
            with Vertical(id="chat-pane"):
                yield RichLog(id="chat-log", highlight=True, markup=True)
                yield Static("", id="model-bar")
                yield Static("🔍 Indexing…", id="status-bar")
                yield Input(
                    placeholder="Ask Operon…  (/settings  /status  /files  /clear  /quit)",
                    id="prompt-input",
                )
            with Vertical(id="workspace-pane"):
                yield Static(
                    "[dim]Workspace — diff previews appear here.[/dim]\n\n"
                    "Press [bold]Ctrl+S[/bold] to open LLM settings.",
                    id="workspace-view",
                )
        yield Footer()

    # ── Startup ───────────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        self.title = "Operon v3 — Autonomous SWE"
        self.last_state: AgentState | None = None
        self._index_state = AgentState(goal="__index__", repo_root=os.getcwd())

        agent.logger.UI_CALLBACK  = self.safe_log
        agent.logger.UI_SHOW_DIFF = self.safe_diff

        self._refresh_model_bar()
        self._log("🧬 [bold blue]Operon v3.1[/bold blue] — Press [bold]Ctrl+S[/bold] to configure your LLM provider.\n")
        self.run_worker(self._bg_index, exclusive=True, thread=True)

    def _bg_index(self) -> None:
        try:
            from tools.semantic_memory import index_repo
            index_repo(os.getcwd())
        except Exception as e:
            agent.logger.log.error(f"Semantic index: {e}")
        try:
            from tools.repo_index import build_full_index
            build_full_index(self._index_state)
            n = len(self._index_state.symbol_index)
            f = len(self._index_state.file_tree)
            self._set_status(f"✅ Index ready — {n} symbols, {f} files")
        except Exception as e:
            agent.logger.log.error(f"Index build: {e}")
            self._set_status("⚠️  Index partial")

    def _refresh_model_bar(self) -> None:
        try:
            from agent.llm import get_model_info
            info = get_model_info()
            self.call_from_thread(
                lambda: self.query_one("#model-bar", Static).update(
                    f"[bold green]⚡ {info['provider'].upper()}[/bold green] "
                    f"[cyan]{info['model']}[/cyan]"
                )
            )
        except Exception:
            pass

    def _set_status(self, text: str) -> None:
        self.call_from_thread(
            lambda: self.query_one("#status-bar", Static).update(text)
        )

    # ── Settings ──────────────────────────────────────────────────────────────

    def action_settings(self) -> None:
        self._open_settings()

    def _open_settings(self) -> None:
        pane = self.query_one("#workspace-pane", Vertical)
        for child in pane.children:
            child.remove()
        pane.mount(LLMSettingsPanel())
        self.query_one("#prompt-input", Input).disabled = True

    def _close_settings(self) -> None:
        pane = self.query_one("#workspace-pane", Vertical)
        for child in pane.children:
            child.remove()
        pane.mount(Static(
            "[dim]Workspace — diff previews appear here.[/dim]",
            id="workspace-view",
        ))
        box = self.query_one("#prompt-input", Input)
        box.disabled = False
        box.focus()
        self._refresh_model_bar()

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
        if text in ("/settings", "/config", "/llm"):
            self._open_settings()
            return
        if text == "/status":
            if self.last_state:
                s = self.last_state
                self._log(
                    f"[cyan]steps={s.step_count}  phase={s.phase}\n"
                    f"modified={s.files_modified}\n"
                    f"symbols={len(s.symbol_index)}  deps={len(s.dep_graph)}[/cyan]"
                )
            else:
                self._log("[dim]No session yet.[/dim]")
            return
        if text == "/files":
            tree = getattr(self._index_state, "file_tree", [])
            self._log(
                "[cyan]Repo files:[/cyan]\n"
                + "\n".join(f"  {f}" for f in tree[:50])
            )
            return

        self._log(f"\n[bold green]You:[/bold green] {text}")
        self.run_worker(lambda: self._run(text), exclusive=True, thread=True)

    # ── Agent execution ───────────────────────────────────────────────────────

    def _run(self, goal: str) -> None:
        state = AgentState(goal=goal, repo_root=os.getcwd())
        # Inject pre-built index
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
        pane.mount(Static(
            "[dim]Workspace cleared — engine resuming…[/dim]",
            id="workspace-view",
        ))
        box = self.query_one("#prompt-input", Input)
        box.disabled = False
        box.focus()
