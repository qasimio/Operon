# agent/loop.py (overwrite)
from runtime import state
from tools.repo_search import search_repo
from agent.goal_parser import extract_target_files, parse_write_instruction
from agent.approval import ask_user_approval
from agent.decide import decide_next_action
from agent.planner import make_plan
from agent.goal_parser import extract_multiline_append
from tools.fs_tools import read_file, write_file
from tools.shell_tools import run_tests
from tools.function_locator import find_function
from tools.code_slice import load_function_slice
import time 


MAX_STEPS = 30


def _valid_path(action):
    """Return a safe string path or None."""
    path = action.get("path") if isinstance(action, dict) else None
    if isinstance(path, str) and path.strip():
        return path
    return None


def run_agent(state):

    # detect function names inside goal
    words = state.goal.replace("(", " ").replace(")", " ").split()

    for w in words:

        loc = find_function(state.repo_root, w)

        if loc:
            slice_data = load_function_slice(state.repo_root, w)

            if slice_data:
                state.observations.append({
                    "function_context": slice_data
                })
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
                    except:
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
            path = action.get("path")
            if path and path.lower() not in [p.lower() for p in allowed_files]:
                state.errors.append(f"Blocked unauthorized file: {path}")
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
            if not path:
                state.errors.append(f"write_file missing valid path: {action}")
                continue

            # approval gate (always triggered)
            if not ask_user_approval("write_file", action):
                state.errors.append("User denied write_file")
                state.done = True
                continue

            # default to append behaviour unless explicitly asked to overwrite
            mode = action.get("mode", "append")  # "append" or "overwrite"
            content = action.get("content", "")

            try:
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
