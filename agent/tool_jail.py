
import json
import re

ALLOWED_ACTIONS = {
    "read_file": ["path"],
    "write_file": ["path", "content"],
    "run_tests": [],
    "git_commit": ["message"],
    "stop": []
}


def _extract_json(text: str):
    """Pull first JSON object from model output."""
    try:
        return json.loads(text)
    except:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except:
                return None
    return None


def validate_action(raw_output: str):
    """
    Return (valid_dict, error_string)
    """

    data = _extract_json(raw_output)

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
