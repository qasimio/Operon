# agent/loop.py
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
from agent.llm import call_llm
from pathlib import Path
import re
import time

MAX_STEPS = 30


def _valid_path(action):
    path = action.get("path") if isinstance(action, dict) else None
    if isinstance(path, str) and path.strip():
        return path
    return None


def _latest_function_context(state):
    for obs in reversed(getattr(state, "observations", [])):
        if isinstance(obs, dict) and obs.get("function_context"):
            return obs.get("function_context")
    return None


def _extract_code_from_llm(output: str) -> str:
    m = re.search(r"```(?:python)?\\n(.*?)\\n```", output, re.S | re.I)
    if m:
        return m.group(1).rstrip() + "\n"
    return output.strip() + "\n"

def _safe_function_rewrite(original_name: str, new_code: str):

    if not new_code:
        return False

    txt = new_code.strip()

    # reject markdown / explanation junk
    if "```" in txt:
        return False

    # must contain same function name
    if f"def {original_name}(" not in txt:
        return False

    # must look like python, not bullets
    if txt.startswith("1.") or txt.startswith("-"):
        return False

    # must be reasonably long
    if len(txt) < 40:
        return False

    return True

def run_agent(state):

    # preload function context if mentioned in goal
    words = state.goal.replace("(", " ").replace(")", " ").split()
    for w in words:
        loc = find_function(state.repo_root, w)
        if loc:
            slice_data = load_function_slice(state.repo_root, w)
            if slice_data:
                state.observations.append({"function_context": slice_data})
                break

    # ensure plan
    if not getattr(state, "plan", None):
        state.plan = make_plan(state.goal, state.repo_root)

    print("\nPLAN:", state.plan, "\n")

    while not state.done and state.step_count < MAX_STEPS:

        action = None

        # force read first
        if not state.files_read:
            targets = extract_target_files(state.repo_root, state.goal)
            if not targets:
                try:
                    targets = search_repo(state.repo_root, state.goal)
                except:
                    targets = []
            if targets:
                action = {"action": "read_file", "path": targets[0]}

        # parsed write
        if action is None:
            multi = extract_multiline_append(state.goal)
            if multi and multi["path"] not in state.files_modified:
                action = multi
            else:
                parsed = parse_write_instruction(state.goal, state.repo_root)
                if parsed and parsed.get("path") and parsed.get("content"):
                    if parsed["path"] not in state.files_modified:
                        action = parsed

        # fallback LLM
        if action is None:
            action = decide_next_action(state) or {}

        print("DEBUG ACTION:", action)

        act = action.get("action")
        state.last_action = act
        state.step_count += 1

        # ================= READ =================
        if act == "read_file":
            path = _valid_path(action)
            if path:
                obs = read_file(path, state.repo_root)
                state.observations.append(obs)
                if path not in state.files_read:
                    state.files_read.append(path)
            else:
                state.errors.append("Invalid path for read_file")
                state.done = True

        # ================= WRITE =================
        elif act == "write_file":

            path = _valid_path(action)
            content = action.get("content", "")
            mode = action.get("mode", "append")

            # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
            # CRITICAL FIX
            # if model outputs path="function" OR goal is modification
            # convert into function rewrite automatically
            # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>

            if path == "function" or "modify" in state.goal.lower():

                func_ctx = _latest_function_context(state)
                if not func_ctx:
                    state.errors.append("No function context")
                    state.done = True
                    continue

                file_rel = func_ctx["file"]
                start = int(func_ctx["start"])
                end = int(func_ctx["end"])
                original = func_ctx["code"]

                prompt = f"""
Rewrite this Python function to satisfy the goal.

GOAL:
{state.goal}

FUNCTION:
{original}

Return ONLY the full rewritten function.
"""

                new_code = _extract_code_from_llm(call_llm(prompt))

                func_name = action.get("function_name")

                if not func_name or not _safe_function_rewrite(func_name, new_code):
                    state.errors.append("LLM returned unsafe rewrite — aborting")
                    state.done = True
                    continue

                full = Path(state.repo_root) / file_rel
                text = full.read_text(encoding="utf-8", errors="ignore")
                lines = text.splitlines(keepends=True)

                new_lines = new_code.splitlines(keepends=True)
                if not new_lines[-1].endswith("\n"):
                    new_lines[-1] += "\n"

                new_text = "".join(lines[:start-1] + new_lines + lines[end:])

                if not ask_user_approval("write_file", {"path": file_rel}):
                    state.done = True
                    continue

                obs = write_file(file_rel, new_text, state.repo_root, mode="overwrite")
                state.observations.append(obs)
                state.files_modified.append(file_rel)
                state.done = True
                continue

            # normal write
                if not path:
                    state.errors.append("Invalid path for write_file")
                    state.done = True
                    continue
    
                if not ask_user_approval("write_file", action):
                    state.done = True
                    continue
    
                obs = write_file(path, content, state.repo_root, mode=mode)
                state.observations.append(obs)
                state.files_modified.append(path)
                state.done = True

        # ================= TEST =================
        elif act == "run_tests":
            obs = run_tests(state.repo_root)
            state.observations.append(obs)

        elif act == "stop":
            state.done = True

        else:
            state.errors.append(f"Unknown action: {action}")
            state.done = True

        time.sleep(0.2)

    return state
