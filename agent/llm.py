import subprocess

LLAMA_PATH = "/home/UserX/llama.cpp/build/bin/llama-cli"
MODEL_PATH = "/home/UserX/llama.cpp/models/codellama-7b-instruct.Q4_K_M.gguf"

def call_llm(prompt: str) -> str:
    try:
        result = subprocess.run(
            [
                LLAMA_PATH,
                "-m", MODEL_PATH,
                "--simple-io",          # ⭐ THIS FIXES EVERYTHING
                "-c", "2048",
                "--n-predict", "512",
                "--temp", "0.2"
            ],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=120   # prevents infinite hang
        )

        output = result.stdout.strip().replace("\x00", "")

        if not output:
            return "ERROR: empty LLM output"

        return output

    except subprocess.TimeoutExpired:
        return "ERROR: LLM timeout"

    except Exception as e:
        return f"ERROR: {str(e)}"






"""
Start the local AI program
Load the CodeLlama model
Send it a prompt
Let it generate up to 512 tokens
Return whatever it says
"""