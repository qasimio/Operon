from pathlib import Path
from tools.function_locator import find_function


def load_function_slice(repo_root: str, func_name: str, context: int = 5):
    """
    Load only the lines surrounding a function/class.
    Returns:
        {
          file,
          start,
          end,
          slice_start,
          slice_end,
          code
        }
    """

    loc = find_function(repo_root, func_name)

    if not loc:
        return None

    file_path = Path(repo_root) / loc["file"]

    if not file_path.exists():
        return None

    lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()


    start = loc["start"]
    end = loc["end"]

    slice_start = max(1, start - context)
    slice_end = min(len(lines), end + context)

    snippet = "\n".join(lines[slice_start-1:slice_end])

    return {
        "file": loc["file"],
        "start": start,
        "end": end,
        "slice_start": slice_start,
        "slice_end": slice_end,
        "code": snippet
    }
