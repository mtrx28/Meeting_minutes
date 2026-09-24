"use client";

import { useState, useRef, useCallback } from "react";
import "./UploadForm.css";

const ACCEPTED_TYPES = [
  "audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp3", "audio/mp4",
  "audio/m4a", "audio/x-m4a", "audio/flac", "audio/ogg", "audio/webm",
  "video/mp4", "video/webm",
];

const ACCEPTED_EXTENSIONS = [".wav", ".mp3", ".m4a", ".flac", ".ogg", ".webm", ".mp4", ".wma", ".aac"];

function formatFileSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function getFileDuration(file) {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file);
    const audio = new Audio();
    audio.addEventListener("loadedmetadata", () => {
      URL.revokeObjectURL(url);
      resolve(audio.duration);
    });
    audio.addEventListener("error", () => {
      URL.revokeObjectURL(url);
      resolve(null);
    });
    audio.src = url;
  });
}

function formatDuration(seconds) {
  if (!seconds || !isFinite(seconds)) return null;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}h ${m}m ${s}s`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

export default function UploadForm({ onUpload, error }) {
  const [dragActive, setDragActive] = useState(false);
  const [selectedFile, setSelectedFile] = useState(null);
  const [fileDuration, setFileDuration] = useState(null);
  const [useMultiAgent, setUseMultiAgent] = useState(false);
  const fileInputRef = useRef(null);

  const validateAndSetFile = useCallback(async (file) => {
    const ext = "." + file.name.split(".").pop().toLowerCase();
    if (!ACCEPTED_EXTENSIONS.includes(ext)) {
      return;
    }
    setSelectedFile(file);
    const duration = await getFileDuration(file);
    setFileDuration(duration);
  }, []);

  const handleDrag = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  }, []);

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files?.[0]) {
      validateAndSetFile(e.dataTransfer.files[0]);
    }
  }, [validateAndSetFile]);

  const handleFileSelect = useCallback((e) => {
    if (e.target.files?.[0]) {
      validateAndSetFile(e.target.files[0]);
    }
  }, [validateAndSetFile]);

  const handleSubmit = useCallback(() => {
    if (selectedFile) {
      onUpload(selectedFile, useMultiAgent);
    }
  }, [selectedFile, useMultiAgent, onUpload]);

  const handleRemoveFile = useCallback(() => {
    setSelectedFile(null);
    setFileDuration(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }, []);

  return (
    <div className="upload-section">
      {/* Hero text */}
      <div className="upload-hero">
        <h2 className="upload-title">
          Transform your meetings into
          <br />
          <span className="gradient-text">actionable minutes</span>
        </h2>
        <p className="upload-subtitle">
          Upload a meeting recording and get AI-generated minutes with speaker
          identification, executive summaries, and action items.
        </p>
      </div>

      {/* Error alert */}
      {error && (
        <div className="upload-error animate-fade-in">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="8" x2="12" y2="12" />
            <line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
          <span>{error}</span>
        </div>
      )}

      {/* Drop zone */}
      <div
        className={`drop-zone ${dragActive ? "drop-zone--active" : ""} ${selectedFile ? "drop-zone--has-file" : ""}`}
        onDragEnter={handleDrag}
        onDragOver={handleDrag}
        onDragLeave={handleDrag}
        onDrop={handleDrop}
        onClick={() => !selectedFile && fileInputRef.current?.click()}
        role="button"
        tabIndex={0}
        id="upload-dropzone"
      >
        <input
          ref={fileInputRef}
          type="file"
          accept={ACCEPTED_EXTENSIONS.join(",")}
          onChange={handleFileSelect}
          className="drop-zone__input"
          id="file-input"
        />

        {!selectedFile ? (
          <div className="drop-zone__prompt">
            <div className="drop-zone__icon">
              <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="17 8 12 3 7 8" />
                <line x1="12" y1="3" x2="12" y2="15" />
              </svg>
            </div>
            <p className="drop-zone__title">
              {dragActive ? "Drop your file here" : "Drag & drop your meeting recording"}
            </p>
            <p className="drop-zone__hint">
              or <span className="drop-zone__browse">browse files</span>
            </p>
            <div className="drop-zone__formats">
              {ACCEPTED_EXTENSIONS.map((ext) => (
                <span key={ext} className="format-tag">{ext}</span>
              ))}
            </div>
          </div>
        ) : (
          <div className="drop-zone__file-info">
            <div className="file-icon">
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M9 18V5l12-2v13" />
                <circle cx="6" cy="18" r="3" />
                <circle cx="18" cy="16" r="3" />
              </svg>
            </div>
            <div className="file-details">
              <p className="file-name">{selectedFile.name}</p>
              <div className="file-meta">
                <span className="file-size">{formatFileSize(selectedFile.size)}</span>
                {fileDuration && (
                  <>
                    <span className="file-meta-sep">·</span>
                    <span className="file-duration">{formatDuration(fileDuration)}</span>
                  </>
                )}
              </div>
            </div>
            <button
              className="file-remove"
              onClick={(e) => { e.stopPropagation(); handleRemoveFile(); }}
              title="Remove file"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>
        )}
      </div>

      {/* Multi-agent toggle */}
      {selectedFile && (
        <label className="multi-agent-toggle animate-fade-in" htmlFor="use-multi-agent">
          <input
            type="checkbox"
            id="use-multi-agent"
            checked={useMultiAgent}
            onChange={(e) => setUseMultiAgent(e.target.checked)}
          />
          <span className="multi-agent-toggle__switch" />
          <span className="multi-agent-toggle__text">
            <span className="multi-agent-toggle__title">
              Verified generation
              <span className="badge badge-accent" style={{ marginLeft: 8 }}>multi-agent</span>
            </span>
            <span className="multi-agent-toggle__hint">
              Extract → Verify → Write: flags action items/decisions that aren&apos;t grounded in the transcript instead of silently including them. Slower (one extra LLM pass).
            </span>
          </span>
        </label>
      )}

      {/* Submit button */}
      {selectedFile && (
        <button className="btn-process animate-fade-in" onClick={handleSubmit} id="btn-process">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polygon points="5 3 19 12 5 21 5 3" />
          </svg>
          Generate Meeting Minutes
        </button>
      )}

      {/* Feature pills */}
      <div className="features-row">
        <div className="feature-pill">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
            <circle cx="9" cy="7" r="4" />
            <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
            <path d="M16 3.13a4 4 0 0 1 0 7.75" />
          </svg>
          Speaker Identification
        </div>
        <div className="feature-pill">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
            <line x1="16" y1="13" x2="8" y2="13" />
            <line x1="16" y1="17" x2="8" y2="17" />
          </svg>
          Executive Summary
        </div>
        <div className="feature-pill">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="9 11 12 14 22 4" />
            <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
          </svg>
          Action Items
        </div>
      </div>
    </div>
  );
}
