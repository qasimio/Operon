# agent/loop.py — Operon v2: upgraded agent loop with 4-level index integration
from runtime import state as state_module
from tools.fs_tools import read_file, write_file
from tools.git_safety import setup_git_env, rollback_macro, commit_success
from tools.repo_search import search_repo
from agent.decide import decide_next_action
from agent.planner import make_plan
from agent.logger import log
from tools.function_locator import find_function
from agent.llm import call_llm
from tools.universal_parser import check_syntax
from tools.diff_engine import parse_search_replace, apply_patch
from tools.diff_report import dump_diff_report_from_json
from pathlib import Path
import re
import time
import json
import os
import difflib

MAX_STEPS = 30
REJECT_THRESHOLD = 3


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _ensure_state_fields(state):
    defaults = {
        "action_log": [], "observations": [], "context_buffer": {},
        "current_step": 0, "loop_counter": 0, "last_action_payload": None,
        "last_action_canonical": None, "step_count": 0,
        "files_read": [], "files_modified": [], "done": False,
        "phase": "CODER", "diff_memory": {}, "git_state": {},
        "skip_counts": {}, "search_counts": {}, "step_cooldown": 0,
        "recent_actions": [], "reject_counts": {}, "plan_validators": [],
        "symbol_index": {}, "dep_graph": {}, "ast_cache": {},
        "allow_read_skip": False,
    }
    for k, v in defaults.items():
        if not hasattr(state, k):
            setattr(state, k, v)


def _goal_achieved(state, file_path: str) -> bool:
    """Check if the current goal is already satisfied for a given file."""
    try:
        full = Path(state.repo_root) / file_path
        if not full.exists():
            return False
        text = full.read_text(encoding="utf-8")
        goal = state.goal.lower()

        m = re.search(r"delete\s+lines?\s+(\d+)\s*[-–]\s*(\d+)", goal)
        if m:
            start, end = int(m.group(1)), int(m.group(2))
            if len(text.splitlines()) < end:
                return True

        if "delete" in goal or "remove" in goal:
            keywords = re.findall(r"[a-zA-Z_]+\(", state.goal)
            for k in keywords:
                if k in text:
                    return False
            return bool(keywords)   # Only return True if we had keywords to check
    except Exception:
        pass
    return False


def canonicalize_payload(payload: dict) -> str:
    try:
        return json.dumps(payload, sort_keys=True, default=str)
    except Exception:
        return str(sorted(payload.items()))


def normalize_action_payload(act: str, payload: dict) -> dict:
    p = dict(payload) if isinstance(payload, dict) else {}
    if "file" in p and "file_path" not in p:
        p["file_path"] = p["file"]
    if "file_path" in p and "file" not in p:
        p["file"] = p["file_path"]
    if "path" in p and "file_path" not in p:
        p["file_path"] = p["path"]
    if "file_path" in p and "path" not in p:
        p["path"] = p["file_path"]
    for k in ("new_content", "content", "function_content", "initial_content"):
        if k in p and "initial_content" not in p:
            p["initial_content"] = p.get(k)
    if act == "rewrite_function" and "file_path" in p and "file" not in p:
        p["file"] = p["file_path"]
    if act == "read_file":
        if "file" in p and "path" not in p:
            p["path"] = p["file"]
        if "file_path" in p and "path" not in p:
            p["path"] = p["file_path"]
    if act == "create_file" and "initial_content" not in p:
        p["initial_content"] = ""
    return p


def resolve_repo_path(repo_root, user_path: str) -> str:
    root = Path(repo_root)
    if not user_path:
        return user_path
    if (root / user_path).exists():
        return user_path
    name = Path(user_path).name.lower()
    matches = [p for p in root.rglob("*")
               if p.is_file() and ".git" not in p.parts and p.name.lower() == name]
    if matches:
        best = sorted(matches, key=lambda x: len(str(x.relative_to(root))))[0]
        return str(best.relative_to(root))
    return user_path


def is_noop_action(act: str, payload: dict) -> bool:
    if not act or act.lower() in {"noop", "error", "none"}:
        return True
    if act == "create_file" and not payload.get("file_path"):
        return True
    if act == "rewrite_function" and not payload.get("file") and not payload.get("initial_content"):
        return True
    return False


