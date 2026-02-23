import json
import re

ALLOWED_ACTIONS = {
    "search_repo": ["query"],
    "read_file": ["path"],
    "rewrite_function": ["file"], 
    "step_complete": ["message"],
    "approve_step": ["message"],
    "reject_step": ["feedback"],
    "finish": ["message"]
}

def validate_action(raw_output: str):
    pass # Managed dynamically by loop.py