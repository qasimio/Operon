import logging
import sys
import queue

# Global UI Bridges
UI_CALLBACK = None
UI_SHOW_DIFF = None
APPROVAL_QUEUE = queue.Queue() # Blocks the worker thread

class TUILogHandler(logging.Handler):
    def emit(self, record):
        msg = self.format(record)
        if UI_CALLBACK:
            UI_CALLBACK(msg)
        else:
            print(msg)

def setup_logger(log_file="operon.log"):
    logger = logging.getLogger("Operon")
    logger.setLevel(logging.DEBUG) 
    
    if not logger.handlers:
        file_handler = logging.FileHandler(log_file, encoding='utf-8', mode='w')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)-8s | %(module)s | %(message)s'))
        
        tui_handler = TUILogHandler()
        tui_handler.setLevel(logging.INFO)
        tui_handler.setFormatter(logging.Formatter('[dim]%(asctime)s[/dim] | %(message)s'))
        
        logger.addHandler(file_handler)
        logger.addHandler(tui_handler)
        
    return logger

log = setup_logger()