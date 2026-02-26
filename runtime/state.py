# runtime/state.py — Operon v2 Enhanced State
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


@dataclass
class AgentState:
    goal: str
    repo_root: str

    # ── Multi-Agent State Machine ───────────────────────────────────────────
    phase: str = "ARCHITECT"          # ARCHITECT → CODER ↔ REVIEWER
    plan: List[str] = field(default_factory=list)
    plan_validators: List[Any] = field(default_factory=list)   # per-step validator dicts
    current_step: int = 0
    is_question: bool = False

    # ── File Tracking ───────────────────────────────────────────────────────
    files_read: List[str] = field(default_factory=list)
    files_modified: List[str] = field(default_factory=list)

    # ── Action & Observation History ────────────────────────────────────────
    last_action_payload: Optional[dict] = None
    last_action_canonical: Optional[str] = None
    action_log: List[str] = field(default_factory=list)
    observations: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    recent_actions: List[Any] = field(default_factory=list)

    # ── Counters ────────────────────────────────────────────────────────────
    step_count: int = 0
    loop_counter: int = 0
    reject_counts: Any = field(default_factory=dict)   # dict keyed by "step_N"
    skip_counts: Dict[str, int] = field(default_factory=dict)
    search_counts: Dict[str, Any] = field(default_factory=dict)
    step_cooldown: int = 0
    reject_threshold: int = 3

    # ── Memory / Context ────────────────────────────────────────────────────
    context_buffer: Dict[str, str] = field(default_factory=dict)   # path → content
    diff_memory: Dict[str, Any] = field(default_factory=dict)      # path → list of patches
    git_state: Dict[str, str] = field(default_factory=dict)

    # ── 4-Level Intelligence Index ──────────────────────────────────────────
    # Level 1: semantic search hits (LanceDB)  → populated by tools/repo_search.py
    # Level 2: symbol index (functions/classes)
    symbol_index: Dict[str, Any] = field(default_factory=dict)     # path → {functions, classes}
    # Level 3: dependency graph
    dep_graph: Dict[str, List[str]] = field(default_factory=dict)  # path → [imported paths]
    # Level 4: AST extraction cache
    ast_cache: Dict[str, Any] = field(default_factory=dict)        # path → extracted symbols

    # ── Misc ────────────────────────────────────────────────────────────────
    done: bool = False
    allow_read_skip: bool = False
