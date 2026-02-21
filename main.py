from runtime.state import AgentState
from agent.loop import run_agent
from agent.logger import log

if __name__ == "__main__":
    state = AgentState(
        goal="""
Action: Open agent/loop.py. 
Find the _rewrite_function and replace the bottom half of it (everything from # Apply all patches down to the return statement) with this exact code:
# Apply all patches
    for search_block, replace_block in blocks:
        patched_text = apply_patch(file_text, search_block, replace_block)
        
        if patched_text is None:
            return {
                "success": False,
                "error": "SEARCH block did not exactly match the file content. LLM hallucinated code."
            }
        file_text = patched_text

    # ========================================================
    # 🛡️ THE SYNTAX SENTINEL (IN-MEMORY ROLLBACK)
    # ========================================================
    if file_path.endswith(".py"):
        try:
            # We try to parse the new code into an Abstract Syntax Tree BEFORE saving
            ast.parse(file_text)
        except SyntaxError as e:
            # If it fails, we ABORT. The bad code never touches the hard drive.
            error_msg = f"CRITICAL: Your patch introduced a Python SyntaxError! '{e.msg}' at line {e.lineno}. The rollback was triggered and the file was NOT saved. You MUST read the file again or rewrite the function with correct Python syntax."
            log.error(f"Syntax check failed for {file_path}. Rollback triggered.")
            return {"success": False, "error": error_msg}

    # If we made it here, the syntax is perfectly valid!
    # Write patched code back to disk
    full_path.write_text(file_text, encoding="utf-8")

    return {
        "success": True,
        "file": file_path,
        "message": f"Successfully applied {len(blocks)} patch(es). Syntax is valid."
    }
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
