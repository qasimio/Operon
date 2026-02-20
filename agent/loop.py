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
                state.errors.append(f"write_file missing valid path: {action}")
                continue

            # ALWAYS require approval
            approved = ask_user_approval("write_file", action)
            if not approved:
                state.errors.append("write denied by user")
                state.done = True
                continue

            mode = action.get("mode", "append")
            content = action.get("content", "")

            # Try to find function context for this file (if any)
            func_ctx = None
            for obs in reversed(state.observations):
                if isinstance(obs, dict) and "function_context" in obs:
                    ctx = obs["function_context"]
                    if ctx.get("file") == path:
                        func_ctx = ctx
                        break

            obs = None

            # Heuristic: if we have a function context AND the provided content looks like an instruction
            # (not a direct code snippet), ask the LLM to generate the updated function and apply it in-place.
            try:
                from agent.llm import call_llm
                from pathlib import Path
                import re
            except Exception:
                call_llm = None

            def looks_like_instruction(text: str) -> bool:
                t = text.strip()
                # If it has newlines and starts with a bullet/number or plain English, treat as instruction.
                if not t:
                    return False
                if t.startswith("def ") or t.startswith("class ") or t.startswith("async def "):
                    return False
                # contains common instruction markers
                if t.startswith("1.") or t.startswith("- ") or "log" in t.lower() or "insert" in t.lower() or "modify" in t.lower():
                    return True
                # if content has many natural-language words (heuristic)
                if len(t.split()) > 6 and not ("\n" in t and len(t.splitlines()) < 3):
                    return True
                return False

            if func_ctx and call_llm and looks_like_instruction(content):
                # Build LLM prompt
                prompt = (
                    "You are a careful Python developer. Do NOT add any explanation. "
                    "Given the FUNCTION below and the GOAL, return the COMPLETE UPDATED FUNCTION ONLY "
                    "(starting with `def` or `async def` or `class`), using valid Python syntax.\n\n"
                    "FUNCTION CODE:\n\n"
                    f"{func_ctx['code']}\n\n"
                    "GOAL:\n\n"
                    f"{state.goal}\n\n"
                    "Return only the updated function (or the original if no change needed). No markdown."
                )

                try:
                    llm_out = call_llm(prompt)
                except Exception as e:
                    llm_out = ""

                # try to extract code block if model used markdown fences
                new_func = ""
                if isinstance(llm_out, str) and llm_out.strip():
                    m = re.search(r"```(?:python)?\n(.*?)```", llm_out, re.S)
                    if m:
                        new_func = m.group(1).strip()
                    else:
                        new_func = llm_out.strip()

                # sanity-check generated output
                if new_func and (new_func.startswith("def ") or new_func.startswith("async def ") or new_func.startswith("class ")):
                    # apply replacement of slice in the file
                    file_path = Path(state.repo_root) / path
                    try:
                        text = file_path.read_text(encoding="utf-8", errors="ignore")
                        lines = text.splitlines()
                        s = func_ctx.get("slice_start", func_ctx.get("start", 1))
                        e = func_ctx.get("slice_end", func_ctx.get("end", len(lines)))
                        # replace lines s..e (1-indexed)
                        pre = lines[: s - 1]
                        post = lines[e:]
                        new_lines = new_func.splitlines()
                        new_text = "\n".join(pre + new_lines + post) + ("\n" if not new_func.endswith("\n") else "")
                        file_path.write_text(new_text, encoding="utf-8")
                        obs = {"success": True, "path": path, "mode": "overwrite", "written_bytes": len(new_text)}
                    except Exception as e:
                        obs = {"success": False, "path": path, "error": f"apply_patch_failed: {e}"}
                else:
                    # generation failed or not useful → fallback to existing write_file behavior
                    try:
                        obs = write_file(path, content, state.repo_root, mode=mode)
                    except Exception as e:
                        obs = {"success": False, "error": str(e), "path": path}
            else:
                # No function context or not an instruction → fallback to original behaviour
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

            else:
                state.errors.append(obs.get("error"))

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