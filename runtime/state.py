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