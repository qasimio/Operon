# agent/loop.py
from runtime import state
from tools.repo_search import search_repo
from agent.goal_parser import extract_target_files, parse_write_instruction, extract_multiline_append
from agent.approval import ask_user_approval
from agent.decide import decide_next_action
from agent.planner import make_plan
from tools.fs_tools import read_file, write_file
from tools.shell_tools import run_tests
from tools.function_locator import find_function
from tools.code_slice import load_function_slice
from pathlib import Path
import time
import re

MAX_STEPS = 30


def _valid_path(action):
    """Return a safe string path or None."""
    path = action.get("path") if isinstance(action, dict) else None
    if isinstance(path, str) and path.strip():
        return path
    return None


def _safe_function_rewrite(original_name: str, new_code: str) -> bool:
    """
    Quick safety checks to avoid the agent replacing code with junk.
    Keep this conservative: reject if output looks like explanation/markdown, is tiny,
    or does not include the same function name.
    """
    if not isinstance(new_code, str):
        return False

    txt = new_code.strip()

    # reject empty or too short outputs
    if len(txt) < 60:
        return False

    # reject markdown fences or obvious explanations
    if "```" in txt or txt.startswith("#") or txt.lower().startswith("explain") or txt.count("\n") < 2:
        return False

    # must contain the original function signature
    if f"def {original_name}(" not in txt and f"async def {original_name}(" not in txt and f"{original_name}(" not in txt:
        return False

    # must not be a bullet list or numbered steps
    if re.match(r'^\s*(?:\d+\.|\-)\s+', txt):
        return False

    # quick check for valid python indentation (presence of colon and indentation)
    if ":" not in txt.splitlines()[0]:
        # first line should be a def/class signature containing ":"
        return False

    return True


def _replace_function_in_file(repo_root: str, slice_data: dict, new_code: str) -> dict:
    """
    Replace function code in-place using slice_data to compute exact lines.
    slice_data is expected to include 'file' (relative path) and either
    ('slice_start','slice_end') or ('start','end') representing 1-based line numbers.
    Returns an observation dict similar to write_file.
    """
    try:
        rel_path = slice_data.get("file") or slice_data.get("path")
        if not rel_path:
            return {"success": False, "error": "slice_data missing file path"}

        full_path = Path(repo_root) / rel_path

        if not full_path.exists():
            return {"success": False, "error": f"target file not found: {rel_path}", "path": rel_path}

        text = full_path.read_text(encoding="utf-8", errors="ignore")
        lines = text.splitlines(True)  # keep newline chars

        # prefer slice_start/slice_end (these are the exact slice lines returned by code_slice)
        start = slice_data.get("slice_start") or slice_data.get("start")
        end = slice_data.get("slice_end") or slice_data.get("end")

        if start is None or end is None:
            return {"success": False, "error": "slice_data missing start/end"}

        # ensure ints
        start = int(start)
        end = int(end)

        # bounds check
        if start < 1:
            start = 1
        if end > len(lines):
            end = len(lines)

        # prepare new code lines (ensure trailing newline)
        new_lines = new_code.splitlines(True)
        if not new_lines:
            new_lines = ["\n"]
        if not new_lines[-1].endswith("\n"):
            new_lines[-1] = new_lines[-1] + "\n"

        # splice
        new_text = "".join(lines[: start - 1] + new_lines + lines[end:])

        # atomic write
        full_path.write_text(new_text, encoding="utf-8")

        return {"success": True, "path": rel_path, "mode": "overwrite", "written_bytes": len(new_text)}

    except Exception as e:
        return {"success": False, "error": str(e)}


