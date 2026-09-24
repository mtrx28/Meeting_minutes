"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import "./AskPanel.css";

export default function AskPanel({ apiBase }) {
  const [messages, setMessages] = useState([]);
  const [question, setQuestion] = useState("");
  const [meetingId, setMeetingId] = useState("");
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, loading]);

  const handleAsk = useCallback(async () => {
    const trimmed = question.trim();
    if (!trimmed || loading) return;

    setMessages((prev) => [...prev, { role: "user", text: trimmed }]);
    setQuestion("");
    setLoading(true);

    try {
      const res = await fetch(`${apiBase}/api/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: trimmed,
          top_k: 5,
          ...(meetingId.trim() ? { meeting_id: meetingId.trim() } : {}),
        }),
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || "Request failed");
      }
      const data = await res.json();
      setMessages((prev) => [...prev, { role: "assistant", ...data }]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", answer: `Error: ${err.message}`, grounded: false, sources: [] },
      ]);
    } finally {
      setLoading(false);
    }
  }, [question, meetingId, loading, apiBase]);

  const handleKeyDown = useCallback(
    (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleAsk();
      }
    },
    [handleAsk]
  );

  return (
    <div className="ask-panel animate-fade-in-up">
      <div className="ask-panel__header">
        <h2>Ask across your meetings</h2>
        <p className="ask-panel__subtitle">
          Retrieval-augmented Q&amp;A over every meeting processed so far. Answers are generated
          only from retrieved transcript excerpts and cited — if nothing relevant is indexed, it
          says so instead of guessing.
        </p>
      </div>

      <div className="ask-panel__scope">
        <label htmlFor="meeting-scope">Scope to one meeting (optional)</label>
        <input
          id="meeting-scope"
          type="text"
          placeholder="e.g. ES2002"
          value={meetingId}
          onChange={(e) => setMeetingId(e.target.value)}
        />
      </div>

      <div className="ask-panel__messages glass-card" ref={scrollRef}>
        {messages.length === 0 && (
          <div className="ask-panel__empty">
            No questions yet — try &ldquo;What did we decide about the budget?&rdquo;
          </div>
        )}
        {messages.map((m, i) =>
          m.role === "user" ? (
            <div key={i} className="ask-message ask-message--user">
              <div className="ask-bubble ask-bubble--user">{m.text}</div>
            </div>
          ) : (
            <div key={i} className="ask-message ask-message--assistant">
              <div className={`ask-bubble ask-bubble--assistant ${m.grounded === false ? "ask-bubble--refused" : ""}`}>
                <div className="ask-bubble__badge">
                  <span className={`badge ${m.grounded ? "badge-success" : "badge-warning"}`}>
                    {m.grounded ? "grounded" : "not grounded"}
                  </span>
                </div>
                <p>{m.answer}</p>
                {m.sources && m.sources.length > 0 && (
                  <div className="ask-sources">
                    {m.sources.map((s, si) => (
                      <span key={si} className="ask-source-chip" title={`similarity ${s.score}`}>
                        {s.citation}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )
        )}
        {loading && (
          <div className="ask-message ask-message--assistant">
            <div className="ask-bubble ask-bubble--assistant ask-bubble--loading">
              <span className="ask-typing-dot" />
              <span className="ask-typing-dot" />
              <span className="ask-typing-dot" />
            </div>
          </div>
        )}
      </div>

      <div className="ask-panel__input-row">
        <textarea
          rows={1}
          placeholder="Ask a question across all indexed meetings..."
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={handleKeyDown}
        />
        <button className="btn-process" onClick={handleAsk} disabled={!question.trim() || loading}>
          Ask
        </button>
      </div>
    </div>
  );
}
