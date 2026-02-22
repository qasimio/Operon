import requests
import json
from agent.logger import log

# Switch to the OpenAI-compatible completions endpoint.
# This forces the local server (llama.cpp/Ollama) to automatically apply 
# the CORRECT chat template (Llama 3, Mistral, etc.) instead of hardcoded ChatML!
URL = "http://127.0.0.1:8080/v1/chat/completions"

def call_llm(prompt: str, require_json: bool = False) -> str:
    payload = {
        "messages": [
            {"role": "system", "content": "You are Operon, an elite autonomous AI software engineer. Think step-by-step. NEVER hallucinate task completion. You MUST explicitly use the 'rewrite_function' tool to modify a file before claiming it is patched."},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 4096,
        "temperature": 0.1,
    }
    
    # Modern llama.cpp uses this standard OpenAI json response format
    if require_json:
        payload["response_format"] = {"type": "json_object"}

    try:
        response = requests.post(URL, json=payload, timeout=120)
        
        # Friendly error if they are using an outdated server binary
        if response.status_code == 404:
            log.error("Endpoint /v1/chat/completions not found! Is your local server running a modern llama.cpp binary?")
            
        response.raise_for_status() 
        data = response.json()

        # Extract content from the chat completions format
        if "choices" in data and len(data["choices"]) > 0:
            return data["choices"][0]["message"]["content"].strip()
            
        return json.dumps(data)
        
    except Exception as e:
        log.error(f"LLM Server Error: {str(e)}")
        return json.dumps({"error": f"LLM Server Error: {str(e)}"})