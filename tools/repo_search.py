import json
from pathlib import Path

def search_repo(repo_root, query):

    repo = Path(repo_root)

    with open(repo / "repo_files.json") as f:
        data = json.load(f)

    hits = []

    q = query.lower()

    for file, info in data.items():

        blob = " ".join([
            file.lower(),
            info.get("summary","").lower(),
            " ".join(info.get("functions",[])).lower(),
            " ".join(info.get("classes",[])).lower(),
            " ".join(info.get("imports",[])).lower()
        ])

        if q in blob:
            hits.append(file)   # IMPORTANT: file already contains full repo path

    return hits[:5]
