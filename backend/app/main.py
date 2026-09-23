"""
FastAPI application for the Meeting Minutes Pipeline.
Provides upload, SSE progress streaming, and results endpoints.
"""

import os
import uuid
import asyncio
import logging
import shutil
from pathlib import Path
from threading import Thread

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv

from typing import Dict, Optional

from .models import UploadResponse, MeetingMinutesResult
from .pipeline import MeetingPipeline

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Directories
BASE_DIR = Path(__file__).resolve().parent.parent
UPLOADS_DIR = BASE_DIR / "uploads"
OUTPUTS_DIR = BASE_DIR / "outputs"
CHUNKS_DIR = BASE_DIR / "audio_chunks"
UPLOADS_DIR.mkdir(exist_ok=True)
OUTPUTS_DIR.mkdir(exist_ok=True)
CHUNKS_DIR.mkdir(exist_ok=True)

# Environment config
HF_TOKEN = os.getenv("HF_API_TOKEN", "")
MISTRAL_KEY = os.getenv("MISTRAL_API_KEY", "")
WHISPER_MODEL = os.getenv("WHISPER_MODEL_SIZE", "base")

ALLOWED_EXTENSIONS = {'.wav', '.mp3', '.m4a', '.flac', '.ogg', '.webm', '.mp4', '.wma', '.aac'}
MAX_FILE_SIZE_MB = 500

# In-memory job store
jobs: Dict[str, dict] = {}

# Lazy-loaded pipeline instance (shared across requests)
_pipeline_instance: Optional[MeetingPipeline] = None


def get_pipeline() -> MeetingPipeline:
    """Get or create the shared pipeline instance."""
    global _pipeline_instance
    if _pipeline_instance is None:
        if not HF_TOKEN:
            raise RuntimeError("HF_API_TOKEN environment variable is not set")
        if not MISTRAL_KEY:
            raise RuntimeError("MISTRAL_API_KEY environment variable is not set")
        _pipeline_instance = MeetingPipeline(
            hf_token=HF_TOKEN,
            mistral_api_key=MISTRAL_KEY,
            whisper_model_size=WHISPER_MODEL,
        )
    return _pipeline_instance


# FastAPI app
app = FastAPI(
    title="Meeting Minutes Pipeline",
    description="Upload meeting recordings and get AI-generated meeting minutes",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "hf_token_set": bool(HF_TOKEN),
        "mistral_key_set": bool(MISTRAL_KEY),
        "whisper_model": WHISPER_MODEL,
    }


@app.post("/api/upload", response_model=UploadResponse)
async def upload_audio(file: UploadFile = File(...)):
    """Upload an audio file for processing."""
    # Validate file extension
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Supported: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

    # Generate job ID and save file
    job_id = str(uuid.uuid4())
    save_path = UPLOADS_DIR / f"{job_id}{ext}"

    try:
        content = await file.read()
        file_size_mb = len(content) / (1024 * 1024)

        if file_size_mb > MAX_FILE_SIZE_MB:
            raise HTTPException(
                status_code=400,
                detail=f"File too large ({file_size_mb:.1f} MB). Maximum is {MAX_FILE_SIZE_MB} MB."
            )

        with open(save_path, "wb") as f:
            f.write(content)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")

    # Register job
    jobs[job_id] = {
        'status': 'uploaded',
        'filename': file.filename,
        'file_path': str(save_path),
        'file_size_mb': round(file_size_mb, 2),
        'events': [],
        'result': None,
        'error': None,
    }

    logger.info(f"File uploaded: {file.filename} ({file_size_mb:.1f} MB) → job {job_id}")

    return UploadResponse(
        job_id=job_id,
        filename=file.filename,
        file_size_mb=round(file_size_mb, 2),
        message="File uploaded successfully. Start processing with /api/process/{job_id}",
    )


@app.get("/api/process/{job_id}")
async def process_audio(job_id: str, use_multi_agent: bool = False):
    """
    Process an uploaded audio file. Streams progress via SSE.

    use_multi_agent: if true, generate minutes via the Extract->Verify->Write
    pipeline instead of a single one-shot LLM call -- slower, but flags
    action items/decisions that aren't grounded in the transcript instead of
    silently shipping them.
    """
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = jobs[job_id]
    if job['status'] == 'complete':
        raise HTTPException(status_code=400, detail="Job already processed")
    if job['status'] == 'processing':
        raise HTTPException(status_code=400, detail="Job is already being processed")

    job['status'] = 'processing'
    event_queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def progress_callback(stage: str, message: str):
        """Thread-safe callback to push events to the async queue."""
        asyncio.run_coroutine_threadsafe(
            event_queue.put({'stage': stage, 'message': message}),
            loop
        )

    def run_pipeline():
        """Run the pipeline in a background thread."""
        try:
            pipeline = get_pipeline()
            work_dir = str(CHUNKS_DIR / job_id)
            os.makedirs(work_dir, exist_ok=True)

            result = pipeline.run(
                audio_path=job['file_path'],
                work_dir=work_dir,
                progress_callback=progress_callback,
                use_multi_agent=use_multi_agent,
            )

            job['result'] = result
            job['status'] = 'complete'
            asyncio.run_coroutine_threadsafe(
                event_queue.put({'stage': 'complete', 'message': 'Meeting minutes generated successfully!'}),
                loop
            )
        except Exception as e:
            logger.error(f"Pipeline error for job {job_id}: {e}", exc_info=True)
            job['error'] = str(e)
            job['status'] = 'error'
            asyncio.run_coroutine_threadsafe(
                event_queue.put({'stage': 'error', 'message': str(e)}),
                loop
            )
        finally:
            # Cleanup work dir
            work_dir = str(CHUNKS_DIR / job_id)
            if os.path.exists(work_dir):
                shutil.rmtree(work_dir, ignore_errors=True)

    # Start pipeline in background thread
    thread = Thread(target=run_pipeline, daemon=True)
    thread.start()

    async def event_generator():
        """Generate SSE events from the queue."""
        import json
        while True:
            try:
                event = await asyncio.wait_for(event_queue.get(), timeout=300)
                data = json.dumps(event)
                yield f"data: {data}\n\n"

                if event['stage'] in ('complete', 'error'):
                    break
            except asyncio.TimeoutError:
                # Send keepalive
                yield f"data: {json.dumps({'stage': 'heartbeat', 'message': 'Still processing...'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/results/{job_id}")
async def get_results(job_id: str):
    """Get the results of a processed job."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = jobs[job_id]

    if job['status'] == 'error':
        raise HTTPException(status_code=500, detail=f"Processing failed: {job['error']}")

    if job['status'] != 'complete':
        raise HTTPException(
            status_code=400,
            detail=f"Job is not complete yet. Current status: {job['status']}"
        )

    result = job['result']
    return {
        'job_id': job_id,
        'filename': job['filename'],
        **result,
    }


@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str):
    """Delete a job and its associated files."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = jobs[job_id]

    # Remove uploaded file
    try:
        if os.path.exists(job['file_path']):
            os.remove(job['file_path'])
    except OSError:
        pass

    del jobs[job_id]
    return {"message": "Job deleted successfully"}
