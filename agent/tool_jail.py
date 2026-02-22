# agent/tool_jail.py
ALLOWED_ACTIONS = {
    "search_repo": ["query"],
    "read_file": ["path"],
    "rewrite_function": ["file"], 
    "finish": ["message"]
}