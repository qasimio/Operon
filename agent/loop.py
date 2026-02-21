from tools.repo_search import search_repo
from agent.approval import ask_user_approval
from agent.decide import decide_next_action
from agent.planner import make_plan
from agent.logger import log
from tools.fs_tools import read_file
from tools.shell_tools import run_tests
from tools.function_locator import find_function
from tools.code_slice import load_function_slice
from agent.llm import call_llm
from pathlib import Path
import time

MAX_STEPS = 60

def _detect_function_from_goal(goal, repo_root):
    # Strip ALL punctuation so we don't miss functions wrapped in backticks or quotes
    import re
    clean_goal = re.sub(r"[^\w\s]", " ", goal)
    words = clean_goal.split()
    for w in words:
        loc = find_function(repo_root, w)
        if loc:
            return w, loc
    return None, None


def _rewrite_function(state, func_name, slice_data, file_path):
    from pathlib import Path
    from tools.diff_engine import parse_search_replace, apply_patch
    
    current_code = slice_data["code"]

    prompt = (
        "You are Operon, a surgical code editor.\n"
        f"GOAL: {state.goal}\n\n"
        "CURRENT FUNCTION TO MODIFY:\n"
        "```python\n"
        f"{current_code}\n"
        "```\n\n"
        "INSTRUCTIONS:\n"
        "You must modify the code using a SEARCH/REPLACE block.\n"
        "1. Find the exact original lines you need to change.\n"
        "2. Output a SEARCH block with the exact original lines.\n"
        "3. Output a REPLACE block with the new lines.\n\n"
        "EXAMPLE OUTPUT FORMAT:\n"
        "<<<<<<< SEARCH\n"
        "    def hello_world():\n"
        "        print(\"hello\")\n"
        "=======\n"
        "    def hello_world():\n"
        "        print(\"hello, world!\")\n"
        ">>>>>>> REPLACE\n\n"
        "RULES:\n"
        "- The SEARCH block must EXACTLY match the existing code character-for-character.\n"
        "- INDENTATION IS MANDATORY. You MUST include all leading spaces in the REPLACE block. If you drop the spaces, the code will break.\n"
        "- ONLY output the SEARCH/REPLACE block. No conversational text.\n"
        "- Keep the changes minimal. Do not replace the whole function.\n"
    )

    raw_output = call_llm(prompt, require_json=False)
    log.debug(f"Raw LLM Output:\n{raw_output}")
    
    blocks = parse_search_replace(raw_output)
    if not blocks:
        return {
            "success": False, 
            "error": f"LLM failed to output valid SEARCH/REPLACE blocks. RAW OUTPUT: {raw_output}"
        }

    full_path = Path(state.repo_root) / file_path
    if not full_path.exists():
        return {"success": False, "error": f"File not found: {file_path}"}

    file_text = full_path.read_text(encoding="utf-8")

    # Apply all patches
    for search_block, replace_block in blocks:
        patched_text = apply_patch(file_text, search_block, replace_block)
        
        if patched_text is None:
            return {
                "success": False,
                "error": "SEARCH block did not exactly match the file content. LLM hallucinated code."
            }
        file_text = patched_text

    # Write patched code back to disk
    full_path.write_text(file_text, encoding="utf-8")

    return {
        "success": True,
        "file": file_path,
        "message": f"Successfully applied {len(blocks)} patch(es)."
    }


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

        # ---------- HEURISTICS (Try to fast-track obvious actions) ----------
        if not state.files_read and loc and "file" in loc:
            action = {"action": "read_file", "path": loc["file"]}

        # NEW: Only rewrite if we haven't already modified this file!
        elif (func_name and loc and "file" in loc 
            and state.files_read 
            and loc["file"] not in state.files_modified
            and not any(f"Failed to write {func_name}" in e for e in state.errors)):
            action = {
                "action": "rewrite_function",
                "function": func_name,
                "file": loc["file"]
            }

        # ---------- FALLBACK TO LLM ----------
        # If heuristics didn't trigger, or failed, LET THE LLM DECIDE
        if not action:
            action = decide_next_action(state) or {}

        # Validate action
        if not isinstance(action, dict) or "action" not in action:
            log.error("FATAL: Invalid action dict. Ending loop.")
            state.done = True
            continue

        log.info(f"Executing action: {action.get('action')}")
        log.debug(f"Full state payload: {action}")

        act = action.get("action")
        state.last_action = act
        state.step_count += 1

        # ================= SEARCH REPO =================

        if act == "search_repo":
            query = action.get("query", "")
            if not query:
                log.error("Search query missing.")
                state.done = True
                continue
            
            log.info(f"Searching repo for: '{query}'")
            hits = search_repo(state.repo_root, query)
            
            # Format the hits so the LLM knows what it found
            if hits:
                obs = {"search_results": f"Found query '{query}' in files: {hits}"}
            else:
                obs = {"search_results": f"No matches found for '{query}'."}
                
            state.observations.append(obs)
            log.debug(f"Search results: {obs}")

        # ================= READ =================

        elif act == "read_file":

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

            # --- Centralized Logging & Git Commits for Patching ---
            if obs.get("success"):
                log.info(f"Successfully patched {action['file']}")
                
                if action["file"] not in state.files_modified:
                    state.files_modified.append(action["file"]) # Mark as done
                
                try:
                    from tools.git_tools import smart_commit_pipeline
                    smart_commit_pipeline(state.goal, state.repo_root)
                except Exception:
                    pass
            else:
                log.error(f"Patch failed: {obs.get('error')}")
                # Tell the state about the failure so the heuristic doesn't infinite loop!
                state.errors.append(f"Failed to rewrite {func_name}: {obs.get('error')}")
            # REMOVED state.done = True so the loop continues and the LLM can choose 'run_tests'

        # ================= TESTS =================
        elif act == "run_tests":
            
            log.info("Running test suite...")
            obs = run_tests(state.repo_root)
            state.observations.append(obs)
            
            # Additional terminal output so you know what happened
            if obs.get("success"):
                log.info("✅ Tests passed successfully.")
            else:
                log.error("❌ Tests FAILED.")
                log.debug(f"Test Stderr:\n{obs.get('stderr')}")

        else:
            log.info(f"Agent finished or chose unknown action: {act}")
            state.done = True

        time.sleep(0.2)

    return state