def _register_recent_action(state, act, canonical):
    if not hasattr(state, "recent_actions"):
        state.recent_actions = []
    state.recent_actions.append((act, canonical))
    if len(state.recent_actions) > 12:
        state.recent_actions.pop(0)


def _detect_alternating_loop(state, window=6) -> bool:
    seq = getattr(state, "recent_actions", [])[-window:]
    if len(seq) < 4:
        return False
    acts = [a for a, _ in seq]
    unique = list(dict.fromkeys(acts))
    if len(unique) != 2:
        return False
    for i, a in enumerate(acts):
        if a != unique[i % 2]:
            return False
    return True


def _increment_search_count(state, key):
    if not hasattr(state, "search_counts"):
        state.search_counts = {}
    entry = state.search_counts.get(key, {"count": 0, "last_step": 0})
    entry["count"] += 1
    entry["last_step"] = getattr(state, "step_count", 0)
    state.search_counts[key] = entry
    return entry["count"]


def _should_throttle_search(state, key, max_retries=3, cool_off_steps=20) -> bool:
    if not hasattr(state, "search_counts"):
        return False
    entry = state.search_counts.get(key)
    if not entry:
        return False
    return (entry["count"] > max_retries and
            (getattr(state, "step_count", 0) - entry["last_step"]) < cool_off_steps)


def _detect_function_from_goal(goal, repo_root):
    clean_goal = re.sub(r"[^\w\s]", " ", goal)
    for w in clean_goal.split():
        loc = find_function(repo_root, w)
        if loc:
            return w, loc
    return None, None


def _persist_diff_memory(state):
    try:
        odir = Path(state.repo_root) / ".operon"
        odir.mkdir(parents=True, exist_ok=True)
        out = odir / "last_session_diff.json"

        # Convert diff_memory to JSON-serializable form (remove non-string keys etc.)
        serializable = {}
        for fpath, patches in state.diff_memory.items():
            serializable[fpath] = [
                {k: v for k, v in p.items() if k in ("ts", "diff", "before", "after")}
                for p in patches
            ]
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(serializable, fh, indent=2)
        tr = odir / "last_session_diff.txt"
        dump_diff_report_from_json(out, tr)
    except Exception as e:
        log.debug(f"Failed to persist diff_memory: {e}")


# ─── Core rewrite engine ──────────────────────────────────────────────────────

