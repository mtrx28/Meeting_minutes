import json
from unittest.mock import patch

from app.agents import Claim, ExtractorAgent, VerifierAgent, WriterAgent, MultiAgentMinutesPipeline
from app.minutes_generator import MeetingMinutesGenerator


def test_extractor_parses_clean_json():
    raw = json.dumps([
        {"claim_type": "action_item", "text": "Bob will follow up on pricing",
         "owner": "Bob", "due_date": None, "source_quote": "I'll follow up on pricing"},
    ])
    claims = ExtractorAgent._parse(raw)
    assert len(claims) == 1
    assert claims[0].text == "Bob will follow up on pricing"
    assert claims[0].owner == "Bob"


def test_extractor_parses_json_wrapped_in_markdown_fence():
    raw = "Here you go:\n```json\n[{\"claim_type\": \"decision\", \"text\": \"Use plastic case\", " \
          "\"owner\": null, \"due_date\": null, \"source_quote\": \"we agreed to use a plastic case\"}]\n```"
    claims = ExtractorAgent._parse(raw)
    assert len(claims) == 1
    assert claims[0].claim_type == "decision"


def test_extractor_returns_empty_on_unparseable_output():
    claims = ExtractorAgent._parse("I couldn't find any action items.")
    assert claims == []


def test_verifier_accepts_claim_with_verbatim_quote_and_overlapping_content():
    transcript = "Alice: We agreed to use a plastic case for the remote. Bob: I'll follow up on pricing next week."
    claims = [Claim(
        claim_type="decision", text="use a plastic case for the remote", owner=None, due_date=None,
        source_quote="We agreed to use a plastic case for the remote",
    )]
    result = VerifierAgent().verify(claims, transcript)
    assert result[0].verified is True
    assert result[0].rejection_reason is None


def test_verifier_rejects_claim_with_fabricated_quote():
    transcript = "Alice: We agreed to use a plastic case for the remote."
    claims = [Claim(
        claim_type="action_item", text="Launch satellite prototype Tuesday",
        owner=None, due_date="Tuesday",
        # No words from this quote exist in the transcript above
        source_quote="launch satellite prototype Tuesday deadline",
    )]
    result = VerifierAgent().verify(claims, transcript)
    assert result[0].verified is False
    assert "grounded" in result[0].rejection_reason


def test_verifier_rejects_too_short_quote():
    claims = [Claim(claim_type="decision", text="Something", owner=None, due_date=None, source_quote="ok")]
    result = VerifierAgent().verify(claims, "ok this is fine, ok great")
    assert result[0].verified is False
    assert "too short" in result[0].rejection_reason


def test_writer_appends_unverified_section_for_rejected_claims():
    generator = MeetingMinutesGenerator(api_key="fake")
    with patch.object(generator, "_api_call_with_retry", return_value="# MEETING MINUTES\n..."):
        writer = WriterAgent(generator._api_call_with_retry)
        claims = [
            Claim(claim_type="action_item", text="Verified thing", owner="Alice", due_date=None,
                  source_quote="verified thing was said", verified=True),
            Claim(claim_type="decision", text="Fabricated thing", owner=None, due_date=None,
                  source_quote="fabricated", verified=False, rejection_reason="source_quote too short to verify"),
        ]
        output = writer.write("transcript", "summary", claims)
    assert "UNVERIFIED" in output
    assert "Fabricated thing" in output


def test_multiagent_pipeline_end_to_end_with_mocked_llm():
    generator = MeetingMinutesGenerator(api_key="fake")

    extraction_response = json.dumps([
        {"claim_type": "action_item", "text": "Bob follows up on pricing", "owner": "Bob", "due_date": None,
         "source_quote": "I will follow up on pricing"},
        {"claim_type": "decision", "text": "Team will launch a rocket", "owner": None, "due_date": None,
         "source_quote": "we will launch a rocket to mars"},
    ])

    call_log = []

    def fake_api_call(messages, max_tokens=4000, temperature=0.1):
        content = messages[0]["content"]
        call_log.append(content[:30])
        if "Return ONLY a JSON array" in content:
            return extraction_response
        if "VERIFIED ACTION ITEMS" in content:
            return "# MEETING MINUTES\n\nfinal minutes body"
        return "- Executive summary bullet"

    with patch.object(generator, "_api_call_with_retry", side_effect=fake_api_call):
        pipeline = MultiAgentMinutesPipeline(generator)
        transcript_data = {
            "segments": [
                {"speaker": "Bob", "start": 0, "end": 5, "text": "I will follow up on pricing"},
                {"speaker": "Alice", "start": 5, "end": 10, "text": "Sounds good to me"},
            ]
        }
        result = pipeline.process_transcript(transcript_data)

    assert len(result["claims"]) == 2
    verified = [c for c in result["claims"] if c["verified"]]
    rejected = [c for c in result["claims"] if not c["verified"]]
    assert len(verified) == 1
    assert len(rejected) == 1
    assert "UNVERIFIED" in result["minutes"]
    assert result["verification_rate"] == 0.5
