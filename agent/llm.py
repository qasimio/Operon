# agent/llm.py — Operon v3
import requests
import json
import time
from agent.logger import log

URL = "http://127.0.0.1:8080/v1/chat/completions"

# Qwen 2.5 Coder 7B @ 8192 ctx.  Budget: 2800 completion, ~5000 prompt chars.
MAX_TOKENS      = 2800
PROMPT_CHAR_CAP = 5000
TIMEOUT         = 180

SYSTEM = (
    "You are Operon, an elite autonomous AI software engineer. "
    "You reason step-by-step and NEVER hallucinate file changes. "
    "You MUST call the rewrite_function tool to actually modify files — "
    "claiming a file is patched without calling the tool is FORBIDDEN. "
    "When asked for JSON, output ONLY raw JSON — no markdown fences, no preamble."
)


def _trim(prompt: str, cap: int = PROMPT_CHAR_CAP) -> str:
    """Keep prompt inside context budget by trimming the middle."""
    if len(prompt) <= cap:
        return prompt
    half = cap // 2
    return prompt[:half] + "\n\n[...context trimmed for budget...]\n\n" + prompt[-half:]


def _strip_fences(text: str) -> str:
    """Remove ```json ... ``` or ``` ... ``` wrappers that Qwen sometimes adds."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # drop first line (```json) and last line (```)
        inner = lines[1:] if lines[0].startswith("```") else lines
        if inner and inner[-1].strip() == "```":
            inner = inner[:-1]
        text = "\n".join(inner).strip()
    return text


def call_llm(prompt: str, require_json: bool = False, retries: int = 2) -> str:
    payload: dict = {
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user",   "content": _trim(prompt)},
        ],
        "max_tokens":  MAX_TOKENS,
        "temperature": 0.15,
        "top_p":       0.9,
        "repeat_penalty": 1.05,
    }
    if require_json:
        payload["response_format"] = {"type": "json_object"}

    last_err = "unknown"
    for attempt in range(retries + 1):
        try:
            r = requests.post(URL, json=payload, timeout=TIMEOUT)
            if r.status_code == 404:
                log.error("llama-server: /v1/chat/completions not found — update your binary.")
            r.raise_for_status()
            data = r.json()
            if "choices" in data and data["choices"]:
                raw = data["choices"][0]["message"]["content"].strip()
                return _strip_fences(raw) if require_json else raw
            return json.dumps(data)
        except requests.Timeout:
            last_err = "timeout"
            log.warning(f"LLM timeout (attempt {attempt + 1}/{retries + 1})")
            time.sleep(2 ** attempt)
        except Exception as e:
            last_err = str(e)
            log.error(f"LLM error attempt {attempt + 1}: {e}")
            time.sleep(1)

    log.error(f"LLM gave up after {retries + 1} attempts: {last_err}")
    return json.dumps({"error": f"LLM unreachable: {last_err}"})
