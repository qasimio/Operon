from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

@dataclass
class AgentState:
    goal: str
    repo_root: str

    plan: List[str] = field(default_factory=list)

    files_read: List[str] = field(default_factory=list)
    files_modified: List[str] = field(default_factory=list)

    last_action: Optional[str] = None
    action_log: List[str] = field(default_factory=list)  # Added: Critical for episodic memory in decide.py
    observations: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    step_count: int = 0
    done: bool = False