# agent/decide.py — Operon v4
"""
REVIEWER is deterministic-first.
  - Reads file from DISK, not cache.
  - Checks diff_memory hash to confirm change happened before calling LLM.
  - LLM sees actual current file content for goal-satisfaction check.
CODER gets full file preview for verbatim SEARCH block copying.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from agent.llm import call_llm
from agent.logger import log


def _read_disk(state, file_path: str) -> str:
    if not file_path:
        return ""
    try:
        from tools.path_resolver import resolve_path
        resolved, found = resolve_path(file_path, state.repo_root, state)
        if found:
            return (Path(state.repo_root) / resolved).read_text(
                encoding="utf-8", errors="ignore"
            )
    except Exception:
        pass
    return ""


def _reviewer_deterministic(state) -> tuple[str, str]:
    """
    Returns (decision, detail).
    decision: "reject" | "ask_llm"
    detail:   reason string | file_path for evidence
    """
    files_modified = getattr(state, "files_modified", [])
    diff_memory    = getattr(state, "diff_memory", {})

    if not files_modified:
        return "reject", "No files have been modified yet."

    for fp in files_modified:
        if fp in diff_memory and diff_memory[fp]:
            last         = diff_memory[fp][-1]
            before_snap  = last.get("before", "")
            current      = _read_disk(state, fp)
            if current and current.strip() != before_snap.strip():
                return "ask_llm", fp
            elif current and current.strip() == before_snap.strip():
                return "reject", (
                    f"File '{fp}' is identical to its pre-modification snapshot. "
                    "The rewrite produced no net change."
                )

    # files_modified set but no diff_memory (e.g. create_file)
    return "ask_llm", files_modified[0]


def decide_next_action(state) -> dict:
    phase        = getattr(state, "phase", "CODER")
    action_log   = getattr(state, "action_log", [])
    observations = getattr(state, "observations", [])
    history      = (
        "\n".join(f"{i+1}. {e}" for i, e in enumerate(action_log[-8:]))
        if action_log else "No actions yet."
    )
    recent_obs   = "\n".join(str(o) for o in observations[-4:]) if observations else "None"
    plan_list    = getattr(state, "plan", [])
    step_idx     = getattr(state, "current_step", 0)
    step_text    = (
        plan_list[step_idx] if step_idx < len(plan_list) else "All steps complete."
    )
    loaded       = list(getattr(state, "context_buffer", {}).keys())

    # ── CODER ─────────────────────────────────────────────────────────────
    if phase == "CODER":
        tactical = ""
        if loaded:
            tactical = (
                f"🚨 FILES LOADED: {loaded}\n"
                "→ Call rewrite_function NOW. Do NOT search or read again.\n"
                "→ SEARCH block must be VERBATIM from the file preview below."
            )
        elif any(kw in history for kw in
                 ("find_file", "exact_search", "semantic_search")):
            tactical = (
                "🚨 You searched already. Call read_file on the best result.\n"
                "→ After reading, call rewrite_function immediately."
            )

        file_preview = ""
        ctx = getattr(state, "context_buffer", {})
        if ctx:
            for fp, content in list(ctx.items())[:2]:
                c = str(content) if not isinstance(content, str) else content
                file_preview += (
                    f"\n[FILE: {fp}]\n"
                    f"{c[:3000]}"
                    f"\n{'[...truncated]' if len(c) > 3000 else ''}\n"
                    f"[END: {fp}]\n"
                )

        ctx_hint = ""
        try:
            from tools.repo_index import get_context_for_query
            ctx_hint = get_context_for_query(state, state.goal, max_chars=300)
        except Exception:
            pass

        mf_hint = ""
        pending = [
            x for x in getattr(state, "multi_file_queue", [])
            if x.get("file") not in getattr(state, "multi_file_done", [])
        ]
        if pending:
            mf_hint = "PENDING FILES:\n" + "\n".join(
                f"  {x['file']}: {x.get('description','')}"
                for x in pending[:4]
            )

        prompt = f"""You are Operon's CODER. Execute the current step.

