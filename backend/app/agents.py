"""
Multi-agent minutes pipeline: Extract -> Verify -> Write.

The single-shot approach in MeetingMinutesGenerator.generate_minutes() asks
one LLM call to read the whole transcript and produce a finished markdown
document in one pass. That call has no way to check its own claims against
the source material, so a fabricated action item looks identical to a real
one in the output.

This module splits generation into three stages with one clear
responsibility each, mirroring how a person would actually minute a meeting:

  1. ExtractorAgent (LLM):   pull out candidate action items/decisions, each
                              with a verbatim supporting quote.
  2. VerifierAgent (rule-based): check each quote actually appears in the
                              transcript and that the claim's content is
                              grounded in it. Deterministic and unit-testable
                              on its own -- a verifier that itself calls an
                              LLM can hallucinate too, so grounding is
                              checked directly against text instead.
  3. WriterAgent (LLM):      format only the *verified* claims into the final
                              document, and separately lists anything the
                              verifier rejected so a human can review it
                              instead of it silently vanishing or silently
                              shipping unverified.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .evaluation import _content_words

logger = logging.getLogger(__name__)

_JSON_BLOCK = re.compile(r'\[.*\]', re.DOTALL)


@dataclass
class Claim:
    """A single extracted action item or decision, with its verification state."""
    claim_type: str  # "action_item" | "decision"
    text: str
    owner: Optional[str]
    due_date: Optional[str]
    source_quote: str
    verified: bool = False
    rejection_reason: Optional[str] = None


class ExtractorAgent:
    """Pulls structured claims (with citations) out of a transcript via the LLM."""

    def __init__(self, api_call):
        # api_call: MeetingMinutesGenerator._api_call_with_retry, reused so
        # extraction gets the same retry/backoff behavior as everything else.
        self._api_call = api_call

    def extract(self, structured_input: str) -> list[Claim]:
        prompt = f"""You are extracting structured facts from a meeting transcript. Read the transcript and list every action item and decision.

TRANSCRIPT:
{structured_input}

Return ONLY a JSON array (no prose, no markdown fences). Each element:
{{
  "claim_type": "action_item" or "decision",
  "text": "concise statement of the action item or decision",
  "owner": "person responsible, or null",
  "due_date": "due date if mentioned, or null",
  "source_quote": "a short VERBATIM quote from the transcript that supports this claim"
}}

If there are no action items or decisions, return [].
The source_quote must be copied exactly from the transcript, not paraphrased."""

        raw = self._api_call(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
            temperature=0.0,
        )
        return self._parse(raw)

    @staticmethod
    def _parse(raw: str) -> list[Claim]:
        match = _JSON_BLOCK.search(raw)
        payload = match.group(0) if match else raw
        try:
            items = json.loads(payload)
        except json.JSONDecodeError:
            logger.warning("ExtractorAgent: could not parse LLM output as JSON, returning no claims")
            return []

        claims = []
        for item in items:
            if not isinstance(item, dict) or not item.get("text"):
                continue
            claims.append(Claim(
                claim_type=item.get("claim_type", "action_item"),
                text=item["text"].strip(),
                owner=item.get("owner") or None,
                due_date=item.get("due_date") or None,
                source_quote=(item.get("source_quote") or "").strip(),
            ))
        return claims


class VerifierAgent:
    """Deterministically checks each claim's quote and content against the source transcript."""

    QUOTE_MIN_LEN = 6       # a too-short quote is nearly free to "support" by chance
    QUOTE_OVERLAP_THRESHOLD = 0.55  # fraction of quote's content words that must appear in transcript
    CONTENT_OVERLAP_THRESHOLD = 0.35  # fraction of claim's content words that must appear in transcript

    def verify(self, claims: list[Claim], source_transcript: str) -> list[Claim]:
        transcript_words = _content_words(source_transcript)

        for claim in claims:
            quote = claim.source_quote
            if len(quote) < self.QUOTE_MIN_LEN:
                claim.verified = False
                claim.rejection_reason = "source_quote too short to verify"
                continue

            # LLMs reliably paraphrase even when asked for verbatim quotes, so a
            # hard substring match rejects almost everything. Word-overlap on the
            # quote's content words is a better grounding signal: if ≥55% of the
            # meaningful words in the quote actually appear in the transcript, the
            # quote is grounded even if the exact phrasing differs slightly.
            quote_words = _content_words(quote)
            if quote_words:
                quote_overlap = len(quote_words & transcript_words) / len(quote_words)
                if quote_overlap < self.QUOTE_OVERLAP_THRESHOLD:
                    claim.verified = False
                    claim.rejection_reason = f"source_quote words not sufficiently grounded in transcript ({quote_overlap:.2f} < {self.QUOTE_OVERLAP_THRESHOLD})"
                    continue

            claim_words = _content_words(claim.text)
            if claim_words:
                overlap = len(claim_words & transcript_words) / len(claim_words)
                if overlap < self.CONTENT_OVERLAP_THRESHOLD:
                    claim.verified = False
                    claim.rejection_reason = f"claim content overlap with transcript too low ({overlap:.2f})"
                    continue

            claim.verified = True
            claim.rejection_reason = None

        return claims

    @staticmethod
    def _normalize(text: str) -> str:
        return ' '.join(text.lower().split())


