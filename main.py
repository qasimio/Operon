from runtime.state import AgentState
from agent.loop import run_agent

if __name__ == "__main__":
    state = AgentState(
        goal=input("Enter clear task with proper goal: "),
        repo_root="/home/UserX/Master/LSEEA"
    )

    final_state = run_agent(state)

    print("DONE")
    print(final_state)