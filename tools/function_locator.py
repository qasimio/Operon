import json
from pathlib import Path


def find_function(repo_root: str, name: str):
    """
    Return file + start/end lines for a function or class.
    """

    brain_path = Path(repo_root) / "repo_files.json"

    if not brain_path.exists():
        return None

    data = json.loads(brain_path.read_text())

    for file, info in data.items():

        # search functions
        for f in info.get("functions", []):
            if f["name"].split(".")[-1] == name:
                return {
                    "file": file,
                    "start": f["start"],
                    "end": f["end"],
                    "type": "function"
                }

        # search classes
        for c in info.get("classes", []):
            if c["name"] == name:
                return {
                    "file": file,
                    "start": c["start"],
                    "end": c["end"],
                    "type": "class"
                }

    return None
