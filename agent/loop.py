from agent.decide import decide_next_action
from tools.fs_tools import read_file
from tools.git_tools import commit

def run_agent(state):
    while not state.done and state.step_count < 20:
        action = decide_next_action(state)
        state.last_action = action["action"]
        state.step_count += 1
        
        if action["action"] == "read_file":
            obs = read_file(action["path"], state.repo_root)
            if obs["success"]:
                state.files_read.append(action["path"])
            else:
                state.errors.append(obs["error"])
            
        elif action["action"]  == "git_commit":
            obs = commit(action["message"], state.repo_root)
            state.observations.append(obs)

        elif action["action"]  == "stop":
            state.done = True
        
        else:
            state.errors.append(f"Unknown action: {action}")
            state.done = True
        
    return state
            



"""
Repeat:
    Ask AI what to do next
    Execute that action
    Record what happened
Stop when:
    AI says stop
    OR 20 steps reached
Return the final agent memory
"""