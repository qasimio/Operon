from runtime.state import AgentState
from agent.loop import run_agent
from agent.logger import log

if __name__ == "__main__":
    state = AgentState(

    goal="""
    Modify the `run_agent` function in `agent/loop.py`.

    Right after the variable `action` is decided, add the following two lines:

    log.info(f"Executing action: {action.get('action')}")
    log.debug(f"Full state payload: {action}")
     
    and at the top of same file add:
    from agent.logger import log

    Ensure both lines use the correct indentation level inside the function.
    Do not change anything else.
""",

        repo_root="/home/UserX/Master/Operon"
    )

    log.info(f"Starting Operon session with goal: {state.goal}")

    final_state = run_agent(state)

    log.info(f"Session finished in {final_state.step_count} steps.")

    print("DONE")
    print(final_state)