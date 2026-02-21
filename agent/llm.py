from agent.logger import log
import requests
import json

URL = "http://127.0.0.1:8080/completion"

def call_llm(prompt: str, require_json: bool = False) -> str:
    # ChatML format forces Instruct models to behave properly
    chatml_prompt = f"<|im_start|>system\nYou are Operon, an elite autonomous AI software engineer.<|im_end|>\n<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n"
    
    payload = {
        "prompt": chatml_prompt,
        "n_predict": 1024,
        "temperature": 0.1,
        "stop": ["</s>", "<|im_end|>"]
    }
    
    # Force llama.cpp to ONLY output valid JSON (No regex needed!)
    if require_json:
        payload["response_format"] = {"type": "json_object"}

    try:
        response = requests.post(URL, json=payload, timeout=120)
        response.raise_for_status() # Throw error if server crashes
        data = response.json()

        # Return a valid JSON string containing the error so the agent doesn't crash
        log.debug(f"LLM Response Time/Tokens... (add any metadata here)")

        return data["content"].strip()
    except Exception as e:
        log.error(f"LLM Server Error: {str(e)}")
        return json.dumps({"error": f"LLM Server Error: {str(e)}"})