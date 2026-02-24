from tools.git_safety import setup_git_env, rollback_macro, commit_success
from tools.repo_search import search_repo
from agent.decide import decide_next_action
from agent.planner import make_plan
from agent.logger import log
from tools.fs_tools import read_file
from tools.function_locator import find_function
from agent.llm import call_llm
from tools.universal_parser import check_syntax
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
    
# Inside _rewrite_function in agent/loop.py, update the prompt variable:

    prompt = f"""You are Operon, an elite surgical code editor.
GOAL: {state.goal}

CRITICAL CONTEXT:
You are editing: `{file_path}`

INSTRUCTIONS:
1. Output a SEARCH block matching the exact original lines.
2. Output a REPLACE block with the new lines.
3. CRITICAL RULES:
   - DO NOT wrap your output in ```python or ```markdown blocks. Output the raw <<<<<<< SEARCH format directly.
   - The SEARCH block MUST perfectly match the exact lines in the original file, including indentation.
   - If adding to the very end of a file, leave the SEARCH block COMPLETELY EMPTY.

FORMAT REQUIREMENT:
<<<<<<< SEARCH
[Exact lines from the original file you want to replace]
=======
[The new modified lines]
>>>>>>> REPLACE

Here is the current code for `{file_path}`:
{code_to_modify}
Now, output the raw SEARCH/REPLACE block to achieve the goal."""

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
    original_file_text = file_text
    
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
        # Restores the file instantly without messing with Git
        full_path.write_text(original_file_text, encoding="utf-8")
        return {"success": False, "error": error_msg}

    if applied_count == 0:
         return {"success": False, "error": "No valid changes were generated."}

    full_path.write_text(file_text, encoding="utf-8")
    return {"success": True, "file": file_path, "message": f"Applied {applied_count} patch(es). Syntax valid."}

