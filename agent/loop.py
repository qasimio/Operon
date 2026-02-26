# agent/loop.py — Operon v3.1
"""
Complete merge of your working loop.py with v3 fixes.

WHAT WAS BROKEN (from log analysis):
  1. read_file("print.js") → Path(repo_root)/"print.js" doesn't exist
     because the file is at agent/print.js. No fuzzy resolution.
     FIX: resolve_path() before every read_file and rewrite_function.

  2. REVIEWER hot-loop: after reject×3, "finish" was blocked by tool_jail,
     so the loop called decide() again every 0.1s → 30 rejects/second.
     FIX: reject_counts tracked in loop.py. At threshold → force abort
     directly (state.done = True) WITHOUT going through decide() again.

  3. "No change made" was treated as success (noop).
     FIX: _rewrite_function returns {"noop": True}. Loop treats noop as
     an error, injects corrective feedback, does NOT hand off to REVIEWER.

  4. REVIEWER had no file evidence → always said "file is unmodified."
     FIX: context_buffer with file preview always injected into REVIEWER
     prompt in decide.py.

KEPT from your working version:
  - resolve_repo_path() approach (now via path_resolver.py)
  - tactical prompt injection in decide.py
  - REVIEWER prompt with file_preview evidence
  - All the clean normalisation and canonical loop detection
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
from tools.diff_engine import parse_search_replace, apply_patch
from tools.git_safety import setup_git_env, rollback_files, commit_success
from tools.path_resolver import resolve_path, read_resolved
from tools.repo_search import search_repo
from tools.universal_parser import check_syntax

MAX_STEPS       = 30
NOOP_STREAK_MAX = 3
REJECT_THRESHOLD = 3


# ── State init ───────────────────────────────────────────────────────────────

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
        "recent_actions":         [],
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


# ── Normalise / canonicalise ─────────────────────────────────────────────────

def _norm(act: str, p: dict) -> dict:
    p = dict(p) if isinstance(p, dict) else {}
    # alias cross-fills
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


def _is_noop(act: str, payload: dict) -> bool:
    if not act or act.lower() in {"noop", "error", "none", ""}:
        return True
    if act == "create_file" and not payload.get("file_path"):
        return True
    if act == "rewrite_function" and not (payload.get("file") or payload.get("initial_content")):
        return True
    return False


# ── diff persistence ─────────────────────────────────────────────────────────

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


# ── Core rewrite engine ──────────────────────────────────────────────────────

def _rewrite_function(state, file_path: str) -> dict:
    """
    Returns:
      {"success": True,  "file": path, "noop": False}  — change applied
      {"success": True,  "file": path, "noop": True}   — no change (BUG2 FIX)
      {"success": False, "error": "..."}               — hard failure
    """
    from agent.approval import ask_user_approval

    # Resolve path (BUG1 FIX)
    resolved, found = resolve_path(file_path, state.repo_root, state)
    full = Path(state.repo_root) / resolved
    full.parent.mkdir(parents=True, exist_ok=True)
    if not full.exists():
        full.touch()

    try:
        original = full.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        return {"success": False, "error": f"Cannot read {resolved}: {e}"}

    # Fast path: explicit "delete lines X-Y" in goal
    goal = (getattr(state, "goal", "") or "").lower()
    m = re.search(r"\bdelete\s+lines?\s+(\d+)\s*[-–]\s*(\d+)\b", goal)
    if m:
        s, e_num = max(1, int(m.group(1))), int(m.group(2))
        lines     = original.splitlines()
        if s <= len(lines):
            snippet  = "\n".join(lines[s-1 : e_num])
            new_text = "\n".join(lines[:s-1] + lines[e_num:]) + "\n"
            if new_text.strip() == original.strip():
                return {"success": True, "file": resolved, "noop": True,
                        "message": "Line deletion produced no change."}
            if not ask_user_approval("rewrite_function",
                                     {"file": resolved,
                                      "search": f"[lines {s}–{e_num}]\n{snippet}",
                                      "replace": ""}):
                return {"success": False, "error": "User rejected deletion."}
            if not check_syntax(new_text, resolved):
                return {"success": False, "error": "Syntax error after deletion."}
            full.write_text(new_text, encoding="utf-8")
            return {"success": True, "file": resolved, "noop": False,
                    "message": f"Deleted lines {s}–{e_num}."}

    # Ask LLM for SEARCH/REPLACE blocks
    ctx_hint = ""
    try:
        from tools.repo_index import get_context_for_query
        ctx_hint = get_context_for_query(state, state.goal, max_chars=400)
    except Exception:
        pass

    prompt = f"""You are Operon, a surgical code editor.
