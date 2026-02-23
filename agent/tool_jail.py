import json

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
    """
    Return (valid_dict, error_string)
    """
    try:
        data = json.loads(raw_output)
    except json.JSONDecodeError:
        return None, "no_json"

    if not data:
        return None, "empty_json"

    # Support nested "tool" format from Swarm update
    if "tool" in data:
        action_payload = data["tool"]
    else:
        action_payload = data

    action = action_payload.get("action")

    if action not in ALLOWED_ACTIONS:
        return None, f"invalid_action:{action}"

    required_fields = ALLOWED_ACTIONS[action]

    for field in required_fields:
        if field not in action_payload:
            return None, f"missing_field:{field}"

    return action_payload, None