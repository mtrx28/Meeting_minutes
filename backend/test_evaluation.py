from app.evaluation import score_rouge, check_grounding, clean_text


def test_clean_text_strips_markdown_and_lowercases():
    assert clean_text("# **Action** Items\n- Do *this*") == "action items - do this"


def test_score_rouge_identical_text_is_perfect():
    text = "The team decided to ship the remote control by Friday."
    scores = score_rouge(text, text)
    assert scores['rouge1']['f1'] == 1.0
    assert scores['rougeL']['f1'] == 1.0


def test_score_rouge_unrelated_text_is_near_zero():
    reference = "The team discussed marketing budgets and target demographics."
    generated = "Quarterly hardware shipment logistics were rescheduled."
    scores = score_rouge(reference, generated)
    assert scores['rouge1']['f1'] < 0.2


def test_grounding_flags_unsupported_action_item():
    transcript = "Alice: We agreed to use a plastic case. Bob: I'll follow up on pricing."
    minutes = """
## ACTION ITEMS
- [ ] Bob will follow up on pricing
- [ ] Launch the satellite prototype by next Tuesday
"""
    result = check_grounding(minutes, transcript)
    assert result.total_claims == 2
    assert result.supported_claims == 1
    assert "satellite" in result.unsupported[0].lower()
    assert result.score == 0.5


def test_grounding_all_supported_scores_one():
    transcript = "Carol: The budget was approved for the new remote design."
    minutes = """
## DECISIONS MADE
- The budget was approved for the new remote design
"""
    result = check_grounding(minutes, transcript)
    assert result.score == 1.0
    assert result.unsupported == []


def test_grounding_no_claims_defaults_to_perfect_score():
    result = check_grounding("## NOTES\n- General discussion happened", "irrelevant transcript")
    assert result.total_claims == 0
    assert result.score == 1.0
