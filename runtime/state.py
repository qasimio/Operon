# runtime/state.py — Operon v5
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


@dataclass
class AgentState:
    goal: str
    repo_root: str

    # ── Phase machine ─────────────────────────────────────────────────────────
    phase: str = "ARCHITECT"   # ARCHITECT → CODER ↔ REVIEWER

    # ── Plan ──────────────────────────────────────────────────────────────────
    plan: List[str] = field(default_factory=list)
    plan_validators: List[Any] = field(default_factory=list)
    current_step: int = 0
    is_question: bool = False

    # ── File tracking ─────────────────────────────────────────────────────────
    files_read: List[str] = field(default_factory=list)
    files_modified: List[str] = field(default_factory=list)

    # ── History ───────────────────────────────────────────────────────────────
    last_action_payload: Optional[dict] = None
    last_action_canonical: Optional[str] = None
    action_log: List[str] = field(default_factory=list)
    observations: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    recent_actions: List[Any] = field(default_factory=list)

    # ── Counters ──────────────────────────────────────────────────────────────
    step_count: int = 0
    loop_counter: int = 0
    reject_counts: Dict[str, int] = field(default_factory=dict)
    skip_counts: Dict[str, int] = field(default_factory=dict)
    search_counts: Dict[str, Any] = field(default_factory=dict)
    step_cooldown: int = 0
    reject_threshold: int = 3
    noop_streak: int = 0

    # ── Memory / context ─────────────────────────────────────────────────────
    context_buffer: Dict[str, str] = field(default_factory=dict)
    diff_memory: Dict[str, List[Dict]] = field(default_factory=dict)
    git_state: Dict[str, str] = field(default_factory=dict)

    # ── 4-Level intelligence index ────────────────────────────────────────────
    # L1 lives in LanceDB (semantic_memory.py) — not stored here
    # L2: symbol index  { rel_path: {functions:[...], classes:[...], ...} }
    symbol_index: Dict[str, Any] = field(default_factory=dict)
    # L3: forward dep graph  { rel_path: [imported_rel_paths] }
    dep_graph: Dict[str, List[str]] = field(default_factory=dict)
    # L3b: reverse dep  { rel_path: [files_that_import_it] }
    rev_dep: Dict[str, List[str]] = field(default_factory=dict)
    # file tree cache
    file_tree: List[str] = field(default_factory=list)

    # ── v5: Full symbol graph (from symbol_graph.py) ─────────────────────────
    # Full graph including cross-refs — built once at startup
    symbol_graph_full: Optional[Dict] = None

    # ── Multi-file work queue ─────────────────────────────────────────────────
    multi_file_queue: List[Dict] = field(default_factory=list)
    multi_file_done: List[str] = field(default_factory=list)

    # ── Misc ──────────────────────────────────────────────────────────────────
    done: bool = False
    allow_read_skip: bool = False
