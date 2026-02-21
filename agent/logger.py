import logging
import sys
from pathlib import Path

def setup_logger(log_file="operon.log"):
    # Create the master logger
    logger = logging.getLogger("Operon")
    logger.setLevel(logging.DEBUG) # Capture EVERYTHING
    
    # Avoid adding handlers multiple times if imported twice
    if not logger.handlers:
        # 1. Console Handler (What YOU see in the terminal: Clean & Concise)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_format = logging.Formatter('\033[93m[Operon]\033[0m %(message)s')
        console_handler.setFormatter(console_format)
        
        # 2. File Handler (What the LOG FILE sees: Deep Forensic Debugging)
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter('%(asctime)s | %(levelname)-8s | %(module)s | %(message)s')
        file_handler.setFormatter(file_format)
        
        # Attach both to the logger
        logger.addHandler(console_handler)
        logger.addHandler(file_handler)
        
    return logger

# Export a single instance to be used across the whole app
log = setup_logger()