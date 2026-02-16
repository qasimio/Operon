from runtime.state import AgentState
from agent.loop import run_agent

if __name__ == "__main__":
    state = AgentState(
        goal="""Overwrite the following code EXACTLY as written (keep structure unchanged) 
to the end of file logs/test.py:

from tools.repo_brain import build_repo_brain
from agent.llm import call_llm

build_repo_brain("/home/UserX/Master/LSEEA/", call_llm)

# write summary of tools/repo_brain.py as a comment in

# this comment is added by L-SEEA from MQ
""",
        repo_root="/home/UserX/Master/LSEEA"
    )

    final_state = run_agent(state)

    print("DONE")
    print(final_state)
