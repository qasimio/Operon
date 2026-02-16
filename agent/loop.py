# agent/loop.py (replace entire file with this)

from agent.goal_parser import extract_target_files
from agent.approval import ask_user_approval
from agent.decide import decide_next_action
from agent.planner import make_plan

from tools.fs_tools import read_file, write_file
from tools.git_tools import commit_to_new_branch
from tools.shell_tools import run_tests

import time

MAX_STEPS = 30


def _valid_path(action):
    """Return a safe string path or None."""
    path = action.get("path")
    if isinstance(path, str) and path.strip():
        return path
    return None


def run_agent(state):

    # ---------- ensure plan exists ----------
    if not getattr(state, "plan", None):
        state.plan = make_plan(state.goal, state.repo_root)

    print("\nPLAN:", state.plan, "\n")

    # ---------- main loop ----------
    while not state.done and state.step_count < MAX_STEPS:

        # ---------- get next action safely ----------
        try:
            action = decide_next_action(state) or {}
        except Exception as e:
            state.errors.append(f"decide_next_action crashed: {e}")
            break

        act = action.get("action")
        state.last_action = act
        state.step_count += 1

        allowed_files = extract_target_files(state.goal)

        if allowed_files:
            path = action.get("path")
            if path and path.lower() not in allowed_files:
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

        # ================= WRITE FILE =================
        elif act == "write_file":
            path = _valid_path(action)
            if not path:
                state.errors.append(f"write_file missing valid path: {action}")
                continue

            # approval gate
            if not ask_user_approval("write_file", action):
                state.errors.append("User denied write_file")
                # If user denies, we stop to avoid repeated requests
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

                # AUTO COMMIT PIPELINE
                from tools.git_tools import smart_commit_pipeline

                smart_commit_pipeline(state.goal, state.repo_root)

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

        # ================= GIT COMMIT =================
        elif act == "git_commit":
            # If no files were modified, ask user whether to continue with empty commit
            if not state.files_modified:
                ok = ask_user_approval("git_commit", {"note": "No files modified. Proceed with commit?"})
                if not ok:
                    state.errors.append("User denied git_commit due to no modified files")
                    # don't mark done; let agent decide next (or we stop to avoid loop)
                    state.done = True
                    continue

            # approval for commit (even if files modified)
            if not ask_user_approval("git_commit", action):
                state.errors.append("User denied git_commit")
                state.done = True
                continue

            prefix = action.get("branch_prefix", "agent/refactor")
            message = action.get("message", "agent automated commit")

            try:
                obs = commit_to_new_branch(prefix, message, state.repo_root)
            except Exception as e:
                obs = {"success": False, "error": str(e)}

            state.observations.append(obs)

            if obs.get("success"):
                state.done = True  # stop after successful commit
            else:
                state.errors.append(obs.get("error", str(obs)))

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
