from runtime.state import AgentState
from agent.loop import run_agent

if __name__ == "__main__":
    state = AgentState(
        goal= "add print(""Hellow MQ"") description in readme.md",
        repo_root="/home/UserX/Master/LSEEA"
    )

    final_state = run_agent(state)

    print("DONE")
    print(final_state)