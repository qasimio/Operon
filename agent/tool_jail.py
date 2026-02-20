
import json
import re

ALLOWED_ACTIONS = {
    "read_file": ["path"],
    "write_file": ["path", "content"],
    "run_tests": [],
    "git_commit": ["message"],
    "stop": []
}


def validate_action(raw_output: str):
    """
    Return (valid_dict, error_string)
    """

    data = json.loads(raw_output)

    if not data:
        return None, "no_json"

    action = data.get("action")

    if action not in ALLOWED_ACTIONS:
        return None, f"invalid_action:{action}"

    required = ALLOWED_ACTIONS[action]

    for field in required:
        if field not in data:
            return None, f"missing_field:{field}"

    return data, None
