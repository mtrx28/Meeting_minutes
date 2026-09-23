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


class Claim(BaseModel):
    """A single extracted action item/decision and its verification status
    (only present when the multi-agent pipeline was used)."""
    claim_type: str
    text: str
    owner: Optional[str] = None
    due_date: Optional[str] = None
    verified: bool
    rejection_reason: Optional[str] = None


class AskRequest(BaseModel):
    """A cross-meeting question for the RAG knowledge base."""
    question: str
    meeting_id: Optional[str] = None  # restrict retrieval to one meeting
    top_k: int = 5


class Source(BaseModel):
    """A cited transcript excerpt backing an /api/ask answer."""
    citation: str
    meeting_id: str
    start: float
    end: float
    score: float


class AskResponse(BaseModel):
    """Answer from the RAG knowledge base, or a refusal if nothing was retrieved."""
    answer: str
    grounded: bool
    sources: List[Source]


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
    claims: Optional[List[Claim]] = None
    verification_rate: Optional[float] = None

