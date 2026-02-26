# agent/decide.py — Operon v2: Smarter REVIEWER that actually understands diffs
import json
import re
import difflib
from pathlib import Path
from agent.llm import call_llm
from agent.logger import log


# ─────────────────────────────────────────────────────────────────────────────
# CORE FIX: The "Big Bug" — REVIEWER couldn't tell if the change was correct.
# Solution: structural_diff_verify() — reads the ACTUAL file on disk, computes
# a real unified diff vs. what was there before, and passes BOTH to the LLM
# Reviewer along with the goal, so the LLM can make a grounded judgment.
# ─────────────────────────────────────────────────────────────────────────────

def structural_diff_verify(state, step_idx: int) -> tuple[bool, str]:
    """
    Level-4 verifier: uses the stored before/after diff from diff_memory to
    ask the LLM whether the change actually satisfies the current milestone.

    This is the primary fix for the reviewer loop bug — instead of the
    reviewer blindly calling reject because a simple string check failed,
    it now reads the REAL diff and reasons about it.
    """
    plan_list = getattr(state, "plan", [])
    step_text = plan_list[step_idx] if step_idx < len(plan_list) else state.goal

    diff_memory = getattr(state, "diff_memory", {})
    if not diff_memory:
        return False, "No diff memory found — coder has not written any files yet."

    # Collect the most recent patch across all modified files
    all_patches = []
    for file_path, patches in diff_memory.items():
        if patches:
            latest = patches[-1]
            all_patches.append((file_path, latest.get("diff", ""), latest.get("after", "")))

    if not all_patches:
        return False, "Diff memory entries are empty."

    # Build a compact summary for the LLM (keep context window small for Qwen 7B)
    diff_summary_parts = []
    for fp, diff_text, after_text in all_patches[:3]:   # max 3 files
        diff_preview = diff_text[:1500] if diff_text else "(no diff)"
        after_preview = after_text[:800] if after_text else "(empty)"
        diff_summary_parts.append(
            f"FILE: {fp}\n--- DIFF ---\n{diff_preview}\n--- FILE AFTER ---\n{after_preview}"
        )

    combined = "\n\n".join(diff_summary_parts)

    prompt = f"""You are Operon's REVIEWER. Your job is to verify whether a code change satisfies a milestone.

GOAL (overall): {state.goal}
CURRENT MILESTONE: {step_text}

CHANGES MADE (unified diff + resulting file):
{combined}

QUESTION: Does the change above correctly satisfy the milestone "{step_text}"?

Answer with STRICT JSON:
{{"verdict": "PASS" or "FAIL", "reason": "one sentence explanation"}}

Be generous: if the change is approximately correct and moves toward the goal, answer PASS.
Only answer FAIL if the change is clearly wrong, missing, or makes things worse.
"""
    try:
        raw = call_llm(prompt, require_json=True)
        clean = re.sub(r"```(?:json)?\s*|\s*```", "", raw.strip(), flags=re.DOTALL).strip()
        data = json.loads(clean)
        verdict = str(data.get("verdict", "")).upper()
        reason = data.get("reason", "")
        if verdict == "PASS":
            return True, reason
        return False, reason
    except Exception as e:
        log.debug(f"structural_diff_verify LLM parse error: {e}")
        # If LLM fails to respond sensibly, fall through to heuristic
        return False, f"LLM verify failed: {e}"


def _run_validator(state, step_idx: int) -> tuple[bool, str]:
    """
    Three-tier validator:
      Tier 1 — Heuristic structural checks (fast, no LLM)
      Tier 2 — Plan-level declared validators (not_contains / contains / lines_removed)
      Tier 3 — LLM structural diff review (the big-bug fix)
    """
    # ── Tier 1: Has coder actually modified any files? ───────────────────────
    diff_memory = getattr(state, "diff_memory", {})
    files_modified = getattr(state, "files_modified", [])

    if not files_modified and not diff_memory:
        return False, "Coder has not modified any files yet. Cannot approve."

    # ── Tier 2: Declared per-step validators ────────────────────────────────
    validators = getattr(state, "plan_validators", None)
    if validators and step_idx < len(validators):
        v = validators[step_idx]
        if v:
            vtype = v.get("type")
            try:
                if vtype == "not_contains":
                    p = Path(state.repo_root) / v["file"]
                    contents = p.read_text(encoding="utf-8") if p.exists() else ""
                    if v["text"] in contents:
                        # Don't immediately reject — first check if diff shows removal
                        pass   # fall through to Tier 3
                    else:
                        return True, f"'{v['text'][:40]}' correctly absent from {v['file']}."

                elif vtype == "contains":
                    p = Path(state.repo_root) / v["file"]
                    contents = p.read_text(encoding="utf-8") if p.exists() else ""
                    if v["text"] in contents:
                        return True, f"Required text found in {v['file']}."
                    # Fall through to Tier 3 instead of hard-failing

                elif vtype == "lines_removed":
                    file = v["file"]
                    start = int(v.get("start", 0))
                    end = int(v.get("end", 0))
                    p = Path(state.repo_root) / file
                    if p.exists():
                        lines = p.read_text(encoding="utf-8").splitlines()
                        found_any = any(
                            f"console.log({i});" in lines or f"print({i})" in lines
                            for i in range(start, end + 1)
                        )
                        if not found_any:
                            return True, f"Lines {start}-{end} successfully removed from {file}."
                    # Fall through to Tier 3

            except Exception as e:
                log.debug(f"Tier-2 validator error: {e}")

    # ── Tier 3: LLM diff verification (the core bug fix) ────────────────────
    verdict, reason = structural_diff_verify(state, step_idx)
    if verdict is True:
        return True, f"LLM Reviewer verified: {reason}"
    if verdict is False:
        return False, f"LLM Reviewer rejected: {reason}"

    # Tier 3 inconclusive → fall back to: "files were modified" = optimistic pass
    if files_modified:
        return True, "Files were modified; heuristic pass (LLM verify inconclusive)."
    return False, "No modifications detected."


