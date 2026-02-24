from time import time

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

def _edit_files(state, files_to_modify):
    from pathlib import Path
    from tools.diff_engine import apply_patch
    from agent.approval import ask_user_approval
    from tools.universal_parser import check_syntax
    import os

    # 1. Load context
    file_contexts = ""
    for f in files_to_modify:
        full_path = Path(state.repo_root) / f
        if not full_path.exists():
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.touch()
        content = full_path.read_text(encoding="utf-8")
        file_contexts += f"\n### FILE: {f} ###\n{content}\n"

    prompt = f"""You are Operon, an elite surgical code editor.
GOAL: {state.goal}

CRITICAL CONTEXT (Files loaded for editing):
{file_contexts}

INSTRUCTIONS:
You can edit multiple files at once. For EACH edit, you MUST specify the file path exactly as shown above, followed by the SEARCH/REPLACE block. 
The SEARCH block must be a SHORT, UNIQUE snippet (3-10 lines) of the file where the change goes. DO NOT output the entire file.

FORMAT REQUIREMENT:
### FILE: path/to/file.py ###
<<<<<<< SEARCH
[Exact lines from the original file]
=======
[New modified lines]
>>>>>>> REPLACE

RULES:
1. DO NOT wrap your output in ```python blocks.
2. The SEARCH block MUST perfectly match the exact lines in the original file, including leading spaces.
3. Repeat the FILE/SEARCH/REPLACE block for every file you need to modify.
"""
    from agent.llm import call_llm
    from agent.logger import log
    raw_output = call_llm(prompt, require_json=False)

    # 2. BULLETPROOF STATE MACHINE PARSER
    blocks = []
    current_file = None
    current_search = []
    current_replace = []
    state_mode = "LOOKING_FOR_FILE" # States: LOOKING_FOR_FILE, IN_SEARCH, IN_REPLACE

    for line in raw_output.splitlines():
        if line.startswith("### FILE:"):
            current_file = line.replace("### FILE:", "").replace("###", "").strip()
            state_mode = "LOOKING_FOR_FILE"
        elif line.startswith("<<<<<<< SEARCH"):
            state_mode = "IN_SEARCH"
        elif line.startswith("======="):
            state_mode = "IN_REPLACE"
        elif line.startswith(">>>>>>> REPLACE"):
            if current_file:
                blocks.append({
                    "file": current_file,
                    "search": "\n".join(current_search),
                    "replace": "\n".join(current_replace)
                })
            current_search, current_replace = [], []
            state_mode = "LOOKING_FOR_FILE"
        else:
            if state_mode == "IN_SEARCH": current_search.append(line)
            elif state_mode == "IN_REPLACE": current_replace.append(line)

    if not blocks:
        return {"success": False, "error": "LLM failed to output valid FILE/SEARCH/REPLACE blocks."}

    applied_count = 0
    files_changed = set()

    for block in blocks:
        file_path = block["file"]
        search_block = block["search"]
        replace_block = block["replace"]
        
        full_path = Path(state.repo_root) / file_path
        file_text = full_path.read_text(encoding="utf-8")

        if search_block.strip() == replace_block.strip(): continue

        # --- THE HARD STOP APPROVAL ---
        if not ask_user_approval("edit_files", {"file": file_path, "search": search_block, "replace": replace_block}):
            return {"success": False, "error": f"User rejected changes for {file_path}."}

        # --- APPLY PATCH ---
        if not file_text.strip():
            patched_text = replace_block + "\n"
        else:
            patched_text = apply_patch(file_text, search_block, replace_block)
            
        if patched_text is None:
            return {"success": False, "error": f"SEARCH block did not match in {file_path}. Make sure you copy the exact indentation."}

        # SYNTAX CHECK
        if not check_syntax(patched_text, file_path):
            return {"success": False, "error": f"SyntaxError detected in {file_path}. Rollback triggered."}

        full_path.write_text(patched_text, encoding="utf-8")
        applied_count += 1
        files_changed.add(file_path)

    return {"success": True, "files": list(files_changed), "message": f"Applied {applied_count} patches."}

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
        state.plan, state.is_question = make_plan(state.goal, state.repo_root)
        log.info(f"[bold magenta]🏛️ ARCHITECT PLAN:[/bold magenta] {state.plan}")
    
    state.phase = "CODER"

    while not getattr(state, "done", False) and state.step_count < MAX_STEPS:
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

        elif act == "edit_files":
            targets = action_payload.get("files", [])
            if isinstance(targets, str): targets = [targets] # Catch LLM hallucinating a string instead of array
            
            obs = _edit_files(state, targets)

            if obs.get("success"):
                changed_files = obs.get("files", [])
                log.info(f"Successfully patched {changed_files}")
                state.action_log.append(f"SUCCESS: Applied code patch to {changed_files}.")
                
                # --- THE AUTO-HANDOFF ---
                log.info("[bold cyan]🔄 Auto-Handing off to REVIEWER...[/bold cyan]")
                state.phase = "REVIEWER"
                state.context_buffer = {} # Wipe coder memory
                state.observations.append({"system": f"Coder successfully modified {changed_files}. Verify if the milestone is complete."})
            else:
                err = obs.get('error') or "Patch failed."
                log.error(err)
                state.action_log.append(f"FAILED multi-file patch.")
                state.observations.append({"error": err})

        elif act == "run_command":
            import subprocess
            cmd = action_payload.get("command", "")
            log.info(f"[bold green]💻 Running in terminal:[/bold green] {cmd}")
            try:
                result = subprocess.run(cmd, shell=True, cwd=state.repo_root, capture_output=True, text=True, timeout=15)
                output = result.stdout if result.returncode == 0 else result.stderr
                output = output[:2000] # Truncate massive logs so we don't blow up context
                obs = f"Exit Code: {result.returncode}\nOutput:\n{output}"
                state.action_log.append(f"Ran command: {cmd}")
            except subprocess.TimeoutExpired:
                obs = "Command timed out after 15 seconds."
                state.action_log.append(f"Command timed out: {cmd}")
            except Exception as e:
                obs = f"Execution failed: {str(e)}"
                state.action_log.append(f"Failed to run: {cmd}")
            
            state.observations.append({"terminal": obs})
               
            
    time.sleep(0.2)

    return state