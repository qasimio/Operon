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
import re

MAX_STEPS = 50

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
    
    prompt = (
        "You are Operon, a surgical code editor.\n"
        f"GOAL: {state.goal}\n\n"

        "CRITICAL CONTEXT - READ CAREFULLY:\n"
        f"You are CURRENTLY EDITING the file: `{file_path}`\n"
        f"Even if the goal mentions multiple files or tasks, you must IGNORE them right now.\n"
        f"Focus 100% ONLY on applying the necessary changes to `{file_path}`.\n"
        "DO NOT output SEARCH/REPLACE blocks for any other files.\n\n"

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
    
    blocks = parse_search_replace(raw_output)
    if not blocks:
        return {"success": False, "error": f"LLM failed to output valid SEARCH/REPLACE blocks. RAW: {raw_output}"}

    full_path = Path(state.repo_root) / file_path
    if not full_path.exists():
        return {"success": False, "error": f"File not found: {file_path}"}

    file_text = full_path.read_text(encoding="utf-8")

    for search_block, replace_block in blocks:
        if search_block.strip() == replace_block.strip():
            return {"success": False, "error": "REPLACE block is identical to SEARCH block. No changes made."}

        # --- PREVIEW CODE CHANGES ---
        print(f"\nFile: {file_path}\n")
        print("CHANGE:")
        print(search_block.strip())
        print("→")
        print(replace_block.strip())
        print()
        
        approval = input("Approve? y/n: ").strip().lower()
        if approval != 'y':
            return {"success": False, "error": "User rejected the specific code change during preview."}

        # --- APPLY PATCH ---
        patched_text = apply_patch(file_text, search_block, replace_block)
        
        # --- WHITESPACE-NORMALIZED MATCHING FALLBACK ---
        if patched_text is None:
            log.warning("Strict match failed. Attempting whitespace-normalized matching...")
            words = search_block.strip().split()
            if words:
                # Build regex that allows arbitrary spacing/newlines between all words
                pattern = r'\s+'.join(re.escape(w) for w in words)
                match = re.search(pattern, file_text)
                if match:
                    patched_text = file_text[:match.start()] + replace_block + file_text[match.end():]
                    log.info("Whitespace-normalized match successful!")
        
        if patched_text is None:
            return {"success": False, "error": "SEARCH block did not exactly match the file content, even with normalization."}
        
        file_text = patched_text

    # SYNTAX SENTINEL
    if file_path.endswith(".py"):
        try:
            ast.parse(file_text)
        except SyntaxError as e:
            error_msg = f"CRITICAL: SyntaxError! '{e.msg}' at line {e.lineno}. Rollback triggered."
            log.error(f"Syntax check failed for {file_path}.")
            return {"success": False, "error": error_msg}

    full_path.write_text(file_text, encoding="utf-8")
    return {"success": True, "file": file_path, "message": f"Applied {len(blocks)} patch(es). Syntax valid."}


def run_agent(state):
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

    while not state.done and state.step_count < MAX_STEPS:
        decision = decide_next_action(state) or {}
        
        # Unpack ReAct decision
        thought = decision.get("thought", "No thought process generated.")
        action = decision.get("tool", {})

        if not isinstance(action, dict) or "action" not in action:
            log.error("FATAL: Invalid action dict. Ending loop.")
            state.done = True
            continue

        act = action.get("action")

        # Programmatic Loop Breaker (Checks the tool payload, ignoring the thought)
        last_action_payload = getattr(state, "last_action_payload", None)
        state.last_action_payload = action
        state.step_count += 1

        if last_action_payload == action:
            log.error(f"LOOP DETECTED: Agent repeated exact tool: {action}")
            state.observations.append({"error": f"SYSTEM OVERRIDE: Loop detected. Do not repeat {action}."})
            state.action_log.append(f"ERROR: Caught in a loop repeating '{act}'. System intervened.")
            continue 

        # --- LOGGING THE AGENT'S THOUGHT PROCESS ---
        log.info(f"🧠 OPERON THOUGHT: {thought}")
        log.info(f"⚙️ EXECUTING TOOL: {act}")
        log.debug(f"Tool payload: {action}")

        # ================= FINISH =================
        if act == "finish":
            # PREMATURE FINISH SAFEGUARD
            if not getattr(state, "files_modified", []):
                log.warning("Agent tried to finish without modifying any files! System override.")
                state.observations.append({"error": "SYSTEM OVERRIDE: You tried to finish, but you haven't patched any files yet. You must use 'read_file' and then 'rewrite_function' to achieve the goal before finishing."})
                state.action_log.append("ERROR: Attempted premature finish without any modifications.")
                continue
            
            # MULTI-FILE SAFEGUARD: Check if they read files they forgot to patch
            files_read = getattr(state, "files_read", [])
            files_modified = getattr(state, "files_modified", [])
            if len(files_read) > len(files_modified):
                unpatched = [f for f in files_read if f not in files_modified]
                log.warning(f"Agent tried to finish but left files unpatched: {unpatched}")
                state.observations.append({"error": f"SYSTEM OVERRIDE: You read these files but NEVER patched them: {unpatched}. Did you forget to use 'rewrite_function' on them? Review the GOAL and ensure ALL tasks are complete before finishing."})
                state.action_log.append("ERROR: Attempted finish but left files unpatched.")
                continue

            msg = action.get('message', 'All tasks completed.')
            log.info(f"✅ OPERON DECLARES VICTORY: {msg}")
            state.action_log.append(f"Session Finished: {msg}")
            state.done = True
            break
        
        # ================= SEARCH REPO =================
        elif act == "search_repo":
            query = action.get("query", "")
            hits = search_repo(state.repo_root, query) if query else []
            
            if hits:
                obs = {"search_results": f"Found query '{query}' in files: {hits}"}
                state.action_log.append(f"Searched for '{query}'. Found {len(hits)} files.")
            else:
                obs = {"search_results": f"No matches found for '{query}'."}
                state.action_log.append(f"Searched for '{query}'. Found 0 files.")
                
            state.observations.append(obs)

        # ================= READ FILE =================
        elif act == "read_file":
            path = action.get("path")
            if not path:
                state_done = True
                continue
            obs = read_file(path, state.repo_root)
            state.observations.append(obs)
            
            if "Error" in str(obs):
                state.action_log.append(f"Attempted to read '{path}' but failed.")
            else:
                state.action_log.append(f"Read contents of file '{path}'.")
                if path not in state.files_read:
                    state.files_read.append(path)

        # ================= FUNCTION REWRITE =================
        elif act == "rewrite_function":
            target_file = action.get("file")
            target_func = action.get("function") or func_name

            if not target_file:
                state.errors.append("No file specified for rewrite.")
                state.action_log.append("FAILED to rewrite: No file specified.")
                continue

            # Bypass generic tool approval to rely on the granular diff preview inside _rewrite_function
            # if not ask_user_approval("rewrite_function", action):
            #     state.action_log.append(f"User rejected patch for {target_file}.")
            #     continue

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
                # Inject success into the human-readable action log!
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

        # ================= HALLUCINATION =================
        else:
            log.warning(f"LLM hallucinated unknown action: {act}")
            state.action_log.append(f"Hallucinated invalid action: {act}")
            state.observations.append({"error": f"SYSTEM OVERRIDE: '{act}' is NOT a valid tool."})
            time.sleep(1)

        time.sleep(0.2)

    return state