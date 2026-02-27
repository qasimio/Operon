# main.py — Operon v5
"""
Entry point.

  python main.py              → launch TUI
  python main.py explain <X>  → explain symbol X
  python main.py rename <old> <new> [--apply]
  python main.py usages <X>
  python main.py docs [--no-llm]
  python main.py summarize <file>
  python main.py signature <func> <params> [--apply]
"""
import sys


def _is_cli_command(argv: list) -> bool:
    CLI_COMMANDS = {"explain", "usages", "rename", "docs", "summarize", "signature"}
    return len(argv) > 1 and argv[1] in CLI_COMMANDS


if __name__ == "__main__":
    if _is_cli_command(sys.argv):
        # CLI mode — no TUI dependency
        from cli.explain import main as cli_main
        cli_main(sys.argv[1:])
    else:
        # TUI mode
        try:
            from tui.app import OperonUI
            OperonUI().run()
        except KeyboardInterrupt:
            print("\nOperon shut down safely.")
            sys.exit(0)
