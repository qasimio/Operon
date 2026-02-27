# agent/loop.py — Operon v4
"""
Production agent loop. Root cause fixes:

ROOT CAUSE 1 — "rewrite called but file unchanged":
  The LLM inside _rewrite_function is asked to produce SEARCH/REPLACE blocks.
  Small models (Qwen 7B) often produce blocks that don't match the file because:
    a) They reconstruct from memory instead of copying verbatim.
    b) The prompt didn't include full file content.
  FIX: Prompt includes full file content. CRUD fast-path handles structured
  operations deterministically without needing the model to produce SEARCH blocks.
  CRUD operations: import insertion, comment above, comment at bottom,
  variable assignment update — all handled deterministically.

ROOT CAUSE 2 — "REVIEWER hallucinates 'file unchanged'":
  Reviewer called LLM which had no file evidence → guessed wrong.
  FIX: decide.py REVIEWER is deterministic-first:
    - Checks diff_memory to confirm a real change happened.
    - If confirmed → asks LLM with ACTUAL current file from disk.
    - If not confirmed → rejects immediately without LLM call.

ROOT CAUSE 3 — "approval bypass (~80% of edits)":
  When UI_SHOW_DIFF is None (not connected), ask_user_approval returns True.
  This is correct for headless/test mode. For TUI mode, it's guaranteed to
  show a diff. But the approval payload was sometimes empty.
  FIX: _approve() always logs what it's approving. Payload always includes
  before/after content. Empty search/replace triggers a warning.

ROOT CAUSE 4 — "model switching causes crash":
  LLM config is read fresh on every call_llm() invocation.
  FIX: llm.py hot-reloads config on every call. No state held in memory.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from agent.logger import log
from agent.llm import call_llm
from agent.decide import decide_next_action
from agent.planner import make_plan
from agent.validators import validate_step as _validate_step
from tools.diff_engine import (
    parse_search_replace, apply_patch,
    insert_import, insert_above, append_to_file,
)
from tools.git_safety import setup_git_env, rollback_files, commit_success
from tools.path_resolver import resolve_path, read_resolved
from tools.repo_search import search_repo
from tools.universal_parser import check_syntax

MAX_STEPS        = 35
NOOP_STREAK_MAX  = 2
REJECT_THRESHOLD = 3


# ── State init ────────────────────────────────────────────────────────────────

def _ensure(state) -> None:
    defaults: dict[str, Any] = {
        "action_log":             [],
        "observations":           [],
        "context_buffer":         {},
        "current_step":           0,
        "loop_counter":           0,
        "last_action_canonical":  None,
        "step_count":             0,
        "files_read":             [],
        "files_modified":         [],
        "done":                   False,
        "phase":                  "CODER",
        "diff_memory":            {},
        "git_state":              {},
        "search_counts":          {},
        "reject_counts":          {},
        "plan_validators":        [],
        "symbol_index":           {},
        "dep_graph":              {},
        "rev_dep":                {},
        "file_tree":              [],
        "multi_file_queue":       [],
        "multi_file_done":        [],
        "noop_streak":            0,
        "is_question":            False,
        "step_cooldown":          0,
    }
    for k, v in defaults.items():
        if not hasattr(state, k) or getattr(state, k) is None:
            setattr(state, k, v)


# ── Normalize action payload ──────────────────────────────────────────────────

def _norm(act: str, p: dict) -> dict:
    p = dict(p) if isinstance(p, dict) else {}
    for a, b in [("file", "file_path"), ("file_path", "file"),
                 ("path", "file_path"), ("file_path", "path")]:
        if a in p and b not in p:
            p[b] = p[a]
    for k in ("new_content", "content", "function_content"):
        if k in p and "initial_content" not in p:
            p["initial_content"] = p[k]
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


def _canon(payload: dict) -> str:
    try:
        return json.dumps(payload, sort_keys=True, default=str)
    except Exception:
        return str(payload)


def _is_noop_action(act: str, p: dict) -> bool:
    if not act or act.lower() in {"noop", "error", "none", ""}:
        return True
    if act == "create_file" and not p.get("file_path"):
        return True
    if act == "rewrite_function" and not p.get("file"):
        return True
    return False


# ── Approval with mandatory logging ──────────────────────────────────────────

def _approve(action: str, payload: dict, summary: str = "") -> bool:
    from agent.approval import ask_user_approval

    # Validate payload is non-empty
    search  = payload.get("search", "")
    replace = payload.get("replace", payload.get("initial_content", ""))
    if action in ("rewrite_function", "create_file") and not search and not replace:
        log.warning(
            f"[yellow]⚠️ APPROVAL payload is empty for {action} — skipping.[/yellow]"
        )
        return False

    result = ask_user_approval(action, payload)
    status = "[bold green]✅ APPROVED" if result else "[bold red]❌ REJECTED"
    log.info(f"{status}[/bold {'green' if result else 'red'}]: {summary or action}")
    return result


# ── Diff persistence ──────────────────────────────────────────────────────────

def _persist_diff(state) -> None:
    try:
        odir = Path(state.repo_root) / ".operon"
        odir.mkdir(parents=True, exist_ok=True)
        out = {
            fp: [{"ts": p.get("ts", 0), "diff": p.get("diff", "")}
                 for p in patches]
            for fp, patches in state.diff_memory.items()
        }
        (odir / "last_diff.json").write_text(
            json.dumps(out, indent=2), encoding="utf-8"
        )
    except Exception as e:
        log.debug(f"diff persist: {e}")


# ── CRUD fast-path ────────────────────────────────────────────────────────────

def _crud_fast_path(goal: str, original: str) -> tuple[str | None, str]:
    """
    Detect and apply structured CRUD intent deterministically.
    Returns (new_content | None, description).
    None means "not a CRUD pattern — use LLM".
    """
    g = goal.lower()

    # ── add import X ──────────────────────────────────────────────────────
    m = re.search(
        r'\badd\s+(?:an?\s+)?(?:the\s+)?import\s+([\w\.]+)',
        goal, re.IGNORECASE
    )
    if m:
        name = m.group(1).strip()
        new_text, already = insert_import(original, f"import {name}")
        if already:
            return None, f"import {name} already present"
        return new_text, f"inserted 'import {name}'"

    # ── add from X import Y ───────────────────────────────────────────────
    m = re.search(r'\badd\s+(?:an?\s+)?(from\s+\S+\s+import\s+\S+)', goal, re.IGNORECASE)
    if m:
        imp = m.group(1).strip()
        new_text, already = insert_import(original, imp)
        if already:
            return None, f"{imp} already present"
        return new_text, f"inserted '{imp}'"

    # ── update/change/set VAR = N (with optional comment) ────────────────
    # Matches: "update MAX_STEPS to 40" / "change MAX_STEPS = 40" /
    #          "set MAX_STEPS to 40 and add comment"
    m = re.search(
        r'\b(?:update|change|set|modify)\s+([\w]+)\s*(?:=|to)\s*([\w\.\-]+)',
        g
    )
    if m:
        var, val = m.group(1), m.group(2)
        # Try to find the variable in the file
        lines = original.splitlines(keepends=True)
        pat   = re.compile(r'^(\s*)' + re.escape(var) + r'\s*=', re.IGNORECASE)
        for i, line in enumerate(lines):
            if pat.match(line):
                m = re.match(r'^(\s*)', line)
                indent = m.group(1) if m else ""
                # Preserve the whole line structure, just change the value
                # and handle trailing comments
                new_line = re.sub(
                    r'(?i)^(\s*' + re.escape(var) + r'\s*=\s*)[\w\.\"\'\-]+',
                    lambda mo: mo.group(1) + val,
                    line,
                ).rstrip("\n") + "\n"
                if new_line == line:
                    return None, f"{var} already equals {val}"
                lines[i] = new_line

                # If goal also says "add comment above", insert it
                if "comment" in g:
                    cm = re.search(
                        r'comment[:\s]+["\']?([^"\']+)["\']?\s+above',
                        goal,
                        re.IGNORECASE
                    )
                    comment_text = cm.group(1).strip() if cm else f"{var} = {val}"
                    lines.insert(i, indent + f"# {comment_text}\n")

                return "".join(lines), f"updated {var} = {val}"

    # ── add comment above IDENTIFIER ─────────────────────────────────────
    m = re.search(r'\badd\s+(?:a\s+)?comment\s+above\s+(.+?)(?:\s+in|\s+to|$)', g)
    if m:
        target  = m.group(1).strip().strip('"\'')
        cm      = re.search(
            r'comment[:\s]+["\']?([^"\']+)["\']?\s+above',
            goal, re.IGNORECASE
        )
        comment = f"# {cm.group(1).strip()}" if cm else f"# {target}"
        new_text, success = insert_above(original, target, comment)
        if not success:
            return None, f"target '{target}' not found"
        if new_text == original:
            return None, "comment already present"
        return new_text, f"added comment above '{target}'"

    # ── add comment at bottom ────────────────────────────────────────────
    m = re.search(r'\badd\s+(?:a\s+)?comment\s+(?:at\s+)?(?:the\s+)?bottom', g)
    if m:
        cm = re.search(r'(?:saying|that\s+says?|:)\s*["\']?([^"\']+)["\']?', goal, re.IGNORECASE)
        comment = f"# {cm.group(1).strip()}" if cm else "# end of file"
        new_text = append_to_file(original, comment)
        return new_text, f"added '{comment}' at bottom"

    # ── add comment at top ───────────────────────────────────────────────
    m = re.search(r'\badd\s+(?:a\s+)?comment\s+(?:at\s+)?(?:the\s+)?top', g)
    if m:
        cm = re.search(r'(?:saying|that\s+says?|:)\s*["\']?([^"\']+)["\']?', goal, re.IGNORECASE)
        comment = f"# {cm.group(1).strip()}" if cm else "# start of file"
        new_text = comment + "\n" + original
        return new_text, f"added '{comment}' at top"

    return None, "no CRUD pattern matched"


# ── Core rewrite engine ───────────────────────────────────────────────────────

def _rewrite_function(state, file_path: str) -> dict:
    """
    Returns:
      {"success": True,  "file": path, "noop": False} — change applied
      {"success": True,  "file": path, "noop": True}  — no change
      {"success": False, "error": "..."}              — failure
    """
    # Resolve path
    resolved, found = resolve_path(file_path, state.repo_root, state)
    full = Path(state.repo_root) / resolved
    full.parent.mkdir(parents=True, exist_ok=True)
    if not full.exists():
        full.touch()

    try:
        original = full.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        return {"success": False, "error": f"Cannot read {resolved}: {e}"}

    goal = (getattr(state, "goal", "") or "")

    # ── Fast path 1: explicit "delete lines X-Y" ──────────────────────────
    m = re.search(r"\bdelete\s+lines?\s+(\d+)\s*[-–]\s*(\d+)\b", goal, re.IGNORECASE)
    if m:
        s_ln, e_ln = max(1, int(m.group(1))), int(m.group(2))
        lines = original.splitlines()
        if s_ln <= len(lines):
            snippet  = "\n".join(lines[s_ln - 1: e_ln])
            new_text = "\n".join(lines[:s_ln - 1] + lines[e_ln:]) + "\n"
            if new_text.strip() == original.strip():
                return {"success": True, "file": resolved, "noop": True,
                        "message": "Line deletion noop."}
            payload = {
                "file":    resolved,
                "search":  f"[lines {s_ln}–{e_ln}]\n{snippet}",
                "replace": "(deleted)",
            }
            if not _approve("rewrite_function", payload,
                            f"delete lines {s_ln}-{e_ln} in {resolved}"):
                return {"success": False, "error": "User rejected deletion."}
            if not check_syntax(new_text, resolved):
                return {"success": False, "error": "Syntax error after line deletion."}
            full.write_text(new_text, encoding="utf-8")
            return {"success": True, "file": resolved, "noop": False}

    # ── Fast path 2: CRUD deterministic ───────────────────────────────────
    crud_result, crud_desc = _crud_fast_path(goal, original)
    if crud_result is not None:
        if crud_result.strip() == original.strip():
            return {"success": True, "file": resolved, "noop": True,
                    "message": f"CRUD noop: {crud_desc}"}
        # Show meaningful diff
        before_lines = original.splitlines()[:10]
        after_lines  = crud_result.splitlines()[:10]
        payload = {
            "file":    resolved,
            "search":  "\n".join(before_lines),
            "replace": "\n".join(after_lines),
        }
        if not _approve("rewrite_function", payload, f"CRUD: {crud_desc} in {resolved}"):
            return {"success": False, "error": "User rejected CRUD change."}
        if not check_syntax(crud_result, resolved):
            return {"success": False, "error": f"Syntax error after CRUD."}
        full.write_text(crud_result, encoding="utf-8")
        return {"success": True, "file": resolved, "noop": False}

    # ── LLM SEARCH/REPLACE path ───────────────────────────────────────────
    prompt = f"""You are Operon, a surgical code editor. Make the MINIMAL change.
