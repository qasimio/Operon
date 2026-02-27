# tools/repo_search.py
from agent.logger import log

def search_repo(repo_root: str, query: str):
    try:
        from tools.semantic_memory import search_memory
        return search_memory(repo_root, query, top_k=5)
    except Exception as e:
        log.debug(f"Semantic search unavailable ({e}) — using exact grep fallback")
        import os
        from pathlib import Path
        hits = []
        terms = query.lower().split()
        root = Path(repo_root)
        for p in root.rglob("*"):
            if p.is_file() and ".git" not in p.parts and ".operon" not in p.parts:
                try:
                    text = p.read_text(encoding="utf-8", errors="ignore").lower()
                    if any(t in text for t in terms):
                        hits.append(str(p.relative_to(root)))
                except Exception:
                    pass
        return hits[:5]
