from runtime.state import AgentState
from agent.loop import run_agent

if __name__ == "__main__":
    state = AgentState(
        goal="""
Modify the write_file function in tools/fs_tools.py so that:

Add print("HELLO") inside write_file function
- Do NOT change existing functionality.
""",
        repo_root="/home/UserX/Master/Operon"
    )



    final_state = run_agent(state)

    print("DONE")
    print(final_state)
