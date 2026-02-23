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

    # ================= ARCHITECT PHASE =================
    if not getattr(state, "plan", None):
        state.phase = "ARCHITECT"
        state.plan, state.is_question = make_plan(state.goal, state.repo_root)
        log.info(f"[bold magenta]🏛️ ARCHITECT PLAN (Is Question: {state.is_question}):[/bold magenta] {state.plan}")
    
    # Hand off to the Coder to begin Step 1
    state.phase = "CODER"

    while not state.done and state.step_count < MAX_STEPS:
        decision = decide_next_action(state) or {}
        
        thought = decision.get("thought", "No thought process generated.")
        action_payload = decision.get("tool", decision)

        if not isinstance(action_payload, dict) or "action" not in action_payload:
            log.error("FATAL: Invalid action dict. LLM Hallucinated format.")
            state.observations.append({"error": "SYSTEM OVERRIDE: Invalid JSON format. You MUST output a dictionary with an 'action' key."})
            time.sleep(1)
            continue

        act = action_payload.get("action")

        if act not in ALLOWED_ACTIONS:
            log.warning(f"Jail intercepted hallucinated tool: {act}")
            state.observations.append({"error": f"SYSTEM OVERRIDE: '{act}' is not a valid tool. Allowed: {list(ALLOWED_ACTIONS.keys())}"})
            time.sleep(1)
            continue

        last_action_payload = getattr(state, "last_action_payload", None)
        state.last_action_payload = action_payload
        state.step_count += 1

        if last_action_payload == action_payload:
            log.error(f"LOOP DETECTED: Agent repeated exact tool: {action_payload}")
            state.observations.append({"error": f"SYSTEM OVERRIDE: Loop detected. Do something else."})
            time.sleep(1)
            continue 

        log.info(f"🧠 {state.phase} THOUGHT: {thought}")
        log.info(f"⚙️ EXECUTING TOOL: {act}")

        # ================= MULTI-AGENT ROUTING =================
        if act == "step_complete":
            state.action_log.append(f"👨‍💻 CODER completed step {state.current_step + 1}: {action_payload.get('message', '')}")
            state.phase = "REVIEWER"
            log.info(f"[bold cyan]👨‍⚖️ Handing over to REVIEWER to check step {state.current_step + 1}...[/bold cyan]")
            
        elif act == "approve_step":
            state.action_log.append(f"👨‍⚖️ REVIEWER approved step {state.current_step + 1}: {action_payload.get('message', '')}")
            state.current_step += 1
            if state.current_step >= len(state.plan):
                log.info("[bold green]✅ All plan steps complete! REVIEWER should finish next.[/bold green]")
            state.phase = "CODER"
            log.info(f"[bold yellow]👨‍💻 Handing back to CODER for next step...[/bold yellow]")
            
        elif act == "reject_step":
            feedback = action_payload.get('feedback', 'No feedback provided.')
            state.action_log.append(f"❌ REVIEWER REJECTED step {state.current_step + 1}: {feedback}")
            state.observations.append({"reviewer_feedback": feedback})
            state.phase = "CODER"
            log.info(f"[bold red]👨‍💻 Handing back to CODER for corrections: {feedback}[/bold red]")
            
        elif act == "finish":
            # WE DELETED THE SYSTEM OVERRIDE. WE TRUST THE REVIEWER NOW!
            msg = action_payload.get('message', 'All tasks completed.')
            log.info(f"✅ OPERON DECLARES VICTORY: {msg}")
            state.action_log.append(f"Session Finished: {msg}")
            state.done = True
            break
        
        # ================= STANDARD TOOLS =================
        elif act == "search_repo":
            query = action_payload.get("query", "")
            hits = search_repo(state.repo_root, query) if query else []
            if hits:
                obs = {"search_results": f"Found '{query}' in: {hits}"}
                state.action_log.append(f"Searched for '{query}'. Found {len(hits)} files.")
            else:
                obs = {"search_results": f"No matches found for '{query}'."}
                state.action_log.append(f"Searched for '{query}'. Found 0 files.")
            state.observations.append(obs)

        elif act == "read_file":
            path = action_payload.get("path")
            if not path: continue
            obs = read_file(path, state.repo_root)
            state.observations.append(obs)
            if "error" in obs:
                state.action_log.append(f"Attempted to read '{path}' but failed.")
            else:
                state.action_log.append(f"Read contents of file '{path}'.")
                if path not in state.files_read:
                    state.files_read.append(path)

        elif act == "rewrite_function":
            target_file = action_payload.get("file")
            if not target_file: continue

            full_path = Path(state.repo_root) / target_file
            if not full_path.exists():
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.touch()

            code_to_modify = full_path.read_text(encoding="utf-8")
            obs = _rewrite_function(state, code_to_modify, target_file)

            if obs.get("success"):
                log.info(f"Successfully patched {target_file}")
                state.action_log.append(f"SUCCESS: Applied code patch to '{target_file}'.")
                if target_file not in state.files_modified:
                    state.files_modified.append(target_file) 
            else:
                err = obs.get('error') or ""
                log.error(f"Patch failed: {err}")
                if "Patch failed" in err or "did not exactly match" in err:
                    err += " HINT: Your SEARCH block was wrong. Match exact lines or leave empty to append."
                state.action_log.append(f"FAILED patch on '{target_file}'. Error: {err}")
                state.observations.append({"error": err})

        time.sleep(0.2)

    return state