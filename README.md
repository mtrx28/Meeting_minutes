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

### Cross-meeting RAG knowledge base

Every meeting the pipeline processes is automatically chunked (`backend/app/retrieval.py`) and appended to a persisted, cross-meeting index (`backend/app/knowledge_base.py`, stored at `backend/outputs/knowledge_base.jsonl`). `POST /api/ask` answers natural-language questions against it:

```bash
curl -X POST http://localhost:8000/api/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What did we decide about the remote'\''s case material?", "top_k": 5}'
```

Retrieval is TF-IDF + cosine similarity over transcript chunks (a classic sparse retriever, not an embedding model) — deliberate, so the RAG layer adds zero model-download/network dependency and zero GPU requirement on top of a pipeline that already runs Whisper + pyannote locally. The answer is generated **only** from the retrieved excerpts, each cited as `{meeting_id} [mm:ss] {speaker}`; if nothing relevant is indexed for the question, the endpoint returns `"grounded": false` and a fixed refusal message instead of letting the LLM guess. Pass `meeting_id` in the request to scope retrieval to a single meeting.

### Cross-meeting knowledge graph

When a meeting is processed with `use_multi_agent=true`, its **verified** claims (`backend/app/agents.py` output — unverified claims are never let in) are ingested into a persisted graph (`backend/app/knowledge_graph.py`, `networkx`, stored at `backend/outputs/knowledge_graph.json`):

```
meeting:<id> --CONTAINS--> claim:<id>
person:<name> --OWNS-----> claim:<id>     (when the claim has an owner)
claim:<id>    --TAGGED----> topic:<keyword>
```

```bash
GET /api/graph/owner/Bob        # everything Bob owns, across every meeting
GET /api/graph/topic/pricing    # every verified claim tagged "pricing", in meeting order
GET /api/graph/stats            # node/edge counts by type
```

Same reasoning as the retrieval layer's TF-IDF-over-embeddings choice: an embedded graph library instead of a graph database server, appropriate for a single-service pipeline at this scale, with the storage layer swappable behind the same `KnowledgeGraph` interface if it ever needs to be a real graph DB.

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
