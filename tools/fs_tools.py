from pathlib import Path
from typing import Dict

def read_file(path: str, repo_root: str) -> Dict:
    full_path = Path(repo_root) / path
    try:
        text = full_path.read_text()
        return {"success": True, "path": path, "content": text, "length": len(text)}
    except Exception as e:
        return {"success": False, "path": path, "error": str(e)}

def write_file(path: str, content: str, repo_root: str, overwrite: bool = True) -> Dict:
    full_path = Path(repo_root) / path
    try:
        full_path.parent.mkdir(parents=True, exist_ok=True)
        if full_path.exists() and not overwrite:
            return {"success": False, "path": path, "error": "file exists and overwrite=False"}
        full_path.write_text(content)
        return {"success": True, "path": path, "written_bytes": len(content)}
    except Exception as e:
        return {"success": False, "path": path, "error": str(e)}



"""
Try to read a file inside a repo. If it works, return the text and size. If it fails, return the error instead of crashing.
"""