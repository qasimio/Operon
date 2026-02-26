# agent/logger.py — Operon v3
import logging
import sys
import queue

# ── Global UI bridges (set by tui/app.py at startup) ─────────────────────────
UI_CALLBACK   = None   # callable(str) — write a line to the chat log
UI_SHOW_DIFF  = None   # callable(filename, search, replace) — render diff panel
APPROVAL_QUEUE: queue.Queue = queue.Queue()  # blocks worker thread until user decides


class TUILogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        if UI_CALLBACK:
            UI_CALLBACK(msg)
        else:
            print(msg, file=sys.stderr)


def setup_logger(log_file: str = "operon.log") -> logging.Logger:
    logger = logging.getLogger("Operon")
    logger.setLevel(logging.DEBUG)

    if not logger.handlers:
        # File handler — full DEBUG output
        fh = logging.FileHandler(log_file, encoding="utf-8", mode="w")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(module)s:%(lineno)d | %(message)s"
        ))

        # TUI handler — INFO+ with rich markup
        th = TUILogHandler()
        th.setLevel(logging.INFO)
        th.setFormatter(logging.Formatter("[dim]%(asctime)s[/dim] | %(message)s"))

        logger.addHandler(fh)
        logger.addHandler(th)

    return logger


log = setup_logger()