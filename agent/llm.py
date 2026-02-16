import requests

URL = "http://127.0.0.1:8080/completion"

def call_llm(prompt: str) -> str:
    try:
        response = requests.post(
            URL,
            json={
                "prompt": prompt,
                "n_predict": 256,
                "temperature": 0.2,
                "stop": ["</s>"]
            },
            timeout=120
        )

        data = response.json()

        return data["content"].strip()

    except Exception as e:
        return f"ERROR: {str(e)}"





"""
Start the local AI program
Load the CodeLlama model
Send it a prompt
Let it generate up to 512 tokens
Return whatever it says
"""