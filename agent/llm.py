import subprocess

def call_llm(prompt: str) -> str:
    try:
        result = subprocess.run(
            [
                "./llama-cli",
                "-m", "models/codellama-7b-instruct.Q4_K_M.gguf",
                "-p", prompt,
                "--n-predict", "512"
            ],
            capture_output=True,
            text=True,
            check=False   # don't auto-crash; we handle it ourselves
        )

        if result.returncode != 0:
            return f"ERROR: LLM process failed\n{result.stderr.strip()}"

        if not result.stdout.strip():
            return "ERROR: LLM returned empty output"

        return result.stdout

    except FileNotFoundError:
        return "ERROR: llama-cli not found or not executable"

    except Exception as e:
        return f"ERROR: {str(e)}"






"""
Start the local AI program
Load the CodeLlama model
Send it a prompt
Let it generate up to 512 tokens
Return whatever it says
"""