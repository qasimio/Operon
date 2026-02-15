import subprocess
import tempfile
import os

LLAMA_PATH = "/home/UserX/llama.cpp/build/bin/llama-cli"
MODEL_PATH = "/home/UserX/llama.cpp/models/codellama-7b-instruct.Q4_K_M.gguf"

def call_llm(prompt: str) -> str:
    try:
        # write prompt into a temp file (llama.cpp handles files MUCH better than stdin)
        with tempfile.NamedTemporaryFile(delete=False, mode="w") as f:
            f.write(prompt)
            prompt_file = f.name

        result = subprocess.run(
            [
                LLAMA_PATH,
                "-m", MODEL_PATH,
                "-f", prompt_file,        # ⭐ file input instead of stdin
                "-c", "1024",             # smaller context = faster start
                "-n", "256",              # shorter output = avoids hangs
                "--temp", "0.2",
                "--simple-io",
                "--no-display-prompt",
                "--threads", "8"
            ],
            capture_output=True,
            text=True,
            timeout=300
        )

        os.unlink(prompt_file)

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