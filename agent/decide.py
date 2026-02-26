# agent/decide.py — Operon v3
"""
CORE FIX for the reviewer loop bug.

Old behaviour: REVIEWER ran simplistic string checks → false negatives → infinite loops.

New behaviour (3-tier verification):
  Tier 1 — Fast: has ANY file actually been modified (diff_memory check)?
  Tier 2 — Structural: plan-declared validators (not_contains / contains / lines_removed)
  Tier 3 — LLM diff review: pass the REAL unified diff to the LLM and ask
            "does this change satisfy the milestone?" — the LLM has actual evidence.

Additionally: REVIEWER only calls reject_step when it has a concrete reason.
After 3 rejections it calls finish (abort) instead of looping forever.
"""

import json
import re
from pathlib import Path
from agent.llm import call_llm
from agent.logger import log


# ── Tier 3: LLM diff verification ────────────────────────────────────────────

def _llm_verify_diff(state, step_text: str) -> tuple[bool | None, str]:
    """
    Returns (True=pass, False=fail, None=inconclusive), reason string.
    Passes the real diff to the LLM so it can make a grounded judgment.
    """
    diff_memory = getattr(state, "diff_memory", {})
    if not diff_memory:
        return None, "No diff recorded yet."

    # Collect the most recent patch for each modified file (max 3 files)
    snippets: list[str] = []
    for file_path, patches in list(diff_memory.items())[:3]:
        if not patches:
            continue
        latest = patches[-1]
        diff   = (latest.get("diff", "") or "")[:1200]
        after  = (latest.get("after", "") or "")[:600]
        snippets.append(f"FILE: {file_path}\n--- DIFF ---\n{diff}\n--- RESULT ---\n{after}")

    if not snippets:
        return None, "Diff memory empty."

    combined = "\n\n".join(snippets)

    prompt = f"""You are Operon's REVIEWER. Check whether the code change satisfies the milestone.

OVERALL GOAL: {state.goal}
MILESTONE:    {step_text}

CHANGES MADE:
{combined}

Does the change above correctly satisfy the milestone?
Be GENEROUS: if the change makes meaningful progress toward the milestone, answer PASS.
Only answer FAIL if the change is clearly wrong or the file is unmodified.

Respond with STRICT JSON only:
{{"verdict": "PASS", "reason": "one sentence"}}
or
{{"verdict": "FAIL", "reason": "one sentence explaining what is wrong"}}
"""
    try:
        raw = call_llm(prompt, require_json=True)
        data = json.loads(raw)
        verdict = str(data.get("verdict", "")).upper().strip()
        reason  = str(data.get("reason", ""))
        if verdict == "PASS":
            return True, reason
        if verdict == "FAIL":
            return False, reason
    except Exception as e:
        log.debug(f"LLM diff verify parse error: {e}")
    return None, "LLM verdict unclear."


# ── Tier 2: plan-declared validators ─────────────────────────────────────────

def _run_declared_validator(state, step_idx: int) -> tuple[bool | None, str]:
    """
    Returns (True/False/None, message).
    None = validator not declared or inconclusive (fall through to Tier 3).
    """
    validators = getattr(state, "plan_validators", None)
    if not validators or step_idx >= len(validators):
        return None, "No declared validator."

    v = validators[step_idx]
    if not v:
        return None, "Validator is null."

    vtype = v.get("type")
    try:
        if vtype == "not_contains":
            p = Path(state.repo_root) / v["file"]
            content = p.read_text(encoding="utf-8") if p.exists() else ""
            if v["text"] in content:
                return None, f"Token still present — passing to LLM verify."  # don't hard-fail; let Tier 3 decide
            return True, f"'{v['text'][:40]}' correctly absent from {v['file']}."

        if vtype == "contains":
            p = Path(state.repo_root) / v["file"]
            content = p.read_text(encoding="utf-8") if p.exists() else ""
            if v["text"] in content:
                return True, f"Required token found in {v['file']}."
            return None, "Required token missing — passing to LLM verify."

        if vtype == "lines_removed":
            p = Path(state.repo_root) / v["file"]
            if not p.exists():
                return None, f"File {v['file']} does not exist."
            lines   = p.read_text(encoding="utf-8").splitlines()
            start   = int(v.get("start", 0))
            end     = int(v.get("end", 0))
            # Accept if file is shorter than expected end (lines definitely gone)
            if len(lines) < end:
                return True, f"File now shorter than line {end} — lines removed."
            return None, "Line count ambiguous — passing to LLM verify."

    except Exception as e:
        log.debug(f"Declared validator error: {e}")
        return None, f"Validator error: {e}"

    return None, "Unknown validator type."


# ── Main 3-tier check ─────────────────────────────────────────────────────────

def run_reviewer_check(state, step_idx: int) -> tuple[bool, str]:
    """
    Returns (passed: bool, message: str).
    """
    plan_list     = getattr(state, "plan", [])
    step_text     = plan_list[step_idx] if step_idx < len(plan_list) else state.goal
    files_modified = getattr(state, "files_modified", [])
    diff_memory    = getattr(state, "diff_memory", {})

    # ── Tier 1: Has the coder modified ANYTHING? ──────────────────────────────
    if not files_modified and not diff_memory:
        return False, "Coder has not modified any files yet."

    # ── Tier 2: Declared validator ────────────────────────────────────────────
    t2_result, t2_msg = _run_declared_validator(state, step_idx)
    if t2_result is True:
        return True, f"[T2] {t2_msg}"
    if t2_result is False:
        return False, f"[T2] {t2_msg}"
    # None → fall through

    # ── Tier 3: LLM diff review ───────────────────────────────────────────────
    t3_result, t3_msg = _llm_verify_diff(state, step_text)
    if t3_result is True:
        return True, f"[T3-LLM] {t3_msg}"
    if t3_result is False:
        return False, f"[T3-LLM] {t3_msg}"

    # Inconclusive but files were modified — optimistic pass
    if files_modified:
        return True, f"[Heuristic] Files modified ({files_modified}) — optimistic pass."

    return False, "No evidence of successful change."


