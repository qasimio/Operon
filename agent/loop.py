from tools.repo_search import search_repo
from agent.approval import ask_user_approval
from agent.decide import decide_next_action
from agent.planner import make_plan
from tools.fs_tools import read_file
from tools.shell_tools import run_tests
from tools.function_locator import find_function
from tools.code_slice import load_function_slice
from agent.llm import call_llm
from pathlib import Path
import time

MAX_STEPS = 30


def _detect_function_from_goal(goal, repo_root):
    words = goal.replace("(", " ").replace(")", " ").replace(".", " ").split()
    for w in words:
        loc = find_function(repo_root, w)
        if loc:
            return w, loc
    return None, None


def _rewrite_function(state, func_name, slice_data, file_path):

    from pathlib import Path
    import re

    current_code = slice_data["code"]

    prompt = f"""
Rewrite this Python function.

GOAL:
{state.goal}

FUNCTION:
{current_code}

STRICT RULES:
Return ONLY the full python function.
No markdown.
No explanation.
Must start with: def {func_name}
Do not rename parameters.
"""

    raw = call_llm(prompt)

    if not raw:
        return {"success": False, "error": "LLM empty"}

    # -------- CLEAN LLM OUTPUT --------

    # remove markdown fences
    raw = raw.replace("```python","").replace("```","").strip()

    # extract first real function
    m = re.search(r"(def\s+" + re.escape(func_name) + r"\s*\(.*)", raw, re.S)
    if not m:
        return {"success": False, "error": "LLM no function found"}

    new_code = m.group(1).rstrip()

    # -------- PATCH FILE --------

    full_path = Path(state.repo_root) / file_path

    try:
        lines = full_path.read_text(encoding="utf-8").splitlines()

        start = slice_data["start"] - 1
        end = slice_data["end"]

        updated = lines[:start] + new_code.splitlines() + lines[end:]

        full_path.write_text("\n".join(updated) + "\n", encoding="utf-8")

        return {"success": True}

    except Exception as e:
        return {"success": False, "error": str(e)}
def run_agent(state):

    func_name, loc = _detect_function_from_goal(state.goal, state.repo_root)

    if func_name:
        slice_data = load_function_slice(state.repo_root, func_name)
        if slice_data:
            state.observations.append({"function_context": slice_data})

    if not getattr(state, "plan", None):
        state.plan = make_plan(state.goal, state.repo_root)

    print("\nPLAN:", state.plan, "\n")

    while not state.done and state.step_count < MAX_STEPS:

        action = None

        # ---------- READ FIRST ----------
        if not state.files_read:

            if loc and "file" in loc:
                action = {"action": "read_file", "path": loc["file"]}

            else:
                hits = search_repo(state.repo_root, state.goal)
                if hits:
                    action = {"action": "read_file", "path": hits[0]}

        # ---------- FUNCTION REWRITE ----------
        elif func_name and loc and "file" in loc:

            action = {
                "action": "rewrite_function",
                "function": func_name,
                "file": loc["file"]
            }

        # ---------- FALLBACK ----------
        else:
            action = decide_next_action(state) or {}

        print("DEBUG ACTION:", action)

        if not isinstance(action, dict):
            state.done = True
            continue

        act = action.get("action")
        state.last_action = act
        state.step_count += 1

        # ================= READ =================
        if act == "read_file":

            path = action.get("path")
            if not path:
                state.done = True
                continue

            obs = read_file(path, state.repo_root)

            state.observations.append(obs)

            if path not in state.files_read:
                state.files_read.append(path)

        # ================= FUNCTION REWRITE =================
        elif act == "rewrite_function":

            if not ask_user_approval("rewrite_function", action):
                state.done = True
                continue

            if not func_name:
                state.errors.append("Function name not detected")
                state.done = True
                continue

            slice_data = load_function_slice(state.repo_root, func_name)

            if not slice_data:
                state.errors.append("Function slice missing")
                state.done = True
                continue

            obs = _rewrite_function(
                state,
                func_name,
                slice_data,
                action["file"]
            )

            state.observations.append(obs)

            if obs.get("success"):
                try:
                    from tools.git_tools import smart_commit_pipeline
                    smart_commit_pipeline(state.goal, state.repo_root)
                except Exception:
                    pass

            state.done = True

        # ================= TESTS =================
        elif act == "run_tests":

            obs = run_tests(state.repo_root)
            state.observations.append(obs)

        else:
            state.done = True

        time.sleep(0.2)

    return state