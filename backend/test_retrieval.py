from app.retrieval import chunk_segments, TfidfIndex


def test_chunk_segments_groups_consecutive_same_speaker():
    segments = [
        {"speaker": "Alice", "start": 0, "end": 2, "text": "Let's discuss the budget."},
        {"speaker": "Alice", "start": 2, "end": 4, "text": "We have ten thousand dollars."},
        {"speaker": "Bob", "start": 4, "end": 6, "text": "That should be enough."},
    ]
    chunks = chunk_segments(segments, meeting_id="ES9999")
    assert len(chunks) == 2
    assert chunks[0].speaker == "Alice"
    assert "budget" in chunks[0].text and "thousand" in chunks[0].text
    assert chunks[1].speaker == "Bob"
    assert chunks[0].start_time == 0
    assert chunks[0].end_time == 4


def test_chunk_segments_splits_on_max_words_overflow():
    long_text = " ".join(["word"] * 100)
    segments = [
        {"speaker": "Alice", "start": 0, "end": 1, "text": long_text},
        {"speaker": "Alice", "start": 1, "end": 2, "text": long_text},
    ]
    chunks = chunk_segments(segments, meeting_id="ES9999", max_words=150)
    assert len(chunks) == 2  # second segment would overflow 150 words, forced split


def test_chunk_segments_skips_empty_text():
    segments = [
        {"speaker": "Alice", "start": 0, "end": 1, "text": ""},
        {"speaker": "Alice", "start": 1, "end": 2, "text": "Actual content here."},
    ]
    chunks = chunk_segments(segments, meeting_id="ES9999")
    assert len(chunks) == 1
    assert chunks[0].text == "Actual content here."


def test_tfidf_index_ranks_relevant_chunk_first():
    segments = [
        {"speaker": "Alice", "start": 0, "end": 5, "text": "We decided to use a plastic case for the remote control."},
        {"speaker": "Bob", "start": 5, "end": 10, "text": "The quarterly marketing budget was approved yesterday."},
        {"speaker": "Carol", "start": 10, "end": 15, "text": "Lunch options include pizza and salad today."},
    ]
    chunks = chunk_segments(segments, meeting_id="ES9999", max_words=20)
    index = TfidfIndex(chunks)

    results = index.query("what case material did the team choose for the remote?", top_k=2)
    assert len(results) >= 1
    top_chunk, top_score = results[0]
    assert "plastic case" in top_chunk.text


def test_tfidf_index_returns_empty_for_no_chunks():
    index = TfidfIndex([])
    assert index.query("anything") == []


def test_tfidf_index_min_score_filters_irrelevant_results():
    segments = [
        {"speaker": "Alice", "start": 0, "end": 5, "text": "We decided to use a plastic case for the remote control."},
    ]
    chunks = chunk_segments(segments, meeting_id="ES9999")
    index = TfidfIndex(chunks)

    results = index.query("completely unrelated astrophysics jargon supernova quasar", min_score=0.9)
    assert results == []
