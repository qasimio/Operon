# agent/loop.py

from tools.repo_search import search_repo
from agent.goal_parser import (
    extract_target_files,
    parse_write_instruction,
    extract_multiline_append,
)
from agent.approval import ask_user_approval
from agent.decide import decide_next_action
from agent.planner import make_plan
from tools.fs_tools import read_file, write_file
from tools.shell_tools import run_tests
from tools.function_locator import find_function
from tools.code_slice import load_function_slice
import time


MAX_STEPS = 30


def _valid_path(action):
    path = action.get("path") if isinstance(action, dict) else None
    if isinstance(path, str) and path.strip():
        return path
    return None


def run_agent(state):


    # -------- FUNCTION CONTEXT DETECTION --------
    words = state.goal.replace("(", " ").replace(")", " ").split()

    for w in words:
        loc = find_function(state.repo_root, w)
        if loc:
            slice_data = load_function_slice(state.repo_root, w)
            if slice_data:
                state.observations.append(
                    {
                        "function_context": slice_data,
                        "function_location": loc,
                    }
                )
                break

    # -------- ENSURE PLAN EXISTS --------
    if not getattr(state, "plan", None):
        state.plan = make_plan(state.goal, state.repo_root)

    print("\nPLAN:", state.plan, "\n")

    # -------- MAIN LOOP --------
    while not state.done and state.step_count < MAX_STEPS:

        try:
            action = None

            # 1️⃣ Force first read if nothing read yet
            if not state.files_read:

                targets = extract_target_files(state.repo_root, state.goal)

                if not targets:
                    try:
                        targets = search_repo(state.repo_root, state.goal)
                        if targets:
                            print("SEARCH HIT:", targets[0])
                    except:
                        targets = []

                if targets:
                    action = {"action": "read_file", "path": targets[0]}

            # 2️⃣ Deterministic write parsing

                        # 2️⃣ Deterministic write parsing (FUNCTION SAFE)

            if action is None:

                # --- If function context exists → force file target ---
                func_file = None
                for obs in state.observations:
                    if "function_location" in obs:
                        func_file = obs["function_location"]["file"]
                        break

                multi = extract_multiline_append(state.goal)

                if multi:
                    # if model gave fake path like "function", replace with real file
                    if func_file:
                        multi["path"] = func_file
                    if multi.get("path") not in state.files_modified:
                        action = multi

                else:
                    parsed = parse_write_instruction(state.goal, state.repo_root)

                    if parsed and parsed.get("content"):

                        # override invalid pseudo-paths
                        if func_file:
                            parsed["path"] = func_file

                        if parsed.get("path") and parsed["path"] not in state.files_modified:
                            action = parsed

            # 3️⃣ Fallback to model
            if action is None:
                action = decide_next_action(state) or {}

        except Exception as e:
            state.errors.append(f"decision error: {e}")
            break

        print("DEBUG ACTION:", action)

        act = action.get("action")
        state.last_action = act
        state.step_count += 1

        # -------- FILE LOCK GUARD --------
        allowed_files = extract_target_files(state.repo_root, state.goal)
        if allowed_files:
            path = action.get("path")
            if path and path.lower() not in [p.lower() for p in allowed_files]:
                state.errors.append(f"Blocked unauthorized file: {path}")
                state.done = True
                continue

        # ================= READ FILE =================
        if act == "read_file":

            path = _valid_path(action)
            if not path:
                state.errors.append(f"invalid read_file action: {action}")
                continue

            try:
                obs = read_file(path, state.repo_root)
            except Exception as e:
                obs = {"success": False, "error": str(e), "path": path}

            state.observations.append(obs)

            if path not in state.files_read:
                state.files_read.append(path)

        # ================= WRITE FILE =================
        elif act == "write_file":

            path = _valid_path(action)
            if not path:
                state.errors.append(f"invalid write_file action: {action}")
                continue

            # ALWAYS require approval
            approved = ask_user_approval("write_file", action)
            if not approved:
                state.errors.append("write denied by user")
                state.done = True
                continue

            mode = action.get("mode", "append")
            content = action.get("content", "")

            try:
                obs = write_file(path, content, state.repo_root, mode=mode)
            except Exception as e:
                obs = {"success": False, "error": str(e), "path": path}

            state.observations.append(obs)

            if obs.get("success"):
                if path not in state.files_modified:
                    state.files_modified.append(path)

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

        # ================= STOP =================
        elif act == "stop":
            state.done = True

        # ================= UNKNOWN =================
        else:
            state.errors.append(f"Unknown action: {action}")
            state.done = True

        time.sleep(0.2)

    return state