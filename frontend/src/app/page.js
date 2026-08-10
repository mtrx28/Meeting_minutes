"use client";

import { useState, useCallback } from "react";
import UploadForm from "../components/UploadForm";
import ProcessingStatus from "../components/ProcessingStatus";
import MeetingMinutes from "../components/MeetingMinutes";
import "./page.css";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function HomePage() {
  // App states: idle | uploading | processing | complete | error
  const [appState, setAppState] = useState("idle");
  const [jobId, setJobId] = useState(null);
  const [filename, setFilename] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const handleUpload = useCallback(async (file) => {
    setAppState("uploading");
    setError(null);

    try {
      const formData = new FormData();
      formData.append("file", file);

      const res = await fetch(`${API_BASE}/api/upload`, {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || "Upload failed");
      }

      const data = await res.json();
      setJobId(data.job_id);
      setFilename(data.filename);
      setAppState("processing");
    } catch (err) {
      setError(err.message);
      setAppState("error");
    }
  }, []);

  const handleProcessingComplete = useCallback(async (completedJobId) => {
    try {
      const res = await fetch(`${API_BASE}/api/results/${completedJobId}`);
      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || "Failed to fetch results");
      }
      const data = await res.json();
      setResult(data);
      setAppState("complete");
    } catch (err) {
      setError(err.message);
      setAppState("error");
    }
  }, []);

  const handleProcessingError = useCallback((errorMsg) => {
    setError(errorMsg);
    setAppState("error");
  }, []);

  const handleReset = useCallback(() => {
    setAppState("idle");
    setJobId(null);
    setFilename("");
    setResult(null);
    setError(null);
  }, []);

  return (
    <div className="app-container">
      {/* Header */}
      <header className="app-header">
        <div className="header-content">
          <div className="logo-group" onClick={handleReset} role="button" tabIndex={0}>
            <div className="logo-icon">
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
                <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                <line x1="12" y1="19" x2="12" y2="23" />
                <line x1="8" y1="23" x2="16" y2="23" />
              </svg>
            </div>
            <div>
              <h1 className="logo-text">
                Meeting<span className="gradient-text">Mind</span>
              </h1>
              <p className="logo-tagline">AI-Powered Meeting Minutes</p>
            </div>
          </div>

          {appState === "complete" && (
            <button className="btn-new-meeting" onClick={handleReset}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="12" y1="5" x2="12" y2="19" />
                <line x1="5" y1="12" x2="19" y2="12" />
              </svg>
              New Meeting
            </button>
          )}
        </div>
      </header>

      {/* Main content */}
      <main className="app-main">
        {(appState === "idle" || appState === "error") && (
          <div className="animate-fade-in-up">
            <UploadForm onUpload={handleUpload} error={error} />
          </div>
        )}

        {(appState === "uploading" || appState === "processing") && (
          <div className="animate-fade-in-up">
            <ProcessingStatus
              jobId={jobId}
              filename={filename}
              apiBase={API_BASE}
              isUploading={appState === "uploading"}
              onComplete={handleProcessingComplete}
              onError={handleProcessingError}
            />
          </div>
        )}

        {appState === "complete" && result && (
          <div className="animate-fade-in-up">
            <MeetingMinutes data={result} onReset={handleReset} />
          </div>
        )}
      </main>

      {/* Footer */}
      <footer className="app-footer">
        <p>
          Powered by <span className="gradient-text">Whisper</span> ·{" "}
          <span className="gradient-text">Pyannote</span> ·{" "}
          <span className="gradient-text">Mistral AI</span>
        </p>
      </footer>
    </div>
  );
}
