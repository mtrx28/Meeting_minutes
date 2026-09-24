"use client";

import { useState, useEffect, useRef } from "react";
import "./ProcessingStatus.css";

const STAGES = [
  { key: "loading_models", label: "Loading AI Models", icon: "🧠" },
  { key: "splitting", label: "Splitting Audio", icon: "✂️" },
  { key: "diarizing", label: "Identifying Speakers", icon: "🎙️" },
  { key: "transcribing", label: "Transcribing Speech", icon: "📝" },
  { key: "generating_minutes", label: "Generating Minutes", icon: "✨" },
  { key: "complete", label: "Complete", icon: "✅" },
];

function getStageIndex(stageKey) {
  return STAGES.findIndex((s) => s.key === stageKey);
}

export default function ProcessingStatus({
  jobId,
  filename,
  apiBase,
  isUploading,
  useMultiAgent,
  onComplete,
  onError,
}) {
  const [currentStage, setCurrentStage] = useState(isUploading ? null : "loading_models");
  const [currentMessage, setCurrentMessage] = useState(
    isUploading ? "Uploading file..." : "Loading AI models... (this takes a while on first run)"
  );
  const [logs, setLogs] = useState([]);
  const [elapsed, setElapsed] = useState(0);
  const startTimeRef = useRef(Date.now());
  const eventSourceRef = useRef(null);

  // Sync state when upload finishes
  useEffect(() => {
    if (!isUploading && currentStage === null) {
      setCurrentStage("loading_models");
      setCurrentMessage("Loading AI models... (this takes a while on first run)");
    }
  }, [isUploading, currentStage]);

  // Timer
  useEffect(() => {
    const interval = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startTimeRef.current) / 1000));
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  // SSE connection
  useEffect(() => {
    if (!jobId || isUploading) return;

    const url = `${apiBase}/api/process/${jobId}${useMultiAgent ? "?use_multi_agent=true" : ""}`;
    const es = new EventSource(url);
    eventSourceRef.current = es;

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);

        if (data.stage === "heartbeat") return;

        if (data.stage === "error") {
          es.close();
          onError(data.message);
          return;
        }

        setCurrentStage(data.stage);
        setCurrentMessage(data.message);
        setLogs((prev) => [
          ...prev,
          { time: new Date().toLocaleTimeString(), stage: data.stage, message: data.message },
        ]);

        if (data.stage === "complete") {
          es.close();
          // Small delay so user sees the "complete" state
          setTimeout(() => onComplete(jobId), 1500);
        }
      } catch (err) {
        console.error("SSE parse error:", err);
      }
    };

    es.onerror = () => {
      es.close();
      onError("Connection to server lost. Please try again.");
    };

    return () => {
      es.close();
    };
  }, [jobId, isUploading, apiBase, useMultiAgent, onComplete, onError]);

  const currentStageIndex = getStageIndex(currentStage);

  function formatElapsed(secs) {
    const m = Math.floor(secs / 60);
    const s = secs % 60;
    return m > 0 ? `${m}m ${s}s` : `${s}s`;
  }

  return (
    <div className="processing-section">
      {/* Header card */}
      <div className="processing-header glass-card">
        <div className="processing-header__icon">
          <div className="spinner" />
        </div>
        <div className="processing-header__info">
          <h2 className="processing-header__title">Processing your meeting</h2>
          <p className="processing-header__file">{filename}</p>
        </div>
        <div className="processing-header__timer">
          <span className="timer-value">{formatElapsed(elapsed)}</span>
          <span className="timer-label">elapsed</span>
        </div>
      </div>

      {/* Stage pipeline */}
      <div className="pipeline-stages">
        {STAGES.map((stage, idx) => {
          let status = "pending";
          if (currentStageIndex > idx) status = "done";
          else if (currentStageIndex === idx) status = "active";

          return (
            <div
              key={stage.key}
              className={`pipeline-stage pipeline-stage--${status}`}
            >
              <div className="pipeline-stage__indicator">
                {status === "done" ? (
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                ) : status === "active" ? (
                  <div className="stage-spinner" />
                ) : (
                  <span className="stage-number">{idx + 1}</span>
                )}
              </div>
              <div className="pipeline-stage__content">
                <span className="pipeline-stage__icon">{stage.icon}</span>
                <span className="pipeline-stage__label">{stage.label}</span>
              </div>
              {idx < STAGES.length - 1 && (
                <div className={`pipeline-stage__connector ${status === "done" ? "pipeline-stage__connector--done" : ""}`} />
              )}
            </div>
          );
        })}
      </div>

      {/* Current status message */}
      <div className="status-message glass-card">
        <div className="status-pulse" />
        <p>{currentMessage}</p>
      </div>

      {/* Log feed */}
      {logs.length > 0 && (
        <div className="log-feed glass-card">
          <h3 className="log-feed__title">Activity Log</h3>
          <div className="log-feed__entries">
            {logs.map((log, i) => (
              <div key={i} className="log-entry animate-slide-in-right">
                <span className="log-entry__time">{log.time}</span>
                <span className="log-entry__message">{log.message}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
