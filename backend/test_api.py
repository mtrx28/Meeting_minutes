import os
from dotenv import load_dotenv
from mistralai import Mistral

load_dotenv()
HF_API_TOKEN = os.getenv("HF_API_TOKEN")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")

print(f"HF_API_TOKEN loaded: {bool(HF_API_TOKEN)}")
print(f"MISTRAL_API_KEY loaded: {bool(MISTRAL_API_KEY)}")

if MISTRAL_API_KEY:
    try:
        client = Mistral(api_key=MISTRAL_API_KEY)
        response = client.chat.complete(
            model="mistral-small-latest",
            messages=[{"role": "user", "content": "Hello"}]
        )
        print("Mistral API is working!")
    except Exception as e:
        print(f"Mistral API failed: {e}")

if HF_API_TOKEN:
    try:
        from pyannote.audio import Pipeline
        pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", use_auth_token=HF_API_TOKEN)
        print("HF Pyannote Pipeline loaded successfully!")
    except Exception as e:
        print(f"HF API failed: {e}")
