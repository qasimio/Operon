# agent/logger.py — Operon v5
import logging
import sys
import queue

# ── Global UI bridges (set by tui/app.py at startup) ─────────────────────────
UI_CALLBACK   = None   # callable(str) — write a line to the chat log
UI_SHOW_DIFF  = None   # callable(filename, search, replace) — render diff panel
APPROVAL_QUEUE: queue.Queue = queue.Queue()  # blocks worker thread until user decides


def _safe_ui_callback(msg: str) -> None:
    """Call UI_CALLBACK safely — never crash when TUI has shut down."""
    cb = UI_CALLBACK
    if cb is None:
        print(msg, file=sys.stderr)
        return
    try:
        cb(msg)
    except RuntimeError:
        # Textual raises RuntimeError("App is not running") on background threads
        # after the TUI exits.  Fall back to stderr silently.
        try:
            print(msg, file=sys.stderr)
        except Exception:
            pass
    except Exception:
        try:
            print(msg, file=sys.stderr)
        except Exception:
            pass


class TUILogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        _safe_ui_callback(msg)


def setup_logger(log_file: str = "operon.log") -> logging.Logger:
    logger = logging.getLogger("Operon")
    logger.setLevel(logging.DEBUG)

    if not logger.handlers:
        fh = logging.FileHandler(log_file, encoding="utf-8", mode="w")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(module)s:%(lineno)d | %(message)s"
        ))

        th = TUILogHandler()
        th.setLevel(logging.INFO)
        th.setFormatter(logging.Formatter("[dim]%(asctime)s[/dim] | %(message)s"))

        logger.addHandler(fh)
        logger.addHandler(th)

    return logger


log = setup_logger()
