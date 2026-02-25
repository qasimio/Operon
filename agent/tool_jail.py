# agent/tool_jail.py

CODER_TOOLS = {
    "semantic_search": ["query"],
    "exact_search": ["text"],
    "read_file": ["path"],
    "rewrite_function": ["file"],
    "create_file": ["file_path", "initial_content"],
    "find_file": ["search_term"],
    "delete_file": ["file_path"]
}

REVIEWER_TOOLS = {
    "approve_step": ["message"],
    "reject_step": ["feedback"],
    "finish": ["commit_message"]
}

ALLOWED_ACTIONS = {**CODER_TOOLS, **REVIEWER_TOOLS}

# agent/tool_jail.py — improved validate_tool
def validate_tool(action, payload, phase, state=None):
    """
    Return (is_valid: bool, message: str).
    If `state` provided, enforce extra sanity checks (throttles, finish safety).
    """
    allowed_by_phase = {
        "CODER": {"exact_search", "semantic_search", "find_file", "read_file", "rewrite_function", "create_file"},
        "REVIEWER": {"approve_step", "reject_step", "finish"}
    }
    if phase not in allowed_by_phase:
        return False, f"Unknown phase: {phase}"

    if action not in allowed_by_phase[phase]:
        return False, f"{phase} cannot use '{action}'. Allowed: {allowed_by_phase[phase]}"

    # basic param presence checks
    if action == "read_file":
        if not payload.get("path"):
            return False, "read_file requires 'path'."
    if action == "rewrite_function":
        if not payload.get("file") and not payload.get("initial_content"):
            return False, "rewrite_function requires 'file' or 'initial_content'."
    if action == "create_file":
        if not payload.get("file_path"):
            return False, "create_file requires 'file_path'."

    # throttle enforcement if state provided
    if state and action in {"semantic_search", "exact_search", "find_file"}:
        key = payload.get("query") or payload.get("text") or payload.get("search_term") or ""
        if key:
            sc = getattr(state, "search_counts", {}).get(key, {"count": 0})
            if sc.get("count", 0) > 6:
                return False, f"Query '{key}' throttled due to repeated attempts ({sc.get('count')})."

    # Prevent REVIEWER calling finish when nothing meaningful happened (protect commits)
    if action == "finish" and state is not None:
        # allow finish when all steps done OR at least one file modified during session
        all_steps_done = getattr(state, "current_step", 0) >= len(getattr(state, "plan", []) or [])
        modified = bool(getattr(state, "files_modified", []))
        if not (all_steps_done or modified):
            return False, "finish blocked: no files modified and plan not completed."

    return True, "ok"