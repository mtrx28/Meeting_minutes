"use client";

import { useState, useMemo } from "react";
import "./MeetingMinutes.css";

const SPEAKER_COLORS = [
  "var(--speaker-0)", "var(--speaker-1)", "var(--speaker-2)", "var(--speaker-3)",
  "var(--speaker-4)", "var(--speaker-5)", "var(--speaker-6)", "var(--speaker-7)",
];

function getSpeakerColor(speaker, speakerList) {
  const idx = speakerList.indexOf(speaker);
  return SPEAKER_COLORS[idx % SPEAKER_COLORS.length];
}

function formatTime(seconds) {
  if (!seconds && seconds !== 0) return "00:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

function formatDuration(seconds) {
  if (!seconds) return "0s";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

/** Simple markdown → JSX renderer for LLM output */
function renderMarkdown(text) {
  if (!text) return null;

  const lines = text.split("\n");
  const elements = [];
  let inList = false;
  let listItems = [];
  let listType = "ul";

  function flushList() {
    if (listItems.length > 0) {
      const ListTag = listType === "ol" ? "ol" : "ul";
      elements.push(
        <ListTag key={`list-${elements.length}`} className="md-list">
          {listItems.map((item, i) => (
            <li key={i} className="md-list-item">
              {item.isAction ? (
                <label className="action-item">
                  <input type="checkbox" className="action-checkbox" />
                  <span>{item.text}</span>
                </label>
              ) : (
                <span dangerouslySetInnerHTML={{ __html: inlineFormat(item.text) }} />
              )}
            </li>
          ))}
        </ListTag>
      );
      listItems = [];
      inList = false;
    }
  }

  function inlineFormat(str) {
    return str
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/\*(.+?)\*/g, "<em>$1</em>")
      .replace(/`(.+?)`/g, '<code class="md-code">$1</code>');
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();

    // Empty line
    if (!trimmed) {
      flushList();
      continue;
    }

    // Headers
    const h1Match = trimmed.match(/^#\s+(.+)/);
    const h2Match = trimmed.match(/^##\s+(.+)/);
    const h3Match = trimmed.match(/^###\s+(.+)/);

    if (h1Match) {
      flushList();
      elements.push(<h2 key={i} className="md-h1" dangerouslySetInnerHTML={{ __html: inlineFormat(h1Match[1]) }} />);
      continue;
    }
    if (h2Match) {
      flushList();
      elements.push(<h3 key={i} className="md-h2" dangerouslySetInnerHTML={{ __html: inlineFormat(h2Match[1]) }} />);
      continue;
    }
    if (h3Match) {
      flushList();
      elements.push(<h4 key={i} className="md-h3" dangerouslySetInnerHTML={{ __html: inlineFormat(h3Match[1]) }} />);
      continue;
    }

    // Horizontal rule
    if (/^---+$/.test(trimmed)) {
      flushList();
      elements.push(<hr key={i} className="md-hr" />);
      continue;
    }

    // Action item (checkbox)
    const actionMatch = trimmed.match(/^-\s*\[[ x]?\]\s*(.+)/i);
    if (actionMatch) {
      inList = true;
      listType = "ul";
      listItems.push({ text: actionMatch[1], isAction: true });
      continue;
    }

    // Unordered list
    const ulMatch = trimmed.match(/^[-*]\s+(.+)/);
    if (ulMatch) {
      inList = true;
      listType = "ul";
      listItems.push({ text: ulMatch[1], isAction: false });
      continue;
    }

    // Ordered list
    const olMatch = trimmed.match(/^\d+\.\s+(.+)/);
    if (olMatch) {
      inList = true;
      listType = "ol";
      listItems.push({ text: olMatch[1], isAction: false });
      continue;
    }

    // Regular paragraph
    flushList();
    elements.push(
      <p key={i} className="md-paragraph" dangerouslySetInnerHTML={{ __html: inlineFormat(trimmed) }} />
    );
  }

  flushList();
  return elements;
}

export default function MeetingMinutes({ data, onReset }) {
  const [activeTab, setActiveTab] = useState("minutes");
  const [transcriptExpanded, setTranscriptExpanded] = useState(false);

  const speakerList = useMemo(() => {
    return Object.keys(data.speaker_stats || {}).sort();
  }, [data.speaker_stats]);

  const maxSpeakerDuration = useMemo(() => {
    const stats = data.speaker_stats || {};
    return Math.max(...Object.values(stats).map((s) => s.duration || 0), 1);
  }, [data.speaker_stats]);

  const handleDownloadText = () => {
    const content = `EXECUTIVE SUMMARY\n${"=".repeat(50)}\n\n${data.summary}\n\n\nDETAILED MINUTES\n${"=".repeat(50)}\n\n${data.minutes}`;
    const blob = new Blob([content], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `meeting_minutes_${data.filename || "output"}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="results-section">
      {/* Success header */}
      <div className="results-header glass-card">
        <div className="results-header__icon">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
            <polyline points="22 4 12 14.01 9 11.01" />
          </svg>
        </div>
        <div className="results-header__info">
          <h2>Meeting minutes generated</h2>
          <p className="results-header__file">{data.filename}</p>
        </div>
        <button className="btn-download" onClick={handleDownloadText} id="btn-download">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="7 10 12 15 17 10" />
            <line x1="12" y1="15" x2="12" y2="3" />
          </svg>
          Download .txt
        </button>
      </div>

      {/* Quick stats */}
      <div className="stats-grid stagger-children">
        <div className="stat-card glass-card">
          <div className="stat-value gradient-text">{data.num_speakers || 0}</div>
          <div className="stat-label">Speakers</div>
        </div>
        <div className="stat-card glass-card">
          <div className="stat-value gradient-text">{formatDuration(data.total_duration)}</div>
          <div className="stat-label">Duration</div>
        </div>
        <div className="stat-card glass-card">
          <div className="stat-value gradient-text">{(data.total_words || 0).toLocaleString()}</div>
          <div className="stat-label">Words</div>
        </div>
        <div className="stat-card glass-card">
          <div className="stat-value gradient-text">{(data.segments || []).length}</div>
          <div className="stat-label">Segments</div>
        </div>
      </div>

      {/* Tabs */}
      <div className="tabs-bar">
        {[
          { key: "minutes", label: "Meeting Minutes" },
          { key: "summary", label: "Executive Summary" },
          { key: "speakers", label: "Speakers" },
          { key: "transcript", label: "Transcript" },
        ].map((tab) => (
          <button
            key={tab.key}
            className={`tab-btn ${activeTab === tab.key ? "tab-btn--active" : ""}`}
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="tab-content glass-card animate-fade-in" key={activeTab}>
        {/* --- Minutes tab --- */}
        {activeTab === "minutes" && (
          <div className="minutes-content">
            {renderMarkdown(data.minutes)}
          </div>
        )}

        {/* --- Summary tab --- */}
        {activeTab === "summary" && (
          <div className="summary-content">
            <div className="summary-highlight">
              <div className="summary-badge badge badge-accent">Executive Summary</div>
            </div>
            {renderMarkdown(data.summary)}
          </div>
        )}

        {/* --- Speakers tab --- */}
        {activeTab === "speakers" && (
          <div className="speakers-content">
            <div className="speakers-grid">
              {speakerList.map((speaker) => {
                const stats = data.speaker_stats[speaker];
                const color = getSpeakerColor(speaker, speakerList);
                const pct = ((stats.duration / maxSpeakerDuration) * 100).toFixed(0);
                const totalDur = data.total_duration || 1;
                const sharePct = ((stats.duration / totalDur) * 100).toFixed(1);

                return (
                  <div key={speaker} className="speaker-card">
                    <div className="speaker-card__header">
                      <div className="speaker-avatar" style={{ background: color }}>
                        {speaker.replace(/SPEAKER_?/i, "S")}
                      </div>
                      <div className="speaker-card__name">
                        <span className="speaker-name">{speaker}</span>
                        <span className="speaker-share">{sharePct}% of meeting</span>
                      </div>
                    </div>
                    <div className="speaker-card__stats">
                      <div className="speaker-stat">
                        <span className="speaker-stat__label">Speaking time</span>
                        <span className="speaker-stat__value">{formatDuration(stats.duration)}</span>
                      </div>
                      <div className="speaker-stat">
                        <span className="speaker-stat__label">Words</span>
                        <span className="speaker-stat__value">{stats.words.toLocaleString()}</span>
                      </div>
                      <div className="speaker-stat">
                        <span className="speaker-stat__label">Segments</span>
                        <span className="speaker-stat__value">{stats.segments}</span>
                      </div>
                    </div>
                    <div className="speaker-bar-track">
                      <div
                        className="speaker-bar-fill"
                        style={{ width: `${pct}%`, background: color }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* --- Transcript tab --- */}
        {activeTab === "transcript" && (
          <div className="transcript-content">
            <div className="transcript-controls">
              <span className="transcript-count">
                {(data.segments || []).length} segments
              </span>
              {(data.segments || []).length > 20 && (
                <button
                  className="btn-expand"
                  onClick={() => setTranscriptExpanded(!transcriptExpanded)}
                >
                  {transcriptExpanded ? "Show less" : "Show all"}
                </button>
              )}
            </div>
            <div className="transcript-entries">
              {(transcriptExpanded ? data.segments : (data.segments || []).slice(0, 20)).map(
                (seg, i) => {
                  const speaker = seg.speaker || "UNKNOWN";
                  const color = getSpeakerColor(speaker, speakerList);

                  return (
                    <div key={i} className="transcript-entry">
                      <div className="transcript-entry__time">
                        {formatTime(seg.start)}
                      </div>
                      <div
                        className="transcript-entry__speaker"
                        style={{ color }}
                      >
                        {seg.overlap ? seg.speakers.join(" & ") : speaker}
                        {seg.overlap && (
                          <span className="overlap-badge">overlap</span>
                        )}
                      </div>
                      <div className="transcript-entry__text">{seg.text}</div>
                    </div>
                  );
                }
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
