from tools.repo_search import search_repo
from agent.approval import ask_user_approval
from agent.decide import decide_next_action
from agent.planner import make_plan
from agent.logger import log
from tools.fs_tools import read_file
from tools.function_locator import find_function
from tools.code_slice import load_function_slice
from agent.llm import call_llm
from pathlib import Path
import ast
import time

MAX_STEPS = 40

def _detect_function_from_goal(goal, repo_root):
    import re
    clean_goal = re.sub(r"[^\w\s]", " ", goal)
    words = clean_goal.split()
    for w in words:
        loc = find_function(repo_root, w)
        if loc:
            return w, loc
    return None, None

def _rewrite_function(state, code_to_modify, file_path):
    from pathlib import Path
    from tools.diff_engine import parse_search_replace, apply_patch
    
    prompt = (
        "You are Operon, a surgical code editor.\n"
        f"GOAL: {state.goal}\n\n"
        "CURRENT CODE TO MODIFY:\n"
        "```python\n"
        f"{code_to_modify}\n"
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

    log.debug(f"LLM Prompt for rewrite:\n{prompt}")
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
        if search_block.strip() == replace_block.strip():
            return {
                "success": False,
                "error": "The REPLACE block is identical to the SEARCH block. You made no changes. Read the goal again and provide actual modifications."
            }

        patched_text = apply_patch(file_text, search_block, replace_block)
        
        if patched_text is None:
            return {
                "success": False,
                "error": "SEARCH block did not exactly match the file content. LLM hallucinated code."
            }
        file_text = patched_text

    # ========================================================
    # 🛡️ THE SYNTAX SENTINEL (IN-MEMORY ROLLBACK)
    # ========================================================
    if file_path.endswith(".py"):
        try:
            # We try to parse the new code into an Abstract Syntax Tree BEFORE saving
            ast.parse(file_text)
        except SyntaxError as e:
            # If it fails, we ABORT. The bad code never touches the hard drive.
            error_msg = f"CRITICAL: Your patch introduced a Python SyntaxError! '{e.msg}' at line {e.lineno}. The rollback was triggered and the file was NOT saved. You MUST read the file again or rewrite the function with correct Python syntax."
            log.error(f"Syntax check failed for {file_path}. Rollback triggered.")
            return {"success": False, "error": error_msg}

    # If we made it here, the syntax is perfectly valid!
    # Write patched code back to disk
    full_path.write_text(file_text, encoding="utf-8")

    return {
        "success": True,
        "file": file_path,
        "message": f"Successfully applied {len(blocks)} patch(es). Syntax is valid."
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

        # ---------- LET DECIDE.PY DO ITS JOB ----------
        # (We deleted the hardcoded heuristics block)
        action = decide_next_action(state) or {}

        if not isinstance(action, dict) or "action" not in action:
            log.error("FATAL: Invalid action dict. Ending loop.")
            state.done = True
            continue

        # ================= PROGRAMMATIC LOOP BREAKER =================
        last_dict = getattr(state, "last_action_dict", None)
        if last_dict == action:
            log.error(f"LOOP DETECTED: LLM repeated exact action: {action}")
            
            # Context-Aware Hard Nudge
            act_name = action.get("action")
            if act_name == "search_repo":
                nudge = "DO NOT SEARCH AGAIN. You MUST use 'read_file' on the most promising file you found."
            elif act_name == "read_file":
                nudge = "DO NOT READ THE SAME FILE AGAIN. You MUST use 'rewrite_function' to modify the code, or use 'stop' if no changes are needed."
            elif act_name == "rewrite_function":
                nudge = "DO NOT EDIT REPEATEDLY. You MUST use 'run_tests' to verify your changes, or 'stop' if the goal is met."
            else:
                nudge = "YOU ARE IN A LOOP. You MUST pick a completely different action."

            override_msg = f"SYSTEM CRITICAL ERROR: You are stuck in a loop repeating {action}. {nudge}"
            
            state.observations.append({"error": override_msg})
            state.step_count += 1
            
            if len(state.observations) > 10:
                state.observations = state.observations[:3] + state.observations[-2:]
                
            continue 
            
        # Save the action so we can check it next loop
        state.last_action_dict = action
        # =============================================================

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
            
            if hits:
                log.info(f"Search found files: {hits}")
                obs = {"search_results": f"Found query '{query}' in files: {hits}"}
            else:
                log.info(f"Search found NO files for '{query}'.")
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
            target_file = action.get("file")
            target_func = action.get("function") # The LLM's chosen function
            
            # Fallback to the heuristic's function name if the LLM left it blank
            target_func = target_func or func_name

            if not target_file:
                state.errors.append("No file specified for rewrite.")
                state.done = True
                continue

            if not ask_user_approval("rewrite_function", action):
                state.done = True
                continue

            # NEW: Try to get a slice, but fallback to the full file if not found/provided!
            code_to_modify = ""
            if target_func:
                slice_data = load_function_slice(state.repo_root, target_func)
                if slice_data:
                    code_to_modify = slice_data["code"]
            
            if not code_to_modify:
                # Read the full file instead
                full_path = Path(state.repo_root) / target_file
                if full_path.exists():
                    code_to_modify = full_path.read_text(encoding="utf-8")
                else:
                    error_msg = f"File not found: {target_file}. You used the wrong path. Check the search results and try again (e.g., agent/logger.py)."
                    state.errors.append(error_msg)
                    state.observations.append({"error": error_msg})
                    # DO NOT set state.done = True! Let it loop and try again.
                    continue

            obs = _rewrite_function(
                state,
                code_to_modify,
                target_file
            )

            state.observations.append(obs)

            if obs.get("success"):
                log.info(f"Successfully patched {target_file}")
                
                if target_file not in state.files_modified:
                    state.files_modified.append(target_file) 
                
                try:
                    from tools.git_tools import smart_commit_pipeline
                    smart_commit_pipeline(state.goal, state.repo_root)
                except Exception:
                    pass
            else:
                log.error(f"Patch failed: {obs.get('error')}")
                error_msg = f"Failed to rewrite {target_func or target_file}: {obs.get('error')}"
                state.errors.append(error_msg)

# ================= STOP =================
        elif act == "stop":
            log.info("Agent has declared the goal met and requested to stop.")
            state.done = True

        # ================= HALLUCINATION RECOVERY =================
        else:
            log.warning(f"LLM hallucinated unknown action: {act}")
            state.observations.append({
                "error": f"SYSTEM OVERRIDE: '{act}' is NOT a valid action. You MUST strictly use one of these exact names: search_repo, read_file, rewrite_function, or stop."
            })
            time.sleep(1)

        time.sleep(0.2)

    return state