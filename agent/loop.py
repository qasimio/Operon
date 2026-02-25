# agent/loop.py (cleaned, drop-in)
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
    if not hasattr(state, "action_log"): state.action_log = []
    if not hasattr(state, "observations"): state.observations = []
    if not hasattr(state, "context_buffer"): state.context_buffer = {}
    if not hasattr(state, "current_step"): state.current_step = 0
    if not hasattr(state, "loop_counter"): state.loop_counter = 0
    if not hasattr(state, "last_action_payload"): state.last_action_payload = None
    if not hasattr(state, "last_action_canonical"): state.last_action_canonical = None
    if not hasattr(state, "step_count"): state.step_count = 0
    if not hasattr(state, "files_read"): state.files_read = []
    if not hasattr(state, "files_modified"): state.files_modified = []
    if not hasattr(state, "done"): state.done = False
    if not hasattr(state, "phase"): state.phase = "CODER"

def canonicalize_payload(payload: dict) -> str:
    try:
        return json.dumps(payload, sort_keys=True, default=str)
    except Exception:
        return str(sorted(payload.items()))

def normalize_action_payload(act: str, payload: dict) -> dict:
    p = dict(payload) if isinstance(payload, dict) else {}
    # Normalize aliases
    if "file" in p and "file_path" not in p:
        p["file_path"] = p["file"]
    if "file_path" in p and "file" not in p:
        p["file"] = p["file_path"]
    if "path" in p and "file_path" not in p:
        p["file_path"] = p["path"]
    if "file_path" in p and "path" not in p:
        p["path"] = p["file_path"]

    # content synonyms
    for k in ("new_content", "content", "function_content", "initial_content"):
        if k in p and "initial_content" not in p:
            p["initial_content"] = p.get(k)

    # rewrite_function expects 'file' key
    if act == "rewrite_function" and "file_path" in p and "file" not in p:
        p["file"] = p["file_path"]

    # read_file expects 'path'
    if act == "read_file":
        if "file" in p and "path" not in p:
            p["path"] = p["file"]
        if "file_path" in p and "path" not in p:
            p["path"] = p["file_path"]

    # create_file default
    if act == "create_file" and "initial_content" not in p:
        p["initial_content"] = ""

    return p

def resolve_repo_path(repo_root, user_path: str):
    """
    Resolve a possibly-short filename to a real repo path.

    Priority:
    1) exact relative path exists
    2) recursive filename match anywhere in repo
    3) return original (caller may create it)
    """
    root = Path(repo_root)

    if not user_path:
        return user_path

    # 1. exact relative path
    candidate = root / user_path
    if candidate.exists():
        return user_path

    # 2. recursive filename search
    name = Path(user_path).name.lower()
    matches = []

    for p in root.rglob("*"):
        if ".git" in p.parts:
            continue
        if p.is_file() and p.name.lower() == name:
            matches.append(p)

    if matches:
        # choose shortest relative path (closest to root)
        best = sorted(matches, key=lambda x: len(str(x.relative_to(root))))[0]
        return str(best.relative_to(root))

    # 3. fallback → allow creation
    resolved = user_path
    log.debug(f"Resolved '{user_path}' → '{resolved}'")
    return user_path

