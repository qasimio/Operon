# tools/fs_tools.py — Operon v3
from pathlib import Path
from typing import Dict


def read_file(path: str, repo_root: str) -> Dict:
    full_path = Path(repo_root) / path
    try:
        text = full_path.read_text(encoding="utf-8", errors="ignore")
        return {"success": True, "path": path, "content": text, "length": len(text)}
    except Exception as e:
        return {"success": False, "path": path, "error": str(e)}


def write_file(path: str, content: str, repo_root: str, mode: str = "overwrite") -> Dict:
    full_path = Path(repo_root) / path
    try:
        full_path.parent.mkdir(parents=True, exist_ok=True)
        if mode == "append":
            with full_path.open("a", encoding="utf-8") as f:
                if full_path.stat().st_size > 0:
                    f.write("\n")
                f.write(content.rstrip() + "\n")
        elif mode == "overwrite":
            full_path.write_text(content, encoding="utf-8")
        else:
            return {"success": False, "error": f"invalid mode: {mode}"}
        return {"success": True, "path": path, "mode": mode}
    except Exception as e:
        return {"success": False, "path": path, "error": str(e)}
