"""
Evaluation utilities for meeting minutes quality.

Two complementary signals are computed for every generated summary:
  1. ROUGE-1/2/L against a human-written reference summary (lexical overlap —
     "does the summary say the same things a human said").
  2. A grounding/faithfulness score that checks whether the bullet points the
     LLM claims as decisions/action items actually have support in the source
     transcript ("did the model invent anything").

ROUGE alone can't catch hallucination: a summary can score well on ROUGE while
still inventing an action item the meeting never discussed. The grounding
check is a cheap, dependency-free proxy for that failure mode, meant to run
in the same regression gate as ROUGE rather than as a substitute for it.
"""

import re
from dataclasses import dataclass, field

from rouge_score import rouge_scorer
from nltk.stem.porter import PorterStemmer

_stemmer = PorterStemmer()

_STOPWORDS = {
    'the', 'a', 'an', 'and', 'or', 'but', 'to', 'of', 'in', 'on', 'for',
    'with', 'is', 'are', 'was', 'were', 'be', 'been', 'will', 'would',
    'should', 'could', 'that', 'this', 'it', 'as', 'at', 'by', 'from',
    'their', 'they', 'we', 'our', 'has', 'have', 'had', 'not', 'no',
}

_BULLET_SECTION_HEADERS = re.compile(
    r'(action items?|decisions? made|key decisions?)', re.IGNORECASE
)
_BULLET_LINE = re.compile(r'^\s*[-*•]\s*(?:\[.?\]\s*)?(.+)$')


def clean_text(text: str) -> str:
    text = re.sub(r'[*#_`]', '', text)
    return ' '.join(text.split()).lower()


def score_rouge(reference: str, generated: str) -> dict:
    """ROUGE-1/2/L precision/recall/F1 between a reference and generated summary."""
    scorer = rouge_scorer.RougeScorer(['rouge1', 'rouge2', 'rougeL'], use_stemmer=True)
    scores = scorer.score(clean_text(reference), clean_text(generated))
    return {
        metric: {
            'precision': round(s.precision, 4),
            'recall': round(s.recall, 4),
            'f1': round(s.fmeasure, 4),
        }
        for metric, s in scores.items()
    }


def _extract_claim_bullets(minutes_markdown: str) -> list[str]:
    """Pull out bullet lines under ACTION ITEMS / DECISIONS MADE sections.

    These are the highest-stakes claims in the document: an invented action
    item or decision is far more damaging than an invented phrase in the
    free-form notes, so grounding is checked specifically against them.
    """
    lines = minutes_markdown.splitlines()
    claims = []
    in_target_section = False
    for line in lines:
        header_match = re.match(r'^\s*#{1,3}\s*(.+)', line)
        if header_match:
            in_target_section = bool(_BULLET_SECTION_HEADERS.search(header_match.group(1)))
            continue
        if in_target_section:
            bullet_match = _BULLET_LINE.match(line)
            if bullet_match:
                claims.append(bullet_match.group(1).strip())
    return claims


def _content_words(text: str) -> set[str]:
    """Stemmed content words, so 'follows'/'follow' or 'launched'/'launch'
    count as the same word — without stemming, the grounding check rejects
    claims that are paraphrased with a different inflection of a word that
    genuinely appears in the transcript."""
    words = re.findall(r"[a-z0-9']+", text.lower())
    return {_stemmer.stem(w) for w in words if w not in _STOPWORDS and len(w) > 2}


@dataclass
class GroundingResult:
    """Per-claim and aggregate grounding score for one generated document."""
    total_claims: int
    supported_claims: int
    unsupported: list[str] = field(default_factory=list)

    @property
    def score(self) -> float:
        if self.total_claims == 0:
            return 1.0
        return round(self.supported_claims / self.total_claims, 4)


def check_grounding(minutes_markdown: str, source_transcript: str, min_overlap: float = 0.4) -> GroundingResult:
    """
    Flag action items / decisions whose content words barely overlap with the
    source transcript — a lightweight proxy for "the LLM made this up".

    min_overlap is the fraction of a claim's content words that must appear
    somewhere in the transcript for the claim to count as supported.
    """
    transcript_words = _content_words(source_transcript)
    claims = _extract_claim_bullets(minutes_markdown)

    supported = 0
    unsupported = []
    for claim in claims:
        claim_words = _content_words(claim)
        if not claim_words:
            supported += 1
            continue
        overlap = len(claim_words & transcript_words) / len(claim_words)
        if overlap >= min_overlap:
            supported += 1
        else:
            unsupported.append(claim)

    return GroundingResult(total_claims=len(claims), supported_claims=supported, unsupported=unsupported)
