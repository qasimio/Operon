from pathlib import Path

def build_repo_summary(repo_root: str, max_files: int = 15) -> str:
    """
    Builds a summary of the files in a repository.

    Args:
        repo_root (str): The root directory of the repository.
        max_files (int, optional): The maximum number of files to include in the summary. Defaults to 15.

    Returns:
        str: A string containing the paths of the files in the repository, up to the maximum number specified.
    """
    root = Path(repo_root)
    files = []

    for p in root.rglob("*"):
        if p.is_file() and ".git" not in str(p):
            files.append(str(p.relative_to(root)))
            if len(files) >= max_files:
                break

    return "\n".join(files)
