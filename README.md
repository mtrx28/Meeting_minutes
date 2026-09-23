# MeetingMind — AI-Powered Minutes of Meeting Automation

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-green)
![Next.js](https://img.shields.io/badge/Next.js-React-black)
![License](https://img.shields.io/badge/License-MIT-blue.svg)

MeetingMind is an end-to-end, highly scalable microservice automation pipeline designed to eliminate manual note-taking overhead. By chaining state-of-the-art acoustic models with Large Language Models (LLMs), it ingests raw meeting audio and automatically outputs structured executive summaries, precise speaker attributions, and actionable items.

## 🚀 Key Impact & Performance

Engineered to solve latency and memory bottlenecks typical in long-form audio processing, this architecture was independently benchmarked on the AMI Meeting Corpus (ES2002):
- **80% Note-Taking Time Reduction**: Condenses a standard 60-minute meeting into structured minutes within ~12 minutes asynchronously.
- **75% Peak Memory & Latency Cut**: Redesigned the data ingestion layer to automatically chunk long-running audio streams into 15-minute segments, effectively avoiding Out-of-Memory (OOM) failures and dramatically speeding up parallel processing.
- **High-Fidelity Summarization**: Achieves a validated **49% ROUGE-1 F1-score** on ES2002, driven by Mistral AI prompt engineering.
- **Grounded, Regression-Gated Evaluation**: `tests/run_benchmark.py` runs the full pipeline across the AMI Meeting Corpus (ES2002–ES2016), scoring each meeting on ROUGE-1/2/L *and* a custom hallucination/grounding check that verifies every generated action item and decision has support in the source transcript — then fails the run if either metric regresses past a stored baseline.

## 🧠 System Architecture

The pipeline uses a two-stage approach. Rather than processing monolithic audio, the system chunks the data, isolates speakers, generates text, maps the timelines, and synthesizes the context:

1. **Ingestion & Chunking**: Audio streams are partitioned (15-min blocks) for memory-safe processing.
2. **Speaker Diarization (`pyannote.audio`)**: Identifies structural speech boundaries ("who spoke when").
3. **Transcription (`Whisper ASR`)**: Converts speech to highly accurate text.
4. **Binary Search Alignment**: Programmatically maps Whisper's word-level timestamps to Pyannote's speaker segments.
5. **Generative Extraction (`Mistral AI`)**: The LLM synthesizes the unified transcript into a structured Markdown document (Agenda, Decisions, Action Items).

### Multi-agent generation (opt-in)

By default step 5 is a single LLM call. Passing `use_multi_agent=true` (API query param, or `use_multi_agent=True` to `MeetingPipeline.run`) switches to a three-stage pipeline instead (`backend/app/agents.py`):

1. **ExtractorAgent** — LLM call that pulls candidate action items/decisions out of the transcript, each with a verbatim supporting quote.
2. **VerifierAgent** — deterministic, no LLM call: checks each quote actually appears in the transcript and that the claim's wording is grounded in it (stemmed content-word overlap). Rejects fabricated or paraphrased-beyond-recognition claims.
3. **WriterAgent** — formats only the verified claims into the final document, and appends anything rejected under an "UNVERIFIED — needs human review" section instead of silently dropping or silently shipping it.

The result includes a `claims` list with per-claim verification status and a `verification_rate`. `tests/run_benchmark.py --multi-agent` runs the benchmark in this mode so the verification rate and grounding score can be compared against single-shot generation.

## 🛠 Tech Stack

- **Frontend**: Next.js, React, Tailwind CSS (Server-Sent Events for real-time progress streaming)
- **Backend Core**: Python, FastAPI
- **Machine Learning**: OpenAI Whisper (ASR), Pyannote Diarization 3.1
- **LLM Engine**: Mistral AI 
- **Testing & Benchmarking**: `rouge-score`, `pytest`, custom grounding/hallucination checker
- **Containerization**: Docker, Docker Compose

## ⚙️ Local Development Setup

### Prerequisites
- **Python 3.10+** & **Node.js 18+**
- **FFmpeg** (Required for `pydub` audio manipulation)
  - *Windows*: `choco install ffmpeg` | *macOS*: `brew install ffmpeg` | *Linux*: `sudo apt install ffmpeg`
- **HuggingFace Account** (For Pyannote gated model access)
- **Mistral API Key**

### 1. Backend Initialization

```bash
cd backend
python -m venv venv
# Activate virtual environment (Windows: venv\Scripts\activate | Unix: source venv/bin/activate)

pip install -r requirements.txt
cp .env.example .env
```
*Add your `HF_API_TOKEN` and `MISTRAL_API_KEY` to the newly created `.env` file.*

### 2. Frontend Initialization

```bash
cd frontend
npm install
```

### 3. Running the Microservices

Launch the **FastAPI Backend**:
```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Launch the **Next.js Frontend**:
```bash
cd frontend
npm run dev
```
Navigate to `http://localhost:3000` to access the upload portal.

### 4. Running with Docker

```bash
cp backend/.env.example backend/.env   # fill in HF_API_TOKEN and MISTRAL_API_KEY
docker compose up --build
```
Backend at `http://localhost:8000`, frontend at `http://localhost:3000`.

## 📊 Evaluation & Benchmarking

Two levels of checks guard output quality:

- **Unit-level (fast, no API calls):** `backend/test_evaluation.py` exercises the ROUGE scoring and grounding-check logic in isolation — run via `pytest` on every change.
- **End-to-end benchmark (full pipeline):** `tests/run_benchmark.py` runs diarization → transcription → summarization on real meeting audio in `wavs/`, scores each meeting against its human reference in `references/` with ROUGE-1/2/L, and flags any generated action item or decision whose content doesn't overlap with the source transcript (a lightweight hallucination check). Results are written to `tests/outputs/` and compared against `tests/baseline_scores.json`, so a quality regression fails the run instead of shipping silently.

```bash
python tests/run_benchmark.py ES2002          # single-meeting smoke test
python tests/run_benchmark.py                 # full ES2002-ES2016 benchmark
python tests/run_benchmark.py --update-baseline  # after an intentional prompt/model change
```

## 📡 API Reference

| HTTP Method | Endpoint | Description |
|-------------|----------|-------------|
| `GET` | `/api/health` | Service health check & uptime status |
| `POST` | `/api/upload` | Multipart form audio upload & ingestion |
| `GET` | `/api/process/{job_id}` | Triggers async pipeline & opens SSE stream |
| `GET` | `/api/results/{job_id}` | Retrieves the finalized Mistral JSON payload |
| `DELETE`| `/api/jobs/{job_id}` | Purges local audio chunks and temporary data |

*Supported Audio Formats: WAV, MP3, M4A, FLAC, OGG, WebM, MP4, AAC*

---
*Built with modern AI tools to optimize productivity and eliminate administrative overhead.*
