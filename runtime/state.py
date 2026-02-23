from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

@dataclass
class AgentState:
    goal: str
    repo_root: str

    # The Multi-Agent State Machine
    phase: str = "ARCHITECT" # ARCHITECT, CODER, REVIEWER
    plan: List[str] = field(default_factory=list)
    current_step: int = 0
    is_question: bool = False

    files_read: List[str] = field(default_factory=list)
    files_modified: List[str] = field(default_factory=list)

    last_action_payload: Optional[dict] = None
    action_log: List[str] = field(default_factory=list)
    observations: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    step_count: int = 0
    done: bool = False