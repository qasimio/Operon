from runtime.state import AgentState
from agent.loop import run_agent

if __name__ == "__main__":
    state = AgentState(
        goal="""
Modify the write_file function in tools/fs_tools.py so that:

1. It logs every write operation to logs/operon.log
2. Each log should contain:
   - timestamp
   - filename
   - mode
3. Do NOT change existing functionality.
""",
        repo_root="/home/UserX/Master/Operon"
    )



    final_state = run_agent(state)

    print("DONE")
    print(final_state)
