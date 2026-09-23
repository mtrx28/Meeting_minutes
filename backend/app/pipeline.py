"""
Pipeline orchestrator: connects diarization → transcription → minutes generation.
Manages the full flow from audio file to formatted meeting minutes.
"""

import os
import json
import logging
import torch
import whisper
from pyannote.audio import Pipeline
from datetime import datetime
from typing import Callable, Optional

from .diarization import process_audio_pipeline
from .minutes_generator import MeetingMinutesGenerator
from .agents import MultiAgentMinutesPipeline
from .knowledge_base import MeetingKnowledgeBase
from .knowledge_graph import KnowledgeGraph

logger = logging.getLogger(__name__)


class MeetingPipeline:
    """
    End-to-end meeting minutes pipeline.
    Audio → Split → Diarize → Transcribe → LLM Summary + Minutes
    """

    def __init__(self, hf_token: str, mistral_api_key: str,
                 whisper_model_size: str = "base",
                 mistral_model: str = "mistral-large-latest"):
        self.hf_token = hf_token
        self.mistral_api_key = mistral_api_key
        self.whisper_model_size = whisper_model_size
        self.mistral_model = mistral_model

        # Models are loaded lazily on first run
        self._whisper_model = None
        self._diarization_pipeline = None
        self._minutes_generator = None
        self.knowledge_base = MeetingKnowledgeBase()
        self.knowledge_graph = KnowledgeGraph()

    def _load_models(self, progress_callback: Optional[Callable] = None):
        """Load ML models if not already loaded."""
        if self._whisper_model is None:
            if progress_callback:
                progress_callback("loading_models", "Loading Whisper speech recognition model...")
            logger.info(f"Loading Whisper model ({self.whisper_model_size})...")
            self._whisper_model = whisper.load_model(self.whisper_model_size)
            logger.info("Whisper model loaded")

        if self._diarization_pipeline is None:
            if progress_callback:
                progress_callback("loading_models", "Loading speaker diarization model...")
            logger.info("Loading pyannote diarization pipeline...")
            self._diarization_pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                token=self.hf_token,
            )
            if torch.cuda.is_available():
                self._diarization_pipeline = self._diarization_pipeline.to(torch.device("cuda"))
                logger.info("Diarization pipeline moved to GPU")
            logger.info("Diarization pipeline loaded")

        if self._minutes_generator is None:
            self._minutes_generator = MeetingMinutesGenerator(
                api_key=self.mistral_api_key,
                model=self.mistral_model,
            )

    def run(self, audio_path: str, work_dir: str = "audio_chunks",
            chunk_minutes: int = 15,
            progress_callback: Optional[Callable] = None,
            use_multi_agent: bool = False,
            meeting_id: Optional[str] = None) -> dict:
        """
        Run the complete pipeline on an audio file.

        Args:
            audio_path: Path to the input audio file.
            work_dir: Temporary directory for audio chunks.
            chunk_minutes: Duration of each audio chunk in minutes.
            progress_callback: Optional callback(stage, message) for progress updates.
            use_multi_agent: If True, generate minutes via the Extract->Verify->Write
                pipeline (app.agents.MultiAgentMinutesPipeline) instead of a single
                one-shot LLM call. Slower (extra LLM call) but rejects/flags action
                items and decisions that aren't grounded in the transcript, and the
                result includes a 'claims' list with per-claim verification status.
            meeting_id: Identifier used to index this meeting's transcript into
                self.knowledge_base for cross-meeting retrieval/Q&A. Defaults to
                the audio filename (without extension).

        Returns:
            dict with: summary, minutes, speaker_stats, segments, metadata
        """
        start_time = datetime.now()

        # Step 1: Load models
        self._load_models(progress_callback)

        # Step 2: Audio → Diarization → Transcription
        if progress_callback:
            progress_callback("splitting", "Starting audio processing pipeline...")

        transcribed_segments = process_audio_pipeline(
            audio_file=audio_path,
            diarization_pipeline=self._diarization_pipeline,
            whisper_model=self._whisper_model,
            chunk_minutes=chunk_minutes,
            work_dir=work_dir,
            progress_callback=progress_callback,
        )

        if not transcribed_segments:
            raise RuntimeError("No segments were transcribed from the audio file")

        # Build transcript data structure
        transcript_data = {
            'metadata': {
                'generated_at': datetime.now().isoformat(),
                'total_segments': len(transcribed_segments),
                'source_file': os.path.basename(audio_path),
            },
            'segments': transcribed_segments,
        }

        # Step 3: Generate meeting minutes via LLM
        if progress_callback:
            progress_callback("generating_minutes", "Generating meeting minutes with AI...")

        if use_multi_agent:
            multi_agent_pipeline = MultiAgentMinutesPipeline(self._minutes_generator)
            result = multi_agent_pipeline.process_transcript(transcript_data)
        else:
            result = self._minutes_generator.process_transcript(transcript_data)

        # Step 4: Index this meeting's transcript for cross-meeting retrieval/Q&A
        resolved_meeting_id = meeting_id or os.path.splitext(os.path.basename(audio_path))[0]
        try:
            self.knowledge_base.index_meeting(resolved_meeting_id, transcribed_segments)
        except Exception as e:
            logger.warning(f"Knowledge base indexing failed (non-fatal): {e}")

        # Step 5: Ingest verified claims into the cross-meeting knowledge graph.
        # Only multi-agent runs produce claims with a verification status; a
        # single-shot run has nothing here to add, by design (see
        # knowledge_graph.py's module docstring for why unverified claims are
        # never let into the graph).
        if use_multi_agent and result.get('claims'):
            try:
                self.knowledge_graph.add_verified_claims(resolved_meeting_id, result['claims'])
            except Exception as e:
                logger.warning(f"Knowledge graph ingestion failed (non-fatal): {e}")

        # Add metadata
        end_time = datetime.now()
        result['metadata'] = {
            'source_file': os.path.basename(audio_path),
            'processed_at': end_time.isoformat(),
            'processing_time_seconds': (end_time - start_time).total_seconds(),
            'whisper_model': self.whisper_model_size,
            'chunk_minutes': chunk_minutes,
        }

        if progress_callback:
            progress_callback("complete", "Meeting minutes generated successfully!")

        logger.info(f"Pipeline complete in {(end_time - start_time).total_seconds():.1f}s")
        return result
