import json
from pathlib import Path

def search_repo(repo_root, query):
    repo = Path(repo_root)
    brain_path = repo / "repo_files.json"
    
    if not brain_path.exists():
        return []

    with open(brain_path) as f:
        data = json.load(f)

    scored_hits = []
    # Use a set to remove duplicate keywords
    keywords = set(query.lower().split())

    # Search the ACTUAL contents and score them
    for file in data.keys():
        full_path = repo / file
        if not full_path.exists():
            continue
            
        try:
            content = full_path.read_text(encoding="utf-8", errors="ignore").lower()
            
            # +1 score for every unique keyword found in the file
            score = sum(1 for k in keywords if k in content)
            
            if score > 0:
                scored_hits.append((score, file))
        except Exception:
            pass

    # Sort files by highest score first!
    scored_hits.sort(key=lambda x: x[0], reverse=True)
    
    # Return just the file names of the top 5 highest-scoring files
    return [hit[1] for hit in scored_hits][:5]