[GOAL] {state.goal}
[STEP] {step_text}
{('[CONTEXT]\n' + ctx_hint) if ctx_hint else ''}
{file_preview}
{mf_hint}
[ACTIONS SO FAR]
{history}
[OBSERVATIONS]
{recent_obs}
{tactical}

TOOLS:
1. {{"action":"find_file",        "search_term":"filename"}}
2. {{"action":"read_file",        "path":"exact/path.ext"}}
3. {{"action":"exact_search",     "text":"exact token"}}
4. {{"action":"semantic_search",  "query":"description"}}
5. {{"action":"rewrite_function", "file":"exact/path.ext"}}
6. {{"action":"create_file",      "file_path":"new/file.ext", "initial_content":"..."}}

RULES: 3 steps max: find→read→rewrite. If file preview shown: rewrite NOW.
SEARCH must be VERBATIM from file preview.

Output STRICT JSON: {{"thought":"...","tool":{{"action":"...",...}}}}"""

    # ── REVIEWER ──────────────────────────────────────────────────────────
    else:
        det_decision, det_detail = _reviewer_deterministic(state)

        if det_decision == "reject":
            log.debug(f"REVIEWER det-REJECT: {det_detail}")
            return {
                "thought": f"Deterministic: {det_detail}",
                "tool": {"action": "reject_step", "feedback": det_detail},
            }

        # Confirmed change — read file from disk for LLM
        evidence_fp      = det_detail
        current_content  = _read_disk(state, evidence_fp)
        diff_memory      = getattr(state, "diff_memory", {})
        diff_evidence    = ""
        if evidence_fp in diff_memory and diff_memory[evidence_fp]:
            diff_evidence = diff_memory[evidence_fp][-1].get("diff", "")[:1000]

        files_modified  = getattr(state, "files_modified", [])
        step_count_all  = len(plan_list)
        at_last         = step_idx >= step_count_all - 1

        prompt = f"""You are Operon's CODE REVIEWER. A change was confirmed on disk.

[GOAL] {state.goal}
[STEP {step_idx+1}/{step_count_all}] {step_text}
[FILES MODIFIED] {files_modified}

[CURRENT FILE ON DISK: {evidence_fp}]
{current_content[:3000] if current_content else '(unreadable)'}
{'[...truncated]' if len(current_content or '') > 3000 else ''}

[DIFF]
{diff_evidence or '(no diff)'}

[RECENT ACTIONS]
{history}
[OBSERVATIONS]
{recent_obs}

RULES:
- A change HAS occurred (system confirmed). Judge if it satisfies the milestone.
- Be GENEROUS: meaningful progress = approve.
- {"Use 'finish' — this is the LAST step." if at_last else "Use 'approve_step'. Do NOT finish yet."}
- Judge ONLY from file content above.

TOOLS:
1. {{"action":"approve_step",  "message":"why"}}
2. {{"action":"reject_step",   "feedback":"what to fix"}}
3. {{"action":"finish",        "commit_message":"summary"}}

Output STRICT JSON: {{"thought":"...","tool":{{"action":"...",...}}}}"""

    log.debug(f"Calling LLM for {phase}...")
    raw   = call_llm(prompt, require_json=False)
    clean = re.sub(r"```(?:json)?\s*(.*?)\s*```", r"\1", raw, flags=re.DOTALL).strip()

    data = None
    try:
        data = json.loads(clean)
    except Exception:
        m = re.search(r"(\{(?:.|\n)*?\})", clean)
        if m:
            try:
                data = json.loads(m.group(1))
            except Exception:
                pass

    if not isinstance(data, dict):
        log.error(f"JSON parse error ({phase}): {raw[:200]}")
        if phase == "REVIEWER":
            return {
                "thought": "Parse error — safe reject.",
                "tool": {
                    "action":   "reject_step",
                    "feedback": "LLM JSON parse failed. Coder: re-attempt.",
                },
            }
        return {"thought": "JSON failed", "tool": {"action": "error"}}

    if "tool" not in data and "action" in data:
        return {"thought": data.get("thought", ""), "tool": data}
    if "tool" not in data:
        if any(k in data for k in ("action", "file", "path", "query", "text")):
            return {"thought": data.get("thought", ""), "tool": data}
    return data
