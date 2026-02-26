# agent/tool_jail.py — Operon v3
"""
Tool permission system.  Validates action + payload before execution.
"""

CODER_TOOLS   = {"find_file", "read_file", "semantic_search", "exact_search",
                 "rewrite_function", "create_file", "delete_file"}
REVIEWER_TOOLS = {"approve_step", "reject_step", "finish"}

_PHASE_TOOLS = {
    "CODER":    CODER_TOOLS,
    "REVIEWER": REVIEWER_TOOLS,
}

_REQUIRED_PARAMS = {
    "read_file":        ["path"],
    "rewrite_function": ["file"],
    "create_file":      ["file_path"],
    "delete_file":      ["file_path"],
    "find_file":        ["search_term"],
    "semantic_search":  ["query"],
    "exact_search":     ["text"],
    "approve_step":     ["message"],
    "reject_step":      ["feedback"],
    "finish":           ["commit_message"],
}


def validate_tool(action: str, payload: dict, phase: str, state=None) -> tuple[bool, str]:
    """Returns (is_valid, reason)."""

    # Phase check
    allowed = _PHASE_TOOLS.get(phase)
    if allowed is None:
        return False, f"Unknown phase: {phase}"
    if action not in allowed:
        return False, f"{phase} cannot use '{action}'. Allowed: {sorted(allowed)}"

    # Required param check
    for param in _REQUIRED_PARAMS.get(action, []):
        if not payload.get(param):
            return False, f"'{action}' requires '{param}' param."

    # Throttle repeated searches
    if state and action in {"semantic_search", "exact_search", "find_file"}:
        key = payload.get("query") or payload.get("text") or payload.get("search_term") or ""
        if key:
            sc = getattr(state, "search_counts", {}).get(key, {})
            if sc.get("count", 0) > 5:
                return False, (
                    f"Query '{key[:40]}' throttled ({sc['count']} attempts). "
                    "Use a different query or try read_file directly."
                )

    # Prevent finish when nothing was done
    if action == "finish" and state is not None:
        all_done  = getattr(state, "current_step", 0) >= len(getattr(state, "plan", []) or [])
        modified  = bool(getattr(state, "files_modified", []))
        if not (all_done or modified):
            return False, "finish blocked: no files modified and plan not completed."

    return True, "ok"