def _rewrite_function(state, code_to_modify: str, file_path: str) -> dict:
    """
    Upgraded surgical rewrite engine.

    v2 changes:
    - Passes 4-level context (symbol index + dep graph hint) into the LLM prompt
    - Stores full before/after in diff_memory for the REVIEWER's LLM verifier
    - Cleaner error messages with actionable hints
    """
    from agent.approval import ask_user_approval

    full_path = Path(state.repo_root) / file_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    if not full_path.exists():
        full_path.touch()

    try:
        file_text = full_path.read_text(encoding="utf-8")
    except Exception as e:
        return {"success": False, "error": f"Cannot read {file_path}: {e}"}

    original_text = file_text

    # ── Fast path: explicit line-range deletion ───────────────────────────────
    line_delete = None
    if isinstance(getattr(state, "goal", None), str):
        m = re.search(r"\bdelete\s+lines?\s+(\d+)\s*[-–]\s*(\d+)\b", state.goal.lower())
        if m:
            try:
                s, e = int(m.group(1)), int(m.group(2))
                line_delete = (max(1, s), max(s, e))
            except Exception:
                pass

    if line_delete:
        start, end = line_delete
        lines = file_text.splitlines()
        if start > len(lines):
            return {"success": False, "error": f"Line deletion out of range: file has {len(lines)} lines."}
        new_lines = lines[:start-1] + lines[end:]
        new_text = "\n".join(new_lines) + ("\n" if file_text.endswith("\n") else "")
        snippet = "\n".join(lines[start-1:end])
        preview = {"file": file_path, "search": f"lines {start}-{end}:\n{snippet}", "replace": ""}
        if not ask_user_approval("rewrite_function", preview):
            return {"success": False, "error": "User rejected line-range deletion."}
        if not check_syntax(new_text, str(file_path)):
            return {"success": False, "error": f"Syntax error after deleting lines {start}-{end}."}
        full_path.write_text(new_text, encoding="utf-8")
        return {"success": True, "file": file_path, "message": f"Deleted lines {start}-{end}."}

    # ── Build 4-level context hint for LLM ───────────────────────────────────
    context_hint = ""
    from tools.repo_index import get_relevant_context
    try:
        hint = get_relevant_context(state, state.goal, max_files=2)
        if hint:
            context_hint = f"\n4-LEVEL CONTEXT:\n{hint[:600]}\n"
    except Exception:
        pass

    # ── LLM prompt for SEARCH/REPLACE blocks ─────────────────────────────────
    prompt = f"""You are Operon, an elite surgical code editor.
GOAL: {state.goal}
FILE: {file_path}
{context_hint}
INSTRUCTIONS:
Output ONLY raw SEARCH/REPLACE blocks using this exact format (no markdown, no explanation):

<<<<<<< SEARCH
[exact original lines to replace or delete]
=======
[new lines — leave empty to DELETE]
>>>>>>> REPLACE

Rules:
- SEARCH must exactly match lines in the file (whitespace-normalized match is attempted).
- To delete: put original lines in SEARCH, leave REPLACE empty.
- To append: leave SEARCH empty, put new code in REPLACE.
- Multiple blocks allowed in sequence.

CURRENT FILE:
{file_text}
"""

    try:
        raw_output = call_llm(prompt, require_json=False)
    except Exception as e:
        return {"success": False, "error": f"LLM call failed: {e}"}

    blocks = []
    if isinstance(raw_output, str) and raw_output.strip():
        try:
            blocks = parse_search_replace(raw_output)
        except Exception:
            pass

    # Fallback: context_buffer full replacement
    candidate = None
    if not blocks:
        candidate = state.context_buffer.get(file_path) or state.context_buffer.get(str(file_path))
        if candidate and not isinstance(candidate, str):
            candidate = str(candidate)

    if not blocks and (not candidate or candidate.strip() == file_text.strip()):
        return {
        "success": False,
        "error": "LLM produced no SEARCH/REPLACE blocks and no alternative content. No changes proposed."
    }

    # ── Dry-run all patches ───────────────────────────────────────────────────
    preview_text = file_text
    applied_any = False
    preview_patches = []

    if blocks:
        for (search_block, replace_block) in blocks:
            search_block = (search_block or "").rstrip("\n")
            replace_block = (replace_block or "").rstrip("\n")
            preview_patches.append({"search": search_block, "replace": replace_block})

            if search_block and not replace_block:
                if search_block in preview_text:
                    preview_text = preview_text.replace(search_block, "", 1)
                    applied_any = True
                    continue
                words = search_block.split()
                if words:
                    pattern = r'\s+'.join(re.escape(w) for w in words)
                    mm = re.search(pattern, preview_text)
                    if mm:
                        preview_text = preview_text[:mm.start()] + preview_text[mm.end():]
                        applied_any = True
                        continue
                return {"success": False, "error": "Deletion SEARCH block not found. Try a smaller or more unique snippet."}

            if not preview_text.strip() and replace_block:
                preview_text = replace_block + "\n"
                applied_any = True
                continue

            patched = apply_patch(preview_text, search_block, replace_block)
            if patched is None:
                words = (search_block or "").split()
                if words:
                    pattern = r'\s+'.join(re.escape(w) for w in words)
                    mm = re.search(pattern, preview_text)
                    if mm:
                        patched = preview_text[:mm.start()] + replace_block + preview_text[mm.end():]

            if patched is None:
                return {
                    "success": False,
                    "error": (
                        "SEARCH block did not match file content. "
                        "HINT: Use a smaller unique snippet or leave SEARCH empty to append."
                    )
                }
            if patched != preview_text:
                preview_text = patched
                applied_any = True
    else:
        candidate_text = candidate or ""
        if candidate_text.strip() and candidate_text.strip() != preview_text.strip():
            preview_text = candidate_text
            preview_patches.append({"search": file_text[:200].strip(), "replace": preview_text[:200].strip()})
            applied_any = True

    if not blocks and (not candidate or candidate.strip() == file_text.strip()):
        return {
        "success": False,
        "error": "LLM produced no SEARCH/REPLACE blocks and no alternative content. No changes proposed."
    }

    # ── Build approval payload ────────────────────────────────────────────────
    joined_search = "\n\n---\n\n".join(p["search"] for p in preview_patches if p.get("search") is not None)
    joined_replace = "\n\n---\n\n".join(p["replace"] for p in preview_patches if p.get("replace") is not None)
    approval_payload = {"file": file_path, "search": joined_search, "replace": joined_replace,
                        "patches": preview_patches}

    from agent.approval import ask_user_approval as _ask
    if not _ask("rewrite_function", approval_payload):
        return {"success": False, "error": "User rejected the code change."}

    # ── Syntax check + write ──────────────────────────────────────────────────
    if not check_syntax(preview_text, str(file_path)):
        full_path.write_text(original_text, encoding="utf-8")
        return {"success": False, "error": "Syntax error after applying patches. Rolled back."}

    try:
        full_path.write_text(preview_text, encoding="utf-8")
    except Exception as e:
        try:
            full_path.write_text(original_text, encoding="utf-8")
        except Exception:
            pass
        return {"success": False, "error": f"Write failed: {e}"}

    return {"success": True, "file": file_path, "message": "Rewrite applied."}


