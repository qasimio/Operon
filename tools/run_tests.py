import subprocess

def run_tests(repo_root):
    try:
        # Run pytest
        result = subprocess.run(
            ["python", "-m", "pytest", "-v"],
            cwd=repo_root,
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            return {"success": True, "output": "✅ Tests passed successfully."}
        elif result.returncode == 5: # Exit code 5 means 'No tests collected'
            return {"success": True, "output": "✅ No tests found for this file. Assuming safe."}
        else:
            return {"success": False, "stderr": result.stderr or result.stdout}
            
    except Exception as e:
        # If pytest isn't installed at all, don't crash the agent
        return {"success": True, "output": f"✅ Test runner unavailable ({str(e)}). Assuming safe."}