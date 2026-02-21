from runtime.state import AgentState
from agent.loop import run_agent
from agent.logger import log

if __name__ == "__main__":
    state = AgentState(
        goal="""
Goal 1: "In agent/logger.py, add the word 'BROKEN' exactly to the end of line 8 without using any quotes or comments.(it should not be inside any pre-existing line)"
after finishing
Goal 2: Inside "repo.py" add comment # Chill, Operon can handle multiple tasks ;) in the end of file.
""",
        repo_root="/home/UserX/Master/Operon"
    )

    # Add a massive visual separator in the log file
    log.info("\n" + "="*50)
    log.info(f"🚀 STARTING NEW OPERON SESSION")
    log.info("="*50)
    log.info(f"Goal: {state.goal}")

    final_state = run_agent(state)

    log.info(f"Session finished in {final_state.step_count} steps.")
    print("DONE")
