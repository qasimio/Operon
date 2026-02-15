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

    # ensure plan exists
    if not getattr(state, "plan", None):
        state.plan = make_plan(state.goal, state.repo_root)

    while not state.done and state.step_count < MAX_STEPS:

        try:
            action = decide_next_action(state) or {}
        except Exception as e:
            state.errors.append(f"decide_next_action crashed: {e}")
            break

        state.last_action = action.get("action")
        state.step_count += 1

        act = action.get("action")

        # ---------------- READ FILE ----------------
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
                if hasattr(state, "files_read"):
                    state.files_read.append(path)
            else:
                state.errors.append(obs.get("error"))

        # ---------------- WRITE FILE ----------------
        elif act == "write_file":

            path = _valid_path(action)
            if not path:
                state.errors.append(f"write_file missing valid path: {action}")
                continue

            content = action.get("content", "")

            try:
                obs = write_file(path, content, state.repo_root)
            except Exception as e:
                obs = {"success": False, "error": str(e), "path": path}

            state.observations.append(obs)

            if obs.get("success"):
                if hasattr(state, "files_modified"):
                    state.files_modified.append(path)
            else:
                state.errors.append(obs.get("error"))

        # ---------------- RUN TESTS ----------------
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

        # ---------------- GIT COMMIT ----------------
        elif act == "git_commit":

            prefix = action.get("branch_prefix", "agent/refactor")
            message = action.get("message", "agent automated commit")

            try:
                obs = commit_to_new_branch(prefix, message, state.repo_root)
            except Exception as e:
                obs = {"success": False, "error": str(e)}

            state.observations.append(obs)

            if not obs.get("success"):
                state.errors.append(obs.get("error", str(obs)))

        # ---------------- STOP ----------------
        elif act == "stop":
            state.done = True

        # ---------------- UNKNOWN ----------------
        else:
            state.errors.append(f"Unknown action: {action}")
            state.done = True

        # avoid tight CPU loops
        time.sleep(0.2)

    return state




"""
Repeat:
    Ask AI what to do next
    Execute that action
    Record what happened
Stop when:
    AI says stop
    OR 20 steps reached
Return the final agent memory
"""