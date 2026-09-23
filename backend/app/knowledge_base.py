"""
Cross-meeting knowledge base: persists transcript chunks from every meeting
run through the pipeline and answers questions against them with retrieval-
augmented generation.

This is the "centralized second brain across internal systems" pattern —
instead of asking an LLM to answer from parametric memory (which is exactly
how hallucination happens), every answer is generated *only* from retrieved
transcript excerpts, and the excerpts are cited so a claim can be traced back
to who said it, in which meeting, at what timestamp. If nothing relevant is
retrieved, the system refuses rather than lets the LLM guess -- that refusal
path is the actual hallucination defense; the citations are what make an
answer auditable after the fact.
"""

import json
import logging
import os
from typing import Optional

from .retrieval import TranscriptChunk, TfidfIndex, chunk_segments

logger = logging.getLogger(__name__)

DEFAULT_STORE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "outputs", "knowledge_base.jsonl")

_NO_CONTEXT_ANSWER = (
    "I don't have enough grounded information in the indexed meetings to answer that."
)


class MeetingKnowledgeBase:
    """Persists chunks across meetings (JSONL) and answers questions via RAG."""

    def __init__(self, store_path: str = DEFAULT_STORE_PATH):
        self.store_path = store_path
        self.chunks: list[TranscriptChunk] = []
        self._load()

    def _load(self):
        if not os.path.exists(self.store_path):
            return
        with open(self.store_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                self.chunks.append(TranscriptChunk(**data))
        logger.info("Loaded %d chunks from %s", len(self.chunks), self.store_path)

    def index_meeting(self, meeting_id: str, segments: list, max_words: int = 150) -> int:
        """Chunk a meeting's segments and append them to the persisted store.
        Returns the number of chunks added."""
        new_chunks = chunk_segments(segments, meeting_id=meeting_id, max_words=max_words)

        os.makedirs(os.path.dirname(self.store_path), exist_ok=True)
        with open(self.store_path, "a", encoding="utf-8") as f:
            for chunk in new_chunks:
                f.write(json.dumps(chunk.__dict__) + "\n")

        self.chunks.extend(new_chunks)
        logger.info("Indexed %d chunks for meeting %s", len(new_chunks), meeting_id)
        return len(new_chunks)

    def query(self, question: str, top_k: int = 5, meeting_id: Optional[str] = None,
              min_score: float = 0.05) -> list[tuple]:
        pool = [c for c in self.chunks if meeting_id is None or c.meeting_id == meeting_id]
        return TfidfIndex(pool).query(question, top_k=top_k, min_score=min_score)

    def answer(self, question: str, api_call, top_k: int = 5,
               meeting_id: Optional[str] = None, min_score: float = 0.05) -> dict:
        """
        Retrieval-augmented answer. api_call is a callable with the same
        signature as MeetingMinutesGenerator._api_call_with_retry
        (messages, max_tokens, temperature) -> str, reused so this gets the
        same retry/backoff behavior as the rest of the pipeline.
        """
        retrieved = self.query(question, top_k=top_k, meeting_id=meeting_id, min_score=min_score)

        if not retrieved:
            return {"answer": _NO_CONTEXT_ANSWER, "grounded": False, "sources": []}

        context_blocks = []
        for chunk, score in retrieved:
            context_blocks.append(f"[{chunk.citation()}]\n{chunk.text}")
        context = "\n\n".join(context_blocks)

        prompt = f"""Answer the question using ONLY the excerpts below. Each excerpt is labeled with its source citation.
If the excerpts don't contain enough information to answer, say so explicitly instead of guessing.
Cite the source (e.g. "ES2003 [04:12] Bob") for every claim you make.

EXCERPTS:
{context}

QUESTION: {question}

ANSWER (with citations):"""

        answer_text = api_call(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=600,
            temperature=0.0,
        )

        return {
            "answer": answer_text,
            "grounded": True,
            "sources": [
                {"citation": chunk.citation(), "meeting_id": chunk.meeting_id,
                 "start": chunk.start_time, "end": chunk.end_time, "score": round(score, 4)}
                for chunk, score in retrieved
            ],
        }
