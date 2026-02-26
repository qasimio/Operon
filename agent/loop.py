# agent/loop.py — Operon v3
"""
Complete rewrite fixing every identified bug:

  BUG 1 FIX: File resolution — uses path_resolver.resolve_path() which does
             recursive fuzzy search so nested files are always found.

  BUG 2 FIX: "No change" = success — rewrite_function now returns {"noop": True}
             when the file wasn't changed, counts toward noop_streak, and forces
             the REVIEWER to reject (so the coder tries again with a real fix).

  BUG 3 FIX: Rollback destroys user work — rollback_files() is surgical: only
             restores files Operon touched. User's pre-existing changes are
             preserved via git stash at session start.

  EXTRA:     Multi-file support — state.multi_file_queue is processed in order,
             one file per CODER→REVIEWER cycle.
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
from tools.fs_tools import read_file
from tools.git_safety import setup_git_env, rollback_files, commit_success
from tools.path_resolver import resolve_path, read_resolved
from tools.repo_search import search_repo
from tools.universal_parser import check_syntax

MAX_STEPS        = 40
NOOP_STREAK_MAX  = 3   # consecutive no-change rewrites before escalating


# ─────────────────────────────────────────────────────────────────────────────
# State initialisation helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ensure_fields(state) -> None:
    defaults: dict[str, Any] = {
        "action_log":          [],
        "observations":        [],
        "context_buffer":      {},
        "current_step":        0,
        "loop_counter":        0,
        "last_action_payload": None,
        "last_action_canonical": None,
        "step_count":          0,
        "files_read":          [],
        "files_modified":      [],
        "done":                False,
        "phase":               "CODER",
        "diff_memory":         {},
        "git_state":           {},
        "skip_counts":         {},
        "search_counts":       {},
        "step_cooldown":       0,
        "recent_actions":      [],
        "reject_counts":       {},
        "plan_validators":     [],
        "symbol_index":        {},
        "dep_graph":           {},
        "rev_dep":             {},
        "file_tree":           [],
        "multi_file_queue":    [],
        "multi_file_done":     [],
        "noop_streak":         0,
        "allow_read_skip":     False,
    }
    for k, v in defaults.items():
        if not hasattr(state, k) or getattr(state, k) is None:
            setattr(state, k, v)


# ─────────────────────────────────────────────────────────────────────────────
# Payload normalisation
# ─────────────────────────────────────────────────────────────────────────────

def _normalise(act: str, payload: dict) -> dict:
    p = dict(payload) if isinstance(payload, dict) else {}

    # Alias normalisation
    alias_pairs = [
        ("file",      "file_path"),
        ("file_path", "file"),
        ("path",      "file_path"),
        ("file_path", "path"),
    ]
    for src, dst in alias_pairs:
        if src in p and dst not in p:
            p[dst] = p[src]

    # content synonyms → initial_content
    for k in ("new_content", "content", "function_content"):
        if k in p and "initial_content" not in p:
            p["initial_content"] = p[k]

    # action-specific fixes
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


def _canonicalise(payload: dict) -> str:
    try:
        return json.dumps(payload, sort_keys=True, default=str)
    except Exception:
        return str(payload)


# ─────────────────────────────────────────────────────────────────────────────
# Loop detection helpers
# ─────────────────────────────────────────────────────────────────────────────

def _register_action(state, act: str, canonical: str) -> None:
    if not hasattr(state, "recent_actions"):
        state.recent_actions = []
    state.recent_actions.append((act, canonical))
    if len(state.recent_actions) > 16:
        state.recent_actions.pop(0)


def _alternating_loop(state, window: int = 6) -> bool:
    seq  = getattr(state, "recent_actions", [])[-window:]
    if len(seq) < 4:
        return False
    acts = [a for a, _ in seq]
    uniq = list(dict.fromkeys(acts))
    if len(uniq) != 2:
        return False
    return all(acts[i] == uniq[i % 2] for i in range(len(acts)))


def _track_search(state, key: str) -> int:
    if not hasattr(state, "search_counts"):
        state.search_counts = {}
    e = state.search_counts.get(key, {"count": 0, "last_step": 0})
    e["count"]     += 1
    e["last_step"]  = getattr(state, "step_count", 0)
    state.search_counts[key] = e
    return e["count"]


def _throttle_search(state, key: str, max_r: int = 3, cool: int = 15) -> bool:
    e = getattr(state, "search_counts", {}).get(key)
    if not e:
        return False
    return e["count"] > max_r and (state.step_count - e["last_step"]) < cool


# ─────────────────────────────────────────────────────────────────────────────
# diff persistence
# ─────────────────────────────────────────────────────────────────────────────

def _persist_diff(state) -> None:
    try:
        odir = Path(state.repo_root) / ".operon"
        odir.mkdir(parents=True, exist_ok=True)
        out = odir / "last_session_diff.json"

        serialisable: dict = {}
        for fp, patches in state.diff_memory.items():
            serialisable[fp] = [
                {k: v for k, v in p.items() if k in ("ts", "diff", "before", "after")}
                for p in patches
            ]
        out.write_text(json.dumps(serialisable, indent=2), encoding="utf-8")

        # human-readable copy
        txt = odir / "last_session_diff.txt"
        lines = ["OPERON v3 DIFF REPORT", "=" * 70]
        import datetime
        for fp, patches in serialisable.items():
            lines += ["", f"FILE: {fp}", "-" * 70]
            for patch in patches:
                ts = datetime.datetime.fromtimestamp(patch.get("ts", 0)).isoformat()
                lines += [f"\nPATCH @ {ts}", patch.get("diff", "(no diff)"), ""]
        txt.write_text("\n".join(lines), encoding="utf-8")
    except Exception as e:
        log.debug(f"diff persist error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Core rewrite engine
# ─────────────────────────────────────────────────────────────────────────────

def _rewrite_function(state, file_path: str) -> dict:
    """
    Resolves the file path, asks LLM for SEARCH/REPLACE blocks,
    dry-runs them, gets user approval, then writes.

    Returns one of:
      {"success": True,  "file": path, "noop": False, "message": "..."}
      {"success": True,  "file": path, "noop": True,  "message": "No changes."}
      {"success": False, "error": "..."}
    """
    from agent.approval import ask_user_approval

    # ── BUG 1 FIX: resolve path recursively ──────────────────────────────────
    resolved, found = resolve_path(file_path, state.repo_root, state)
    if not found:
        # If it doesn't exist and isn't in the index, it might be a creation
        resolved = file_path

    full_path = Path(state.repo_root) / resolved
    full_path.parent.mkdir(parents=True, exist_ok=True)
    if not full_path.exists():
        full_path.touch()

    try:
        original_text = full_path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        return {"success": False, "error": f"Cannot read {resolved}: {e}"}

    # ── Fast path: explicit "delete lines X-Y" ────────────────────────────────
    goal = getattr(state, "goal", "") or ""
    m = re.search(r"\bdelete\s+lines?\s+(\d+)\s*[-–]\s*(\d+)\b", goal, re.IGNORECASE)
    if m:
        s, e = max(1, int(m.group(1))), int(m.group(2))
        lines = original_text.splitlines()
        if s <= len(lines):
            snippet  = "\n".join(lines[s - 1 : e])
            new_text = "\n".join(lines[: s - 1] + lines[e:]) + "\n"
            # BUG 2 FIX: detect noop
            if new_text.strip() == original_text.strip():
                return {"success": True, "file": resolved, "noop": True, "message": "Line deletion produced no change."}
            approval = {"file": resolved, "search": f"[lines {s}–{e}]\n{snippet}", "replace": ""}
            if not ask_user_approval("rewrite_function", approval):
                return {"success": False, "error": "User rejected deletion."}
            if not check_syntax(new_text, resolved):
                return {"success": False, "error": f"Syntax error after deleting lines {s}–{e}."}
            full_path.write_text(new_text, encoding="utf-8")
            return {"success": True, "file": resolved, "noop": False, "message": f"Deleted lines {s}–{e}."}

    # ── Get 4-level context hint ───────────────────────────────────────────────
    ctx_hint = ""
    try:
        from tools.repo_index import get_context_for_query
        ctx_hint = get_context_for_query(state, goal, max_chars=500)
    except Exception:
        pass

    # ── LLM prompt for SEARCH/REPLACE ────────────────────────────────────────
    prompt = f"""You are Operon's surgical code editor.

