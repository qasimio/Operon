# agent/loop.py  (cleaned, drop-in)
from tools.fs_tools import read_file
from tools.git_safety import setup_git_env, rollback_macro, commit_success
from tools.repo_search import search_repo
from agent.decide import decide_next_action
from agent.planner import make_plan
from agent.logger import log
from tools.function_locator import find_function
from agent.llm import call_llm
from tools.universal_parser import check_syntax
from pathlib import Path
import re
import time
import json
import os

MAX_STEPS = 25

# --- Helpers -----------------------------------------------------------------
def _ensure_state_fields(state):
    # Minimal, safe defaults so the rest of the loop can assume these exist
    if not hasattr(state, "action_log"): state.action_log = []
    if not hasattr(state, "observations"): state.observations = []
    if not hasattr(state, "context_buffer"): state.context_buffer = {}
    if not hasattr(state, "current_step"): state.current_step = 0
    if not hasattr(state, "loop_counter"): state.loop_counter = 0
    if not hasattr(state, "last_action_payload"): state.last_action_payload = None
    if not hasattr(state, "step_count"): state.step_count = 0
    if not hasattr(state, "files_read"): state.files_read = []
    if not hasattr(state, "files_modified"): state.files_modified = []
    if not hasattr(state, "done"): state.done = False
    if not hasattr(state, "phase"): state.phase = "CODER"

def canonicalize_payload(payload: dict) -> str:
    """
    Convert payload to a canonical JSON string (sorted keys) for reliable
    loop-detection comparisons.
    """
    try:
        return json.dumps(payload, sort_keys=True, default=str)
    except Exception:
        # fallback: simple string repr
        return str(sorted(payload.items()))

def normalize_action_payload(act: str, payload: dict) -> dict:
    """
    Accept sloppy LLM output and normalize common alias keys so our tool
    validator doesn't choke on synonyms.
    Examples:
      - create_file may yield 'file' or 'path' => map to 'file_path'
      - rewrite_function may yield 'file_path' => map to 'file'
      - read_file may yield 'file_path' => map to 'path'
    This function mutates and returns a new dict.
    """
    p = dict(payload) if isinstance(payload, dict) else {}
    # common aliases
    if "file" in p and "file_path" not in p:
        p["file_path"] = p["file"]
    if "file_path" in p and "file" not in p:
        p["file"] = p["file_path"]

    if "path" in p and "file_path" not in p:
        p["file_path"] = p["path"]
    if "file_path" in p and "path" not in p:
        p["path"] = p["file_path"]

    if "text" in p and "text" not in p:
        p["text"] = p.get("text")

    # specific: rewrite_function expects 'file' in your tool_jail
    if act == "rewrite_function" and "file_path" in p and "file" not in p:
        p["file"] = p["file_path"]

    # create_file should accept missing initial_content
    if act == "create_file" and "initial_content" not in p:
        p["initial_content"] = ""

    # read_file: prefer 'path'
    if act == "read_file":
        if "file" in p and "path" not in p:
            p["path"] = p["file"]
        if "file_path" in p and "path" not in p:
            p["path"] = p["file_path"]

    return p

def is_noop_action(act: str, payload: dict) -> bool:
    """Return True for no-op or malformed actions we should skip safely."""
    if not act or act in {"noop", "error", "none"}:
        return True
    # If action is create_file but no filename supplied, treat as noop
    if act == "create_file" and not payload.get("file_path"):
        return True
    if act == "rewrite_function" and not payload.get("file"):
        return True
    return False

# ---------------------------------------------------------------------------

def _detect_function_from_goal(goal, repo_root):
    clean_goal = re.sub(r"[^\w\s]", " ", goal)
    words = clean_goal.split()
    for w in words:
        loc = find_function(repo_root, w)
        if loc:
            return w, loc
    return None, None

