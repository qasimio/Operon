# agent/llm.py — Operon v2: smarter LLM client with retry + token budget
import requests
import json
import time
from agent.logger import log

# OpenAI-compatible endpoint for llama.cpp / Ollama
URL = "http://127.0.0.1:8080/v1/chat/completions"

# Qwen 2.5 Coder 7B fits comfortably at 8192 context
# We budget 3072 tokens for the response, leaving 5120 for the prompt.
MAX_TOKENS = 3072
PROMPT_TOKEN_BUDGET = 5000   # characters ≈ tokens (rough heuristic for Qwen)

SYSTEM_PROMPT = (
    "You are Operon, an elite autonomous AI software engineer. "
    "Think step-by-step. NEVER hallucinate task completion. "
    "You MUST explicitly use the 'rewrite_function' tool to modify a file before claiming it is patched. "
    "Always output valid JSON when asked. Never wrap JSON in markdown code fences."
)


def _trim_prompt(prompt: str, budget: int = PROMPT_TOKEN_BUDGET) -> str:
    """Trim prompt to stay inside context window. Removes middle content first."""
    if len(prompt) <= budget:
        return prompt
    half = budget // 2
    return prompt[:half] + "\n... [truncated for context budget] ...\n" + prompt[-half:]


def call_llm(prompt: str, require_json: bool = False, retries: int = 2) -> str:
    trimmed = _trim_prompt(prompt)
    payload = {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": trimmed},
        ],
        "max_tokens": MAX_TOKENS,
        "temperature": 0.1,
        "top_p": 0.9,
        "repeat_penalty": 1.0,
    }

    if require_json:
        payload["response_format"] = {"type": "json_object"}

    last_err = None
    for attempt in range(retries + 1):
        try:
            response = requests.post(URL, json=payload, timeout=180)

            if response.status_code == 404:
                log.error(
                    "Endpoint /v1/chat/completions not found! "
                    "Ensure llama-server is running a modern binary."
                )

            response.raise_for_status()
            data = response.json()

            if "choices" in data and data["choices"]:
                content = data["choices"][0]["message"]["content"].strip()
                # Strip accidental markdown fences that some llama.cpp versions add
                if require_json:
                    content = content.strip("`")
                    if content.startswith("json"):
                        content = content[4:].strip()
                return content

            return json.dumps(data)

        except requests.exceptions.Timeout:
            last_err = "LLM request timed out."
            log.warning(f"LLM timeout (attempt {attempt+1}/{retries+1})")
            time.sleep(1.5 * (attempt + 1))
        except Exception as e:
            last_err = str(e)
            log.error(f"LLM error (attempt {attempt+1}): {e}")
            time.sleep(0.5)

    log.error(f"LLM failed after {retries+1} attempts: {last_err}")
    return json.dumps({"error": f"LLM Server Error: {last_err}"})