GOAL:    {goal}
FILE:    {resolved}
{('CONTEXT:\n' + ctx_hint) if ctx_hint else ''}

Produce ONLY SEARCH/REPLACE blocks. No explanation, no markdown.

Format (exact):
<<<<<<< SEARCH
[exact lines to replace or delete]
=======
[replacement lines — empty to DELETE]
>>>>>>> REPLACE

Rules:
- SEARCH must match the file exactly (whitespace-normalised).
- To delete: fill SEARCH, leave REPLACE empty.
- To append: leave SEARCH empty, put new code in REPLACE.
- Multiple blocks are allowed in sequence.
- Output NOTHING except the blocks.

FILE CONTENT:
{original_text}
"""

    try:
        raw = call_llm(prompt, require_json=False)
    except Exception as e:
        return {"success": False, "error": f"LLM error: {e}"}

    blocks = parse_search_replace(raw) if raw else []

    # Fallback: full replacement from context_buffer
    if not blocks:
        candidate = state.context_buffer.get(resolved) or state.context_buffer.get(file_path)
        if candidate and isinstance(candidate, str) and candidate.strip() != original_text.strip():
            blocks = [("", candidate)]  # empty search = append/replace entire file content
        else:
            return {
                "success": True, "file": resolved, "noop": True,
                "message": "LLM produced no SEARCH/REPLACE blocks and no candidate in buffer.",
            }

    # ── Dry-run all blocks ────────────────────────────────────────────────────
    working_text = original_text
    preview_patches: list[dict] = []
    any_change = False

    for search_block, replace_block in blocks:
        sb = (search_block or "").rstrip("\n")
        rb = (replace_block or "").rstrip("\n")

        patched, reason = apply_patch(working_text, sb, rb)

        if reason == "noop":
            continue  # this block changed nothing — skip silently

        if patched is None:
            # Last-resort: regex-normalized deletion
            if sb and not rb:
                words   = sb.split()
                pattern = r"\s+".join(re.escape(w) for w in words)
                mm      = re.search(pattern, working_text)
                if mm:
                    patched = working_text[: mm.start()] + working_text[mm.end() :]
                    reason  = "ok"

        if patched is None:
            return {
                "success": False,
                "error": (
                    f"SEARCH block not found in {resolved}. "
                    "Hint: use find_file or read_file to get the exact content first, "
                    "then match a smaller unique snippet."
                ),
            }

        if patched != working_text:
            working_text = patched
            any_change   = True
        preview_patches.append({"search": sb, "replace": rb})

    # BUG 2 FIX: hard noop check
    if not any_change or working_text.strip() == original_text.strip():
        return {
            "success": True, "file": resolved, "noop": True,
            "message": "Dry-run produced no changes — SEARCH blocks matched but replacement was identical.",
        }

    # ── Approval ──────────────────────────────────────────────────────────────
    joined_search  = "\n\n---\n\n".join(p["search"]  for p in preview_patches)
    joined_replace = "\n\n---\n\n".join(p["replace"] for p in preview_patches)
    approval_payload = {
        "file":    resolved,
        "search":  joined_search,
        "replace": joined_replace,
    }
    if not ask_user_approval("rewrite_function", approval_payload):
        return {"success": False, "error": "User rejected the change."}

    # ── Syntax check ─────────────────────────────────────────────────────────
    if not check_syntax(working_text, resolved):
        full_path.write_text(original_text, encoding="utf-8")
        return {"success": False, "error": "Syntax error after patch — file restored."}

    # ── Write ─────────────────────────────────────────────────────────────────
    try:
        full_path.write_text(working_text, encoding="utf-8")
    except Exception as e:
        try:
            full_path.write_text(original_text, encoding="utf-8")
        except Exception:
            pass
        return {"success": False, "error": f"Write failed: {e}"}

    return {"success": True, "file": resolved, "noop": False, "message": "Patch applied."}


# ─────────────────────────────────────────────────────────────────────────────
# Main agent loop
# ─────────────────────────────────────────────────────────────────────────────

def run_agent(state):
    from agent.tool_jail import validate_tool
    from agent.approval import ask_user_approval

    _ensure_fields(state)

    REJECT_THRESHOLD = getattr(state, "reject_threshold", 3)

    # ── ARCHITECT: build index + plan ────────────────────────────────────────
    if not getattr(state, "plan", None):
        state.phase    = "ARCHITECT"
        state.git_state = setup_git_env(state.repo_root)

        # Build 4-level index BEFORE planning (gives planner context)
        try:
            from tools.repo_index import build_full_index
            build_full_index(state)
        except Exception as e:
            log.warning(f"Index build failed (non-fatal): {e}")

        try:
            result = make_plan(state.goal, state.repo_root, state=state)
            state.plan           = result[0]
            state.is_question    = bool(result[1]) if len(result) > 1 else False
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

    # ── Main loop ─────────────────────────────────────────────────────────────
    while not state.done:
        if state.step_count >= MAX_STEPS:
            log.error(f"Max steps ({MAX_STEPS}) reached.")
            rollback_files(state.repo_root, state.git_state, state.files_modified)
            break

        if getattr(state, "step_cooldown", 0) > 0:
            state.step_cooldown -= 1
            state.step_count    += 1
            time.sleep(0.1)
            continue

        # ── Decide ───────────────────────────────────────────────────────────
        decision = decide_next_action(state) or {}

        thought        = decision.get("thought", "…")
        action_payload = decision.get("tool", decision) or {}
        if isinstance(action_payload, dict) and "action" not in action_payload and "tool" in action_payload:
            action_payload = action_payload["tool"]

        act = (action_payload.get("action") if isinstance(action_payload, dict) else None) or ""
        np  = _normalise(act, action_payload if isinstance(action_payload, dict) else {})
        canonical = _canonicalise({"action": act, **np})

        _register_action(state, act, canonical)

        # ── Noop / malformed guard ────────────────────────────────────────────
        if not act or act.lower() in {"noop", "error", "none", ""}:
            log.warning("LLM returned empty/noop action.")
            state.observations.append({"error": "No valid action from LLM. Try a different approach."})
            state.step_count += 1
            time.sleep(0.3)
            continue

        # ── Tool jail ─────────────────────────────────────────────────────────
        valid, msg = validate_tool(act, np, state.phase, state)
        if not valid:
            log.warning(f"Tool jail: {msg}")
            state.observations.append({"error": f"SYSTEM: {msg}"})
            state.step_count += 1
            time.sleep(0.3)
            continue

        # ── Alternating-loop detector ─────────────────────────────────────────
        if _alternating_loop(state):
            log.error("Alternating loop detected — escalating to REVIEWER.")
            state.observations.append({"error": "Loop detected. Escalating to REVIEWER."})
            state.phase       = "REVIEWER"
            state.recent_actions = []
            state.step_count += 1
            time.sleep(0.2)
            continue

        # ── Search throttle ───────────────────────────────────────────────────
        q_key = (
            np.get("query") or np.get("text") or np.get("search_term") or ""
            if act in {"semantic_search", "exact_search", "find_file"} else ""
        )
        if q_key:
            _track_search(state, q_key)
            if _throttle_search(state, q_key):
                log.warning(f"Throttling '{q_key}' → REVIEWER.")
                state.observations.append({"error": f"Too many searches for '{q_key}'. Change strategy."})
                state.phase      = "REVIEWER"
                state.step_count += 1
                time.sleep(0.2)
                continue

        # ── Exact-repeat loop breaker ─────────────────────────────────────────
        if getattr(state, "last_action_canonical", None) == canonical:
            state.loop_counter += 1
            if state.loop_counter >= 3:
                log.error("Exact loop × 3 — forcing REVIEWER.")
                state.phase             = "REVIEWER"
                state.loop_counter      = 0
                state.last_action_canonical = None
                state.observations.append({"error": "Stuck in exact repeat. Escalating."})
            else:
                state.observations.append({"error": "Repeated identical action. Do something different."})
            state.step_count += 1
            time.sleep(0.2)
            continue
        else:
            state.loop_counter          = 0
            state.last_action_payload   = np
            state.last_action_canonical = canonical

        # ── Execute ───────────────────────────────────────────────────────────
        state.step_count += 1
        log.info(f"[cyan][{state.phase}][/cyan] 🧠 {thought}")
        log.info(f"[cyan]⚙️  {act}[/cyan]")

        try:
            # ── SEARCH ACTIONS ────────────────────────────────────────────────
            if act == "semantic_search":
                query = np.get("query", "")
                hits  = search_repo(state.repo_root, query) if query else []
                obs   = f"Semantic results for '{query}': {hits}" if hits else "No semantic matches."
                state.observations.append({"search": obs})
                state.action_log.append(f"semantic_search: '{query}'")

            elif act == "exact_search":
                needle = np.get("text", "")
                hits   = []
                root   = state.repo_root
                for dirpath, _, fnames in os.walk(root):
                    if any(d in dirpath for d in (".git", "__pycache__", ".operon", "venv")):
                        continue
                    for fname in fnames:
                        fpath = os.path.join(dirpath, fname)
                        try:
                            with open(fpath, encoding="utf-8", errors="ignore") as fh:
                                if needle in fh.read():
                                    hits.append(os.path.relpath(fpath, root))
                        except Exception:
                            pass
                obs = f"Exact matches for '{needle}': {hits}" if hits else f"No exact matches for '{needle}'."
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
                    state.observations.append({"find_file": f"Found {len(found)} files:\n" + "\n".join(found[:20])})
                else:
                    state.observations.append({"find_file": f"No files matching '{term}'. Try semantic_search."})

            # ── READ ──────────────────────────────────────────────────────────
            elif act == "read_file":
                raw_path = np.get("path") or np.get("file") or ""
                if not raw_path:
                    state.observations.append({"error": "read_file requires 'path'."})
                    continue

                # BUG 1 FIX: resolve before reading
                resolved, found_flag, content = read_resolved(raw_path, state.repo_root, state)
                if not found_flag:
                    # Final attempt: check file_tree
                    matches = [f for f in state.file_tree if Path(f).name.lower() == Path(raw_path).name.lower()]
                    if matches:
                        resolved = matches[0]
                        try:
                            content   = (Path(state.repo_root) / resolved).read_text(encoding="utf-8", errors="ignore")
                            found_flag = True
                        except Exception:
                            pass

                if not found_flag:
                    state.observations.append({"error": f"File not found: '{raw_path}'. Use find_file to locate it."})
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

            # ── CREATE FILE ───────────────────────────────────────────────────
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
                    existing = full.read_text(encoding="utf-8")
                    if existing.strip() == content.strip():
                        state.observations.append({"success": f"{fp} already exists with identical content."})
                        state.phase = "REVIEWER"
                        state.context_buffer[fp] = existing
                    else:
                        state.observations.append({"error": f"{fp} already exists with different content. Use rewrite_function."})
                    continue

                full.parent.mkdir(parents=True, exist_ok=True)
                full.write_text(content, encoding="utf-8")
                log.info(f"[green]📄 Created: {fp}[/green]")

                ts = time.time()
                state.diff_memory.setdefault(fp, []).append({
                    "ts": ts, "before": "", "after": content,
                    "diff": f"--- /dev/null\n+++ {fp}\n+" + "\n+".join(content.splitlines()),
                })
                _persist_diff(state)

                state.context_buffer[fp] = content
                state.files_modified.append(fp)
                state.action_log.append(f"Created '{fp}'")
                state.observations.append({
                    "system": f"Created {fp}. REVIEWER: verify the goal is met.",
                    "file_preview": content[:1500],
                })
                state.phase = "REVIEWER"

            # ── REWRITE FUNCTION ──────────────────────────────────────────────
            elif act == "rewrite_function":
                raw_file = np.get("file") or np.get("file_path") or ""
                if not raw_file:
                    state.observations.append({"error": "rewrite_function requires 'file'."})
                    continue

                # Snapshot before
                resolved_pre, _, before_text = read_resolved(raw_file, state.repo_root, state)
                if not before_text and not (Path(state.repo_root) / raw_file).exists():
                    # Try file_tree lookup
                    matches = [f for f in state.file_tree if Path(f).name.lower() == Path(raw_file).name.lower()]
                    if matches:
                        raw_file = matches[0]

                full_before = Path(state.repo_root) / raw_file
                before_text = full_before.read_text(encoding="utf-8", errors="ignore") if full_before.exists() else ""

                result = _rewrite_function(state, raw_file)

                # ── BUG 2 FIX: explicit noop handling ────────────────────────
                if result.get("noop"):
                    state.noop_streak = getattr(state, "noop_streak", 0) + 1
                    log.warning(
                        f"[yellow]⚠️  Noop rewrite ({state.noop_streak}/{NOOP_STREAK_MAX}): "
                        f"{result.get('message', '')}[/yellow]"
                    )
                    state.observations.append({
                        "error": (
                            f"rewrite_function produced NO changes to '{raw_file}'. "
                            "Your SEARCH block did not match or the replacement was identical. "
                            "Read the file first and use an exact snippet from it."
                        )
                    })
                    state.action_log.append(f"NOOP rewrite '{raw_file}'")

                    if state.noop_streak >= NOOP_STREAK_MAX:
                        log.error("Too many noops — escalating to REVIEWER.")
                        state.phase       = "REVIEWER"
                        state.noop_streak = 0
                    continue  # Do NOT record as success, loop back

                if result.get("success"):
                    resolved_path = result.get("file", raw_file)
                    full_after    = Path(state.repo_root) / resolved_path
                    after_text    = full_after.read_text(encoding="utf-8", errors="ignore") if full_after.exists() else ""

                    ts       = time.time()
                    diff_txt = "\n".join(difflib.unified_diff(
                        before_text.splitlines(keepends=True),
                        after_text.splitlines(keepends=True),
                        fromfile=f"a/{resolved_path}",
                        tofile=f"b/{resolved_path}",
                        lineterm="",
                    ))
                    state.diff_memory.setdefault(resolved_path, []).append({
                        "ts": ts, "before": before_text, "after": after_text, "diff": diff_txt,
                    })
                    _persist_diff(state)

                    # Reset loop counters on real progress
                    state.loop_counter          = 0
                    state.noop_streak           = 0
                    state.last_action_canonical = None
                    if hasattr(state, "skip_counts"):
                        state.skip_counts.clear()

                    # Run step validator
                    if _validate_step(state, resolved_path, before_text, after_text):
                        log.info("[bold green]🎯 Validator PASSED — goal achieved.[/bold green]")
                        commit_success(state.repo_root, f"Step {state.current_step + 1}: patched {resolved_path}")
                        state.done = True
                        return state

                    # Normal REVIEWER handoff
                    if resolved_path not in state.files_modified:
                        state.files_modified.append(resolved_path)
                    state.context_buffer[resolved_path] = after_text
                    state.action_log.append(f"Patched '{resolved_path}'")
                    state.observations.append({
                        "system":       f"Coder patched {resolved_path}. REVIEWER: verify the diff.",
                        "file_preview": after_text[:1500],
                        "diff_preview": diff_txt[:2000],
                    })
                    log.info(f"[cyan]🔄 Handing off to REVIEWER...[/cyan]")
                    state.phase = "REVIEWER"

                    # Multi-file: mark this file done
                    mf_queue = getattr(state, "multi_file_queue", [])
                    mf_done  = getattr(state, "multi_file_done", [])
                    if any(item.get("file") == resolved_path for item in mf_queue):
                        if resolved_path not in mf_done:
                            mf_done.append(resolved_path)
                        state.multi_file_done = mf_done

                else:
                    err = result.get("error", "Unknown error")
                    log.error(f"Patch failed: {err}")
                    state.action_log.append(f"FAILED rewrite '{raw_file}': {err}")
                    state.observations.append({"error": err})

            # ── DELETE FILE ───────────────────────────────────────────────────
            elif act == "delete_file":
                fp = np.get("file_path") or np.get("file") or ""
                if not fp:
                    state.observations.append({"error": "delete_file requires 'file_path'."})
                    continue
                resolved, found_flag = resolve_path(fp, state.repo_root, state)
                if not found_flag:
                    state.observations.append({"error": f"Cannot delete: '{fp}' not found."})
                    continue
                full = Path(state.repo_root) / resolved
                try:
                    full.unlink()
                    state.files_modified.append(resolved)
                    state.action_log.append(f"Deleted '{resolved}'")
                    state.observations.append({"success": f"Deleted '{resolved}'."})
                except Exception as e:
                    state.observations.append({"error": f"Delete failed: {e}"})

            # ── REVIEWER ACTIONS ──────────────────────────────────────────────
            elif act == "approve_step":
                state.action_log.append(f"✅ Approved step {state.current_step + 1}")
                state.current_step += 1
                state.reject_counts = {}
                state.noop_streak   = 0
                state.step_cooldown = 1

                if state.current_step >= len(state.plan):
                    log.info("[bold green]✅ All steps done. REVIEWER should finish.[/bold green]")
                    state.observations.append({"system": "All steps complete. Use 'finish'."})
                else:
                    log.info(f"[yellow]👨‍💻 CODER: step {state.current_step + 1}[/yellow]")
                    state.phase        = "CODER"
                    state.observations = []

            elif act == "reject_step":
                feedback = np.get("feedback") or np.get("message") or "No feedback."
                key      = f"step_{state.current_step}"
                if not isinstance(state.reject_counts, dict):
                    state.reject_counts = {}
                state.reject_counts[key] = state.reject_counts.get(key, 0) + 1
                count = state.reject_counts[key]
                state.action_log.append(f"❌ Rejected step {state.current_step + 1} (×{count}): {feedback}")
                state.observations.append({"reviewer_feedback": feedback})

                if count >= REJECT_THRESHOLD:
                    log.error(f"Step rejected {count} times — aborting.")
                    rollback_files(state.repo_root, state.git_state, state.files_modified)
                    state.done = True
                    return state

                state.step_cooldown = 2
                state.phase         = "CODER"
                log.info(f"[red]👨‍💻 Back to CODER for corrections (rejection {count}/{REJECT_THRESHOLD}).[/red]")

            elif act == "finish":
                msg = np.get("message") or np.get("commit_message") or "Task complete."
                log.info(f"[bold green]✅ DONE: {msg}[/bold green]")
                commit_success(state.repo_root, msg)
                state.done = True
                break

            else:
                log.warning(f"Unhandled action: {act}")
                state.observations.append({"error": f"Unknown action '{act}'."})

        except Exception as exc:
            log.exception(f"Unhandled exception during '{act}'")
            state.observations.append({"error": f"Exception in '{act}': {exc}"})

        time.sleep(0.1)

    return state
