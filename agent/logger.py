import logging
import sys

def setup_logger(log_file="operon.log"):
    logger = logging.getLogger("Operon")
    logger.setLevel(logging.DEBUG) 
    
    if not logger.handlers:
        # Console Handler: Standard output
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        # Added Yellow (\033[93m) for Warnings if we ever use them, keeping standard for INFO
        console_format = logging.Formatter('\033[93m[Operon]\033[0m \033[33m%(message)s\033[0m')
        console_handler.setFormatter(console_format)
        
        # File Handler: Overwrite mode ('w') so it resets every run! No more 3000 lines.
        file_handler = logging.FileHandler(log_file, encoding='utf-8', mode='w')
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter('%(asctime)s | %(levelname)-8s | %(module)s | %(message)s')
        file_handler.setFormatter(file_format)
        
        logger.addHandler(console_handler)
        logger.addHandler(file_handler)
        
    return logger

log = setup_logger()