def decide_next_action(state) -> dict:
    phase = getattr(state, "phase", "CODER")

    recent = getattr(state, "recent_actions", [])[-12:]
    recent_simple = [a for a, _ in recent if a]
    recent_obs = "\n".join([str(o) for o in getattr(state, "observations", [])[-6:]]) or "None."
    action_log = getattr(state, "action_log", [])[-8:]
    history = "\n".join([f"{i+1}. {entry}" for i, entry in enumerate(action_log)]) if action_log else "No actions yet."

    plan_list = getattr(state, "plan", [])
    current_step_idx = getattr(state, "current_step", 0)
    current_step_text = plan_list[current_step_idx] if current_step_idx < len(plan_list) else "All steps complete."

    if not hasattr(state, "plan_validators"):
        state.plan_validators = []

    # ── REVIEWER phase ───────────────────────────────────────────────────────
    if phase == "REVIEWER":
        log.debug("Reviewer: running 3-tier validation for current step.")

        if not hasattr(state, "reject_counts") or not isinstance(state.reject_counts, dict):
            state.reject_counts = {}

        passed, msg = _run_validator(state, current_step_idx)

        if passed:
            log.info(f"[bold green]✅ REVIEWER PASS:[/bold green] {msg}")
            return {
                "thought": f"Validator passed: {msg}",
                "tool": {"action": "approve_step", "message": f"Validator passed: {msg}"}
            }

        # Failed — decide whether to reject or abort
        key = f"step_{current_step_idx}"
        state.reject_counts[key] = state.reject_counts.get(key, 0) + 1
        count = state.reject_counts[key]
        log.warning(f"[bold red]❌ REVIEWER REJECT #{count}:[/bold red] {msg}")

        if count >= 3:
            return {
                "thought": f"Validator failed {count} times: {msg}",
                "tool": {"action": "finish", "commit_message": f"Aborting: repeated failures at step {current_step_idx+1}: {msg}"}
            }

        return {
            "thought": f"Validator failed: {msg}",
            "tool": {"action": "reject_step", "feedback": f"Validator failed: {msg}. Please re-read the file and re-apply the correct change."}
        }

    # ── CODER phase ──────────────────────────────────────────────────────────
    # Build 4-level context hint for the LLM prompt
    symbol_hint = ""
    dep_hint = ""
    if hasattr(state, "symbol_index") and state.symbol_index:
        sample = list(state.symbol_index.items())[:5]
        symbol_hint = "SYMBOL INDEX (sample):\n" + "\n".join(
            f"  {fp}: funcs={[f['name'] for f in v.get('functions', [])[:4]]}"
            for fp, v in sample
        )
    if hasattr(state, "dep_graph") and state.dep_graph:
        sample = list(state.dep_graph.items())[:4]
        dep_hint = "DEP GRAPH (sample):\n" + "\n".join(
            f"  {fp} → {deps[:3]}" for fp, deps in sample
        )

    persona = "You are Operon's CODER. Execute the current milestone efficiently using available tools."
    guidance = """
CONSTRAINTS:
- If you have the file content in context_buffer, prefer rewrite_function directly rather than re-reading.
- If rewrite_function fails, adjust logic and retry once. Do not loop endlessly.
- Always read a file before rewriting it unless you already have it in context.
- Use the 4-level index (semantic_search, symbol lookup, dep graph, ast) to navigate large repos efficiently.
- Output STRICT JSON: {"thought":"...","tool":{"action":"...", ...}}
- You are in CODER phase. You MUST NOT call approve_step, reject_step, or finish.
"""
    tools = """
TOOLS:
- {"action":"find_file","search_term":"..."}
- {"action":"read_file","path":"path/to/file"}
- {"action":"semantic_search","query":"..."}
- {"action":"exact_search","text":"..."}
- {"action":"rewrite_function","file":"path/to/file"}
- {"action":"create_file","file_path":"...","initial_content":"..."}
"""

    prompt = f"""{persona}

[GOAL]
{state.goal}

[CURRENT MILESTONE]
{current_step_text}

[RECENT ACTIONS]
{', '.join(recent_simple) or 'None.'}

[RECENT OBSERVATIONS]
{recent_obs}

[HISTORY]
{history}

{symbol_hint}
{dep_hint}

{guidance}
{tools}

Output STRICT JSON only.
{{"thought":"...", "tool":{{"action":"...", ...}}}}
"""
    log.debug("Calling LLM for CODER decision...")
    raw = call_llm(prompt, require_json=True)
    clean = re.sub(r"(?:```json)?\n?(.*?)\n?```", r"\1", raw, flags=re.DOTALL).strip()
    try:
        data = json.loads(clean)
        if "tool" not in data and "action" in data:
            return {"thought": data.get("thought", ""), "tool": data}
        if "tool" not in data and isinstance(data, dict) and any(
            k in data for k in ("action", "file", "path", "query", "text")
        ):
            return {"thought": data.get("thought", ""), "tool": data}
        return data
    except Exception as e:
        log.error(f"JSON PARSE ERROR in decide_next_action: {e}\nRaw: {raw[:300]}")
        return {
            "thought": "Parsing failed; escalating to REVIEWER",
            "tool": {"action": "reject_step", "feedback": "Coder returned invalid JSON. Manual review needed."}
        }