class WriterAgent:
    """Formats verified claims (plus the executive summary) into the final markdown document."""

    def __init__(self, api_call):
        self._api_call = api_call

    def write(self, structured_input: str, summary: str, claims: list[Claim]) -> str:
        verified = [c for c in claims if c.verified]
        rejected = [c for c in claims if not c.verified]

        verified_json = json.dumps([
            {"claim_type": c.claim_type, "text": c.text, "owner": c.owner, "due_date": c.due_date}
            for c in verified
        ], indent=2)

        prompt = f"""You are a professional meeting documentation specialist. Using the transcript and the pre-verified list of action items/decisions below, write formal Minutes of Meeting.

TRANSCRIPT:
{structured_input}

VERIFIED ACTION ITEMS AND DECISIONS (already fact-checked against the transcript -- use these, do not invent additional ones):
{verified_json}

Generate meeting minutes with this structure (markdown):

# MEETING MINUTES
**Date:** {datetime.now().strftime('%B %d, %Y')}

## ATTENDEES
- [List all speakers with their roles if mentioned]

## AGENDA ITEMS

### 1. [Topic/Section Name]
- **[Speaker Name]**: [Key points and context]

## ACTION ITEMS
- [ ] [action item text] — Assigned to: [owner or Unassigned] — Due: [due date or Not specified]

## DECISIONS MADE
- [decision text]

## NOTES
- [Any additional context from the transcript]

Only include action items and decisions from the VERIFIED list above in those sections. Use the transcript for attendees, agenda items and notes."""

        minutes = self._api_call(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4000,
            temperature=0.1,
        )

        if rejected:
            review_section = "\n\n## UNVERIFIED (flagged by automated fact-check, needs human review)\n"
            for c in rejected:
                review_section += f"- [{c.claim_type}] {c.text} — reason: {c.rejection_reason}\n"
            minutes += review_section

        return minutes


class MultiAgentMinutesPipeline:
    """Orchestrates Extract -> Verify -> Write as an alternative to single-shot generation."""

    def __init__(self, generator):
        # generator: a MeetingMinutesGenerator, reused for its API client,
        # retry logic, segment loading, and structured-input formatting.
        self._generator = generator
        self._extractor = ExtractorAgent(generator._api_call_with_retry)
        self._verifier = VerifierAgent()
        self._writer = WriterAgent(generator._api_call_with_retry)

    def process_transcript(self, transcript_data: dict) -> dict:
        segments = self._generator.load_segments(transcript_data)
        if not segments:
            raise ValueError("No valid segments found in transcript data")

        structured_input = self._generator.create_structured_input(segments)
        source_transcript = ' '.join(s.text for s in segments)

        logger.info("Extracting candidate claims...")
        claims = self._extractor.extract(structured_input)

        logger.info("Verifying %d claims against transcript...", len(claims))
        claims = self._verifier.verify(claims, source_transcript)
        verified_count = sum(1 for c in claims if c.verified)
        logger.info("%d/%d claims verified", verified_count, len(claims))

        logger.info("Generating executive summary...")
        summary = self._generator.generate_summary(structured_input)

        logger.info("Writing final minutes from verified claims...")
        minutes = self._writer.write(structured_input, summary, claims)

        base_result = self._generator._build_result(segments, summary, minutes)
        base_result['claims'] = [
            {
                'claim_type': c.claim_type, 'text': c.text, 'owner': c.owner,
                'due_date': c.due_date, 'verified': c.verified,
                'rejection_reason': c.rejection_reason,
            }
            for c in claims
        ]
        base_result['verification_rate'] = round(verified_count / len(claims), 4) if claims else 1.0
        return base_result
