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
import agent.logger
import ast
import time
import re

MAX_STEPS = 30

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
    
    prompt = (
        "You are Operon, an elite surgical code editor.\n"
        f"GOAL: {state.goal}\n\n"
        "CRITICAL CONTEXT:\n"
        f"You are editing: `{file_path}`\n\n"
        "CURRENT CODE:\n"
        f"```python\n{code_to_modify}\n```\n\n"
        "INSTRUCTIONS:\n"
        "1. Output a SEARCH block matching the exact original lines.\n"
        "2. Output a REPLACE block with the new lines.\n"
        "3. CRITICAL: If the user asks you to replace MULTIPLE occurrences of something, or perform MULTIPLE distinct tasks (like adding an import AND changing a function), you MUST output MULTIPLE separate <<<<<<< SEARCH / >>>>>>> REPLACE blocks. Do not stop until ALL requirements of the goal are met in this file.\n\n"
        "EXAMPLE FORMAT:\n"
        "<<<<<<< SEARCH\noriginal code\n=======\nnew code\n>>>>>>> REPLACE\n\n"
        "RULES:\n"
        "- SEARCH block must EXACTLY match character-for-character.\n"
        "- INDENTATION IS MANDATORY.\n"
    )

    log.debug(f"LLM Prompt for rewrite:\n{prompt}")
    raw_output = call_llm(prompt, require_json=False)
    
    blocks = parse_search_replace(raw_output)
    if not blocks:
        return {"success": False, "error": "LLM failed to output valid SEARCH/REPLACE blocks."}

    for search_block, replace_block in blocks:
        payload = {
            "file": file_path,
            "search": search_block.strip(),
            "replace": replace_block.strip()
        }
    
    if not ask_user_approval("rewrite_function", payload):
        return {"success": False, "error": "User rejected the code change during preview."}

    code_to_modify = code_to_modify.replace(search_block, replace_block)
    if code_to_modify is None:
        return {"success": False, "error": "Failed to apply patch. SEARCH block not found in the original code."}

    full_path = Path(state.repo_root) / file_path
    if not full_path.exists():
        return {"success": False, "error": f"File not found: {file_path}"}

    file_text = full_path.read_text(encoding="utf-8")
    
    applied_count = 0
    for search_block, replace_block in blocks:
        if search_block.strip() == replace_block.strip():
            continue

        # --- ASK FOR UI APPROVAL USING OUR NEW THREAD-SAFE QUEUE ---
        payload = {"file": file_path, "search": search_block.strip(), "replace": replace_block.strip()}
        if not ask_user_approval("rewrite_function", payload):
            return {"success": False, "error": "User rejected the code change during preview."}

        # --- APPLY PATCH ---
        patched_text = apply_patch(file_text, search_block, replace_block)
        
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

    # SYNTAX SENTINEL
    if file_path.endswith(".py"):
        try:
            ast.parse(file_text)
        except SyntaxError as e:
            error_msg = f"CRITICAL: SyntaxError! '{e.msg}' at line {e.lineno}. Rollback triggered."
            return {"success": False, "error": error_msg}

    if applied_count == 0:
         return {"success": False, "error": "No valid changes were generated."}

    full_path.write_text(file_text, encoding="utf-8")
    return {"success": True, "file": file_path, "message": f"Applied {applied_count} patch(es). Syntax valid."}


def run_agent(state):
    from agent.tool_jail import ALLOWED_ACTIONS
    import time
    from pathlib import Path

    # Initialize robust Episodic Memory
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
        
        # Unpack ReAct decision
        thought = decision.get("thought", "No thought process generated.")
        
        # Flexibly handle if LLM output {"tool": {"action": "x"}} OR just {"action": "x"}
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
        # ==========================================================

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

        # --- LOGGING THE AGENT'S THOUGHT PROCESS ---
        log.info(f"🧠 OPERON THOUGHT: {thought}")
        log.info(f"⚙️ EXECUTING TOOL: {act}")
        log.debug(f"Tool payload: {action_payload}")

        # ================= ROUTING =================
        if act == "finish":
            # PREMATURE FINISH SAFEGUARD
            if not getattr(state, "files_modified", []):
                log.warning("Agent tried to finish without modifying any files! System override.")
                state.observations.append({"error": "SYSTEM OVERRIDE: You tried to finish, but you haven't patched any files yet. You must use 'rewrite_function' to achieve the goal before finishing."})
                state.action_log.append("ERROR: Attempted premature finish without any modifications.")
                continue
            
            # MULTI-FILE SAFEGUARD
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
                state_done = True
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
            
            if not code_to_modify:
                full_path = Path(state.repo_root) / target_file
                if full_path.exists():
                    code_to_modify = full_path.read_text(encoding="utf-8")
                else:
                    error_msg = f"File not found: {target_file}"
                    state.observations.append({"error": error_msg})
                    state.action_log.append(f"FAILED to rewrite: {error_msg}")
                    continue

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
                err = obs.get('error')
                log.error(f"Patch failed: {err}")
                state.action_log.append(f"FAILED patch on '{target_file}'. Error: {err}")

            state.observations.append(obs)

        time.sleep(0.2)

    return state