def run_agent(state):
    from agent.tool_jail import validate_tool
    import time
    from pathlib import Path

    if not hasattr(state, "action_log"): state.action_log = []
    if not hasattr(state, "observations"): state.observations = []
    if not hasattr(state, "context_buffer"): state.context_buffer = {}
    if not hasattr(state, "current_step"): state.current_step = 0
    if not hasattr(state, "loop_counter"): state.loop_counter = 0

    # ================= ARCHITECT PHASE =================
    if not getattr(state, "plan", None):
        state.phase = "ARCHITECT"

        state.git_state = setup_git_env(state.repo_root)

        state.plan, state.is_question = make_plan(state.goal, state.repo_root)
        log.info(f"[bold magenta]🏛️ ARCHITECT PLAN:[/bold magenta] {state.plan}")
    
    state.phase = "CODER"

    while not getattr(state, "done", False):
        # macro roll back

        if state.step_count >= MAX_STEPS:
            log.error(f"Hit max steps({MAX_STEPS}). Operon failed to complete the task.")
            rollback_macro(state.repo_root, getattr(state, "git_state", {}))
            break

        decision = decide_next_action(state) or {}
        thought = decision.get("thought", "Thinking...")
        action_payload = decision.get("tool", decision)

        act = action_payload.get("action")
        
        # --- 1. STRICT TOOL VALIDATION ---
        is_valid, val_msg = validate_tool(act, action_payload, state.phase)
        if not is_valid:
            log.warning(f"Jail intercepted: {val_msg}")
            state.observations.append({"error": f"SYSTEM OVERRIDE: {val_msg}"})
            time.sleep(1)
            continue

        # --- 2. THE LOOP BREAKER ---
        last_payload = getattr(state, "last_action_payload", None)
        if last_payload == action_payload:
            state.loop_counter += 1
            log.error(f"LOOP DETECTED ({state.loop_counter}): Repeated {act}")
            
            if state.loop_counter >= 3:
                log.error("CRITICAL LOOP. Wiping memory and forcing REVIEWER handoff.")
                state.observations.append({"error": "FATAL LOOP OVERRIDE: You are stuck. Submitting for review."})
                state.phase = "REVIEWER"
                state.last_action_payload = None # Wipe payload to break the cycle
                state.loop_counter = 0
                time.sleep(1)
                continue
            else:
                state.observations.append({"error": "SYSTEM OVERRIDE: You just did this exact action. DO SOMETHING ELSE."})
                time.sleep(1)
                continue
        else:
            state.loop_counter = 0 # Reset on fresh action
            state.last_action_payload = action_payload

        state.step_count += 1
        log.info(f"🧠 {state.phase} THOUGHT: {thought}")
        log.info(f"⚙️ EXECUTING: {act}")

        # ================= ROUTING & EXECUTION =================
        if act == "approve_step":
            state.action_log.append(f"👨‍⚖️ REVIEWER approved step {state.current_step + 1}.")
            state.current_step += 1
            
            if state.current_step >= len(state.plan):
                log.info("[bold green]✅ All steps complete! REVIEWER should finish next.[/bold green]")
                state.observations.append({"system": "All steps complete. You must use the 'finish' tool."})
            else:
                state.phase = "CODER"
                state.observations = [] # Clear obs for the new step
                log.info(f"[bold yellow]👨‍💻 Back to CODER for next step...[/bold yellow]")
                
        elif act == "reject_step":
            feedback = action_payload.get('feedback', '')
            state.action_log.append(f"❌ REVIEWER REJECTED step {state.current_step + 1}: {feedback}")
            state.observations.append({"reviewer_feedback": feedback})
            state.phase = "CODER"
            log.info(f"[bold red]👨‍💻 Back to CODER for corrections...[/bold red]")
            
        elif act == "finish":
            msg = action_payload.get('message', 'Complete.')
            log.info(f"✅ OPERON VICTORY: {msg}")

            commit_success(state.repo_root, msg)

            state.done = True
            break
   # Inside your run_agent function in agent/loop.py

        elif act == "semantic_search": # Renamed from search_repo
            query = action_payload.get("query", "")
            hits = search_repo(state.repo_root, query) if query else [] # Your LanceDB logic
            obs = f"Semantic matches for '{query}': {hits}" if hits else f"No matches."
            state.observations.append({"search": obs})
            state.action_log.append(f"Semantic search: '{query}'.")

        elif act == "exact_search":
            search_text = action_payload.get("text", "")
            import os
            hits = []
            # Simple python grep equivalent
            for root, _, files in os.walk(state.repo_root):
                if '.git' in root or '__pycache__' in root or 'venv' in root: continue
                for file in files:
                    if not file.endswith('.py') and not file.endswith('.md'): continue
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            if search_text in f.read():
                                hits.append(os.path.relpath(file_path, state.repo_root))
                    except: pass
            
            obs = f"Exact matches for '{search_text}': {hits}" if hits else f"No exact matches found."
            state.observations.append({"exact_search": obs})
            state.action_log.append(f"Exact search for '{search_text}'.")

        elif act == "read_file":
            path = action_payload.get("path")
            obs = read_file(path, state.repo_root)
            if "error" in obs:
                state.observations.append(obs)
                state.action_log.append(f"Failed to read '{path}'.")
            else:
                state.context_buffer[path] = obs["content"]
                state.observations.append({"success": f"Loaded {path} into memory."})
                state.action_log.append(f"Loaded '{path}' into memory.")

        elif act == "rewrite_function":
            target_file = action_payload.get("file")
            full_path = Path(state.repo_root) / target_file
            if not full_path.exists(): full_path.touch()

            code_to_modify = full_path.read_text(encoding="utf-8")
            obs = _rewrite_function(state, code_to_modify, target_file)

            if obs.get("success"):
                log.info(f"Successfully patched {target_file}")
                state.action_log.append(f"SUCCESS: Applied code patch to '{target_file}'.")
                
                # --- THE AUTO-HANDOFF (FIXED) ---
                log.info("[bold cyan]🔄 Auto-Handing off to REVIEWER...[/bold cyan]")
                state.phase = "REVIEWER"
                
                # 1. Read the fresh, newly updated code
                updated_code = full_path.read_text(encoding="utf-8")
                
                # 2. Give the Reviewer the exact file context so it isn't blind
                state.context_buffer = {target_file: updated_code} 
                
                # 3. Force the Reviewer to acknowledge the update
                state.observations.append({
                    "system": f"Coder successfully modified {target_file}. REVIEWER MUST look at the updated file in context and verify the goal was met before rejecting.",
                    "file_preview": updated_code[:2000] # Inject a preview so it doesn't even need to use read_file
                })

        time.sleep(0.2)

    return state