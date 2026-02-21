from runtime.state import AgentState
from agent.loop import run_agent
from agent.logger import log

if __name__ == "__main__":
    state = AgentState(

    goal="""
    Modify the `_rewrite_function` function in `agent/loop.py`,
    right before calling LLM:
    log.debug(f"LLM Prompt for rewrite:\n{prompt}".

    Do not change anything else.
""",

        repo_root="/home/UserX/Master/Operon"
    )

    log.info(f"Starting Operon session with goal: {state.goal}")

    final_state = run_agent(state)

    log.info(f"Session finished in {final_state.step_count} steps.")

    print("DONE")
    print(final_state)