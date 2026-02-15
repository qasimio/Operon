from pathlib import Path

def read_file(path: str, repo_root: str) -> dict:
    full_path = Path(repo_root) / path
    try:
        content = full_path.read_text()
        return {
            "success": True,
            "path": path,
            "content": content,
            "length": len(content)
        }
    except Exception as e:
        return {
            "success": False,
            "path": path,
            "error": str(e)
        }


"""
Try to read a file inside a repo. If it works, return the text and size. If it fails, return the error instead of crashing.
"""