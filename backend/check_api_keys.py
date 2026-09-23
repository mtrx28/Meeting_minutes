"""
Manual smoke check for API keys/models in backend/.env — makes real network
calls, so it's a standalone script (run directly), not a pytest test.
"""

import os
from dotenv import load_dotenv
from mistralai.client.sdk import Mistral

def main():
    load_dotenv()
    hf_token = os.getenv("HF_API_TOKEN")
    mistral_key = os.getenv("MISTRAL_API_KEY")

    print(f"HF_API_TOKEN loaded: {bool(hf_token)}")
    print(f"MISTRAL_API_KEY loaded: {bool(mistral_key)}")

    if mistral_key:
        try:
            client = Mistral(api_key=mistral_key)
            client.chat.complete(
                model="mistral-small-latest",
                messages=[{"role": "user", "content": "Hello"}]
            )
            print("Mistral API is working!")
        except Exception as e:
            print(f"Mistral API failed: {e}")

    if hf_token:
        try:
            from pyannote.audio import Pipeline
            Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", use_auth_token=hf_token)
            print("HF Pyannote Pipeline loaded successfully!")
        except Exception as e:
            print(f"HF API failed: {e}")


if __name__ == "__main__":
    main()
