from runtime.state import AgentState
from agent.loop import run_agent
from agent.logger import log

if __name__ == "__main__":
    state = AgentState(

    goal="""
    Modify 'search_repo' function in repo_search:
    change the hit from :5 to :10 in return
    Do not change anything else.
""",

        repo_root="/home/UserX/Master/Operon"
    )

    log.info(f"Starting Operon session with goal: {state.goal}")

    final_state = run_agent(state)

    log.info(f"Session finished in {final_state.step_count} steps.")

    print("DONE")
    print(final_state)