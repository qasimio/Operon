from runtime.state import AgentState
from agent.loop import run_agent

if __name__ == "__main__":
    state = AgentState(
        goal='append "from tools.repo_brain import build_repo_brain' + 
'from agent.llm import call_llm' + 
'build_repo_brain("/home/UserX/Master/LSEEA/", call_llm)" to logs/test.py',

        repo_root="/home/UserX/Master/LSEEA"
    )

    final_state = run_agent(state)

    print("DONE")
    print(final_state)