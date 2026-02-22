from runtime.state import AgentState
from agent.loop import run_agent
from agent.logger import log

if __name__ == "__main__":
    state = AgentState(
        goal="""
File: agent/repo.py
Function: build_repo_summary
Goal: Commment explanation of this build_repo_summary in Plain English above same function.
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
