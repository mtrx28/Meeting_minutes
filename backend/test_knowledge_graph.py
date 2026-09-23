from app.knowledge_graph import KnowledgeGraph, extract_topics


def _verified_claims():
    return [
        {"claim_type": "action_item", "text": "Bob will follow up on remote pricing",
         "owner": "Bob", "due_date": "Friday", "verified": True, "rejection_reason": None},
        {"claim_type": "decision", "text": "The team decided on a plastic case",
         "owner": None, "due_date": None, "verified": True, "rejection_reason": None},
        {"claim_type": "action_item", "text": "Launch the satellite prototype",
         "owner": "Bob", "due_date": None, "verified": False,
         "rejection_reason": "source_quote not found verbatim in transcript"},
    ]


def test_extract_topics_is_deterministic_and_skips_stopwords_and_short_words():
    topics = extract_topics("Bob will follow up on the remote pricing plan")
    assert "the" not in topics
    assert "on" not in topics
    assert "follow" in topics
    assert len(topics) <= 3


def test_unverified_claims_are_never_added(tmp_path):
    kg = KnowledgeGraph(store_path=str(tmp_path / "kg.json"))
    added = kg.add_verified_claims("ES2002", _verified_claims())

    assert added == 2  # only the two verified=True claims
    stats = kg.stats()
    assert stats["nodes_by_type"].get("claim", 0) == 2
    # the fabricated satellite claim must not exist anywhere in the graph
    all_texts = [d.get("text") for _, d in kg.graph.nodes(data=True) if d.get("type") == "claim"]
    assert not any("satellite" in (t or "") for t in all_texts)


def test_claims_by_owner_returns_only_that_owners_claims(tmp_path):
    kg = KnowledgeGraph(store_path=str(tmp_path / "kg.json"))
    kg.add_verified_claims("ES2002", _verified_claims())

    bob_claims = kg.claims_by_owner("Bob")
    assert len(bob_claims) == 1
    assert bob_claims[0]["text"] == "Bob will follow up on remote pricing"

    # owner lookup is case/whitespace-insensitive
    assert kg.claims_by_owner("  bob  ") == bob_claims

    assert kg.claims_by_owner("Nobody") == []


def test_claims_by_topic_and_timeline_span_multiple_meetings(tmp_path):
    kg = KnowledgeGraph(store_path=str(tmp_path / "kg.json"))
    kg.add_verified_claims("ES2002", [
        {"claim_type": "decision", "text": "Use a plastic case for the remote",
         "owner": None, "due_date": None, "verified": True, "rejection_reason": None},
    ])
    kg.add_verified_claims("ES2003", [
        {"claim_type": "decision", "text": "Reconsider the plastic case material",
         "owner": None, "due_date": None, "verified": True, "rejection_reason": None},
    ])

    timeline = kg.topic_timeline("plastic")
    assert len(timeline) == 2
    assert [c["meeting_id"] for c in timeline] == ["ES2002", "ES2003"]


def test_graph_persists_and_reloads(tmp_path):
    store_path = str(tmp_path / "kg.json")
    kg = KnowledgeGraph(store_path=store_path)
    kg.add_verified_claims("ES2002", _verified_claims())

    reloaded = KnowledgeGraph(store_path=store_path)
    assert reloaded.stats() == kg.stats()
    assert len(reloaded.claims_by_owner("Bob")) == 1


def test_stats_counts_node_types(tmp_path):
    kg = KnowledgeGraph(store_path=str(tmp_path / "kg.json"))
    kg.add_verified_claims("ES2002", _verified_claims())
    stats = kg.stats()
    assert stats["nodes_by_type"]["meeting"] == 1
    assert stats["nodes_by_type"]["claim"] == 2
    assert stats["nodes_by_type"]["person"] == 1
    assert stats["total_nodes"] == sum(stats["nodes_by_type"].values())
