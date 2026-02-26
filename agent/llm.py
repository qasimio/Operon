# agent/llm.py — Operon v3.1  Universal LLM Router
"""
Supports every major provider + any local server:
  Local:      llama.cpp / Ollama / LM Studio   (OpenAI-compat /v1/chat/completions)
  OpenAI:     gpt-4o, gpt-4-turbo, o1, o3 …
  Anthropic:  claude-opus-4-6, claude-sonnet-4-6, claude-haiku-4-5 …
  OpenRouter: any model via openrouter.ai
  Deepseek:   deepseek-chat, deepseek-coder
  Groq:       llama3, mixtral, gemma
  Together:   mistral, llama, qwen
  Azure:      azure openai deployments

Config lives at  .operon/llm_config.json  — hot-reloaded on every call.
Switch providers by editing "provider" + "api_key" in that file.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Optional

import requests

from agent.logger import log

# ── Default config skeleton ─────────────────────────────────────────────────
_DEFAULT_CONFIG: dict = {
    "provider":    "local",
    "model":       "local",
    "api_key":     "",
    "base_url":    "http://127.0.0.1:8080/v1",
    "max_tokens":  2800,
    "temperature": 0.15,
    "top_p":       0.9,
    "timeout":     180,
    "retries":     2,
    "_presets": {
        "local":      {"base_url": "http://127.0.0.1:8080/v1",         "model": "local"},
        "ollama":     {"base_url": "http://127.0.0.1:11434/v1",        "model": "qwen2.5-coder:7b"},
        "lmstudio":   {"base_url": "http://127.0.0.1:1234/v1",         "model": "local"},
        "openai":     {"base_url": "https://api.openai.com/v1",         "model": "gpt-4o"},
        "anthropic":  {"base_url": "https://api.anthropic.com",         "model": "claude-sonnet-4-6"},
        "openrouter": {"base_url": "https://openrouter.ai/api/v1",      "model": "anthropic/claude-3.5-sonnet"},
        "deepseek":   {"base_url": "https://api.deepseek.com/v1",       "model": "deepseek-coder"},
        "groq":       {"base_url": "https://api.groq.com/openai/v1",    "model": "llama-3.1-70b-versatile"},
        "together":   {"base_url": "https://api.together.xyz/v1",       "model": "Qwen/Qwen2.5-Coder-32B-Instruct"},
        "azure":      {"base_url": "https://{resource}.openai.azure.com/openai/deployments/{deploy}/", "model": "gpt-4o"},
    },
}

SYSTEM_PROMPT = (
    "You are Operon, an elite autonomous AI software engineer. "
    "You reason step-by-step and NEVER hallucinate file changes. "
    "You MUST call rewrite_function to actually modify a file — "
    "claiming it is patched without calling the tool is FORBIDDEN. "
    "When asked for JSON output, respond with ONLY raw JSON — no markdown, no explanation."
)

PROMPT_CHAR_CAP = 5500


# ── Config ───────────────────────────────────────────────────────────────────

def _config_path() -> Path:
    return Path(os.getcwd()) / ".operon" / "llm_config.json"


def _load_config() -> dict:
    p = _config_path()
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(_DEFAULT_CONFIG, indent=2), encoding="utf-8")
        log.info(f"[cyan]Created LLM config at {p}[/cyan]")
    try:
        cfg: dict = json.loads(p.read_text(encoding="utf-8"))
        # Apply preset base_url/model if not overridden
        provider = cfg.get("provider", "local")
        presets  = _DEFAULT_CONFIG.get("_presets", {})
        preset   = presets.get(provider, {})
        if not cfg.get("base_url") and preset.get("base_url"):
            cfg["base_url"] = preset["base_url"]
        if not cfg.get("model") and preset.get("model"):
            cfg["model"] = preset["model"]
        return cfg
    except Exception as e:
        log.warning(f"Config read error ({e}) — using defaults.")
        return dict(_DEFAULT_CONFIG)


def save_config(cfg: dict) -> None:
    p = _config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    # never write api keys that look like placeholders
    p.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _trim(prompt: str) -> str:
    if len(prompt) <= PROMPT_CHAR_CAP:
        return prompt
    half = PROMPT_CHAR_CAP // 2
    return prompt[:half] + "\n\n[...context trimmed...]\n\n" + prompt[-half:]


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        inner = lines[1:] if lines[0].startswith("```") else lines
        if inner and inner[-1].strip() in ("```", "```json"):
            inner = inner[:-1]
        text = "\n".join(inner).strip()
    return text


def _extract_json(raw: str) -> str:
    raw = _strip_fences(raw)
    m = re.search(r"(\{[\s\S]*\})", raw)
    return m.group(1) if m else raw


# ── Provider calls ───────────────────────────────────────────────────────────

def _openai_compat(cfg: dict, messages: list, require_json: bool) -> str:
    url     = cfg["base_url"].rstrip("/") + "/chat/completions"
    api_key = cfg.get("api_key", "")

    headers: dict = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if "openrouter" in cfg.get("base_url", ""):
        headers["HTTP-Referer"] = "https://github.com/operon-ai/operon"
        headers["X-Title"]      = "Operon"

    payload: dict = {
        "model":       cfg.get("model", "local"),
        "messages":    messages,
        "max_tokens":  int(cfg.get("max_tokens", 2800)),
        "temperature": float(cfg.get("temperature", 0.15)),
        "top_p":       float(cfg.get("top_p", 0.9)),
    }
    if require_json:
        payload["response_format"] = {"type": "json_object"}

    r = requests.post(url, headers=headers, json=payload,
                      timeout=int(cfg.get("timeout", 180)))
    if r.status_code == 404:
        raise RuntimeError(
            f"404 at {url} — check base_url in .operon/llm_config.json\n"
            "For llama.cpp: http://127.0.0.1:8080/v1\n"
            "For Ollama:    http://127.0.0.1:11434/v1"
        )
    r.raise_for_status()
    data = r.json()
    if "choices" in data and data["choices"]:
        return data["choices"][0]["message"]["content"].strip()
    raise RuntimeError(f"Unexpected response: {list(data.keys())}")


def _anthropic_native(cfg: dict, messages: list, require_json: bool) -> str:
    api_key = cfg.get("api_key", "")
    if not api_key:
        raise RuntimeError("Anthropic requires api_key in .operon/llm_config.json")

    system  = SYSTEM_PROMPT
    msgs    = [m for m in messages if m["role"] != "system"]

    headers = {
        "x-api-key":         api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type":      "application/json",
    }
    payload = {
        "model":      cfg.get("model", "claude-sonnet-4-6"),
        "max_tokens": int(cfg.get("max_tokens", 2800)),
        "system":     system,
        "messages":   msgs,
    }
    r = requests.post("https://api.anthropic.com/v1/messages",
                      headers=headers, json=payload,
                      timeout=int(cfg.get("timeout", 180)))
    r.raise_for_status()
    data = r.json()
    if "content" in data and data["content"]:
        return data["content"][0]["text"].strip()
    raise RuntimeError(f"Anthropic error: {data}")


# ── Public API ────────────────────────────────────────────────────────────────

def call_llm(prompt: str, require_json: bool = False,
             retries: Optional[int] = None) -> str:
    cfg      = _load_config()
    provider = cfg.get("provider", "local").lower()
    n_retry  = retries if retries is not None else int(cfg.get("retries", 2))

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": _trim(prompt)},
    ]

    last_err = "unknown"
    for attempt in range(n_retry + 1):
        try:
            if provider == "anthropic":
                raw = _anthropic_native(cfg, messages, require_json)
            else:
                raw = _openai_compat(cfg, messages, require_json)

            return _extract_json(raw) if require_json else raw

        except requests.Timeout:
            last_err = "timeout"
            log.warning(f"LLM timeout (attempt {attempt + 1})")
            time.sleep(2 ** attempt)
        except Exception as e:
            last_err = str(e)
            log.error(f"LLM error attempt {attempt + 1}: {e}")
            time.sleep(1 + attempt)

    log.error(f"LLM failed after {n_retry + 1} attempts: {last_err}")
    return json.dumps({"error": f"LLM unreachable: {last_err}"})


def get_model_info() -> dict:
    cfg = _load_config()
    return {
        "provider": cfg.get("provider", "local"),
        "model":    cfg.get("model", "unknown"),
        "base_url": cfg.get("base_url", ""),
    }
