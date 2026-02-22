# agent/logger.py
import logging
import sys

# Global callback that the Textual App will hook into
UI_CALLBACK = None

class TUILogHandler(logging.Handler):
    """Streams log records directly to the Textual UI if connected."""
    def emit(self, record):
        msg = self.format(record)
        if UI_CALLBACK:
            # We pass it to the UI callback
            UI_CALLBACK(msg)
        else:
            # Fallback if running without UI (for debugging)
            print(msg)

def setup_logger(log_file="operon.log"):
    logger = logging.getLogger("Operon")
    logger.setLevel(logging.DEBUG) 
    
    if not logger.handlers:
        # File Handler: Keep the permanent record exactly as it was
        file_handler = logging.FileHandler(log_file, encoding='utf-8', mode='w')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)-8s | %(module)s | %(message)s'))
        
        # TUI Handler: Formats logs using Rich markup tags instead of ANSI
        tui_handler = TUILogHandler()
        tui_handler.setLevel(logging.INFO)
        tui_handler.setFormatter(logging.Formatter('[dim]%(asctime)s[/dim] | %(message)s'))
        
        logger.addHandler(file_handler)
        logger.addHandler(tui_handler)
        
    return logger

log = setup_logger()