from runtime import state
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
from tools.universal_parser import check_syntax
import agent.logger
import time
import re

MAX_STEPS = 20

def _detect_function_from_goal(goal, repo_root):
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
    from agent.approval import ask_user_approval
    
    prompt = f"""You are Operon, an elite surgical code editor.
GOAL: {state.goal}

CRITICAL CONTEXT:
You are editing: `{file_path}`

INSTRUCTIONS:
1. Output a SEARCH block matching the exact original lines.
2. Output a REPLACE block with the new lines.
3. CRITICAL: If the user asks you to replace MULTIPLE occurrences of something, or perform MULTIPLE distinct tasks (like adding an import AND changing a function), you MUST output MULTIPLE separate <<<<<<< SEARCH / >>>>>>> REPLACE blocks. Do not stop until ALL requirements of the goal are met in this file.

RULES FOR EDITING:
1. You MUST output your edits using strictly formatted SEARCH/REPLACE blocks.
2. The SEARCH block MUST perfectly match the exact lines in the original file, including indentation.
3. Keep the blocks small. Target only the specific function or lines that need changing.
4. INDENTATION IS MANDATORY.
5. **IF ADDING NEW CODE**: If you are simply appending new functions/code to the end of a file, leave the SEARCH block COMPLETELY EMPTY. Just put your new code in the REPLACE block.
6. **IF FILE IS EMPTY**: If the file has no code in it yet, leave the SEARCH block COMPLETELY EMPTY.

FORMAT REQUIREMENT:
<<<<<<< SEARCH
[Exact lines from the original file you want to replace]
=======
[The new modified lines]
>>>>>>> REPLACE

Here is the current code for `{file_path}`:
{code_to_modify}
Now, output the SEARCH/REPLACE block to achieve the goal."""

    log.debug(f"LLM Prompt for rewrite:\n{prompt}")
    raw_output = call_llm(prompt, require_json=False)
    
    blocks = parse_search_replace(raw_output)
    if not blocks:
        return {"success": False, "error": "LLM failed to output valid SEARCH/REPLACE blocks."}

    full_path = Path(state.repo_root) / file_path
    
    # Ensure file exists so we can read and write properly
    if not full_path.exists():
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.touch()

    file_text = full_path.read_text(encoding="utf-8")
    
    applied_count = 0
    for search_block, replace_block in blocks:
        if search_block.strip() == replace_block.strip():
            continue

        # --- ASK FOR UI APPROVAL USING OUR THREAD-SAFE QUEUE (Only ONCE now!) ---
        payload = {"file": file_path, "search": search_block.strip(), "replace": replace_block.strip()}
        if not ask_user_approval("rewrite_function", payload):
            return {"success": False, "error": "User rejected the code change during preview."}

        # --- BULLETPROOF APPLY PATCH ---
        # If the file is completely empty, ignore SEARCH entirely and just insert the code.
        if not file_text.strip():
            patched_text = replace_block.strip() + "\n"
        else:
            patched_text = apply_patch(file_text, search_block, replace_block)
            
            # Fallback to loose matching if exact fails
            if patched_text is None:
                log.warning("Strict match failed. Attempting whitespace-normalized matching...")
                words = search_block.strip().split()
                if words:
                    pattern = r'\s+'.join(re.escape(w) for w in words)
                    match = re.search(pattern, file_text)
                    if match:
                        patched_text = file_text[:match.start()] + replace_block + file_text[match.end():]
        
        if patched_text is None:
            return {"success": False, "error": "SEARCH block did not exactly match the file content."}
            
        file_text = patched_text
        applied_count += 1

    # SYNTAX SENTINEL (Universal parser check)
    if not check_syntax(file_text, file_path):
        error_msg = f"CRITICAL: SyntaxError detected in {file_path}! You broke the code structure. Rollback triggered."
        log.error(f"Syntax check failed for {file_path}.")
        return {"success": False, "error": error_msg}

    if applied_count == 0:
         return {"success": False, "error": "No valid changes were generated."}

    full_path.write_text(file_text, encoding="utf-8")
    return {"success": True, "file": file_path, "message": f"Applied {applied_count} patch(es). Syntax valid."}


