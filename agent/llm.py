# agent/llm.py — Operon v3.2
"""
Universal LLM router: local / OpenAI / Anthropic / OpenRouter / Deepseek / Groq / Together / Azure.

KEY FIX vs v3.1:
  - PROMPT_CHAR_CAP removed from rewrite prompts — the file content is NEVER
    trimmed when it's passed for editing. Trimming caused the LLM to never
    see the target line and generate empty/noop SEARCH/REPLACE blocks.
  - Trimming only applies to context/history sections, not file content.
  - Model switching: save_config() writes immediately, call_llm() hot-reloads
    on every call — no restart needed.

Config: .operon/llm_config.json  (auto-created, UI-managed, never edit manually)
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

# ── Default config ─────────────────────────────────────────────────────────────
_DEFAULT_CFG: dict = {
    "provider":    "local",
    "model":       "local",
    "api_key":     "",
    "base_url":    "http://127.0.0.1:8080/v1",
    "max_tokens":  4096,
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
        "azure":      {"base_url": "",                                   "model": "gpt-4o"},
    },
}

SYSTEM_PROMPT = (
    "You are Operon, an elite autonomous AI software engineer. "
    "You reason step by step and NEVER hallucinate file changes. "
    "Calling rewrite_function is the ONLY way to modify a file — "
    "claiming a file is changed without the tool call is FORBIDDEN. "
    "For JSON output: respond with raw JSON only, no markdown fences."
)

# Soft cap for non-file sections of prompts (history, context hints, etc.)
_CONTEXT_CAP = 2000


# ── Config ─────────────────────────────────────────────────────────────────────

def _cfg_path() -> Path:
    return Path(os.getcwd()) / ".operon" / "llm_config.json"


def _load_config() -> dict:
    p = _cfg_path()
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(_DEFAULT_CFG, indent=2), encoding="utf-8")
        log.info(f"[cyan]Created LLM config: {p}[/cyan]")
    try:
        cfg: dict = json.loads(p.read_text(encoding="utf-8"))
        prov     = cfg.get("provider", "local")
        preset   = _DEFAULT_CFG["_presets"].get(prov, {})
        if not cfg.get("base_url"):
            cfg["base_url"] = preset.get("base_url", "")
        if not cfg.get("model"):
            cfg["model"] = preset.get("model", "local")
        return cfg
    except Exception as e:
        log.warning(f"Config read error ({e}) — using defaults.")
        return dict(_DEFAULT_CFG)


def save_config(cfg: dict) -> None:
    """Write config. Takes effect on next call_llm() call without restart."""
    p = _cfg_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    log.info(f"[green]Config saved: {cfg.get('provider')}/{cfg.get('model')}[/green]")


# ── JSON cleaning ──────────────────────────────────────────────────────────────

def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        inner = lines[1:] if lines[0].startswith("```") else lines
        if inner and inner[-1].strip() in ("```", "```json"):
            inner = inner[:-1]
        text = "\n".join(inner).strip()
    return text


def extract_json(raw: str) -> str:
    raw = _strip_fences(raw)
    m   = re.search(r"(\{[\s\S]*\})", raw)
    return m.group(1) if m else raw


# ── Provider calls ─────────────────────────────────────────────────────────────

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
        "max_tokens":  int(cfg.get("max_tokens", 4096)),
        "temperature": float(cfg.get("temperature", 0.15)),
        "top_p":       float(cfg.get("top_p", 0.9)),
    }
    if require_json:
        payload["response_format"] = {"type": "json_object"}

    r = requests.post(url, headers=headers, json=payload,
                      timeout=int(cfg.get("timeout", 180)))
    if r.status_code == 404:
        raise RuntimeError(
            f"404 from {url}\n"
            "Check base_url in .operon/llm_config.json\n"
            "llama.cpp: http://127.0.0.1:8080/v1\n"
            "Ollama:    http://127.0.0.1:11434/v1"
        )
    r.raise_for_status()
    data = r.json()
    if "choices" in data and data["choices"]:
        return data["choices"][0]["message"]["content"].strip()
    raise RuntimeError(f"Unexpected response shape: {list(data.keys())}")


def _anthropic(cfg: dict, messages: list) -> str:
    api_key = cfg.get("api_key", "")
    if not api_key:
        raise RuntimeError("Anthropic requires api_key in .operon/llm_config.json")
    system = SYSTEM_PROMPT
    msgs   = [m for m in messages if m["role"] != "system"]
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                 "Content-Type": "application/json"},
        json={"model": cfg.get("model", "claude-sonnet-4-6"),
              "max_tokens": int(cfg.get("max_tokens", 4096)),
              "system": system, "messages": msgs},
        timeout=int(cfg.get("timeout", 180)),
    )
    r.raise_for_status()
    data = r.json()
    if "content" in data and data["content"]:
        return data["content"][0]["text"].strip()
    raise RuntimeError(f"Anthropic error: {data}")


# ── Public API ─────────────────────────────────────────────────────────────────

def call_llm(prompt: str, require_json: bool = False,
             retries: Optional[int] = None) -> str:
    """
    Call the configured LLM. Hot-reloads config on every call.
    Never truncates the prompt (caller is responsible for sizing).
    """
    cfg      = _load_config()
    provider = cfg.get("provider", "local").lower()
    n_retry  = retries if retries is not None else int(cfg.get("retries", 2))

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": prompt},
    ]

    last_err = "unknown"
    for attempt in range(n_retry + 1):
        try:
            if provider == "anthropic":
                raw = _anthropic(cfg, messages)
            else:
                raw = _openai_compat(cfg, messages, require_json)
            return extract_json(raw) if require_json else raw

        except requests.Timeout:
            last_err = "timeout"
            log.warning(f"LLM timeout (attempt {attempt + 1})")
            time.sleep(2 ** attempt)
        except Exception as e:
            last_err = str(e)
            log.error(f"LLM error attempt {attempt + 1}: {e}")
            time.sleep(1 + attempt)

    log.error(f"LLM gave up after {n_retry + 1} attempts: {last_err}")
    return json.dumps({"error": f"LLM unreachable: {last_err}"})


def get_model_info() -> dict:
    cfg = _load_config()
    return {
        "provider": cfg.get("provider", "local"),
        "model":    cfg.get("model", "unknown"),
        "base_url": cfg.get("base_url", ""),
    }