def is_noop_action(act: str, payload: dict) -> bool:
    if not act or act.lower() in {"noop", "error", "none"}:
        return True
    if act == "create_file" and not payload.get("file_path"):
        return True
    if act == "rewrite_function" and not payload.get("file") and not payload.get("initial_content"):
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
    Robust, integrated rewrite_function.

    Features:
    - Accepts SEARCH/REPLACE blocks (preferred).
    - Supports deletion via empty REPLACE.
    - Supports line-range deletion when the goal contains "delete lines X-Y".
    - Accepts full replacement content via state.context_buffer[file_path].
    - Dry-run all changes first and skip if noop.
    - Single user approval for the proposed change (shaped for UI compatibility).
    - Applies patches with strict match then whitespace-normalized fallback.
    - Syntax-checks result with universal parser and rolls back on failure.
    - Returns structured result dict: {"success": bool, "file": path, "message"/"error": ...}
    """
    import re
    from pathlib import Path
    from tools.diff_engine import parse_search_replace, apply_patch
    from agent.approval import ask_user_approval
    from agent.llm import call_llm
    from agent.logger import log
    from tools.universal_parser import check_syntax

    # Prepare file paths
    full_path = Path(state.repo_root) / file_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    if not full_path.exists():
        full_path.touch()

    # Read current file content to operate on
    try:
        file_text = full_path.read_text(encoding="utf-8")
    except Exception as e:
        log.error(f"Failed reading {full_path}: {e}")
        file_text = ""

    original_text = file_text

    # --- 0) Quick support: explicit line-range deletion command in the state's goal ---
    # e.g. "delete lines 8-11" (case-insensitive)
    line_delete = None
    if isinstance(getattr(state, "goal", None), str):
        m = re.search(r"\bdelete\s+lines?\s+(\d+)\s*[-–]\s*(\d+)\b", state.goal.lower())
        if m:
            try:
                start_line = int(m.group(1))
                end_line = int(m.group(2))
                # Clamp
                if start_line < 1: start_line = 1
                if end_line < start_line: end_line = start_line
                line_delete = (start_line, end_line)
            except Exception:
                line_delete = None

    if line_delete:
        start, end = line_delete
        lines = file_text.splitlines()
        if start > len(lines):
            return {"success": False, "error": f"Line deletion out of range: file has {len(lines)} lines."}

        # Prepare preview of deletion
        new_lines = lines[:start-1] + lines[end:]
        new_text = "\n".join(new_lines) + ("\n" if file_text.endswith("\n") else "")

        # Ask for approval showing the exact lines to be removed
        snippet = "\n".join(lines[start-1:end])
        preview_payload = {
            "file": file_path,
            "search": f"lines {start}-{end} to be deleted:\n{snippet}",
            "replace": ""
        }

        if not ask_user_approval("rewrite_function", preview_payload):
            return {"success": False, "error": "User rejected line-range deletion."}

        # Syntax check before writing
        if not check_syntax(new_text, str(file_path)):
            return {"success": False, "error": f"CRITICAL: Syntax error after deleting lines {start}-{end}. Aborting."}

        full_path.write_text(new_text, encoding="utf-8")
        return {"success": True, "file": file_path, "message": f"Deleted lines {start}-{end}."}

    # --- 1) Prompt LLM for SEARCH/REPLACE blocks (maintain previous prompt semantics) ---
    prompt = f"""You are Operon, an elite surgical code editor.
GOAL: {state.goal}

CRITICAL CONTEXT:
You are editing: `{file_path}`

INSTRUCTIONS:
1) Output raw SEARCH/REPLACE blocks only, using this exact format:

<<<<<<< SEARCH
[original exact lines to replace OR lines to delete]
=======
[new replacement lines OR leave empty to DELETE]
>>>>>>> REPLACE

Rules:
- To DELETE code: put the original lines in SEARCH and LEAVE REPLACE EMPTY.
- To DELETE whole file: SEARCH should contain the entire file; REPLACE empty.
- If adding at EOF: SEARCH may be empty and REPLACE contains the appended code.
- If multiple edits needed, output multiple SEARCH/REPLACE blocks in sequence.