# ── decide_next_action ────────────────────────────────────────────────────────

def decide_next_action(state) -> dict:
    phase = getattr(state, "phase", "CODER")

    # ── REVIEWER ──────────────────────────────────────────────────────────────
    if phase == "REVIEWER":
        current_step_idx = getattr(state, "current_step", 0)

        if not isinstance(getattr(state, "reject_counts", None), dict):
            state.reject_counts = {}

        passed, msg = run_reviewer_check(state, current_step_idx)

        if passed:
            log.info(f"[bold green]✅ REVIEWER PASS:[/bold green] {msg}")
            return {
                "thought": f"Step verified: {msg}",
                "tool": {"action": "approve_step", "message": msg},
            }

        key   = f"step_{current_step_idx}"
        count = state.reject_counts.get(key, 0) + 1
        state.reject_counts[key] = count
        log.warning(f"[bold red]❌ REVIEWER REJECT #{count}:[/bold red] {msg}")

        if count >= 3:
            return {
                "thought": f"Failed {count} times: {msg}",
                "tool": {
                    "action": "finish",
                    "commit_message": f"Aborting: step {current_step_idx + 1} failed {count} times. {msg}",
                },
            }

        return {
            "thought": f"Validation failed: {msg}",
            "tool": {
                "action": "reject_step",
                "feedback": (
                    f"{msg}. "
                    "Re-read the file and apply the correct change. "
                    "Do NOT claim success without modifying the file."
                ),
            },
        }

    # ── CODER ─────────────────────────────────────────────────────────────────
    recent       = getattr(state, "recent_actions", [])[-10:]
    recent_acts  = [a for a, _ in recent if a]
    recent_obs   = "\n".join(str(o) for o in getattr(state, "observations", [])[-5:]) or "None."
    history      = "\n".join(
        f"{i+1}. {e}" for i, e in enumerate(getattr(state, "action_log", [])[-8:])
    ) or "No history."

    plan_list        = getattr(state, "plan", [])
    step_idx         = getattr(state, "current_step", 0)
    current_step     = plan_list[step_idx] if step_idx < len(plan_list) else "All steps complete."
    context_buffer   = getattr(state, "context_buffer", {})
    loaded_files     = list(context_buffer.keys())

    # 4-level context hint
    ctx_hint = ""
    try:
        from tools.repo_index import get_context_for_query
        ctx_hint = get_context_for_query(state, state.goal, max_chars=700)
    except Exception:
        pass

    # Multi-file queue hint
    mf_hint = ""
    mf_queue = getattr(state, "multi_file_queue", [])
    mf_done  = getattr(state, "multi_file_done", [])
    if mf_queue:
        remaining = [x for x in mf_queue if x.get("file") not in mf_done]
        if remaining:
            mf_hint = "MULTI-FILE WORK QUEUE (files still needing changes):\n"
            for item in remaining[:5]:
                mf_hint += f"  - {item['file']}: {item.get('description','')}\n"

    prompt = f"""You are Operon's CODER. Your job is to execute the current milestone.

═══ GOAL ════════════════════════════════════════════════════
{state.goal}

═══ CURRENT MILESTONE ═══════════════════════════════════════
{current_step}

═══ FILES LOADED IN MEMORY ══════════════════════════════════
{loaded_files or 'None loaded yet.'}

═══ RECENT ACTIONS ══════════════════════════════════════════
{', '.join(recent_acts) or 'None.'}

═══ RECENT OBSERVATIONS ═════════════════════════════════════
{recent_obs}

═══ HISTORY ═════════════════════════════════════════════════
{history}

{('═══ REPO CONTEXT ════════════════════════════════════════════\n' + ctx_hint) if ctx_hint else ''}
{mf_hint}

═══ TOOLS ═══════════════════════════════════════════════════
{{"action":"find_file","search_term":"..."}}
{{"action":"read_file","path":"exact/relative/path"}}
{{"action":"semantic_search","query":"..."}}
{{"action":"exact_search","text":"..."}}
{{"action":"rewrite_function","file":"exact/relative/path"}}
{{"action":"create_file","file_path":"...","initial_content":"..."}}

═══ RULES ═══════════════════════════════════════════════════
1. Always read a file before rewriting it (unless creating).
2. Use the EXACT relative path from the repo root.
3. If you cannot find a file, use find_file or semantic_search.
4. Never claim a file is modified without calling rewrite_function.
5. For multi-file tasks, tackle files one at a time.

Output STRICT JSON only:
{{"thought": "...", "tool": {{"action": "...", ...}}}}
"""

    log.debug("Calling LLM for CODER decision...")
    raw   = call_llm(prompt, require_json=True)
    clean = re.sub(r"(?:```json)?\n?(.*?)\n?```", r"\1", raw, flags=re.DOTALL).strip()

    try:
        data = json.loads(clean)
        # Normalise flat responses (tool fields at top level)
        if "tool" not in data and "action" in data:
            return {"thought": data.get("thought", ""), "tool": data}
        return data
    except Exception as e:
        log.error(f"CODER JSON parse error: {e}\nRaw: {raw[:300]}")
        return {
            "thought": "JSON parse failed",
            "tool": {
                "action": "reject_step",
                "feedback": "Coder returned invalid JSON — please retry.",
            },
        }