def run_agent(state):
    # detect function names inside goal and attach function context early
    words = state.goal.replace("(", " ").replace(")", " ").split()

    for w in words:
        try:
            loc = find_function(state.repo_root, w)
        except Exception:
            loc = None

        if loc:
            try:
                slice_data = load_function_slice(state.repo_root, w)
            except Exception:
                slice_data = None

            if slice_data:
                state.observations.append({"function_context": slice_data})
                break

    # ---------- ensure plan exists ----------
    if not getattr(state, "plan", None):
        state.plan = make_plan(state.goal, state.repo_root)

    print("\nPLAN:", state.plan, "\n")

    # ---------- main loop ----------
    while not state.done and state.step_count < MAX_STEPS:

        # ---------- determine next action (deterministic first moves) ----------
        try:
            action = None

            # If nothing has been read yet, force a read of the primary target file
            if not state.files_read:

                # 1️⃣ First try explicit file in goal
                targets = extract_target_files(state.repo_root, state.goal)

                # 2️⃣ If none found → use repo search intelligence
                if not targets:
                    try:
                        targets = search_repo(state.repo_root, state.goal)
                        if targets:
                            print("SEARCH HIT:", targets[0])
                    except Exception:
                        targets = []

                # 3️⃣ read first candidate if any
                if targets:
                    action = {"action": "read_file", "path": targets[0]}

            # If parsed concrete write exists and file not yet modified, prefer it
            if action is None:
                multi = extract_multiline_append(state.goal)
                if multi and multi["path"] not in state.files_modified:
                    action = multi
                else:
                    parsed = parse_write_instruction(state.goal, state.repo_root)
                    if parsed and parsed.get("path") and parsed.get("content"):
                        if parsed["path"] not in state.files_modified:
                            action = parsed

            # otherwise ask the model
            if action is None:
                action = decide_next_action(state) or {}

        except Exception as e:
            state.errors.append(f"decide_next_action crashed: {e}")
            break

        # DEBUG: show what action we will execute
        print("DEBUG ACTION:", action)

        act = action.get("action")
        state.last_action = act
        state.step_count += 1

        # ---------- file-lock guard ----------
        allowed_files = extract_target_files(state.repo_root, state.goal)
        if allowed_files:
            path_check = action.get("path")
            func_allowed = bool(action.get("function_name") or action.get("target_function"))
            # allow special token 'function' and explicit function-targeted actions
            if path_check and path_check.lower() not in [p.lower() for p in allowed_files] and not (path_check == "function" or func_allowed):
                state.errors.append(f"Blocked unauthorized file: {path_check}")
                state.done = True
                continue

        # ================= READ FILE =================
        if act == "read_file":
            path = _valid_path(action)
            if not path:
                state.errors.append(f"read_file missing valid path: {action}")
                continue

            try:
                obs = read_file(path, state.repo_root)
            except Exception as e:
                obs = {"success": False, "error": str(e), "path": path}

            state.observations.append(obs)

            if obs.get("success"):
                if path not in state.files_read:
                    state.files_read.append(path)
            else:
                state.errors.append(obs.get("error"))
                # IMPORTANT: mark as attempted so we don't retry forever
                if path not in state.files_read:
                    state.files_read.append(path)

        # ================= WRITE FILE =================
        elif act == "write_file":
            path = _valid_path(action)
            # path may be "function" for function-level writes
            if not path and not (action.get("function_name") or action.get("target_function")):
                state.errors.append(f"write_file missing valid path or function target: {action}")
                continue

            # approval gate (always triggered)
            if not ask_user_approval("write_file", action):
                state.errors.append("User denied write_file")
                state.done = True
                continue

            # default to append behaviour unless explicitly asked to overwrite
            mode = action.get("mode", "append")  # "append" or "overwrite"
            content = action.get("content", "")

            # special-case: function-level replacement
            func_name = action.get("function_name") or action.get("target_function")
            if (path == "function" or func_name) and func_name:
                # new_code should be the model's generated function text
                new_code = content

                if not _safe_function_rewrite(func_name, new_code):
                    state.errors.append("LLM returned unsafe rewrite — aborting")
                    state.done = True
                    continue

                # locate exact slice for this function
                slice_data = load_function_slice(state.repo_root, func_name)
                if not slice_data:
                    state.errors.append(f"function slice not found for: {func_name}")
                    state.done = True
                    continue

                obs = _replace_function_in_file(state.repo_root, slice_data, new_code)
                state.observations.append(obs)

                if obs.get("success"):
                    if slice_data.get("file") not in state.files_modified:
                        state.files_modified.append(slice_data.get("file"))
                    # AUTO COMMIT (deterministic)
                    try:
                        from tools.git_tools import smart_commit_pipeline
                        smart_commit_pipeline(state.goal, state.repo_root)
                        print("DEBUG: auto-commit executed")
                    except Exception as e:
                        print("DEBUG: commit skipped:", e)
                    state.done = True
                    continue
                else:
                    state.errors.append(obs.get("error"))
                    state.done = True
                    continue

            # normal file-level write path
            try:
                if path:
                    obs = write_file(path, content, state.repo_root, mode=mode)
            except Exception as e:
                obs = {"success": False, "error": str(e), "path": path}

            state.observations.append(obs)

            if obs.get("success"):
                if path not in state.files_modified:
                    state.files_modified.append(path)

                # AUTO COMMIT (deterministic, not LLM controlled)
                try:
                    from tools.git_tools import smart_commit_pipeline
                    smart_commit_pipeline(state.goal, state.repo_root)
                    print("DEBUG: auto-commit executed")
                except Exception as e:
                    print("DEBUG: commit skipped:", e)

                state.done = True

        # ================= RUN TESTS =================
        elif act == "run_tests":
            try:
                obs = run_tests(state.repo_root)
            except Exception as e:
                obs = {"success": False, "error": str(e)}

            state.observations.append(obs)

            if not obs.get("success"):
                state.errors.append(
                    f"tests_failed: {obs.get('returncode', obs.get('error'))}"
                )

        # ================= STOP =================
        elif act == "stop":
            state.done = True

        # ================= UNKNOWN =================
        else:
            state.errors.append(f"Unknown action: {action}")
            state.done = True

        # prevent CPU hammering
        time.sleep(0.2)

    return state