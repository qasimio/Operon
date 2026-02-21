import requests

URL = "http://127.0.0.1:8080/completion"

def call_llm(prompt: str, require_json: bool = False) -> str:
    payload = {
        "prompt": prompt,
        "n_predict": 768,       # Increased to allow full function generation
        "temperature": 0.1,     # Lowered for deterministic coding
        "stop": ["</s>", "<|im_end|>"] # Added Qwen's specific stop token
    }
    
    # Force llama.cpp to ONLY generate valid JSON
    if require_json:
        payload["response_format"] = {"type": "json_object"}

    try:
        response = requests.post(URL, json=payload, timeout=120)
        data = response.json()
        return data["content"].strip()

    except Exception as e:
        return f'{{"error": "{str(e)}"}}'




"""
Start the local AI program
Load the CodeLlama model
Send it a prompt
Let it generate up to 512 tokens
Return whatever it says
"""