# tools/fs_tools.py
from pathlib import Path
from typing import Dict

def read_file(path: str, repo_root: str) -> Dict:
    full_path = Path(repo_root) / path
    try:
        text = full_path.read_text(encoding="utf-8", errors="ignore")
        return {"success": True, "path": path, "content": text, "length": len(text)}
    except Exception as e:
        return {"success": False, "path": path, "error": str(e)}

def write_file(path: str, content: str, repo_root: str, mode: str = "append") -> Dict:
    """
    Write to a file inside repo_root.

    mode:
      - "append" (default): append content (creates file if missing)
      - "overwrite": replace file contents entirely
    """
    full_path = Path(repo_root) / path
    try:
        print("WRITE CALLED")
        full_path.parent.mkdir(parents=True, exist_ok=True)

        if mode not in ("append", "overwrite"):
            return {"success": False, "path": path, "error": f"invalid mode: {mode}"}

        if mode == "append":
            # open in append mode (creates file if not exists)
            with full_path.open("a", encoding="utf-8") as f:
                # ensure newline before append
                if full_path.exists():
                    with full_path.open("rb") as check:
                        check.seek(0, 2)
                        if check.tell() > 0:
                            f.write("\n")

                f.write(content.rstrip() + "\n")


        else:  # overwrite
            full_path.write_text(content, encoding="utf-

"""
Try to read a file inside a repo. If it works, return the text and size. If it fails, return the error instead of crashing.
"""
