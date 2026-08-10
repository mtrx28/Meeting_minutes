import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from generate_minutes import BulletproofMeetingMinutesGenerator
from dotenv import load_dotenv

def run():
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.dirname(__file__)), 'backend', '.env'))
    api_key = os.getenv("MISTRAL_API_KEY")
    generator = BulletproofMeetingMinutesGenerator(api_key=api_key)
    
    json_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'es2002', 'ES2002_truth_transcript.json')
    output_path = os.path.join(os.path.dirname(__file__), 'final_minutes.txt')
    
    print(f"Processing {json_path}...")
    try:
        generator.process_meeting_bulletproof(json_path, output_path)
        print("Success! Summary generated.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    run()
