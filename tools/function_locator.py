# tools/function_locator.py — Operon v3
from pathlib import Path
import json
from tools.universal_parser import extract_symbols

IGNORE = {".git", ".venv", "__pycache__", "node_modules", "dist", "build", ".operon"}


def find_function(repo_root: str, func_name: str) -> dict | None:
    """
    Search the repo for a function or class by name.
    Returns {"file": rel_path, "start": int, "end": int} or None.
    """
    root = Path(repo_root)
    for p in root.rglob("*"):
        if not p.is_file() or any(d in p.parts for d in IGNORE):
            continue
        if p.suffix not in {".py", ".js", ".jsx", ".java", ".ts", ".tsx"}:
            continue
        try:
            content = p.read_text(encoding="utf-8", errors="ignore")
            syms = extract_symbols(content, str(p))
            for item in syms.get("functions", []) + syms.get("classes", []):
                if item["name"] == func_name:
                    return {
                        "file": str(p.relative_to(root)),
                        "start": item["start"],
                        "end":   item["end"],
                    }
        except Exception:
            pass
    return None
