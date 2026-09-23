"""
Cross-meeting knowledge graph over verified claims.

Only claims the VerifierAgent (backend/app/agents.py) marked verified=True are
ever added here -- an unverified claim is, by construction, one the pipeline
couldn't confirm was actually said in the meeting, and a knowledge graph that
lets those in stops being a trustworthy "second brain" the moment one bad
node ships. This is the same principle as the RAG layer's refusal-when-
ungrounded behavior, applied to structured storage instead of a generated
answer.

Graph shape (a property graph, not a full ontology -- deliberately simple):

    meeting:<id> --CONTAINS--> claim:<id>
    person:<name> --OWNS-----> claim:<id>       (only when the claim has an owner)
    claim:<id>    --TAGGED----> topic:<keyword>   (lightweight keyword extraction)

This enables the two query patterns a "what's outstanding" tool needs:
everything owned by a person across every meeting, and how a topic has come
up over time.

Why an embedded graph library (networkx) instead of a graph database server:
same reasoning as TF-IDF vs. embeddings in retrieval.py -- this pipeline is a
single Python service, and a corpus of a few hundred claims across a few
dozen meetings doesn't need Neo4j's operational overhead. The graph is
persisted as JSON (networkx node-link format) alongside the other pipeline
outputs; swapping to a real graph database later is a storage-layer change
behind the same KnowledgeGraph interface, not a rearchitecture.
"""

import json
import logging
import os
import re
from typing import Optional

import networkx as nx

from .evaluation import _STOPWORDS

logger = logging.getLogger(__name__)

DEFAULT_STORE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "outputs", "knowledge_graph.json"
)


def _normalize_person(name: str) -> str:
    return " ".join(name.strip().lower().split())


def extract_topics(text: str, max_topics: int = 3) -> list[str]:
    """Lightweight keyword extraction: unique content words (len > 3, not a
    stopword), in order of first appearance, capped at max_topics. Not a
    substitute for real NLP topic modeling -- a deliberately cheap heuristic
    that's fast, dependency-free and fully deterministic (so it's testable
    without mocking a model), documented as such rather than passed off as
    more than it is."""
    words = re.findall(r"[a-z][a-z']+", text.lower())
    topics = []
    for w in words:
        if w in _STOPWORDS or len(w) <= 3:
            continue
        if w not in topics:
            topics.append(w)
        if len(topics) >= max_topics:
            break
    return topics


class KnowledgeGraph:
    """Persisted, queryable graph of verified claims across meetings."""

    def __init__(self, store_path: str = DEFAULT_STORE_PATH):
        self.store_path = store_path
        self.graph = nx.MultiDiGraph()
        self._load()

    def _load(self):
        if not os.path.exists(self.store_path):
            return
        with open(self.store_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.graph = _node_link_graph(data)
        logger.info("Loaded knowledge graph: %d nodes, %d edges from %s",
                    self.graph.number_of_nodes(), self.graph.number_of_edges(), self.store_path)

    def _save(self):
        os.makedirs(os.path.dirname(self.store_path), exist_ok=True)
        data = _node_link_data(self.graph)
        with open(self.store_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def add_verified_claims(self, meeting_id: str, claims: list[dict], meeting_date: Optional[str] = None) -> int:
        """
        Ingest a meeting's verified claims (as produced by
        MultiAgentMinutesPipeline.process_transcript -> result['claims']).
        Unverified claims are silently skipped -- by design, see module docstring.
        Returns the number of claim nodes added.
        """
        meeting_node = f"meeting:{meeting_id}"
        if meeting_node not in self.graph:
            self.graph.add_node(meeting_node, type="meeting", meeting_id=meeting_id, date=meeting_date)

        added = 0
        for i, claim in enumerate(claims):
            if not claim.get("verified"):
                continue

            claim_node = f"claim:{meeting_id}_{i:03d}"
            self.graph.add_node(
                claim_node, type="claim", meeting_id=meeting_id,
                claim_type=claim.get("claim_type"), text=claim.get("text"),
                owner=claim.get("owner"), due_date=claim.get("due_date"),
            )
            self.graph.add_edge(meeting_node, claim_node, relation="CONTAINS")

            owner = claim.get("owner")
            if owner:
                person_node = f"person:{_normalize_person(owner)}"
                if person_node not in self.graph:
                    self.graph.add_node(person_node, type="person", name=owner)
                self.graph.add_edge(person_node, claim_node, relation="OWNS")

            for topic in extract_topics(claim.get("text", "")):
                topic_node = f"topic:{topic}"
                if topic_node not in self.graph:
                    self.graph.add_node(topic_node, type="topic", keyword=topic)
                self.graph.add_edge(claim_node, topic_node, relation="TAGGED")

            added += 1

        self._save()
        return added

    def _claim_nodes_from(self, source_node: str) -> list[dict]:
        if source_node not in self.graph:
            return []
        claims = []
        for _, target, data in self.graph.out_edges(source_node, data=True):
            node_data = self.graph.nodes[target]
            if node_data.get("type") == "claim":
                claims.append({"claim_node": target, **node_data})
        return claims

    def claims_by_owner(self, owner: str) -> list[dict]:
        return self._claim_nodes_from(f"person:{_normalize_person(owner)}")

    def claims_by_topic(self, topic: str) -> list[dict]:
        topic_node = f"topic:{topic.lower().strip()}"
        if topic_node not in self.graph:
            return []
        claims = []
        for source, _, data in self.graph.in_edges(topic_node, data=True):
            node_data = self.graph.nodes[source]
            if node_data.get("type") == "claim":
                claims.append({"claim_node": source, **node_data})
        return claims

    def topic_timeline(self, topic: str) -> list[dict]:
        """Claims tagged with topic, ordered by their meeting's insertion
        order into the graph -- a coarse but dependency-free stand-in for
        "how has this decision evolved over time" when meeting_date isn't
        reliably available for every meeting."""
        claims = self.claims_by_topic(topic)
        meeting_order = {n: i for i, n in enumerate(
            n for n, d in self.graph.nodes(data=True) if d.get("type") == "meeting"
        )}
        return sorted(claims, key=lambda c: meeting_order.get(f"meeting:{c['meeting_id']}", 0))

    def stats(self) -> dict:
        by_type = {}
        for _, data in self.graph.nodes(data=True):
            t = data.get("type", "unknown")
            by_type[t] = by_type.get(t, 0) + 1
        return {
            "total_nodes": self.graph.number_of_nodes(),
            "total_edges": self.graph.number_of_edges(),
            "nodes_by_type": by_type,
        }


def _node_link_data(graph):
    """networkx >=3.4 requires `edges=` (the `link` kwarg is deprecated);
    older versions don't accept `edges=` at all -- support both installs."""
    try:
        return nx.node_link_data(graph, edges="edges")
    except TypeError:
        return nx.node_link_data(graph)


def _node_link_graph(data):
    try:
        return nx.node_link_graph(data, edges="edges")
    except TypeError:
        return nx.node_link_graph(data)