GOAL: {goal}
FILE: {resolved}

Output ONLY SEARCH/REPLACE blocks. Nothing else.

<<<<<<< SEARCH
[copy VERBATIM from the file — exact characters, spaces, and indentation]
=======
[the replacement — or empty to DELETE]
>>>>>>> REPLACE

RULES:
- SEARCH must EXACTLY match what is in the file. Copy-paste it, do not reconstruct.
- For single-line change: put only that one line in SEARCH.
- For variable: SEARCH = "VAR = oldvalue", REPLACE = "VAR = newvalue"
- Multiple blocks allowed.
- Output NOTHING except the blocks.

THE FULL FILE (copy from this):
{original}"""

    try:
        raw = call_llm(prompt, require_json=False)
    except Exception as e:
        return {"success": False, "error": f"LLM call failed: {e}"}

    blocks = parse_search_replace(raw) if raw else []

    # Fallback: context buffer has different content from file
    if not blocks:
        candidate = (
            state.context_buffer.get(resolved) or
            state.context_buffer.get(file_path)
        )
        if (candidate and isinstance(candidate, str)
                and candidate.strip() != original.strip()):
            blocks = [("", candidate)]
        else:
            return {"success": True, "file": resolved, "noop": True,
                    "message": "LLM produced no SEARCH/REPLACE blocks."}

    # Dry-run
    working   = original
    any_change = False
    applied   : list[dict] = []

    for sb, rb in blocks:
        sb = (sb or "").rstrip("\n")
        rb = (rb or "").rstrip("\n")

        # Deletion
        if sb and not rb:
            if sb in working:
                working    = working.replace(sb, "", 1)
                any_change = True
                applied.append({"search": sb, "replace": ""})
                continue
            words = sb.split()
            if words:
                pat = r'\s+'.join(re.escape(w) for w in words)
                mm  = re.search(pat, working)
                if mm:
                    working    = working[:mm.start()] + working[mm.end():]
                    any_change = True
                    applied.append({"search": sb, "replace": ""})
                    continue
            return {
                "success": False,
                "error": (
                    f"Deletion SEARCH not found in {resolved}.\n"
                    "Hint: copy the exact text from the file."
                ),
            }

        # Append to empty
        if not working.strip() and rb:
            working    = rb + "\n"
            any_change = True
            applied.append({"search": "", "replace": rb})
            continue

        patched, reason = apply_patch(working, sb, rb)
        if reason == "noop":
            applied.append({"search": sb, "replace": rb, "noop": True})
            continue
        if patched is None:
            return {
                "success": False,
                "error": (
                    f"SEARCH block did not match {resolved}.\n"
                    "Hint: read the file first and copy an EXACT snippet."
                ),
            }
        if patched != working:
            working    = patched
            any_change = True
            applied.append({"search": sb, "replace": rb})

    # Hard noop check
    if not any_change or working.strip() == original.strip():
        return {"success": True, "file": resolved, "noop": True,
                "message": "Dry-run: no net change."}

    # Approval (after confirmed real change, with real diff)
    joined_s = "\n---\n".join(
        p.get("search", "") for p in applied if not p.get("noop")
    )
    joined_r = "\n---\n".join(
        p.get("replace", "") for p in applied if not p.get("noop")
    )
    payload = {"file": resolved, "search": joined_s, "replace": joined_r}
    if not _approve("rewrite_function", payload, f"patch {resolved}"):
        return {"success": False, "error": "User rejected the change."}

    # Syntax check
    if not check_syntax(working, resolved):
        try:
            full.write_text(original, encoding="utf-8")
        except Exception:
            pass
        return {"success": False, "error": "Syntax error after patch — restored original."}

    # Write
    try:
        full.write_text(working, encoding="utf-8")
    except Exception as e:
        try:
            full.write_text(original, encoding="utf-8")
        except Exception:
            pass
        return {"success": False, "error": f"Write failed: {e}"}

    return {"success": True, "file": resolved, "noop": False}


# ── Main loop ─────────────────────────────────────────────────────────────────

def run_agent(state):
    from agent.tool_jail import validate_tool

    _ensure(state)

    # ── ARCHITECT ────────────────────────────────────────────────────────────
    if not getattr(state, "plan", None):
        state.phase     = "ARCHITECT"
        state.git_state = setup_git_env(state.repo_root)

        try:
            from tools.repo_index import build_full_index
            build_full_index(state)
        except Exception as e:
            log.warning(f"Index (non-fatal): {e}")

        try:
            result                = make_plan(state.goal, state.repo_root, state=state)
            state.plan            = result[0]
            state.is_question     = bool(result[1]) if len(result) > 1 else False
            state.plan_validators = list(result[2]) if len(result) > 2 else []
        except Exception:
            log.error("Planner crashed — single-step.")
            state.plan            = [state.goal]
            state.plan_validators = [None]
            state.is_question     = False

        log.info(f"[bold magenta]🏛️ PLAN ({len(state.plan)} steps):[/bold magenta]")
        for i, s in enumerate(state.plan):
            log.info(f"  {i+1}. {s}")

    if not isinstance(getattr(state, "reject_counts", None), dict):
        state.reject_counts = {}

    state.phase = "CODER"

    # ── Execution loop ────────────────────────────────────────────────────────
    while not state.done:

        if state.step_count >= MAX_STEPS:
            log.error(f"Max steps ({MAX_STEPS}) — aborting.")
            rollback_files(state.repo_root, state.git_state, state.files_modified)
            break

        if getattr(state, "step_cooldown", 0) > 0:
            state.step_cooldown -= 1
            state.step_count    += 1
            time.sleep(0.05)
            continue

        decision = decide_next_action(state) or {}
        thought  = decision.get("thought", "…")
        ap       = decision.get("tool", decision) or {}
        if isinstance(ap, dict) and "action" not in ap and "tool" in ap:
            ap = ap["tool"]

        act       = (ap.get("action") if isinstance(ap, dict) else None) or ""
        np        = _norm(act, ap if isinstance(ap, dict) else {})
        canonical = _canon({"action": act, **np})

        if _is_noop_action(act, np):
            log.warning(f"Noop/malformed: '{act}'")
            state.observations.append({"error": "No valid action. Try something different."})
            state.step_count += 1
            time.sleep(0.3)
            continue

        valid, msg = validate_tool(act, np, state.phase, state)
        if not valid:
            # BUG6 FIX: finish blocked + reject threshold → abort directly
            if act == "finish" and state.phase == "REVIEWER":
                key   = f"step_{state.current_step}"
                count = state.reject_counts.get(key, 0)
                if count >= REJECT_THRESHOLD:
                    log.error("finish blocked at reject threshold — aborting task.")
                    rollback_files(state.repo_root, state.git_state, state.files_modified)
                    state.done = True
                    break
            log.warning(f"Tool jail: {msg}")
            state.observations.append({"error": f"SYSTEM: {msg}"})
            state.step_count += 1
            time.sleep(0.3)
            continue

        # Exact-repeat loop detection
        if getattr(state, "last_action_canonical", None) == canonical:
            state.loop_counter = getattr(state, "loop_counter", 0) + 1
            log.error(f"Loop ×{state.loop_counter}: {act}")
            if state.loop_counter >= 3:
                log.error("Critical loop — forcing REVIEWER.")
                state.observations.append({
                    "error": (
                        "FATAL LOOP: same action repeated 3 times. "
                        "If file is loaded → use rewrite_function NOW."
                    )
                })
                state.phase              = "REVIEWER"
                state.last_action_canonical = None
                state.loop_counter       = 0
            else:
                state.observations.append({
                    "error": (
                        "REPEAT: You just did this exact action. "
                        "If file is loaded → rewrite_function now. "
                        "If not → read_file first."
                    )
                })
            state.step_count += 1
            time.sleep(0.3)
            continue
        else:
            state.loop_counter            = 0
            state.last_action_canonical   = canonical

        state.step_count += 1
        log.info(f"[cyan][{state.phase}][/cyan] 🧠 {thought}")
        log.info(f"[cyan]⚙️  {act}[/cyan]")

        try:
            # ═══════════════════════════════════════════════════════════════
            # REVIEWER ACTIONS
            # ═══════════════════════════════════════════════════════════════
            if act == "approve_step":
                state.action_log.append(
                    f"✅ REVIEWER approved step {state.current_step + 1}."
                )
                log.info(
                    f"[bold green]✅ REVIEWER PASS:[/bold green] "
                    f"{np.get('message', '')}"
                )
                state.current_step += 1
                state.reject_counts = {}
                state.noop_streak   = 0
                state.step_cooldown = 1

                if state.current_step >= len(state.plan):
                    log.info("[bold green]✅ All steps done.[/bold green]")
                    state.observations.append(
                        {"system": "All steps complete. Use 'finish'."}
                    )
                else:
                    log.info(
                        f"[yellow]👨‍💻 CODER: step "
                        f"{state.current_step + 1}/{len(state.plan)}[/yellow]"
                    )
                    state.phase          = "CODER"
                    state.observations   = []
                    state.context_buffer = {}  # fresh context per step

            elif act == "reject_step":
                feedback = np.get("feedback") or np.get("message") or "No feedback."
                key      = f"step_{state.current_step}"
                state.reject_counts[key] = state.reject_counts.get(key, 0) + 1
                count = state.reject_counts[key]
                state.action_log.append(
                    f"❌ Rejected step {state.current_step + 1} (×{count}): {feedback}"
                )
                state.observations.append({"reviewer_feedback": feedback})
                log.info(
                    f"[bold red]❌ REVIEWER REJECT #{count}:[/bold red] {feedback}"
                )

                if count >= REJECT_THRESHOLD:
                    log.error(f"Step failed {count} times — aborting.")
                    rollback_files(state.repo_root, state.git_state, state.files_modified)
                    state.done = True
                    break

                state.phase          = "CODER"
                state.step_cooldown  = 1
                state.context_buffer = {}  # force fresh read on retry
                log.info(
                    f"[red]👨‍💻 Back to CODER ({count}/{REJECT_THRESHOLD}): {feedback}[/red]"
                )

            elif act == "finish":
                msg = np.get("message") or np.get("commit_message") or "Task complete."
                log.info(f"[bold green]✅ DONE: {msg}[/bold green]")
                commit_success(state.repo_root, msg)
                state.done = True
                break

            # ═══════════════════════════════════════════════════════════════
            # CODER ACTIONS
            # ═══════════════════════════════════════════════════════════════
            elif act == "semantic_search":
                query = np.get("query", "")
                hits  = search_repo(state.repo_root, query) if query else []
                obs   = (
                    f"Semantic: '{query}': {hits}"
                    if hits else f"No semantic matches for '{query}'."
                )
                state.observations.append({"search": obs})
                state.action_log.append(f"semantic_search: '{query}'")

            elif act == "exact_search":
                needle = np.get("text", "")
                hits   = []
                for dirpath, _, fnames in os.walk(state.repo_root):
                    if any(d in dirpath for d in
                           (".git", "__pycache__", ".operon", "venv")):
                        continue
                    for fname in fnames:
                        fp = os.path.join(dirpath, fname)
                        try:
                            with open(fp, encoding="utf-8", errors="ignore") as fh:
                                if needle in fh.read():
                                    hits.append(
                                        os.path.relpath(fp, state.repo_root)
                                    )
                        except Exception:
                            pass
                obs = (
                    f"Exact matches for '{needle}': {hits}"
                    if hits else f"No exact matches for '{needle}'."
                )
                state.observations.append({"exact_search": obs})
                state.action_log.append(f"exact_search: '{needle}'")

            elif act == "find_file":
                term  = np.get("search_term", "").lower()
                root  = Path(state.repo_root)
                found_list = [
                    str(p.relative_to(root))
                    for p in root.rglob("*")
                    if p.is_file()
                    and ".git" not in p.parts
                    and ".operon" not in p.parts
                    and (term in p.name.lower()
                         or term in str(p.relative_to(root)).lower())
                ]
                if found_list:
                    obs = (f"Found {len(found_list)} file(s):\n"
                           + "\n".join(found_list[:20]))
                else:
                    obs = f"No files matching '{term}'. Try exact_search or semantic_search."
                state.observations.append({"find_file": obs})
                state.action_log.append(f"find_file: '{term}'")

            elif act == "read_file":
                raw_path = (
                    np.get("path") or np.get("file") or np.get("file_path") or ""
                )
                if not raw_path:
                    state.observations.append({"error": "read_file requires 'path'."})
                    continue

                resolved_r, content_r, ok_r = read_resolved(
                    raw_path, state.repo_root, state
                )

                if not ok_r:
                    # Last fallback: file_tree name match
                    candidates = [
                        f for f in state.file_tree
                        if Path(f).name.lower() == Path(raw_path).name.lower()
                    ]
                    if candidates:
                        resolved_r = candidates[0]
                        try:
                            content_r = (
                                Path(state.repo_root) / resolved_r
                            ).read_text(encoding="utf-8", errors="ignore")
                            ok_r = True
                        except Exception:
                            pass

                if not ok_r:
                    state.observations.append({
                        "error": (
                            f"File not found: '{raw_path}'. "
                            "Use find_file to locate it first."
                        )
                    })
                    state.action_log.append(f"FAILED read_file '{raw_path}'")
                    continue

                # Store in buffer — this is what the CODER uses for SEARCH
                state.context_buffer[resolved_r] = content_r
                state.observations.append({
                    "success":  f"Loaded '{resolved_r}' ({len(content_r)} chars).",
                    "preview":  content_r[:300],
                })
                if resolved_r not in state.files_read:
                    state.files_read.append(resolved_r)
                state.action_log.append(f"read_file '{resolved_r}'")

            elif act == "create_file":
                fp      = np.get("file_path") or np.get("file") or ""
                content = np.get("initial_content", "")
                if not fp:
                    state.observations.append({"error": "create_file requires 'file_path'."})
                    continue

                payload = {"file": fp, "search": "", "replace": content}
                if not _approve("create_file", payload, f"create {fp}"):
                    state.observations.append({"error": "User rejected file creation."})
                    continue

                full = Path(state.repo_root) / fp
                if full.exists():
                    existing = full.read_text(encoding="utf-8", errors="ignore")
                    if existing.strip() == content.strip():
                        state.observations.append({
                            "success": f"{fp} already has correct content."
                        })
                        state.context_buffer[fp] = existing
                        if content.strip():
                            state.phase = "REVIEWER"
                            state.observations.append({
                                "system": f"{fp} already correct. REVIEWER: verify.",
                                "file_preview": existing[:2000],
                            })
                    else:
                        state.observations.append({
                            "error": (
                                f"{fp} exists with different content. "
                                "Use rewrite_function to modify it."
                            )
                        })
                    continue

                full.parent.mkdir(parents=True, exist_ok=True)
                full.write_text(content, encoding="utf-8")
                log.info(f"[green]📄 Created: {fp}[/green]")

                before_snap = ""
                ts          = time.time()
                diff_txt    = "\n".join(f"+{l}" for l in content.splitlines())
                state.diff_memory.setdefault(fp, []).append({
                    "ts": ts, "before": before_snap,
                    "after": content, "diff": diff_txt
                })
                _persist_diff(state)

                if fp not in state.files_modified:
                    state.files_modified.append(fp)
                state.context_buffer[fp] = content
                state.action_log.append(f"Created '{fp}'")

                if content.strip():
                    state.phase = "REVIEWER"
                    state.observations.append({
                        "system": f"Created {fp}. REVIEWER: verify goal met.",
                        "file_preview": content[:2000],
                    })
                else:
                    state.observations.append({
                        "system": f"Empty file {fp} created. CODER: write content."
                    })

            elif act == "rewrite_function":
                raw_file = np.get("file") or np.get("file_path") or ""
                if not raw_file:
                    state.observations.append(
                        {"error": "rewrite_function requires 'file'."}
                    )
                    continue

                # Snapshot before
                resolved_b, _ = resolve_path(raw_file, state.repo_root, state)
                full_b = Path(state.repo_root) / resolved_b
                before = (
                    full_b.read_text(encoding="utf-8", errors="ignore")
                    if full_b.exists() else ""
                )

                # Pass initial_content as candidate
                init = np.get("initial_content")
                if init and isinstance(init, str) and init.strip() != before.strip():
                    state.context_buffer[resolved_b] = init

                result = _rewrite_function(state, raw_file)

                # Noop: real error
                if result.get("noop"):
                    state.noop_streak = getattr(state, "noop_streak", 0) + 1
                    log.warning(
                        f"[yellow]⚠️ NOOP rewrite "
                        f"({state.noop_streak}/{NOOP_STREAK_MAX}): "
                        f"{result.get('message', '')}[/yellow]"
                    )
                    state.observations.append({
                        "error": (
                            f"rewrite_function made NO changes to '{raw_file}'. "
                            "Your SEARCH block must EXACTLY match the file content.\n"
                            "Copy verbatim from the file preview — character by character.\n"
                            "Check indentation, trailing spaces, and comments."
                        )
                    })
                    state.action_log.append(f"NOOP rewrite '{raw_file}'")
                    if state.noop_streak >= NOOP_STREAK_MAX:
                        log.error("Noop streak — forcing REVIEWER.")
                        state.phase       = "REVIEWER"
                        state.noop_streak = 0
                    continue

                if result.get("success"):
                    rpath  = result.get("file", raw_file)
                    full_a = Path(state.repo_root) / rpath
                    after  = (
                        full_a.read_text(encoding="utf-8", errors="ignore")
                        if full_a.exists() else ""
                    )

                    ts       = time.time()
                    diff_txt = "\n".join(difflib.unified_diff(
                        before.splitlines(keepends=True),
                        after.splitlines(keepends=True),
                        fromfile=f"a/{rpath}",
                        tofile=f"b/{rpath}",
                        lineterm="",
                    ))
                    state.diff_memory.setdefault(rpath, []).append({
                        "ts": ts, "before": before, "after": after,
                        "diff": diff_txt
                    })
                    _persist_diff(state)

                    state.loop_counter          = 0
                    state.noop_streak           = 0
                    state.last_action_canonical = None

                    # Inline validator check
                    if _validate_step(state, rpath, before, after):
                        log.info("[bold green]🎯 Validator passed.[/bold green]")
                        commit_success(
                            state.repo_root,
                            f"[step {state.current_step + 1}] {rpath}"
                        )
                        state.done = True
                        return state

                    if rpath not in state.files_modified:
                        state.files_modified.append(rpath)

                    state.context_buffer = {rpath: after}
                    state.action_log.append(f"Patched '{rpath}'")
                    state.observations.append({
                        "system": (
                            f"Coder patched {rpath}. "
                            "REVIEWER: read CURRENT FILE ON DISK and verify."
                        ),
                        "file_preview": after[:2000],
                        "diff_preview": diff_txt[:1200],
                    })
                    log.info("[cyan]🔄 → REVIEWER[/cyan]")
                    state.phase = "REVIEWER"

                    # Multi-file tracking
                    mf  = getattr(state, "multi_file_queue", [])
                    mfd = getattr(state, "multi_file_done", [])
                    if any(x.get("file") == rpath for x in mf) and rpath not in mfd:
                        mfd.append(rpath)
                    state.multi_file_done = mfd

                else:
                    err  = result.get("error", "Unknown error")
                    hint = ""
                    if "did not match" in err or "not found" in err.lower():
                        hint = (
                            "\nHint: use read_file first, then copy the EXACT "
                            "snippet from the file preview into your SEARCH block."
                        )
                    log.error(f"Patch failed: {err}")
                    state.observations.append({"error": err + hint})
                    state.action_log.append(f"FAILED rewrite '{raw_file}': {err}")

            elif act == "delete_file":
                fp = np.get("file_path") or np.get("file") or ""
                if not fp:
                    state.observations.append({"error": "delete_file requires 'file_path'."})
                    continue
                resolved_d, ok_d = resolve_path(fp, state.repo_root, state)
                if not ok_d:
                    state.observations.append({"error": f"Cannot delete: '{fp}' not found."})
                    continue
                try:
                    (Path(state.repo_root) / resolved_d).unlink()
                    if resolved_d not in state.files_modified:
                        state.files_modified.append(resolved_d)
                    state.observations.append({"success": f"Deleted '{resolved_d}'."})
                    state.action_log.append(f"Deleted '{resolved_d}'")
                except Exception as ex:
                    state.observations.append({"error": f"Delete failed: {ex}"})

            else:
                log.warning(f"Unhandled action: {act}")
                state.observations.append({"error": f"Unknown action '{act}'."})

        except Exception as exc:
            log.exception(f"Exception in '{act}'")
            state.observations.append({"error": f"Exception in '{act}': {exc}"})

        time.sleep(0.15)

    return state
