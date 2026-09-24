"use client";

import { useState, useCallback, useEffect } from "react";
import "./KnowledgeGraphPanel.css";

function ClaimRow({ claim }) {
  return (
    <div className="graph-claim">
      <div className="graph-claim__top">
        <span className={`badge ${claim.claim_type === "decision" ? "badge-accent" : "badge-success"}`}>
          {claim.claim_type === "decision" ? "decision" : "action item"}
        </span>
        <span className="graph-claim__meeting">{claim.meeting_id}</span>
      </div>
      <p className="graph-claim__text">{claim.text}</p>
      {(claim.owner || claim.due_date) && (
        <div className="graph-claim__meta">
          {claim.owner && <span>Owner: {claim.owner}</span>}
          {claim.due_date && <span>Due: {claim.due_date}</span>}
        </div>
      )}
    </div>
  );
}

export default function KnowledgeGraphPanel({ apiBase }) {
  const [mode, setMode] = useState("owner"); // owner | topic
  const [query, setQuery] = useState("");
  const [claims, setClaims] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [stats, setStats] = useState(null);

  useEffect(() => {
    fetch(`${apiBase}/api/graph/stats`)
      .then((res) => (res.ok ? res.json() : null))
      .then(setStats)
      .catch(() => setStats(null));
  }, [apiBase]);

  const handleSearch = useCallback(async () => {
    const trimmed = query.trim();
    if (!trimmed) return;
    setLoading(true);
    setError(null);
    setClaims(null);
    try {
      const path = mode === "owner" ? `/api/graph/owner/${encodeURIComponent(trimmed)}` : `/api/graph/topic/${encodeURIComponent(trimmed)}`;
      const res = await fetch(`${apiBase}${path}`);
      if (!res.ok) throw new Error("Request failed");
      const data = await res.json();
      setClaims(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [apiBase, mode, query]);

  const handleKeyDown = useCallback(
    (e) => {
      if (e.key === "Enter") handleSearch();
    },
    [handleSearch]
  );

  return (
    <div className="graph-panel animate-fade-in-up">
      <div className="graph-panel__header">
        <h2>Cross-meeting knowledge graph</h2>
        <p className="graph-panel__subtitle">
          Built only from <strong>verified</strong> claims (meetings processed with the multi-agent
          pipeline) — person owns claim, claim belongs to meeting, claim tagged with topic.
        </p>
      </div>

      {stats && (
        <div className="graph-stats-row">
          <div className="graph-stat">
            <span className="graph-stat__value">{stats.nodes_by_type?.claim || 0}</span>
            <span className="graph-stat__label">verified claims</span>
          </div>
          <div className="graph-stat">
            <span className="graph-stat__value">{stats.nodes_by_type?.meeting || 0}</span>
            <span className="graph-stat__label">meetings</span>
          </div>
          <div className="graph-stat">
            <span className="graph-stat__value">{stats.nodes_by_type?.person || 0}</span>
            <span className="graph-stat__label">people</span>
          </div>
          <div className="graph-stat">
            <span className="graph-stat__value">{stats.nodes_by_type?.topic || 0}</span>
            <span className="graph-stat__label">topics</span>
          </div>
        </div>
      )}

      <div className="graph-search">
        <div className="graph-mode-toggle">
          <button
            className={`graph-mode-btn ${mode === "owner" ? "graph-mode-btn--active" : ""}`}
            onClick={() => setMode("owner")}
          >
            By owner
          </button>
          <button
            className={`graph-mode-btn ${mode === "topic" ? "graph-mode-btn--active" : ""}`}
            onClick={() => setMode("topic")}
          >
            By topic
          </button>
        </div>
        <div className="graph-search__input-row">
          <input
            type="text"
            placeholder={mode === "owner" ? "e.g. Bob" : "e.g. pricing"}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
          />
          <button className="btn-process" onClick={handleSearch} disabled={!query.trim() || loading}>
            {loading ? "Searching..." : "Search"}
          </button>
        </div>
      </div>

      {error && <div className="upload-error">{error}</div>}

      {claims !== null && (
        <div className="graph-results">
          {claims.length === 0 ? (
            <p className="graph-panel__empty">
              No verified claims found for &ldquo;{query}&rdquo;.
            </p>
          ) : (
            claims.map((c, i) => <ClaimRow key={c.claim_node || i} claim={c} />)
          )}
        </div>
      )}
    </div>
  );
}
