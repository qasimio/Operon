from runtime.state import AgentState
from agent.loop import run_agent
from agent.logger import log

if __name__ == "__main__":

    state = AgentState(
        goal="""
        Action: Inside smart_commit_pipeline, find the commit line (_run(["git", "commit", "-m", msg], repo_root)) and change it to this:
        msg = f"[Operon Auto-Patch] {goal[:50].strip()}..."
    _run(["git", "commit", "-m", msg], repo_root)
""",
        repo_root="/home/UserX/Master/Operon"
    )

    log.info(f"Starting Operon session with goal: {state.goal}")

    final_state = run_agent(state)

    log.info(f"Session finished in {final_state.step_count} steps.")

    print("DONE")
    print(final_state)


        # Find where the LLM server URL or port (8080) is defined. 
        # Change the port from 8080 to 9090.
        # Do not change anything else.