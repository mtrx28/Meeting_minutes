"""
Pydantic models for API request/response schemas.
"""

from pydantic import BaseModel
from typing import Dict, List, Optional


class UploadResponse(BaseModel):
    """Response after file upload."""
    job_id: str
    filename: str
    file_size_mb: float
    message: str


class PipelineProgress(BaseModel):
    """SSE progress event data."""
    stage: str  # splitting, diarizing, transcribing, generating_summary, generating_minutes, complete, error
    message: str
    progress: Optional[float] = None  # 0.0 - 1.0


class SpeakerStats(BaseModel):
    """Statistics for a single speaker."""
    duration: float
    words: int
    segments: int


class TranscriptSegment(BaseModel):
    """A single transcript segment."""
    speaker: Optional[str]
    speakers: List[str]
    start: float
    end: float
    text: str
    overlap: bool = False


class MeetingMinutesResult(BaseModel):
    """Complete meeting minutes result."""
    job_id: str
    filename: str
    summary: str
    minutes: str
    speaker_stats: Dict[str, SpeakerStats]
    total_words: int
    total_duration: float
    num_speakers: int
    segments: List[TranscriptSegment]

