from runtime.state import AgentState
from agent.loop import run_agent
from agent.logger import log

if __name__ == "__main__":
    state = AgentState(
        goal="""
Modify the `search_repo` function in `tools/repo_search.py`.
Add a print statement `print(f"Searching for: {query}")`
right above the `hits = []` array is initialized with proper indentations.
Do not change anything else.
""",
        repo_root="/home/UserX/Master/Operon"
    )

    log.info(f"Starting Operon session with goal: {state.goal}")

    final_state = run_agent(state)

    log.info(f"Session finished in {final_state.step_count} steps.")

    print("DONE")
    print(final_state)