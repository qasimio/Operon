from runtime.state import AgentState
from agent.loop import run_agent
from agent.logger import log

if __name__ == "__main__":
    state = AgentState(
        goal="""
File: agent/decide.py
Action: In decide_next_action, update your CRITICAL RULES FOR SELF-HEALING section to look exactly like this:
CRITICAL RULES FOR BEHAVIOR:
- If a search returns "No matches found", DO NOT repeat the exact same search. Try a single, unique keyword (e.g., "8080" or "port").
- If you just successfully used "rewrite_function" to edit a file, DO NOT edit it again immediately! Your next action MUST be "run_tests" to verify it, or "stop" if tests are not needed.
- If your "Recent Observations" show that tests FAILED or a command crashed, you MUST look at the stderr/traceback, identify the file and function that caused the error, and use "rewrite_function" to fix your mistake!
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

        # Find where the LLM server URL or port (8080) is defined. 
        # Change the port from 8080 to 9090.
        # Do not change anything else.