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
    observations: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    
    step_count:int = 0
    done: bool = False



"""
Create a notebook for an AI worker that tracks its mission, the folder it's working in, the steps it plans, 
the files it touched, what happened, mistakes, how many moves it made, and whether it's finished.
"""