CURRENT FILE CONTENT:
{file_text}
"""

    try:
        raw_output = call_llm(prompt, require_json=False)
    except Exception as e:
        log.error(f"LLM call failed in rewrite_function: {e}")
        raw_output = ""

    blocks = []
    if isinstance(raw_output, str) and raw_output.strip():
        try:
            blocks = parse_search_replace(raw_output)
        except Exception as e:
            log.debug(f"parse_search_replace error: {e}")
            blocks = []

    # --- 2) If no blocks from LLM, check for an explicit replacement candidate in state.context_buffer ---
    # This allows callers (run_agent) to pass a full replacement via state.context_buffer[target_file]
    candidate = None
    if not blocks:
        candidate = state.context_buffer.get(file_path) or state.context_buffer.get(str(file_path))
        if candidate and not isinstance(candidate, str):
            candidate = str(candidate)

    # If still nothing to do and file_text unchanged, skip
    if not blocks and (not candidate or candidate.strip() == file_text.strip()):
        return {"success": True, "file": file_path, "message": "No changes proposed."}

    # --- 3) Dry-run: apply all blocks or full replacement to preview_text (do not write yet) ---
    preview_text = file_text
    applied_any = False
    preview_patches = []

    if blocks:
        for (search_block, replace_block) in blocks:
            # normalize trailing newlines out from the blocks to avoid double newlines confusion
            search_block = (search_block or "").rstrip("\n")
            replace_block = (replace_block or "").rstrip("\n")

            preview_patches.append({"search": search_block, "replace": replace_block})

            # CASE: deletion (SEARCH present, REPLACE empty)
            if search_block and not replace_block:
                if search_block in preview_text:
                    preview_text = preview_text.replace(search_block, "")
                    applied_any = True
                    continue

                # fallback: whitespace-normalized search
                words = search_block.split()
                if words:
                    pattern = r'\s+'.join(re.escape(w) for w in words)
                    m = re.search(pattern, preview_text)
                    if m:
                        preview_text = preview_text[:m.start()] + preview_text[m.end():]
                        applied_any = True
                        continue

                # not found -> fail dry-run
                return {"success": False, "error": "Deletion SEARCH block not found during dry-run."}

            # CASE: append to empty file (SEARCH empty)
            if not preview_text.strip() and replace_block:
                preview_text = replace_block + ("\n" if not replace_block.endswith("\n") else "")
                applied_any = True
                continue

            # Normal patch: try strict apply
            patched = apply_patch(preview_text, search_block, replace_block)
            if patched is None:
                # whitespace-normalized fallback: find loose match of search words
                words = (search_block or "").split()
                if words:
                    pattern = r'\s+'.join(re.escape(w) for w in words)
                    m = re.search(pattern, preview_text)
                    if m:
                        patched = preview_text[:m.start()] + replace_block + preview_text[m.end():]

            if patched is None:
                return {"success": False, "error": "SEARCH block did not match during dry-run."}

            if patched != preview_text:
                preview_text = patched
                applied_any = True

    else:
        # Use candidate full replacement
        candidate_text = candidate or ""
        if candidate_text.strip() and candidate_text.strip() != preview_text.strip():
            preview_text = candidate_text
            preview_patches.append({"search": (file_text[:200] or "").strip(), "replace": (preview_text[:200] or "").strip()})
            applied_any = True

    # If nothing would change, return success (no-op)
    if not applied_any:
        return {"success": True, "file": file_path, "message": "No effective changes after dry-run."}

    # --- 4) Compose approval payload for UI compatibility ---
    # Provide both a combined preview AND a single-block preview (first block) to satisfy various UI implementations.
    if preview_patches:
        joined_search = "\n\n---\n\n".join(p["search"] for p in preview_patches if p.get("search") is not None)
        joined_replace = "\n\n---\n\n".join(p["replace"] for p in preview_patches if p.get("replace") is not None)
    else:
        joined_search = (file_text[:200] or "").strip()
        joined_replace = (preview_text[:200] or "").strip()

    approval_payload = {
        "file": file_path,
        "search": joined_search,
        "replace": joined_replace,
        "patches": preview_patches  # UI may ignore this, but it's useful for richer clients
    }

    # Request single approval for the entire change set
    if not ask_user_approval("rewrite_function", approval_payload):
        return {"success": False, "error": "User rejected the code change during preview."}

    # --- 5) Final syntax check and write ---
    if not check_syntax(preview_text, str(file_path)):
        # do not write broken content; preserve original
        full_path.write_text(original_text, encoding="utf-8")
        return {"success": False, "error": "CRITICAL: SyntaxError detected after applying patches. Rollback to original."}

    try:
        full_path.write_text(preview_text, encoding="utf-8")
    except Exception as e:
        # Attempt to restore original on unexpected IO error
        try:
            full_path.write_text(original_text, encoding="utf-8")
        except Exception:
            log.error(f"Failed to restore original after write error: {e}")
        return {"success": False, "error": f"Failed to write file: {e}"}

    return {"success": True, "file": file_path, "message": "Rewrite applied."}


# -------------------- Main agent loop ----------------------------------------
def run_agent(state):
    from agent.tool_jail import validate_tool
    from agent.approval import ask_user_approval  # used for file create previews
    _ensure_state_fields(state)

    # ARCHITECT PHASE
    if not getattr(state, "plan", None):
        state.phase = "ARCHITECT"
        state.git_state = setup_git_env(state.repo_root)
        try:
            plan_tuple = make_plan(state.goal, state.repo_root)
            if isinstance(plan_tuple, (list, tuple)):
                state.plan = plan_tuple[0]
                state.is_question = bool(plan_tuple[1]) if len(plan_tuple) > 1 else False
            else:
                state.plan = plan_tuple
                state.is_question = False
        except Exception:
            log.error("Planner failed, falling back to single-step plan.")
            state.plan = [state.goal]
            state.is_question = False

        log.info(f"[bold magenta]🏛️ ARCHITECT PLAN:[/bold magenta] {state.plan}")

    state.phase = "CODER"

    while not getattr(state, "done", False):
        if state.step_count >= MAX_STEPS:
            log.error(f"Hit max steps({MAX_STEPS}). Operon failed to complete the task.")
            rollback_macro(state.repo_root, getattr(state, "git_state", {}))
            break

        decision = decide_next_action(state) or {}
        # Back-compat: if decide returned a "prompt" string (older behavior), call LLM
        if "prompt" in decision and isinstance(decision["prompt"], str):
            try:
                raw = call_llm(decision["prompt"], require_json=False)
                clean = re.sub(r"```(?:json)?\s*(.*?)\s*```", r"\1", raw, flags=re.DOTALL).strip()
                decision = json.loads(clean)
            except Exception:
                decision = {"thought": "LLM returned non-JSON", "tool": {"action": "error"}}

        thought = decision.get("thought", "Thinking...")
        action_payload = decision.get("tool", decision) or {}
        if isinstance(action_payload, dict) and "action" not in action_payload and "tool" in action_payload:
            action_payload = action_payload["tool"]

        act = action_payload.get("action") if isinstance(action_payload, dict) else None
        normalized_payload = normalize_action_payload(act or "", action_payload if isinstance(action_payload, dict) else {})

        if is_noop_action(act or "", normalized_payload):
            log.warning("Received noop or malformed action; skipping.")
            state.observations.append({"error": "No valid action supplied by LLM."})
            state.step_count += 1
            time.sleep(0.5)
            continue

        is_valid, val_msg = validate_tool(act, normalized_payload, state.phase)
        if not is_valid:
            log.warning(f"Jail intercepted: {val_msg}")
            state.observations.append({"error": f"SYSTEM OVERRIDE: {val_msg}"})
            state.step_count += 1
            time.sleep(1)
            continue

        # Loop detection using canonical payload
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

                if not file_path:
                    state.observations.append({"error": "create_file requires a 'file_path' parameter."})
                    state.action_log.append("FAILED: create_file missing 'file_path' parameter.")
                    continue

                file_path = resolve_repo_path(state.repo_root, file_path)

                # Approval before writing
                preview = {"file": file_path, "search": "", "replace": content}
                if not ask_user_approval("create_file", preview):
                    state.observations.append({"error": "User rejected file creation."})
                    state.action_log.append(f"FAILED: User rejected creating {file_path}")
                    continue

                full_path = Path(state.repo_root) / file_path

                if full_path.exists():
                    existing = full_path.read_text(encoding="utf-8")
                    if existing.strip() == content.strip():
                        state.observations.append({"success": f"File {file_path} already exists with identical content."})
                        state.action_log.append(f"Skipped create_file: already exists and matches {file_path}")
                        # If content is empty, remain CODER (so agent can write); otherwise hand off to REVIEWER
                        if content.strip():
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

                    # If content non-empty, hand off to reviewer; else keep coder to write contents
                    if content.strip():
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
                    else:
                        # empty file created intentionally — let CODER fill it
                        state.observations.append({"system": f"Empty file {file_path} created; CODER must write content."})

            elif act == "rewrite_function":
                # define target_file here (avoid UnboundLocalError)
                target_file = normalized_payload.get("file")
                if not target_file:
                    state.observations.append({"error": "rewrite_function requires a 'file' parameter."})
                    state.action_log.append("FAILED: rewrite_function missing 'file' parameter.")
                    continue

                target_file = resolve_repo_path(state.repo_root, target_file)

                full_path = Path(state.repo_root) / target_file
                if not full_path.exists():
                    # create an empty file to be modified
                    full_path.parent.mkdir(parents=True, exist_ok=True)
                    full_path.touch()

                code_to_modify = full_path.read_text(encoding="utf-8")

                # PREVENT useless rewrite if cached context matches file
                cached = state.context_buffer.get(target_file) or state.context_buffer.get(str(target_file))
                if cached and isinstance(cached, str) and cached.strip() == code_to_modify.strip():
                    state.observations.append({"system": f"{target_file} already matches cached content. Skipping rewrite."})
                    # Hand off to reviewer to acknowledge
                    state.phase = "REVIEWER"
                    state.context_buffer = {target_file: cached}
                    continue

                # if caller provided content in payload (some model outputs): accept it as replacement candidate
                # normalized_payload may include `initial_content` with intended file content
                initial_content = normalized_payload.get("initial_content")
                if initial_content:
                    # put replacement candidate into context_buffer so _rewrite_function can pick it up if needed
                    state.context_buffer[target_file] = initial_content

                obs = _rewrite_function(state, code_to_modify, target_file)

                if obs.get("success"):
                    log.info(f"Successfully patched {target_file}")
                    state.action_log.append(f"SUCCESS: Applied code patch to '{target_file}'.")
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
                log.warning(f"Unhandled action reached execution: {act}")
                state.observations.append({"error": f"Unhandled action: {act}"})

        except Exception as exc:
            state.observations.append({"error": f"Unhandled exception during '{act}': {exc}"})
            log.exception("Unhandled exception in run_agent loop.")

        time.sleep(0.2)

    return state