def run_agent(state):
    from agent.tool_jail import ALLOWED_ACTIONS
    import time
    from pathlib import Path

    if not hasattr(state, "action_log"):
        state.action_log = []

    func_name, loc = _detect_function_from_goal(state.goal, state.repo_root)
    if func_name:
        slice_data = load_function_slice(state.repo_root, func_name)
        if slice_data:
            state.observations.append({"function_context": slice_data})

    if not getattr(state, "plan", None):
        state.plan = make_plan(state.goal, state.repo_root)
    print("\nPLAN:", state.plan, "\n")
    log.info(f"[bold magenta]PLAN GENERATED:[/bold magenta] {state.plan}")

    while not state.done and state.step_count < MAX_STEPS:
        decision = decide_next_action(state) or {}
        
        thought = decision.get("thought", "No thought process generated.")
        action_payload = decision.get("tool", decision)

        if not isinstance(action_payload, dict) or "action" not in action_payload:
            log.error("FATAL: Invalid action dict. LLM Hallucinated format.")
            state.observations.append({"error": "SYSTEM OVERRIDE: Invalid JSON format. You MUST output a dictionary with an 'action' key."})
            state.action_log.append("FAILED: LLM output did not contain a valid action.")
            time.sleep(1)
            continue

        act = action_payload.get("action")

        # ================= TOOL JAIL INTERCEPTION =================
        if act not in ALLOWED_ACTIONS:
            log.warning(f"Jail intercepted hallucinated tool: {act}")
            state.observations.append({"error": f"SYSTEM OVERRIDE: '{act}' is not a valid tool. Allowed: {list(ALLOWED_ACTIONS.keys())}"})
            state.action_log.append(f"FAILED: Hallucinated invalid tool '{act}'.")
            time.sleep(1)
            continue
            
        missing_fields = [f for f in ALLOWED_ACTIONS[act] if f not in action_payload]
        if missing_fields:
            err_msg = f"Tool '{act}' is missing required fields: {missing_fields}"
            log.warning(f"Jail intercepted bad payload: {err_msg}")
            state.observations.append({"error": f"SYSTEM OVERRIDE: {err_msg}"})
            state.action_log.append(f"FAILED: {err_msg}")
            time.sleep(1)
            continue

        # Programmatic Loop Breaker
        last_action_payload = getattr(state, "last_action_payload", None)
        state.last_action_payload = action_payload
        state.step_count += 1

        if last_action_payload == action_payload:
            log.error(f"LOOP DETECTED: Agent repeated exact tool: {action_payload}")
            state.observations.append({"error": f"SYSTEM OVERRIDE: Loop detected. You just tried to do exactly {action_payload} again. Do something else."})
            state.action_log.append(f"ERROR: Caught in a loop repeating '{act}'. System intervened.")
            time.sleep(1)
            continue 

        log.info(f"🧠 OPERON THOUGHT: {thought}")
        log.info(f"⚙️ EXECUTING TOOL: {act}")
        log.debug(f"Tool payload: {action_payload}")

        # ================= ROUTING =================
        if act == "finish":
            if not getattr(state, "files_modified", []):
                log.warning("Agent tried to finish without modifying any files! System override.")
                state.observations.append({"error": "SYSTEM OVERRIDE: You tried to finish, but you haven't patched any files yet. You must use 'rewrite_function' to achieve the goal before finishing."})
                state.action_log.append("ERROR: Attempted premature finish without any modifications.")
                continue
            
            files_read = getattr(state, "files_read", [])
            files_modified = getattr(state, "files_modified", [])
            if len(files_read) > len(files_modified):
                unpatched = [f for f in files_read if f not in files_modified]
                log.warning(f"Agent left files unpatched: {unpatched}")
                state.observations.append({"error": f"SYSTEM OVERRIDE: You read these files but NEVER patched them: {unpatched}. Did you forget to use 'rewrite_function'?"})
                state.action_log.append("ERROR: Attempted finish but left files unpatched.")
                continue

            msg = action_payload.get('message', 'All tasks completed.')
            log.info(f"✅ OPERON DECLARES VICTORY: {msg}")
            state.action_log.append(f"Session Finished: {msg}")
            state.done = True
            break
        
        elif act == "search_repo":
            query = action_payload.get("query", "")
            hits = search_repo(state.repo_root, query) if query else []
            
            if hits:
                obs = {"search_results": f"Found query '{query}' in files: {hits}"}
                state.action_log.append(f"Searched for '{query}'. Found {len(hits)} files.")
            else:
                obs = {"search_results": f"No matches found for '{query}'."}
                state.action_log.append(f"Searched for '{query}'. Found 0 files.")
                
            state.observations.append(obs)

        elif act == "read_file":
            path = action_payload.get("path")
            if not path:
                continue
            obs = read_file(path, state.repo_root)
            state.observations.append(obs)
            
            if "error" in obs:
                state.action_log.append(f"Attempted to read '{path}' but failed: {obs['error']}")
            else:
                state.action_log.append(f"Read contents of file '{path}'.")
                if path not in state.files_read:
                    state.files_read.append(path)

        elif act == "rewrite_function":
            target_file = action_payload.get("file")
            target_func = action_payload.get("function") or func_name

            if not target_file:
                state.observations.append({"error": "rewrite_function requires a 'file' parameter"})
                state.action_log.append("FAILED: rewrite_function missing 'file' parameter")
                continue

            code_to_modify = ""
            if target_func and target_func != "None":
                slice_data = load_function_slice(state.repo_root, target_func)
                if slice_data: code_to_modify = slice_data["code"]
            
            # --- FIX: SMART FILE CREATION ---
            full_path = Path(state.repo_root) / target_file
            if not full_path.exists():
                log.info(f"File {target_file} not found. Creating a new empty file so Operon can write to it.")
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.touch()

            if not code_to_modify:
                code_to_modify = full_path.read_text(encoding="utf-8")

            obs = _rewrite_function(state, code_to_modify, target_file)

            if obs.get("success"):
                log.info(f"Successfully patched {target_file}")
                state.action_log.append(f"SUCCESS: Applied code patch to '{target_file}'.")
                
                if target_file not in state.files_modified:
                    state.files_modified.append(target_file) 
                
                try:
                    from tools.git_tools import smart_commit_pipeline
                    smart_commit_pipeline(state.goal, state.repo_root)
                except Exception:
                    pass
            else:
                err = obs.get('error') or ""
                log.error(f"Patch failed: {err}")

                if "Patch failed" in err or "did not exactly match" in err:
                    err += " HINT: Your SEARCH block was wrong. Try matching a smaller, more unique part of the code, or leave SEARCH completely empty if appending to the bottom."

                state.action_log.append(f"FAILED patch on '{target_file}'. Error: {err}")
                state.observations.append({"error": err})

            state.observations.append(obs)

        time.sleep(0.2)

    return state