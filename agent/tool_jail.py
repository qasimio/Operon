# agent/tool_jail.py — Operon v4
"""
Tool permission enforcement + model-switch support.
"""

CODER_TOOLS    = {
    "find_file", "read_file", "semantic_search", "exact_search",
    "rewrite_function", "create_file", "delete_file",
}
REVIEWER_TOOLS = {"approve_step", "reject_step", "finish"}

_PHASE_TOOLS  = {"CODER": CODER_TOOLS, "REVIEWER": REVIEWER_TOOLS}

_REQUIRED: dict[str, list[str]] = {
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


def validate_tool(
    action: str,
    payload: dict,
    phase: str,
    state=None,
) -> tuple[bool, str]:
    """Returns (is_valid, reason_string)."""

    allowed = _PHASE_TOOLS.get(phase)
    if allowed is None:
        return False, f"Unknown phase '{phase}'"
    if action not in allowed:
        return False, f"{phase} cannot use '{action}'. Allowed: {sorted(allowed)}"

    for param in _REQUIRED.get(action, []):
        if not payload.get(param):
            return False, f"'{action}' requires '{param}'"

    # Throttle identical repeated searches
    if state and action in {"semantic_search", "exact_search", "find_file"}:
        key = (payload.get("query") or payload.get("text")
               or payload.get("search_term") or "")
        if key:
            sc  = getattr(state, "search_counts", {})
            cnt = sc.get(key, {}).get("count", 0)
            if cnt > 4:
                return False, (
                    f"'{key[:40]}' throttled ({cnt} attempts). "
                    "Use read_file directly or try a different query."
                )
            sc.setdefault(key, {"count": 0})["count"] = cnt + 1
            state.search_counts = sc

    # Prevent finish before any work
    if action == "finish" and state is not None:
        all_done = getattr(state, "current_step", 0) >= len(
            getattr(state, "plan", []) or []
        )
        modified = bool(getattr(state, "files_modified", []))
        if not (all_done or modified):
            return False, "finish blocked: no files modified and plan not completed."

    return True, "ok"
