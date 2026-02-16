from runtime.state import AgentState
from agent.loop import run_agent

if __name__ == "__main__":
    state = AgentState(
        goal='append "# this comment is added by L-SEEA on the order of MQ" to build_brain.py',

        repo_root="/home/UserX/Master/LSEEA"
    )

    final_state = run_agent(state)

    print("DONE")
    print(final_state)