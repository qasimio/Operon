from runtime.state import AgentState
from agent.loop import run_agent

if __name__ == "__main__":
    state = AgentState(
        goal="""
    Modify the `search_repo` function in `tools/repo_search.py`.
    Add a print statement `print(f"Searching for: {query}")` right above the `hits = []` array is initialized with proper indentations.
    Do not change anything else.
""",
        repo_root="/home/UserX/Master/Operon"
    )



    final_state = run_agent(state)

    print("DONE")
    print(final_state)
