# tools/repo_search.py
from tools.semantic_memory import search_memory
from agent.logger import log

def search_repo(repo_root: str, query: str):
    """
    Operon's tool to search the codebase.
    Now backed by LanceDB + FastEmbed for semantic retrieval!
    """
    log.debug(f"Performing semantic search for: '{query}'")
    hits = search_memory(repo_root, query, top_k=5)
    return hits