GOAL: {state.goal}
FILE: {resolved}
{('CONTEXT:\n' + ctx_hint) if ctx_hint else ''}

Output ONLY SEARCH/REPLACE blocks — nothing else.

<<<<<<< SEARCH
[exact lines to replace or delete]
=======
[replacement — leave empty to DELETE]
>>>>>>> REPLACE

Rules:
- SEARCH must match existing file content exactly (whitespace-normalised).
- Multiple blocks allowed.
- To append: empty SEARCH, new code in REPLACE.
- Output NOTHING except blocks.

FILE CONTENT:
{original}"""

    try:
        raw = call_llm(prompt, require_json=False)
    except Exception as e:
        return {"success": False, "error": f"LLM error: {e}"}

    blocks = parse_search_replace(raw) if raw else []

    # Fallback: candidate in context_buffer
    if not blocks:
        candidate = (
            state.context_buffer.get(resolved) or
            state.context_buffer.get(file_path)
        )
        if candidate and isinstance(candidate, str) and candidate.strip() != original.strip():
            blocks = [("", candidate)]
        else:
            return {"success": True, "file": resolved, "noop": True,
                    "message": "LLM produced no SEARCH/REPLACE and no buffer candidate."}

    # Dry-run
    working  = original
    any_real = False
    patches  = []

    for sb, rb in blocks:
        sb = (sb or "").rstrip("\n")
        rb = (rb or "").rstrip("\n")
        patches.append({"search": sb, "replace": rb})

        # deletion with empty replace
        if sb and not rb:
            if sb in working:
                working  = working.replace(sb, "", 1)
                any_real = True
                continue
            # whitespace-normalised deletion fallback
            words = sb.split()
            if words:
                pat = r'\s+'.join(re.escape(w) for w in words)
                mm  = re.search(pat, working)
                if mm:
                    working  = working[:mm.start()] + working[mm.end():]
                    any_real = True
                    continue
            return {"success": False,
                    "error": (
                        f"SEARCH block not found in {resolved}. "
                        "Hint: read the file first and use an exact snippet."
                    )}

        # append
        if not working.strip() and rb:
            working  = rb + "\n"
            any_real = True
            continue

        # normal patch  (returns (text, reason) in our diff_engine)
        result = apply_patch(working, sb, rb)
        # Handle both old (returns str|None) and new (returns tuple) diff_engine
        if isinstance(result, tuple):
            patched, reason = result
        else:
            patched, reason = result, ("ok" if result is not None else "no_match")

        if reason == "noop":
            continue
        if patched is None:
            return {"success": False,
                    "error": (
                        f"SEARCH block did not match {resolved}. "
                        "Read the file first, then use an exact snippet."
                    )}
        if patched != working:
            working  = patched
            any_real = True

    # BUG2 FIX: hard noop guard
    if not any_real or working.strip() == original.strip():
        return {"success": True, "file": resolved, "noop": True,
                "message": "Dry-run produced no net change."}

    # Approval
    joined_s = "\n---\n".join(p["search"]  for p in patches)
    joined_r = "\n---\n".join(p["replace"] for p in patches)
    if not ask_user_approval("rewrite_function",
                             {"file": resolved,
                              "search": joined_s,
                              "replace": joined_r}):
        return {"success": False, "error": "User rejected."}

    # Syntax check
    if not check_syntax(working, resolved):
        full.write_text(original, encoding="utf-8")
        return {"success": False, "error": "Syntax error after patch — restored."}

    try:
        full.write_text(working, encoding="utf-8")
    except Exception as e:
        try:
            full.write_text(original, encoding="utf-8")
        except Exception:
            pass
        return {"success": False, "error": f"Write failed: {e}"}

    return {"success": True, "file": resolved, "noop": False}


# ── Main loop ────────────────────────────────────────────────────────────────

def run_agent(state):
    from agent.tool_jail import validate_tool
    from agent.approval import ask_user_approval

    _ensure(state)

    # ── ARCHITECT ────────────────────────────────────────────────────────────
    if not getattr(state, "plan", None):
        state.phase     = "ARCHITECT"
        state.git_state = setup_git_env(state.repo_root)

        try:
            from tools.repo_index import build_full_index
            build_full_index(state)
        except Exception as e:
            log.warning(f"Index build (non-fatal): {e}")

        try:
            result            = make_plan(state.goal, state.repo_root, state=state)
            state.plan        = result[0]
            state.is_question = bool(result[1]) if len(result) > 1 else False
            state.plan_validators = list(result[2]) if len(result) > 2 else []
        except Exception:
            log.error("Planner crashed — using fallback.")
            state.plan            = [state.goal]
            state.plan_validators = [None]
            state.is_question     = False

        log.info(f"[bold magenta]🏛️ PLAN ({len(state.plan)} steps):[/bold magenta]")
        for i, s in enumerate(state.plan):
            log.info(f"  {i+1}. {s}")

    if not isinstance(getattr(state, "reject_counts", None), dict):
        state.reject_counts = {}

    state.phase = "CODER"

    # ── Execution loop ───────────────────────────────────────────────────────
    while not state.done:

        if state.step_count >= MAX_STEPS:
            log.error(f"Max steps ({MAX_STEPS}) reached — aborting.")
            rollback_files(state.repo_root, state.git_state, state.files_modified)
            break

        if getattr(state, "step_cooldown", 0) > 0:
            state.step_cooldown -= 1
            state.step_count    += 1
            time.sleep(0.05)
            continue

        # ── Decide ──────────────────────────────────────────────────────────
        decision = decide_next_action(state) or {}
        thought  = decision.get("thought", "…")
        ap       = decision.get("tool", decision) or {}
        if isinstance(ap, dict) and "action" not in ap and "tool" in ap:
            ap = ap["tool"]

        act = (ap.get("action") if isinstance(ap, dict) else None) or ""
        np  = _norm(act, ap if isinstance(ap, dict) else {})
        canonical = _canon({"action": act, **np})

        # ── Noop guard ───────────────────────────────────────────────────────
        if _is_noop(act, np):
            log.warning("Noop/malformed action.")
            state.observations.append({"error": "No valid action. Try a different approach."})
            state.step_count += 1
            time.sleep(0.3)
            continue

        # ── Tool jail ────────────────────────────────────────────────────────
        valid, msg = validate_tool(act, np, state.phase, state)
        if not valid:
            # BUG: old code spun forever when "finish" was blocked.
            # Now: if we're in REVIEWER and finish is blocked, abort cleanly.
            if act == "finish" and state.phase == "REVIEWER":
                key   = f"step_{state.current_step}"
                count = state.reject_counts.get(key, 0)
                if count >= REJECT_THRESHOLD:
                    log.error("finish blocked + reject threshold reached — aborting task.")
                    rollback_files(state.repo_root, state.git_state,
                                   state.files_modified)
                    state.done = True
                    break
            log.warning(f"Tool jail: {msg}")
            state.observations.append({"error": f"SYSTEM: {msg}"})
            state.step_count += 1
            time.sleep(0.3)
            continue

        # ── Exact repeat loop detection ───────────────────────────────────────
        if getattr(state, "last_action_canonical", None) == canonical:
            state.loop_counter = getattr(state, "loop_counter", 0) + 1
            log.error(f"LOOP DETECTED ({state.loop_counter}): {act}")
            if state.loop_counter >= 3:
                log.error("CRITICAL LOOP — forcing REVIEWER.")
                state.observations.append({
                    "error": "FATAL LOOP: You are stuck repeating the same action. "
                             "The REVIEWER will now judge current progress."
                })
                state.phase              = "REVIEWER"
                state.last_action_canonical = None
                state.loop_counter       = 0
            else:
                state.observations.append({
                    "error": (
                        "SYSTEM OVERRIDE: You just did this exact action. "
                        "Do something different — if you already read a file, "
                        "call rewrite_function on it now."
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
            #  REVIEWER ACTIONS
            # ═══════════════════════════════════════════════════════════════
            if act == "approve_step":
                state.action_log.append(
                    f"✅ REVIEWER approved step {state.current_step + 1}."
                )
                state.current_step += 1
                state.reject_counts = {}
                state.noop_streak   = 0
                state.step_cooldown = 1

                if state.current_step >= len(state.plan):
                    log.info("[bold green]✅ All steps done. REVIEWER should finish.[/bold green]")
                    state.observations.append(
                        {"system": "All steps complete. Use 'finish' tool now."}
                    )
                else:
                    log.info(f"[yellow]👨‍💻 CODER: step {state.current_step + 1}[/yellow]")
                    state.phase        = "CODER"
                    state.observations = []

            elif act == "reject_step":
                feedback = np.get("feedback") or np.get("message") or "No feedback."
                key      = f"step_{state.current_step}"
                state.reject_counts[key] = state.reject_counts.get(key, 0) + 1
                count = state.reject_counts[key]
                state.action_log.append(
                    f"❌ REJECTED step {state.current_step + 1} (×{count}): {feedback}"
                )
                state.observations.append({"reviewer_feedback": feedback})

                if count >= REJECT_THRESHOLD:
                    log.error(f"Step rejected {count} times — aborting task.")
                    rollback_files(state.repo_root, state.git_state,
                                   state.files_modified)
                    state.done = True
                    break

                state.phase         = "CODER"
                state.step_cooldown = 2
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
            #  CODER ACTIONS
            # ═══════════════════════════════════════════════════════════════
            elif act == "semantic_search":
                query = np.get("query", "")
                hits  = search_repo(state.repo_root, query) if query else []
                obs   = f"Semantic matches for '{query}': {hits}" if hits else "No matches."
                state.observations.append({"search": obs})
                state.action_log.append(f"semantic_search: '{query}'")

            elif act == "exact_search":
                needle = np.get("text", "")
                hits   = []
                for dirpath, _, fnames in os.walk(state.repo_root):
                    if any(d in dirpath for d in (".git", "__pycache__", ".operon", "venv")):
                        continue
                    for fname in fnames:
                        fp = os.path.join(dirpath, fname)
                        try:
                            with open(fp, encoding="utf-8", errors="ignore") as fh:
                                if needle in fh.read():
                                    hits.append(os.path.relpath(fp, state.repo_root))
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
                found = [
                    str(p.relative_to(root))
                    for p in root.rglob("*")
                    if p.is_file()
                    and ".git" not in p.parts
                    and ".operon" not in p.parts
                    and (term in p.name.lower() or term in str(p.relative_to(root)).lower())
                ]
                if found:
                    obs = f"Found {len(found)} files:\n" + "\n".join(found[:20])
                else:
                    obs = f"No files matching '{term}'. Try semantic_search."
                state.observations.append({"find_file": obs})
                state.action_log.append(f"find_file: '{term}'")

            elif act == "read_file":
                raw_path = (
                    np.get("path") or np.get("file") or np.get("file_path") or ""
                )
                if not raw_path:
                    state.observations.append({"error": "read_file requires 'path'."})
                    continue

                # BUG1 FIX: fuzzy resolve before read
                resolved, content, ok = read_resolved(raw_path, state.repo_root, state)

                if not ok:
                    # last try: file_tree exact name match
                    matches = [
                        f for f in state.file_tree
                        if Path(f).name.lower() == Path(raw_path).name.lower()
                    ]
                    if matches:
                        resolved = matches[0]
                        try:
                            content = (Path(state.repo_root) / resolved).read_text(
                                encoding="utf-8", errors="ignore"
                            )
                            ok = True
                        except Exception:
                            pass

                if not ok:
                    state.observations.append({
                        "error": (
                            f"File not found: '{raw_path}'. "
                            "Use find_file to locate it first."
                        )
                    })
                    state.action_log.append(f"FAILED read_file '{raw_path}'")
                    continue

                state.context_buffer[resolved] = content
                state.observations.append({
                    "success": f"Loaded '{resolved}' ({len(content)} chars).",
                    "preview": content[:1500],
                })
                if resolved not in state.files_read:
                    state.files_read.append(resolved)
                state.action_log.append(f"read_file '{resolved}'")

            elif act == "create_file":
                fp      = np.get("file_path") or np.get("file") or ""
                content = np.get("initial_content", "")

                if not fp:
                    state.observations.append({"error": "create_file requires 'file_path'."})
                    continue

                preview = {"file": fp, "search": "", "replace": content}
                if not ask_user_approval("create_file", preview):
                    state.observations.append({"error": "User rejected file creation."})
                    continue

                full = Path(state.repo_root) / fp
                if full.exists():
                    existing = full.read_text(encoding="utf-8", errors="ignore")
                    if existing.strip() == content.strip():
                        state.observations.append({
                            "success": f"{fp} already exists with identical content."
                        })
                        state.context_buffer[fp] = existing
                        if content.strip():
                            state.phase = "REVIEWER"
                            state.observations.append({
                                "system": f"File {fp} already has the right content. REVIEWER: verify goal.",
                                "file_preview": existing[:2000],
                            })
                    else:
                        state.observations.append({
                            "error": f"{fp} already exists with different content. Use rewrite_function instead."
                        })
                    continue

                full.parent.mkdir(parents=True, exist_ok=True)
                full.write_text(content, encoding="utf-8")
                log.info(f"[green]📄 Created: {fp}[/green]")

                ts = time.time()
                diff_txt = "\n".join(
                    f"+{l}" for l in content.splitlines()
                )
                state.diff_memory.setdefault(fp, []).append(
                    {"ts": ts, "before": "", "after": content, "diff": diff_txt}
                )
                _persist_diff(state)
                state.context_buffer[fp] = content
                if fp not in state.files_modified:
                    state.files_modified.append(fp)
                state.action_log.append(f"Created '{fp}'")

                if content.strip():
                    log.info("[cyan]🔄 → REVIEWER...[/cyan]")
                    state.phase = "REVIEWER"
                    state.observations.append({
                        "system": f"File {fp} created. REVIEWER: verify goal is met.",
                        "file_preview": content[:2000],
                    })
                else:
                    state.observations.append({
                        "system": f"Empty file {fp} created. CODER must write content."
                    })

            elif act == "rewrite_function":
                raw_file = np.get("file") or np.get("file_path") or ""
                if not raw_file:
                    state.observations.append(
                        {"error": "rewrite_function requires 'file'."}
                    )
                    continue

                # Resolve before snapshot (BUG1 FIX)
                resolved_pre, _ = resolve_path(raw_file, state.repo_root, state)
                full_pre = Path(state.repo_root) / resolved_pre
                before   = (
                    full_pre.read_text(encoding="utf-8", errors="ignore")
                    if full_pre.exists() else ""
                )

                # PREVENT useless rewrite if cache matches file
                cached = (
                    state.context_buffer.get(resolved_pre) or
                    state.context_buffer.get(raw_file)
                )
                if (cached and isinstance(cached, str)
                        and cached.strip() == before.strip()
                        and before.strip()):
                    state.observations.append({
                        "system": (
                            f"{resolved_pre} already matches cached content. "
                            "Skipping to REVIEWER."
                        )
                    })
                    state.phase = "REVIEWER"
                    continue

                # Pass candidate content if provided
                init = np.get("initial_content")
                if init:
                    state.context_buffer[resolved_pre] = init

                result = _rewrite_function(state, raw_file)

                # BUG2 FIX: noop = real error
                if result.get("noop"):
                    state.noop_streak = getattr(state, "noop_streak", 0) + 1
                    log.warning(
                        f"[yellow]⚠️ NOOP rewrite ({state.noop_streak}/{NOOP_STREAK_MAX}): "
                        f"{result.get('message', '')}[/yellow]"
                    )
                    state.observations.append({
                        "error": (
                            f"rewrite_function made NO changes to '{raw_file}'. "
                            "Your SEARCH block did not match the actual file content. "
                            "Read the file with read_file first, then use an exact "
                            "snippet from what you see."
                        )
                    })
                    state.action_log.append(f"NOOP rewrite '{raw_file}'")
                    if state.noop_streak >= NOOP_STREAK_MAX:
                        log.error("Too many noops → forcing REVIEWER.")
                        state.phase       = "REVIEWER"
                        state.noop_streak = 0
                    continue

                if result.get("success"):
                    resolved_path = result.get("file", raw_file)
                    full_after    = Path(state.repo_root) / resolved_path
                    after         = (
                        full_after.read_text(encoding="utf-8", errors="ignore")
                        if full_after.exists() else ""
                    )

                    ts       = time.time()
                    diff_txt = "\n".join(difflib.unified_diff(
                        before.splitlines(keepends=True),
                        after.splitlines(keepends=True),
                        fromfile=f"a/{resolved_path}",
                        tofile=f"b/{resolved_path}",
                        lineterm="",
                    ))
                    state.diff_memory.setdefault(resolved_path, []).append({
                        "ts": ts, "before": before, "after": after, "diff": diff_txt
                    })
                    _persist_diff(state)

                    # Reset loop counters on real progress
                    state.loop_counter          = 0
                    state.noop_streak           = 0
                    state.last_action_canonical = None

                    # Validate immediately
                    if _validate_step(state, resolved_path, before, after):
                        log.info("[bold green]🎯 Validator PASSED.[/bold green]")
                        commit_success(
                            state.repo_root,
                            f"Step {state.current_step + 1}: patched {resolved_path}"
                        )
                        state.done = True
                        return state

                    if resolved_path not in state.files_modified:
                        state.files_modified.append(resolved_path)

                    state.context_buffer = {resolved_path: after}
                    state.action_log.append(f"Patched '{resolved_path}'")
                    state.observations.append({
                        "system": (
                            f"Coder patched {resolved_path}. "
                            "REVIEWER: look at file_preview and verify goal."
                        ),
                        "file_preview": after[:2000],
                        "diff_preview": diff_txt[:1500],
                    })
                    log.info("[cyan]🔄 → REVIEWER...[/cyan]")
                    state.phase = "REVIEWER"

                    # Multi-file tracking
                    mf = getattr(state, "multi_file_queue", [])
                    md = getattr(state, "multi_file_done", [])
                    if any(x.get("file") == resolved_path for x in mf):
                        if resolved_path not in md:
                            md.append(resolved_path)
                        state.multi_file_done = md

                else:
                    err = result.get("error", "Unknown error")
                    hint = ""
                    if "did not match" in err or "not found" in err.lower():
                        hint = (
                            " HINT: Use read_file first, then copy an exact "
                            "snippet from the file into your SEARCH block."
                        )
                    log.error(f"Patch failed: {err}")
                    state.observations.append({"error": err + hint})
                    state.action_log.append(f"FAILED rewrite '{raw_file}': {err}")

            elif act == "delete_file":
                fp = np.get("file_path") or np.get("file") or ""
                if not fp:
                    state.observations.append({"error": "delete_file requires 'file_path'."})
                    continue
                resolved, ok = resolve_path(fp, state.repo_root, state)
                if not ok:
                    state.observations.append({"error": f"Cannot delete: '{fp}' not found."})
                    continue
                try:
                    (Path(state.repo_root) / resolved).unlink()
                    if resolved not in state.files_modified:
                        state.files_modified.append(resolved)
                    state.action_log.append(f"Deleted '{resolved}'")
                    state.observations.append({"success": f"Deleted '{resolved}'."})
                except Exception as ex:
                    state.observations.append({"error": f"Delete failed: {ex}"})

            else:
                log.warning(f"Unhandled action: {act}")
                state.observations.append({"error": f"Unknown action '{act}'."})

        except Exception as exc:
            log.exception(f"Exception during '{act}'")
            state.observations.append({"error": f"Exception in '{act}': {exc}"})

        time.sleep(0.15)

    return state
