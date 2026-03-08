import os
import json
from mistralai import Mistral
from typing import List
import time
import logging
from dataclasses import dataclass
from datetime import datetime

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Dataclass with overlap and multi-speaker support
@dataclass
class MeetingSegment:
    speaker: str
    start_time: float
    end_time: float
    text: str
    overlap: bool = False
    speakers: List[str] = None


class BulletproofMeetingMinutesGenerator:
    def __init__(self, api_key: str, model: str = "mistral-large-latest"):
        self.client = Mistral(api_key=api_key) if api_key else None
        self.model = model

    def safe_api_call(self, func, *args, **kwargs):
        if not self.client:
            return False, "", "No API key provided"

        retry_configs = [
            {"max_retries": 3, "base_delay": 1.0},
            {"max_retries": 2, "base_delay": 5.0},
            {"max_retries": 1, "base_delay": 10.0}
        ]

        for config in retry_configs:
            try:
                for attempt in range(config["max_retries"]):
                    try:
                        result = func(*args, **kwargs)
                        return True, result, ""
                    except Exception as e:
                        error_str = str(e).lower()
                        if config == retry_configs[-1] and attempt == config["max_retries"] - 1:
                            break
                        if any(code in error_str for code in ['429', '502', '503', '504', 'rate limit', 'server error', 'timeout']):
                            time.sleep(config["base_delay"] * (attempt + 1))
                        else:
                            break
            except Exception:
                continue

        return False, "", str(e) if 'e' in locals() else "Unknown API error"

    def load_and_structure_data(self, json_file: str) -> tuple[List[MeetingSegment], str]:
        segments = []
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                transcript = json.load(f)

            for seg in transcript.get('segments', []):
                text = seg.get('text', '').strip()
                if not text:
                    continue

                segment = MeetingSegment(
                    speaker=seg.get('speaker', 'UNKNOWN'),
                    start_time=seg.get('start', 0),
                    end_time=seg.get('end', 0),
                    text=text,
                    overlap=seg.get('overlap', False),
                    speakers=seg.get('speakers', [seg.get('speaker', 'UNKNOWN')])
                )
                segments.append(segment)

            if not segments:
                segments = [MeetingSegment("SYSTEM", 0, 0, "Meeting transcript data could not be loaded")]

            complete_transcript = '\n'.join(
                f"{' & '.join(seg.speakers) if seg.overlap else seg.speaker}: {seg.text}"
                for seg in segments
            )
            return segments, complete_transcript

        except Exception as e:
            return [MeetingSegment("SYSTEM", 0, 0, f"Error loading transcript: {e}")], f"Error loading transcript: {e}"

    def create_structured_input(self, segments: List[MeetingSegment]) -> str:
        if not segments:
            return "No meeting data available"

        try:
            structured_parts = []
            current_speaker_key = None
            current_block = []

            for segment in segments:
                # Use combined speaker key for overlap
                speaker_key = " & ".join(sorted(segment.speakers or [segment.speaker])) if segment.overlap else segment.speaker

                if current_speaker_key != speaker_key:
                    if current_block:
                        start_time = current_block[0].start_time
                        end_time = current_block[-1].end_time
                        combined_text = ' '.join(s.text for s in current_block)
                        tag = "🔁 OVERLAP" if current_block[0].overlap else ""
                        structured_parts.append(
                            f"{tag}\n[{self._format_time(start_time)}-{self._format_time(end_time)}] {current_speaker_key}:\n{combined_text}"
                        )
                    current_block = [segment]
                    current_speaker_key = speaker_key
                else:
                    current_block.append(segment)

            # Handle last block
            if current_block:
                start_time = current_block[0].start_time
                end_time = current_block[-1].end_time
                combined_text = ' '.join(s.text for s in current_block)
                tag = "🔁 OVERLAP" if current_block[0].overlap else ""
                structured_parts.append(
                    f"{tag}\n[{self._format_time(start_time)}-{self._format_time(end_time)}] {current_speaker_key}:\n{combined_text}"
                )

            result = '\n\n'.join(structured_parts)
            if len(result) > 100000:
                result = result[-100000:]
                result = "...[earlier content truncated]...\n\n" + result
            return result

        except Exception:
            return '\n'.join(f"{seg.speaker}: {seg.text}" for seg in segments[:20])

    def _format_time(self, seconds: float) -> str:
        try:
            minutes = int(seconds // 60)
            seconds = int(seconds % 60)
            return f"{minutes:02d}:{seconds:02d}"
        except:
            return "00:00"

    def generate_with_api(self, structured_input: str) -> tuple[bool, str]:
        if not self.client:
            return False, "No API client available"

        prompt = f"""You are a professional meeting documentation specialist. Convert this meeting transcript into formal Minutes of Meeting (MoM).

TRANSCRIPT:
{structured_input}

Generate comprehensive meeting minutes with the following structure:

MEETING MINUTES
Date: {datetime.now().strftime('%B %d, %Y')}

ATTENDEES:
- [List all speakers with their roles if mentioned]

AGENDA ITEMS:

1. [Topic/Section Name]
   - [Speaker Name]: [Key points, decisions, action items]

ACTION ITEMS:
- [ ] [Action item] - Assigned to: [Person] - Due: [Date if mentioned]

DECISIONS MADE:
- [List key decisions]"""

        def api_call():
            response = self.client.chat.complete(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=4000,
                temperature=0.1
            )
            return response.choices[0].message.content.strip()

        success, result, _ = self.safe_api_call(api_call)
        return success, result

    def generate_summary(self, structured_input: str) -> tuple[bool, str]:
        if not self.client:
            return False, "No API client available"

        prompt = f"""You are an expert summarizer. Read the following meeting transcript and generate a concise executive summary (4-8 bullet points).

TRANSCRIPT:
{structured_input}

SUMMARY:
- """

        def api_call():
            response = self.client.chat.complete(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=600,
                temperature=0.2
            )
            return response.choices[0].message.content.strip()

        success, result, _ = self.safe_api_call(api_call)
        return success, result

    def process_meeting_bulletproof(self, json_file: str, output_file: str = 'final_minutes.txt') -> str:
        start_time = time.time()
        logger.info("Starting bulletproof meeting processing...")

        segments, complete_transcript = self.load_and_structure_data(json_file)
        structured_input = self.create_structured_input(segments)

        summary_success, summary_text = self.generate_summary(structured_input)
        if not summary_success:
            raise RuntimeError("Executive summary API failed and no fallback is allowed.")

        api_success, api_result = self.generate_with_api(structured_input)
        if not (api_success and api_result):
            raise RuntimeError("Minutes generation API failed and no fallback is allowed.")

        combined_output = f"""********** EXECUTIVE SUMMARY *********\n\n{summary_text}\n\n********* DETAILED MINUTES **********\n\n{api_result}"""

        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(combined_output)
            logger.info(f"Saved to: {output_file}")
        except Exception as e:
            logger.error(f"Failed to save file: {e}")

        return combined_output


def main():
    API_KEY = MISTRAL_API_KEY
    generator = BulletproofMeetingMinutesGenerator(api_key=API_KEY)

    transcription_folder = "/data/output/transcripts"
    output_folder = "/data/output/minutes"

    os.makedirs(output_folder, exist_ok=True)

    for filename in os.listdir(transcription_folder):
        if filename.endswith(".json"):
            json_path = os.path.join(transcription_folder, filename)
            base_name = os.path.splitext(filename)[0].replace("_combined_transcription", "")
            output_path = os.path.join(output_folder, f"mom_{base_name}.txt")

            if os.path.exists(output_path):
                print(f"⏭ Skipping {filename}, already processed.")
                continue

            print(f"\n📄 Processing {filename}...")
            try:
                result = generator.process_meeting_bulletproof(
                    json_file=json_path,
                    output_file=output_path
                )
                print(result[:400] + "...\n✅ Done with:", filename)
            except RuntimeError as e:
                logging.error(f"❌ Failed processing {filename}: {e}")

if __name__ == "__main__":
    main()