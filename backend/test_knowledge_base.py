import os

from app.knowledge_base import MeetingKnowledgeBase, _NO_CONTEXT_ANSWER


def _segments():
    return [
        {"speaker": "Alice", "start": 0, "end": 5, "text": "We decided to use a plastic case for the remote control."},
        {"speaker": "Bob", "start": 5, "end": 10, "text": "I will follow up on pricing with the supplier next week."},
    ]


def test_index_and_reload_persists_chunks(tmp_path):
    store_path = str(tmp_path / "kb.jsonl")

    kb = MeetingKnowledgeBase(store_path=store_path)
    added = kb.index_meeting("ES2002", _segments())
    assert added == 2
    assert os.path.exists(store_path)

    reloaded = MeetingKnowledgeBase(store_path=store_path)
    assert len(reloaded.chunks) == 2
    assert reloaded.chunks[0].meeting_id == "ES2002"


def test_query_filters_by_meeting_id(tmp_path):
    kb = MeetingKnowledgeBase(store_path=str(tmp_path / "kb.jsonl"))
    kb.index_meeting("ES2002", _segments())
    kb.index_meeting("ES2003", [
        {"speaker": "Carol", "start": 0, "end": 5, "text": "The prototype battery life needs improvement."},
    ])

    results_all = kb.query("battery life")
    results_scoped = kb.query("battery life", meeting_id="ES2002")

    assert any(c.meeting_id == "ES2003" for c, _ in results_all)
    assert all(c.meeting_id == "ES2002" for c, _ in results_scoped) or results_scoped == []


def test_answer_refuses_when_nothing_indexed(tmp_path):
    kb = MeetingKnowledgeBase(store_path=str(tmp_path / "kb.jsonl"))

    called = []
    def fake_api_call(messages, max_tokens=600, temperature=0.0):
        called.append(messages)
        return "should not be called"

    result = kb.answer("What did we decide about the remote's case material?", fake_api_call)
    assert result["grounded"] is False
    assert result["answer"] == _NO_CONTEXT_ANSWER
    assert result["sources"] == []
    assert called == []  # LLM must not be called when nothing was retrieved


def test_answer_uses_retrieved_context_and_cites_sources(tmp_path):
    kb = MeetingKnowledgeBase(store_path=str(tmp_path / "kb.jsonl"))
    kb.index_meeting("ES2002", _segments())

    captured_prompt = {}
    def fake_api_call(messages, max_tokens=600, temperature=0.0):
        captured_prompt["content"] = messages[0]["content"]
        return "The team decided to use a plastic case. [ES2002 [00:00] Alice]"

    result = kb.answer("What material did the team choose for the case?", fake_api_call)

    assert result["grounded"] is True
    assert "plastic case" in captured_prompt["content"]
    assert len(result["sources"]) >= 1
    assert result["sources"][0]["meeting_id"] == "ES2002"
