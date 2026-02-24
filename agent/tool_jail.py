# agent/tool_jail.py

CODER_TOOLS = {
    "semantic_search": ["query"],
    "exact_search": ["text"],
    "read_file": ["path"],
    # "rewrite_function": ["file"]
    "edit_files": ["files"],
    "run_command": ["command"]
}

REVIEWER_TOOLS = {
    "approve_step": ["message"],
    "reject_step": ["feedback"],
    "finish": ["message"]
}

ALLOWED_ACTIONS = {**CODER_TOOLS, **REVIEWER_TOOLS}

def validate_tool(act, payload, phase):
    if phase == "CODER" and act not in CODER_TOOLS:
        return False, f"CODER cannot use '{act}'. Allowed: {list(CODER_TOOLS.keys())}"
    
    if phase == "REVIEWER" and act not in REVIEWER_TOOLS:
        return False, f"REVIEWER cannot use '{act}'. Allowed: {list(REVIEWER_TOOLS.keys())}"
    
    required_keys = ALLOWED_ACTIONS.get(act, [])
    for key in required_keys:
        if key not in payload:
            return False, f"Tool '{act}' is missing required parameter '{key}'."
            
    return True, "Valid"