def _rewrite_function(state, code_to_modify, file_path):
    """
    Universal, robust rewrite_function:
    - ask a single approval for all SEARCH/REPLACE blocks
    - apply deterministic patching with whitespace fallback
    - syntax-check with universal parser
    - rollback to original if syntax fails
    """
    from tools.diff_engine import parse_search_replace, apply_patch
    from agent.approval import ask_user_approval

    # keep the original prompt semantics you used
    prompt = f"""You are Operon, an elite surgical code editor.
GOAL: {state.goal}

CRITICAL CONTEXT:
You are editing: `{file_path}`

INSTRUCTIONS:
1. Output a SEARCH block matching the exact original lines.
2. Output a REPLACE block with the new lines.
3. CRITICAL RULES:
   - DO NOT wrap your output in code blocks. Output the raw <<<<<<< SEARCH format directly.
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

    # --- ASK FOR UI APPROVAL ONCE (all blocks together) ---
    # Build preview payload containing all patches for a single approval UI
    preview_patches = []
    for s, r in blocks:
        preview_patches.append({"search": s.strip(), "replace": r.strip()})

    approval_payload = {"file": file_path, "patches": preview_patches}
    if not ask_user_approval("rewrite_function", approval_payload):
        return {"success": False, "error": "User rejected the code change during preview."}

    applied_count = 0
    for search_block, replace_block in blocks:
        # skip no-op replacements
        if search_block.strip() == replace_block.strip():
            continue

        # If the file is empty, just append/replace with new content
        if not file_text.strip():
            patched_text = replace_block.strip() + "\n"
        else:
            patched_text = apply_patch(file_text, search_block, replace_block)

            # Fallback: whitespace-normalized matching if strict failed
            if patched_text is None:
                log.warning("Strict match failed. Attempting whitespace-normalized matching...")
                words = search_block.strip().split()
                if words:
                    pattern = r'\s+'.join(re.escape(w) for w in words)
                    m = re.search(pattern, file_text)
                    if m:
                        patched_text = file_text[:m.start()] + replace_block + file_text[m.end():]

        if patched_text is None:
            # Keep original file on failure (we haven't overwritten it yet)
            return {"success": False, "error": "SEARCH block did not exactly match the file content."}

        file_text = patched_text
        applied_count += 1

    # Syntax sentinel — use string path for parser
    if not check_syntax(file_text, str(file_path)):
        error_msg = f"CRITICAL: SyntaxError detected in {file_path}! You broke the code structure. Rollback triggered."
        log.error(f"Syntax check failed for {file_path}.")
        # Restore the file instantly without messing with Git
        full_path.write_text(original_file_text, encoding="utf-8")
        return {"success": False, "error": error_msg}

    if applied_count == 0:
         return {"success": False, "error": "No valid changes were generated."}

    full_path.write_text(file_text, encoding="utf-8")
    return {"success": True, "file": file_path, "message": f"Applied {applied_count} patch(es). Syntax valid."}

# -------------------- Main agent loop ----------------------------------------
def run_agent(state):
    from agent.tool_jail import validate_tool
    from agent.approval import ask_user_approval  # used in create_file fallback
    _ensure_state_fields(state)

    # ================= ARCHITECT PHASE =================
    if not getattr(state, "plan", None):
        state.phase = "ARCHITECT"
        state.git_state = setup_git_env(state.repo_root)
        # allow planner to return (plan, is_question) or just plan
        try:
            plan_tuple = make_plan(state.goal, state.repo_root)
            if isinstance(plan_tuple, (list, tuple)):
                state.plan = plan_tuple[0]
                state.is_question = bool(plan_tuple[1]) if len(plan_tuple) > 1 else False
            else:
                state.plan = plan_tuple
                state.is_question = False
        except Exception as e:
            log.error("Planner failed, falling back to single-step plan.")
            state.plan = [state.goal]
            state.is_question = False

        log.info(f"[bold magenta]🏛️ ARCHITECT PLAN:[/bold magenta] {state.plan}")

    state.phase = "CODER"

    while not getattr(state, "done", False):
        # Macro rollback safety
        if state.step_count >= MAX_STEPS:
            log.error(f"Hit max steps({MAX_STEPS}). Operon failed to complete the task.")
            rollback_macro(state.repo_root, getattr(state, "git_state", {}))
            break

        # --- DECIDE / NORMALIZE ---
        decision = decide_next_action(state) or {}
        # Back-compat: if decide_next_action returned a "prompt" (old behavior), call LLM directly
        if "prompt" in decision and isinstance(decision["prompt"], str):
            try:
                raw = call_llm(decision["prompt"], require_json=False)
                # try to parse JSON out of response, but be defensive
                clean = re.sub(r"```(?:json)?\n?(.*?)\n?```", r"\1", raw, flags=re.DOTALL).strip()
                try:
                    decision = json.loads(clean)
                except Exception:
                    # expect {"thought": "...", "tool": {...}}
                    decision = {"thought": "LLM returned non-JSON", "tool": {"action": "error"}}
            except Exception:
                decision = {"thought": "LLM call failed", "tool": {"action": "error"}}

        thought = decision.get("thought", "Thinking...")
        action_payload = decision.get("tool", decision) or {}
        if isinstance(action_payload, dict) and "action" not in action_payload and "tool" in action_payload:
            action_payload = action_payload["tool"]

        # Normalize action payload keys for robustness
        act = action_payload.get("action") if isinstance(action_payload, dict) else None
        normalized_payload = normalize_action_payload(act or "", action_payload if isinstance(action_payload, dict) else {})

        # Guard against no-op or malformed actions
        if is_noop_action(act or "", normalized_payload):
            log.warning("Received noop or malformed action; skipping.")
            state.observations.append({"error": "No valid action supplied by LLM."})
            state.step_count += 1
            time.sleep(0.5)
            continue

        # --- 1. STRICT TOOL VALIDATION ---
        is_valid, val_msg = validate_tool(act, normalized_payload, state.phase)
        if not is_valid:
            log.warning(f"Jail intercepted: {val_msg}")
            state.observations.append({"error": f"SYSTEM OVERRIDE: {val_msg}"})
            state.step_count += 1
            time.sleep(1)
            continue

        # --- 2. THE LOOP BREAKER (use canonicalized payload for equality)
        canonical = canonicalize_payload({"action": act, **normalized_payload})
        if getattr(state, "last_action_canonical", None) == canonical:
            state.loop_counter += 1
            log.error(f"LOOP DETECTED ({state.loop_counter}): Repeated {act}")
            if state.loop_counter >= 3:
                log.error("CRITICAL LOOP. Wiping memory and forcing REVIEWER handoff.")
                state.observations.append({"error": "FATAL LOOP OVERRIDE: You are stuck. Submitting for review."})
                state.phase = "REVIEWER"
                state.last_action_payload = None
                state.last_action_canonical = None
                state.loop_counter = 0
                state.step_count += 1
                time.sleep(1)
                continue
            else:
                state.observations.append({"error": "SYSTEM OVERRIDE: You just did this exact action. DO SOMETHING ELSE."})
                state.step_count += 1
                time.sleep(1)
                continue
        else:
            state.loop_counter = 0
            state.last_action_payload = normalized_payload
            state.last_action_canonical = canonical

        state.step_count += 1
        log.info(f"🧠 {state.phase} THOUGHT: {thought}")
        log.info(f"⚙️ EXECUTING: {act}")
        log.debug(f"Normalized payload: {normalized_payload}")

        # ------------------ ROUTING & EXECUTION -----------------------
        try:
            if act == "approve_step":
                state.action_log.append(f"👨‍⚖️ REVIEWER approved step {state.current_step + 1}.")
                state.current_step += 1
                if state.current_step >= len(state.plan):
                    log.info("[bold green]✅ All steps complete! REVIEWER should finish next.[/bold green]")
                    state.observations.append({"system": "All steps complete. You must use the 'finish' tool."})
                else:
                    state.phase = "CODER"
                    state.observations = []
                    log.info(f"[bold yellow]👨‍💻 Back to CODER for next step...[/bold yellow]")

            elif act == "reject_step":
                feedback = normalized_payload.get('feedback', '')
                state.action_log.append(f"❌ REVIEWER REJECTED step {state.current_step + 1}: {feedback}")
                state.observations.append({"reviewer_feedback": feedback})
                state.phase = "CODER"
                log.info(f"[bold red]👨‍💻 Back to CODER for corrections...[/bold red]")

            elif act == "finish":
                msg = normalized_payload.get('message') or normalized_payload.get('commit_message') or 'Complete.'
                log.info(f"✅ OPERON VICTORY: {msg}")
                commit_success(state.repo_root, msg)
                state.done = True
                break

            elif act == "semantic_search":
                query = normalized_payload.get("query", "")
                hits = search_repo(state.repo_root, query) if query else []
                obs = f"Semantic matches for '{query}': {hits}" if hits else f"No matches."
                state.observations.append({"search": obs})
                state.action_log.append(f"Semantic search: '{query}'.")

            elif act == "exact_search":
                search_text = normalized_payload.get("text", "")
                hits = []
                for root, _, files in os.walk(state.repo_root):
                    if '.git' in root or '__pycache__' in root or 'venv' in root: continue
                    for file in files:
                        if not file.endswith('.py') and not file.endswith('.md'): continue
                        file_path = os.path.join(root, file)
                        try:
                            with open(file_path, 'r', encoding='utf-8') as fh:
                                if search_text in fh.read():
                                    hits.append(os.path.relpath(file_path, state.repo_root))
                        except: pass
                obs = f"Exact matches for '{search_text}': {hits}" if hits else f"No exact matches found."
                state.observations.append({"exact_search": obs})
                state.action_log.append(f"Exact search for '{search_text}'.")

            elif act == "read_file":
                path = normalized_payload.get("path")
                if not path:
                    state.observations.append({"error": "read_file requires a 'path' parameter."})
                    state.action_log.append("FAILED: read_file missing 'path' parameter.")
                    continue
                obs = read_file(path, state.repo_root)
                if "error" in obs:
                    state.observations.append(obs)
                    state.action_log.append(f"Failed to read '{path}'.")
                else:
                    state.context_buffer[path] = obs["content"]
                    state.observations.append({"success": f"Loaded {path} into memory."})
                    state.action_log.append(f"Loaded '{path}' into memory.")
                    if path not in state.files_read:
                        state.files_read.append(path)

            elif act == "find_file":
                term = normalized_payload.get("search_term", "").lower()
                root = Path(state.repo_root)
                matches = []
                for p in root.rglob("*"):
                    if p.is_file() and ".git" not in p.parts and term in p.name.lower():
                        matches.append(str(p.relative_to(root)))
                if matches:
                    state.observations.append({"find_file": f"Found {len(matches)} matching files:\n" + "\n".join(matches)})
                else:
                    state.observations.append({"find_file": f"No files found matching '{term}'. Try semantic search instead."})

            elif act == "create_file":
                file_path = normalized_payload.get("file_path")
                content = normalized_payload.get("initial_content", "")

                # Preview payload structure matches rewrite UI but is a single-create action
                preview = {"file": file_path, "search": "", "replace": content}
                if not ask_user_approval("create_file", preview):
                    state.observations.append({"error": "User rejected file creation."})
                    state.action_log.append(f"FAILED: User rejected creating {file_path}")
                    time.sleep(0.2)
                    continue

                if not file_path:
                    state.observations.append({"error": "create_file requires a 'file_path' parameter."})
                    state.action_log.append("FAILED: create_file missing 'file_path' parameter.")
                    continue

                full_path = Path(state.repo_root) / file_path
                if full_path.exists():
                    # If content is identical, consider it success and hand off to reviewer
                    existing = full_path.read_text(encoding="utf-8")
                    if existing.strip() == content.strip():
                        state.observations.append({"success": f"File {file_path} already exists with identical content."})
                        state.action_log.append(f"Skipped create_file: already exists and matches {file_path}")
                        # Auto-handoff so the reviewer can approve without the coder looping
                        state.phase = "REVIEWER"
                        state.context_buffer = {file_path: existing}
                        state.observations.append({
                            "system": f"Coder reports file {file_path} already matches requested content. REVIEWER: please verify.",
                            "file_preview": existing[:2000]
                        })
                        continue
                    else:
                        state.observations.append({"error": f"File {file_path} already exists and differs."})
                        state.action_log.append(f"FAILED: create_file collision {file_path}")
                        continue
                else:
                    full_path.parent.mkdir(parents=True, exist_ok=True)
                    full_path.write_text(content, encoding="utf-8")
                    state.action_log.append(f"Created new file: {file_path}")
                    state.observations.append({"success": f"File {file_path} created successfully."})
                    log.info(f"📄 Created new file: {file_path}")

                    # --- AUTO HANDOFF TO REVIEWER (same logic as rewrite_function) ---
                    log.info("[bold cyan]🔄 Auto-Handing off to REVIEWER after file creation...[/bold cyan]")
                    state.phase = "REVIEWER"
                    updated_code = full_path.read_text(encoding="utf-8")
                    state.context_buffer = {file_path: updated_code}
                    state.observations.append({
                        "system": f"Coder successfully created {file_path}. REVIEWER MUST verify the goal was met.",
                        "file_preview": updated_code[:2000]
                    })
                    if file_path not in state.files_modified:
                        state.files_modified.append(file_path)

            elif act == "rewrite_function":
                target_file = normalized_payload.get("file")
                if not target_file:
                    state.observations.append({"error": "rewrite_function requires a 'file' parameter."})
                    state.action_log.append("FAILED: rewrite_function missing 'file' parameter.")
                    continue
                full_path = Path(state.repo_root) / target_file
                if not full_path.exists():
                    full_path.touch()
                code_to_modify = full_path.read_text(encoding="utf-8")
                obs = _rewrite_function(state, code_to_modify, target_file)

                if obs.get("success"):
                    log.info(f"Successfully patched {target_file}")
                    state.action_log.append(f"SUCCESS: Applied code patch to '{target_file}'.")
                    # --- THE AUTO-HANDOFF ---
                    log.info("[bold cyan]🔄 Auto-Handing off to REVIEWER...[/bold cyan]")
                    state.phase = "REVIEWER"
                    updated_code = full_path.read_text(encoding="utf-8")
                    state.context_buffer = {target_file: updated_code}
                    state.observations.append({
                        "system": f"Coder successfully modified {target_file}. REVIEWER MUST look at the updated file in context and verify the goal was met before rejecting.",
                        "file_preview": updated_code[:2000]
                    })
                    if target_file not in state.files_modified:
                        state.files_modified.append(target_file)

                else:
                    err = obs.get("error") or ""
                    log.error(f"Patch failed: {err}")
                    if "Patch failed" in err or "did not exactly match" in err:
                        err += " HINT: Your SEARCH block was wrong. Try matching a smaller, more unique part of the code, or leave SEARCH completely empty if appending to the bottom."
                    state.action_log.append(f"FAILED patch on '{target_file}'. Error: {err}")
                    state.observations.append({"error": err})

            else:
                # Unknown but validated actions should not reach here; defensive catch
                log.warning(f"Unhandled action reached execution: {act}")
                state.observations.append({"error": f"Unhandled action: {act}"})

        except Exception as exc:
            # Never let an unexpected exception silently kill the loop
            state.observations.append({"error": f"Unhandled exception during '{act}': {exc}"})
            log.exception("Unhandled exception in run_agent loop.")

        # short sleep to avoid hot-looping
        time.sleep(0.2)

    return state