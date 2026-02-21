import json
from pathlib import Path

def search_repo(repo_root, query):
    repo = Path(repo_root)
    
    with open(repo / "repo_files.json") as f:
        data = json.load(f)

    hits = []
    # Split the query into individual keywords
    keywords = query.lower().split()

    for file, info in data.items():
        # Build a search blob using list comprehensions to avoid dictionary TypeErrors
        blob = " ".join([
            file.lower(),
            info.get("summary", "").lower(),
            " ".join([f.get("name", "") for f in info.get("functions", [])]).lower(),
            " ".join([c.get("name", "") for c in info.get("classes", [])]).lower(),
            " ".join(info.get("imports", [])).lower()
        ])

        # If ANY of the keywords are in this file's blob, count it as a hit
        if any(k in blob for k in keywords):
            hits.append(file)

    return hits[:5]