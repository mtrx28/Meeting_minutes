"""
Meeting minutes generation module using Mistral LLM.
Takes structured transcript data and produces executive summary + detailed minutes.
"""

import time
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from mistralai.client.sdk import Mistral

logger = logging.getLogger(__name__)


@dataclass
class MeetingSegment:
    """A single segment of meeting transcript with speaker info."""
    speaker: Optional[str]
    start_time: float
    end_time: float
    text: str
    overlap: bool = False
    speakers: list[str] = field(default_factory=list)


class MeetingMinutesGenerator:
    """Generates meeting minutes from structured transcript using Mistral API."""

    MAX_RETRIES = 5
    RETRYABLE_ERRORS = ('429', '502', '503', '504', 'rate limit', 'server error', 'timeout')

    def __init__(self, api_key: str, model: str = "mistral-large-latest"):
        if not api_key:
            raise ValueError("Mistral API key is required")
        self.client = Mistral(api_key=api_key)
        self.model = model

    def _api_call_with_retry(self, messages: list[dict], max_tokens: int = 4000,
                             temperature: float = 0.1) -> str:
        """
        Make an API call with exponential backoff retry for transient errors.
        """
        last_error = None
        for attempt in range(self.MAX_RETRIES):
            try:
                response = self.client.chat.complete(
                    model=self.model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                return response.choices[0].message.content.strip()
            except Exception as e:
                last_error = e
                error_str = str(e).lower()
                is_retryable = any(code in error_str for code in self.RETRYABLE_ERRORS)

                if is_retryable and attempt < self.MAX_RETRIES - 1:
                    delay = min(2 ** attempt, 30)  # 1, 2, 4, 8, 16 seconds (capped at 30)
                    logger.warning(f"Retryable error (attempt {attempt + 1}): {e}. Retrying in {delay}s...")
                    time.sleep(delay)
                else:
                    break

        raise RuntimeError(f"API call failed after {self.MAX_RETRIES} attempts: {last_error}")

    def load_segments(self, transcript_data: dict) -> list[MeetingSegment]:
        """Load transcript segments from JSON data (dict, not file path)."""
        segments = []
        for seg in transcript_data.get('segments', []):
            text = seg.get('text', '').strip()
            if not text:
                continue
            segments.append(MeetingSegment(
                speaker=seg.get('speaker'),
                start_time=seg.get('start', 0),
                end_time=seg.get('end', 0),
                text=text,
                overlap=seg.get('overlap', False),
                speakers=seg.get('speakers', [seg.get('speaker', 'UNKNOWN')]),
            ))
        return segments

    def create_structured_input(self, segments: list[MeetingSegment]) -> str:
        """
        Format segments into structured text for LLM consumption.
        Merges consecutive segments from the same speaker.
        """
        if not segments:
            return "No meeting data available"

        structured_parts = []
        current_speaker_key = None
        current_block: list[MeetingSegment] = []

        for segment in segments:
            speaker_key = (" & ".join(sorted(segment.speakers))
                           if segment.overlap
                           else (segment.speaker or 'UNKNOWN'))

            if current_speaker_key != speaker_key:
                if current_block:
                    structured_parts.append(
                        self._format_block(current_block, current_speaker_key)
                    )
                current_block = [segment]
                current_speaker_key = speaker_key
            else:
                current_block.append(segment)

        # Handle last block
        if current_block:
            structured_parts.append(
                self._format_block(current_block, current_speaker_key)
            )

        result = '\n\n'.join(structured_parts)

        # Truncate if too long for API context window
        if len(result) > 100000:
            result = "...[earlier content truncated]...\n\n" + result[-100000:]

        return result

    def _format_block(self, block: list[MeetingSegment], speaker_key: str) -> str:
        """Format a block of consecutive same-speaker segments."""
        start_time = block[0].start_time
        end_time = block[-1].end_time
        combined_text = ' '.join(s.text for s in block)
        tag = "🔁 OVERLAP\n" if block[0].overlap else ""
        return f"{tag}[{self._format_time(start_time)}-{self._format_time(end_time)}] {speaker_key}:\n{combined_text}"

    @staticmethod
    def _format_time(total_seconds: float) -> str:
        """Format seconds into MM:SS string."""
        try:
            mins = int(total_seconds // 60)
            secs = int(total_seconds % 60)
            return f"{mins:02d}:{secs:02d}"
        except Exception:
            return "00:00"

    def generate_minutes(self, structured_input: str) -> str:
        """Generate detailed meeting minutes from structured transcript."""
        prompt = f"""You are a professional meeting documentation specialist. Convert this meeting transcript into formal Minutes of Meeting (MoM).

TRANSCRIPT:
{structured_input}

Generate comprehensive meeting minutes with the following structure (use markdown formatting):

# MEETING MINUTES
**Date:** {datetime.now().strftime('%B %d, %Y')}

## ATTENDEES
- [List all speakers with their roles if mentioned]

## AGENDA ITEMS

### 1. [Topic/Section Name]
- **[Speaker Name]**: [Key points, decisions, action items]

## ACTION ITEMS
- [ ] [Action item] — Assigned to: [Person] — Due: [Date if mentioned]

## DECISIONS MADE
- [List key decisions]

## NOTES
- [Any additional observations or context]

Important: Be thorough and capture all key discussion points. Use the speaker labels as provided. If topics are unclear, group related discussion logically."""

        return self._api_call_with_retry(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4000,
            temperature=0.1,
        )

    def generate_summary(self, structured_input: str) -> str:
        """Generate a concise executive summary from structured transcript."""
        prompt = f"""You are an expert meeting summarizer. Read the following meeting transcript and generate a concise executive summary.

TRANSCRIPT:
{structured_input}

Generate an executive summary with:
- 4-8 bullet points covering the key topics discussed
- Key decisions made
- Critical action items
- Overall meeting outcome

Format in clean markdown with bullet points."""

        return self._api_call_with_retry(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=800,
            temperature=0.2,
        )

    def process_transcript(self, transcript_data: dict) -> dict:
        """
        Full minutes generation pipeline:
        1. Load and structure segments
        2. Generate executive summary
        3. Generate detailed minutes
        Returns dict with summary, minutes, speaker_stats, and segments.
        """
        segments = self.load_segments(transcript_data)
        if not segments:
            raise ValueError("No valid segments found in transcript data")

        structured_input = self.create_structured_input(segments)

        # Generate both outputs
        logger.info("Generating executive summary...")
        summary = self.generate_summary(structured_input)

        logger.info("Generating detailed minutes...")
        minutes = self.generate_minutes(structured_input)

        # Compute speaker statistics
        speaker_stats = {}
        total_words = 0
        for seg in segments:
            speaker = seg.speaker or 'UNKNOWN'
            words = len(seg.text.split())
            total_words += words
            if speaker not in speaker_stats:
                speaker_stats[speaker] = {'duration': 0.0, 'words': 0, 'segments': 0}
            speaker_stats[speaker]['duration'] += (seg.end_time - seg.start_time)
            speaker_stats[speaker]['words'] += words
            speaker_stats[speaker]['segments'] += 1

        return {
            'summary': summary,
            'minutes': minutes,
            'speaker_stats': speaker_stats,
            'total_words': total_words,
            'total_duration': sum(s['duration'] for s in speaker_stats.values()),
            'num_speakers': len(speaker_stats),
            'segments': [
                {
                    'speaker': seg.speaker,
                    'speakers': seg.speakers,
                    'start': seg.start_time,
                    'end': seg.end_time,
                    'text': seg.text,
                    'overlap': seg.overlap,
                }
                for seg in segments
            ],
        }
