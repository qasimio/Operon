from pathlib import Path

def build_repo_summary(repo_root: str, max_files: int = 15) -> str:
    root = Path(repo_root)
    files = []

    for p in root.rglob("*"):
        if p.is_file() and ".git" not in str(p):
            files.append(str(p.relative_to(root)))
            if len(files) >= max_files:
                break

    return "\n".join(files)  # I am Operon with TUI