# ─── Main agent loop ──────────────────────────────────────────────────────────

def run_agent(state):
    from agent.tool_jail import validate_tool
    from agent.approval import ask_user_approval
    from agent.validators import validate_step as _validate

    _ensure_state_fields(state)

    if not hasattr(state, "diff_memory") or state.diff_memory is None:
        state.diff_memory = {}

    if not hasattr(state, "step_cooldown"):
        state.step_cooldown = 0

    ALLOW_READ_SKIP = bool(getattr(state, "allow_read_skip", False))
    _REJECT_THRESHOLD = getattr(state, "reject_threshold", REJECT_THRESHOLD)

    # ── ARCHITECT: plan + 4-level index ──────────────────────────────────────
    if not getattr(state, "plan", None):
        state.phase = "ARCHITECT"
        state.git_state = setup_git_env(state.repo_root)

        # Build 4-level index BEFORE planning so planner has context
        try:
            from tools.repo_index import build_full_index
            build_full_index(state)
        except Exception as e:
            log.warning(f"4-level index build failed (non-fatal): {e}")

        try:
            plan_tuple = make_plan(state.goal, state.repo_root, state=state)
            if isinstance(plan_tuple, (list, tuple)):
                state.plan = plan_tuple[0]
                state.is_question = bool(plan_tuple[1]) if len(plan_tuple) > 1 else False
                state.plan_validators = list(plan_tuple[2]) if len(plan_tuple) > 2 else []
            else:
                state.plan = plan_tuple
                state.is_question = False
                state.plan_validators = []
        except Exception:
            log.error("Planner failed, falling back to single-step plan.")
            state.plan = [state.goal]
            state.is_question = False
            state.plan_validators = []

        log.info(f"[bold magenta]🏛️ PLAN ({len(state.plan)} steps):[/bold magenta] {state.plan}")

    if not hasattr(state, "reject_counts") or not isinstance(state.reject_counts, dict):
        state.reject_counts = {}

    state.phase = "CODER"

    # ── Main loop ─────────────────────────────────────────────────────────────
    while not getattr(state, "done", False):
        if state.step_count >= MAX_STEPS:
            log.error(f"Max steps ({MAX_STEPS}) reached. Rolling back.")
            rollback_macro(state.repo_root, getattr(state, "git_state", {}))
            break

        if getattr(state, "step_cooldown", 0) > 0:
            state.step_cooldown -= 1
            state.step_count += 1
            time.sleep(0.15)
            continue

        # ── Decision ─────────────────────────────────────────────────────────
        decision = decide_next_action(state) or {}
        if "prompt" in decision and isinstance(decision["prompt"], str):
            try:
                raw = call_llm(decision["prompt"], require_json=False)
                clean = re.sub(r"```(?:json)?\n?(.*?)\n?```", r"\1", raw, flags=re.DOTALL).strip()
                try:
                    decision = json.loads(clean)
                except Exception:
                    decision = {"thought": "Non-JSON", "tool": {"action": "error"}}
            except Exception:
                decision = {"thought": "LLM fail", "tool": {"action": "error"}}

        thought = decision.get("thought", "Thinking...")
        action_payload = decision.get("tool", decision) or {}
        if isinstance(action_payload, dict) and "action" not in action_payload and "tool" in action_payload:
            action_payload = action_payload["tool"]

        act = action_payload.get("action") if isinstance(action_payload, dict) else None
        normalized_payload = normalize_action_payload(
            act or "", action_payload if isinstance(action_payload, dict) else {}
        )
        canonical = canonicalize_payload({"action": act, **normalized_payload})
        _register_recent_action(state, act, canonical)

        # ── Read-skip logic ───────────────────────────────────────────────────
        if ALLOW_READ_SKIP and act == "read_file":
            path = normalized_payload.get("path")
            if path and state.context_buffer.get(path):
                state.observations.append({"info": f"Skipped redundant read_file: {path}"})
                state.action_log.append(f"SKIP read_file {path}")
                state.step_count += 1
                time.sleep(0.1)
                continue

        # ── Safety checks ─────────────────────────────────────────────────────
        if is_noop_action(act or "", normalized_payload):
            log.warning("Received noop/malformed action; skipping.")
            state.observations.append({"error": "No valid action from LLM."})
            state.step_count += 1
            time.sleep(0.35)
            continue

        is_valid, val_msg = validate_tool(act, normalized_payload, state.phase, state)
        if not is_valid:
            log.warning(f"Tool jail intercepted: {val_msg}")
            state.observations.append({"error": f"SYSTEM: {val_msg}"})
            state.step_count += 1
            time.sleep(0.5)
            continue

        if _detect_alternating_loop(state, window=6):
            log.error("Alternating loop detected → escalating to REVIEWER.")
            state.observations.append({"error": "Alternating loop. Escalating."})
            state.phase = "REVIEWER"
            state.recent_actions = []
            state.step_count += 1
            time.sleep(0.2)
            continue

        query_key = None
        if act in {"semantic_search", "exact_search"}:
            query_key = normalized_payload.get("query") or normalized_payload.get("text") or ""
        elif act == "find_file":
            query_key = normalized_payload.get("search_term") or ""
        if query_key:
            _increment_search_count(state, query_key)
            if _should_throttle_search(state, query_key):
                log.warning(f"Throttling repeated search '{query_key}' → REVIEWER.")
                state.observations.append({"error": f"Too many searches for '{query_key}'."})
                state.phase = "REVIEWER"
                state.step_count += 1
                time.sleep(0.2)
                continue

        last_canon = getattr(state, "last_action_canonical", None)
        if last_canon == canonical:
            state.loop_counter += 1
            if state.loop_counter >= 3:
                log.error("CRITICAL LOOP → wiping memory, forcing REVIEWER.")
                state.observations.append({"error": "FATAL LOOP: Submitting for review."})
                state.phase = "REVIEWER"
                state.last_action_canonical = None
                state.loop_counter = 0
                state.step_count += 1
                time.sleep(0.2)
                continue
            else:
                state.observations.append({"error": "Repeated action. Do something different."})
                state.step_count += 1
                time.sleep(0.2)
                continue
        else:
            state.loop_counter = 0
            state.last_action_payload = normalized_payload
            state.last_action_canonical = canonical

        # ── Execution ─────────────────────────────────────────────────────────
        state.step_count += 1
        log.info(f"🧠 [{state.phase}] {thought}")
        log.info(f"⚙️  EXEC: {act}")

        try:
            # ── SEARCH ACTIONS ────────────────────────────────────────────────
            if act == "semantic_search":
                query = normalized_payload.get("query", "")
                hits = search_repo(state.repo_root, query) if query else []
                obs = f"Semantic matches for '{query}': {hits}" if hits else "No semantic matches."
                state.observations.append({"search": obs})
                state.action_log.append(f"Semantic search: '{query}'.")

            elif act == "exact_search":
                search_text = normalized_payload.get("text", "")
                hits = []
                for root_dir, _, files in os.walk(state.repo_root):
                    if any(x in root_dir for x in ('.git', '__pycache__', 'venv', '.operon')):
                        continue
                    for fname in files:
                        fpath = os.path.join(root_dir, fname)
                        try:
                            with open(fpath, 'r', encoding='utf-8', errors='ignore') as fh:
                                if search_text in fh.read():
                                    hits.append(os.path.relpath(fpath, state.repo_root))
                        except Exception:
                            pass
                obs = f"Exact matches for '{search_text}': {hits}" if hits else "No exact matches."
                state.observations.append({"exact_search": obs})
                state.action_log.append(f"Exact search: '{search_text}'.")

            elif act == "find_file":
                term = normalized_payload.get("search_term", "").lower()
                root = Path(state.repo_root)
                matches = [
                    str(p.relative_to(root))
                    for p in root.rglob("*")
                    if p.is_file() and ".git" not in p.parts and term in p.name.lower()
                ]
                if matches:
                    state.observations.append({"find_file": f"Found {len(matches)} files:\n" + "\n".join(matches)})
                else:
                    state.observations.append({"find_file": f"No files matching '{term}'."})

            # ── READ ──────────────────────────────────────────────────────────
            elif act == "read_file":
                path = normalized_payload.get("path")
                if not path:
                    state.observations.append({"error": "read_file requires 'path'."})
                    continue
                obs = read_file(path, state.repo_root)
                if "error" in obs:
                    state.observations.append(obs)
                else:
                    state.context_buffer[path] = obs["content"]
                    state.observations.append({"success": f"Loaded {path} ({obs['length']} chars)."})
                    if path not in state.files_read:
                        state.files_read.append(path)

            # ── CREATE FILE ───────────────────────────────────────────────────
            elif act == "create_file":
                file_path = normalized_payload.get("file_path")
                content = normalized_payload.get("initial_content", "")

                preview = {"file": file_path, "search": "", "replace": content}
                if not ask_user_approval("create_file", preview):
                    state.observations.append({"error": "User rejected file creation."})
                    continue
                if not file_path:
                    state.observations.append({"error": "create_file requires 'file_path'."})
                    continue

                full_path = Path(state.repo_root) / file_path
                if full_path.exists():
                    existing = full_path.read_text(encoding="utf-8")
                    if existing.strip() == content.strip():
                        state.observations.append({"success": f"{file_path} already exists with identical content."})
                        state.phase = "REVIEWER"
                        state.context_buffer[file_path] = existing
                    else:
                        state.observations.append({"error": f"{file_path} already exists and differs."})
                    continue

                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(content, encoding="utf-8")
                log.info(f"📄 Created: {file_path}")
                state.action_log.append(f"Created: {file_path}")
                state.observations.append({"success": f"Created {file_path}."})
                state.phase = "REVIEWER"
                updated_code = full_path.read_text(encoding="utf-8")
                state.context_buffer[file_path] = updated_code
                state.observations.append({
                    "system": f"Coder created {file_path}. REVIEWER: verify goal met.",
                    "file_preview": updated_code[:2000]
                })
                if file_path not in state.files_modified:
                    state.files_modified.append(file_path)

            # ── REWRITE FUNCTION ──────────────────────────────────────────────
            elif act == "rewrite_function":
                target_file = normalized_payload.get("file")
                if not target_file:
                    state.observations.append({"error": "rewrite_function requires 'file'."})
                    continue

                try:
                    target_file = resolve_repo_path(state.repo_root, target_file)
                except Exception:
                    pass

                full_path = Path(state.repo_root) / target_file
                if not full_path.exists():
                    full_path.touch()
                before_text = full_path.read_text(encoding="utf-8")

                obs = _rewrite_function(state, before_text, target_file)

                if obs.get("success"):
                    after_text = full_path.read_text(encoding="utf-8")
                    ts = time.time()
                    diff_lines = list(difflib.unified_diff(
                        before_text.splitlines(keepends=True),
                        after_text.splitlines(keepends=True),
                        fromfile=f"a/{target_file}",
                        tofile=f"b/{target_file}",
                        lineterm=""
                    ))
                    diff_text = "\n".join(diff_lines)
                    
                    if not diff_text.strip():
                        log.warning("Rewrite resulted in empty diff. Treating as failure.")
                        state.observations.append({"error": "Rewrite produced no changes."})
                        state.phase = "CODER"
                        continue

                    # Store full diff in memory (critical for REVIEWER's LLM verifier)
                    state.diff_memory.setdefault(target_file, []).append({
                        "ts": ts,
                        "before": before_text,
                        "after": after_text,
                        "diff": diff_text,
                    })
                    _persist_diff_memory(state)

                    if hasattr(state, "skip_counts"):
                        state.skip_counts.clear()
                    state.loop_counter = 0
                    state.last_action_canonical = None

                    # Check goal achieved via validator
                    if _validate(state, target_file, before_text, after_text):
                        log.info("🎯 Validator PASSED. Forcing completion.")
                        commit_success(state.repo_root, f"Applied patch to {target_file}")
                        state.done = True
                        return state

                    # Normal REVIEWER handoff — REVIEWER now has diff_memory to inspect
                    state.action_log.append(f"SUCCESS: Patched '{target_file}'.")
                    log.info("[bold cyan]🔄 Handing off to REVIEWER...[/bold cyan]")
                    state.phase = "REVIEWER"
                    state.context_buffer[target_file] = after_text
                    state.observations.append({
                        "system": (
                            f"Coder modified {target_file}. "
                            "REVIEWER: use structural_diff_verify to check the diff."
                        ),
                        "file_preview": after_text[:2000],
                        "diff_preview": diff_text[:3000],
                    })

                    if diff_text.strip() and target_file not in state.files_modified:
                        state.files_modified.append(target_file)

                else:
                    err = obs.get("error") or "Unknown error"
                    log.error(f"Patch failed: {err}")
                    state.action_log.append(f"FAILED patch on '{target_file}': {err}")
                    state.observations.append({"error": err})

            # ── REVIEWER ACTIONS ──────────────────────────────────────────────
            elif act == "approve_step":
                state.action_log.append(f"✅ REVIEWER approved step {state.current_step + 1}.")
                state.current_step += 1
                state.reject_counts = {}
                state.step_cooldown = 2
                if state.current_step >= len(state.plan):
                    log.info("[bold green]✅ All steps complete! Reviewer should finish.[/bold green]")
                    state.observations.append({"system": "All steps complete. Use 'finish' tool."})
                else:
                    state.phase = "CODER"
                    state.observations = []
                    log.info("[bold yellow]👨‍💻 Back to CODER for next step.[/bold yellow]")

            elif act == "reject_step":
                feedback = normalized_payload.get("feedback", "") or normalized_payload.get("message", "")
                key = f"step_{state.current_step}"
                if not isinstance(state.reject_counts, dict):
                    state.reject_counts = {}
                state.reject_counts[key] = state.reject_counts.get(key, 0) + 1
                state.action_log.append(f"❌ REVIEWER REJECTED step {state.current_step + 1}: {feedback}")
                state.observations.append({"reviewer_feedback": feedback})
                if state.reject_counts.get(key, 0) >= _REJECT_THRESHOLD:
                    log.error(f"Step rejected {_REJECT_THRESHOLD} times. Aborting.")
                    rollback_macro(state.repo_root, getattr(state, "git_state", {}))
                    state.done = True
                    return state
                state.step_cooldown = 3
                state.phase = "CODER"
                log.info("[bold red]👨‍💻 Back to CODER for corrections.[/bold red]")

            elif act == "finish":
                msg = normalized_payload.get("message") or normalized_payload.get("commit_message") or "Complete."
                log.info(f"[bold green]✅ OPERON DONE: {msg}[/bold green]")
                commit_success(state.repo_root, msg)
                state.done = True
                break

            else:
                log.warning(f"Unhandled action: {act}")
                state.observations.append({"error": f"Unhandled action: {act}"})

        except Exception as exc:
            state.observations.append({"error": f"Exception during '{act}': {exc}"})
            log.exception("Unhandled exception in run_agent loop.")

        time.sleep(0.15)

    return state
