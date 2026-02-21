# tools/shell_tools.py
from agent.logger import log
import subprocess
from typing import Dict

def run_tests(repo_root: str, test_command: str = "pytest -q") -> Dict:
    """
    Run the project's tests. Default uses pytest -q. Adjust test_command as needed.
    """
    try:
        result = subprocess.run(
            test_command.split(),
            cwd=repo_root,
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            log.info("Tests passed successfully.")
        else:
            log.error("Tests FAILED.")
            log.debug(f"Test Stderr:\n{result.stderr}")
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode
        }
    except FileNotFoundError as e:
        return {"success": False, "error": f"Command not found: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": str(e)}
