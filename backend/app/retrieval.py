"""
Retrieval layer: chunks meeting transcripts into retrievable units and ranks
them against a query with TF-IDF + cosine similarity.

Why TF-IDF instead of dense embeddings: meeting transcript corpora here are
small (dozens to low hundreds of chunks per meeting), so a classic sparse
retriever gets ranking quality competitive with a dense encoder while adding
zero model-download/network dependency and zero GPU requirement — meaningful
for a pipeline that already runs Whisper + pyannote locally on CPU. The
tradeoff is it won't match on paraphrase/synonymy the way embeddings would;
`TfidfIndex` is the one place that assumption lives, so swapping in a
sentence-transformer encoder later only touches this file.
"""

from dataclasses import dataclass, field

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


@dataclass
class TranscriptChunk:
    """A retrievable unit of transcript: several consecutive same-speaker
    segments, capped in size so retrieval is finer-grained than "whole
    meeting" but coarser than "one utterance" (which would lose context)."""
    chunk_id: str
    meeting_id: str
    speaker: str
    start_time: float
    end_time: float
    text: str

    def citation(self) -> str:
        mins_s, secs_s = divmod(int(self.start_time), 60)
        return f"{self.meeting_id} [{mins_s:02d}:{secs_s:02d}] {self.speaker}"


def _field(seg, dict_key: str, attr_key: str):
    """Segments arrive either as MeetingSegment objects (start_time/end_time
    attributes) or as plain dicts (start/end keys, e.g. from a transcript
    JSON payload) -- normalize both to one accessor."""
    if isinstance(seg, dict):
        return seg.get(dict_key)
    return getattr(seg, attr_key)


def chunk_segments(segments: list, meeting_id: str, max_words: int = 150) -> list[TranscriptChunk]:
    """Group consecutive same-speaker segments into chunks of up to max_words."""
    chunks: list[TranscriptChunk] = []
    current_speaker = None
    current_texts: list[str] = []
    current_words = 0
    current_start = None
    current_end = None

    def flush():
        nonlocal current_texts, current_words, current_start, current_end
        if current_texts:
            chunks.append(TranscriptChunk(
                chunk_id=f"{meeting_id}_{len(chunks):04d}",
                meeting_id=meeting_id,
                speaker=current_speaker or "UNKNOWN",
                start_time=current_start,
                end_time=current_end,
                text=" ".join(current_texts),
            ))
        current_texts = []
        current_words = 0
        current_start = None
        current_end = None

    for seg in segments:
        speaker = (_field(seg, "speaker", "speaker") or "UNKNOWN")
        text = _field(seg, "text", "text")
        if not text:
            continue
        words = len(text.split())

        speaker_changed = speaker != current_speaker
        would_overflow = current_words + words > max_words
        if speaker_changed or would_overflow:
            flush()
            current_speaker = speaker

        if current_start is None:
            current_start = _field(seg, "start", "start_time")
        current_end = _field(seg, "end", "end_time")
        current_texts.append(text)
        current_words += words

    flush()
    return chunks


class TfidfIndex:
    """In-memory TF-IDF index over a list of TranscriptChunks."""

    def __init__(self, chunks: list[TranscriptChunk]):
        self.chunks = chunks
        self._vectorizer = None
        self._matrix = None
        if chunks:
            self._vectorizer = TfidfVectorizer(stop_words="english")
            self._matrix = self._vectorizer.fit_transform([c.text for c in chunks])

    def query(self, text: str, top_k: int = 5, min_score: float = 0.05) -> list[tuple]:
        """Returns up to top_k (chunk, score) pairs with score >= min_score,
        highest first. Empty list means "nothing relevant was retrieved" --
        callers should treat that as a signal to refuse rather than guess."""
        if not self.chunks:
            return []
        query_vec = self._vectorizer.transform([text])
        scores = cosine_similarity(query_vec, self._matrix)[0]
        ranked = sorted(zip(self.chunks, scores), key=lambda pair: pair[1], reverse=True)
        return [(chunk, float(score)) for chunk, score in ranked[:top_k] if score >= min_score]
